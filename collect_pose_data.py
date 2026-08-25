"""기존 키 기반 UI를 유지하는 자세 ML 데이터 수집기.

사용법:
    python collect_pose_data.py --output pose_dataset.csv --person-id person_001

키 매핑:
    1 : normal
    2 : turtle_neck
    3 : slouch
    4 : shoulder_tilt
    5 : pelvis_tilt
    space : 기록 일시정지
    q : 종료

기존 UI/라벨 방식은 유지하되, 저장되는 한 행은 4개 이진 target을 함께 가진다.
예: turtle_neck -> neck_label=1, 나머지=0.
"""

import argparse
import csv
import os
import uuid
from datetime import datetime, timezone

import cv2
import mediapipe as mp

from pose_features import (
    FEATURE_COLUMNS_BY_PART,
    LABEL_TO_KOREAN,
    POSE_LABELS,
    PARTS,
    extract_all_part_features,
    landmarks_to_array,
)

KEY_TO_LABEL = {
    ord('1'): "normal",
    ord('2'): "turtle_neck",
    ord('3'): "slouch",
    ord('4'): "shoulder_tilt",
    ord('5'): "pelvis_tilt",
}
LABEL_TO_TARGET = {
    "normal": {"neck": 0, "torso": 0, "shoulder": 0, "pelvis": 0},
    "turtle_neck": {"neck": 1, "torso": 0, "shoulder": 0, "pelvis": 0},
    "slouch": {"neck": 0, "torso": 1, "shoulder": 0, "pelvis": 0},
    "shoulder_tilt": {"neck": 0, "torso": 0, "shoulder": 1, "pelvis": 0},
    "pelvis_tilt": {"neck": 0, "torso": 0, "shoulder": 0, "pelvis": 1},
}


def _new_session_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]


def _header():
    cols = ["session_id", "person_id", "frame_id", "source_label"]
    cols += [f"{part}_label" for part in PARTS]
    for part in PARTS:
        cols += FEATURE_COLUMNS_BY_PART[part]
    return cols


def main():
    parser = argparse.ArgumentParser(description="자세 데이터 수집기")
    parser.add_argument("--output", default="pose_dataset.csv", help="저장할 CSV 경로")
    parser.add_argument("--camera", type=int, default=0, help="웹캠 장치 인덱스")
    parser.add_argument("--person-id", default=None, help="사람 식별자. 미지정 시 실행 중 입력받습니다.")
    parser.add_argument("--session-id", default=None, help="세션 ID. 미지정 시 자동 생성")
    args = parser.parse_args()

    person_id = (args.person_id or input("Person ID: ").strip())
    if not person_id:
        raise SystemExit("person_id는 비워둘 수 없습니다.")
    session_id = args.session_id or _new_session_id()

    file_exists = os.path.exists(args.output)
    counts = {label: 0 for label in POSE_LABELS}
    if file_exists:
        try:
            with open(args.output, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    label = row.get("source_label") or row.get("label")
                    if label in counts:
                        counts[label] += 1
        except Exception as e:
            print(f"[경고] 기존 카운트 읽기 실패: {e}")

    need_header = not file_exists or os.path.getsize(args.output) == 0
    csv_file = open(args.output, "a", newline="", encoding="utf-8")
    writer = csv.writer(csv_file)
    if need_header:
        writer.writerow(_header())

    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        model_complexity=1, min_detection_confidence=0.5, min_tracking_confidence=0.5
    )
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"카메라 {args.camera} 를 열 수 없습니다.")

    current_label = None
    frame_id = 0
    print(f"[수집] person_id={person_id}, session_id={session_id}")
    print("숫자 키(1~5)로 기존 라벨을 선택하면 그 라벨로 계속 기록됩니다.")
    print("space: 일시정지 / q: 종료")
    for k, v in KEY_TO_LABEL.items():
        print(f"  {chr(k)} -> {v} ({LABEL_TO_KOREAN[v]})")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord(' '):
                current_label = None
            elif key in KEY_TO_LABEL:
                current_label = KEY_TO_LABEL[key]

            if results.pose_landmarks:
                mp.solutions.drawing_utils.draw_landmarks(
                    frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS
                )
                if current_label is not None:
                    landmarks = landmarks_to_array(results.pose_landmarks.landmark)
                    all_features = extract_all_part_features(landmarks)
                    targets = LABEL_TO_TARGET[current_label]
                    frame_id += 1
                    row = [session_id, person_id, frame_id, current_label]
                    row += [targets[part] for part in PARTS]
                    for part in PARTS:
                        row += all_features[part].tolist()
                    writer.writerow(row)
                    csv_file.flush()
                    counts[current_label] += 1

            status = f"기록 중: {LABEL_TO_KOREAN[current_label]}" if current_label else "일시정지 (숫자 키를 누르세요)"
            color = (0, 255, 0) if current_label else (0, 0, 255)
            cv2.putText(frame, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            y = 60
            for label, cnt in counts.items():
                cv2.putText(frame, f"{LABEL_TO_KOREAN[label]}: {cnt}", (10, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                y += 22
            cv2.putText(frame, f"person: {person_id} | session: {session_id}", (10, 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            cv2.imshow("Pose Data Collector (q: quit)", frame)
    finally:
        cap.release()
        pose.close()
        cv2.destroyAllWindows()
        csv_file.close()
        print("수집 완료:", counts)


if __name__ == "__main__":
    main()
