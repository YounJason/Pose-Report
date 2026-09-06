import json
import os
import random
import re
import sys

import requests
from dotenv import load_dotenv

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=env_path) if os.path.exists(env_path) else load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
SHORTS_POOL_FILE = os.path.join(BASE_DIR, "shorts_pool.json")

YT_SHORTS_PER_CHANNEL_FETCH = 50
YT_SHORTS_MAX_DURATION_SEC = 60
YT_SHORTS_PER_CHANNEL_CAP = 20

PLAYBACK_REGION = "KR"

_handle_cache = {}


def _parse_iso8601_duration_sec(duration):
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", duration or "")
    if not m:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in m.groups())
    return hours * 3600 + minutes * 60 + seconds


def _resolve_channel_id(channel_ref):
    if re.match(r"^UC[A-Za-z0-9_-]{22}$", channel_ref):
        return channel_ref

    if channel_ref in _handle_cache:
        return _handle_cache[channel_ref]

    handle = channel_ref if channel_ref.startswith("@") else f"@{channel_ref}"
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"key": YOUTUBE_API_KEY, "part": "id", "forHandle": handle},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        return None
    channel_id = items[0]["id"]
    _handle_cache[channel_ref] = channel_id
    return channel_id


def _fetch_shorts_playlist_video_ids(channel_id):
    playlist_id = "UUSH" + channel_id[2:]
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/playlistItems",
        params={
            "key": YOUTUBE_API_KEY,
            "playlistId": playlist_id,
            "part": "contentDetails",
            "maxResults": YT_SHORTS_PER_CHANNEL_FETCH,
        },
        timeout=15,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [
        item["contentDetails"]["videoId"]
        for item in items
        if item.get("contentDetails", {}).get("videoId")
    ]


def _fetch_channel_video_ids_via_search(channel_id):
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "key": YOUTUBE_API_KEY,
            "channelId": channel_id,
            "part": "id",
            "order": "date",
            "type": "video",
            "maxResults": YT_SHORTS_PER_CHANNEL_FETCH,
        },
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [
        item["id"]["videoId"]
        for item in items
        if item.get("id", {}).get("videoId")
    ]


def _is_region_blocked(content_details, region=PLAYBACK_REGION):
    region_restriction = content_details.get("regionRestriction") or {}
    blocked = region_restriction.get("blocked")
    if blocked and region in blocked:
        return True
    allowed = region_restriction.get("allowed")
    if allowed and region not in allowed:
        return True
    return False


def _filter_embeddable_shorts(video_ids):
    if not video_ids:
        return []
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={
            "key": YOUTUBE_API_KEY,
            "id": ",".join(video_ids),
            "part": "status,contentDetails",
        },
        timeout=15,
    )
    resp.raise_for_status()
    result = []
    for item in resp.json().get("items", []):
        status = item.get("status", {})
        content_details = item.get("contentDetails", {})

        if not status.get("embeddable"):
            continue
        if status.get("madeForKids"):
            continue
        if status.get("privacyStatus") != "public":
            continue

        content_rating = content_details.get("contentRating", {}) or {}
        if content_rating.get("ytRating") == "ytAgeRestricted":
            continue

        if _is_region_blocked(content_details):
            continue

        duration_sec = _parse_iso8601_duration_sec(content_details.get("duration"))
        if duration_sec is None or duration_sec > YT_SHORTS_MAX_DURATION_SEC:
            continue
        result.append(item["id"])
    return result


def load_shorts():
    if not YOUTUBE_API_KEY:
        print(
            "[LoadShorts] YOUTUBE_API_KEY가 설정되어 있지 않습니다. .env를 확인해주세요.",
            flush=True,
        )
        return False
    if not config.TRUSTED_YT_CHANNELS:
        print(
            "[LoadShorts] config.TRUSTED_YT_CHANNELS가 비어 있습니다.",
            flush=True,
        )
        return False

    all_filtered_ids = []
    channel_stats = []

    for channel_ref in config.TRUSTED_YT_CHANNELS:
        try:
            channel_id = _resolve_channel_id(channel_ref)
        except requests.RequestException as e:
            print(f"[LoadShorts] 채널 핸들 조회 실패 ({channel_ref}): {e}", flush=True)
            channel_stats.append((channel_ref, 0, 0, 0, "핸들 조회 실패"))
            continue
        if channel_id is None:
            print(f"[LoadShorts] 채널을 찾지 못했습니다: {channel_ref}", flush=True)
            channel_stats.append((channel_ref, 0, 0, 0, "채널 없음"))
            continue

        source = "UUSH"
        try:
            video_ids = _fetch_shorts_playlist_video_ids(channel_id)
            if video_ids is None:
                source = "search(fallback)"
                video_ids = _fetch_channel_video_ids_via_search(channel_id)
        except requests.RequestException as e:
            print(f"[LoadShorts] 채널 영상 조회 실패 ({channel_ref}): {e}", flush=True)
            channel_stats.append((channel_ref, 0, 0, 0, "영상 조회 실패"))
            continue

        fetched_count = len(video_ids)

        try:
            filtered_ids = []
            for i in range(0, len(video_ids), 50):
                filtered_ids.extend(_filter_embeddable_shorts(video_ids[i : i + 50]))
        except requests.RequestException as e:
            print(f"[LoadShorts] 영상 필터링 실패 ({channel_ref}): {e}", flush=True)
            channel_stats.append((channel_ref, fetched_count, 0, 0, "필터링 실패"))
            continue

        passed_count = len(filtered_ids)
        if passed_count > YT_SHORTS_PER_CHANNEL_CAP:
            filtered_ids = random.sample(filtered_ids, YT_SHORTS_PER_CHANNEL_CAP)
        capped_count = len(filtered_ids)
        channel_stats.append((channel_ref, fetched_count, passed_count, capped_count, source))
        all_filtered_ids.extend(filtered_ids)

    print("[LoadShorts] ===== 채널별 결과 =====", flush=True)
    for channel_ref, fetched_count, passed_count, capped_count, source in channel_stats:
        rate = f"{(passed_count / fetched_count * 100):.0f}%" if fetched_count else "0%"
        print(
            f"[LoadShorts]   {channel_ref:<20} 조회 {fetched_count:>3}개 -> "
            f"필터 통과 {passed_count:>3}개 ({rate}, {source}) -> 풀 반영 {capped_count:>3}개",
            flush=True,
        )
    print("[LoadShorts] =========================", flush=True)

    all_filtered_ids = list(dict.fromkeys(all_filtered_ids))

    if not all_filtered_ids:
        print("[LoadShorts] 조건에 맞는 쇼츠를 찾지 못했습니다.", flush=True)
        return False

    with open(SHORTS_POOL_FILE, "w", encoding="utf-8") as f:
        json.dump({"video_ids": all_filtered_ids}, f, ensure_ascii=False)

    print(
        f"[LoadShorts] 갱신 완료: 총 {len(all_filtered_ids)}개 "
        f"(채널 {len(channel_stats)}개 처리)",
        flush=True,
    )
    return True


if __name__ == "__main__":
    ok = load_shorts()
    sys.exit(0 if ok else 1)