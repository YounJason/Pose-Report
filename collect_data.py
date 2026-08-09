# -*- coding: utf-8 -*-
"""
collect_data.py
----------------
웹캠으로 자세를 보면서 데이터를 라벨링해 학습 데이터를 모으는 스크립트.

실행:
    python collect_data.py

사용법 (2단계 방식):
    1) 먼저 숫자 키(1~6)를 눌러서 "지금부터 저장할 라벨"을 선택합니다.
       -> 화면 상단에 선택된 라벨이 표시됩니다. 이 시점에는 아직 저장되지 않습니다.
    2) 전신이 카메라에 나오도록 자리를 잡은 뒤, 마우스로 화면(영상 창)을 클릭하면
       그 순간 프레임의 특징을 뽑아 저장합니다.
       -> 라벨 선택은 유지되므로, 같은 라벨로 여러 번 클릭해서 계속 저장할 수 있습니다.
          (무선 마우스로 뒤로 물러나서 전신이 나온 채로 클릭만 하면 됩니다.)
    - 다른 자세로 바꿀 때만 다시 숫자 키를 눌러 라벨을 바꾸면 됩니다.
    - q 를 누르면 종료합니다.

단축키 -> 라벨:
    1: normal          (정상 자세)
    2: turtle_neck      (거북목)
    3: rounded_back     (등/허리 굽음)
    4: shoulder_asymm   (어깨 비대칭)
    5: pelvis_asymm     (골반 비대칭)
    6: leg_cross        (다리 꼬기)

라벨을 더 추가하고 싶으면 KEY_TO_LABEL 딕셔너리와 ml/pose_classifier.py 의
LABEL_INFO 를 함께 수정하세요.
"""

import csv
import os

import cv2
import mediapipe as mp

from ml.pose_features import FEATURE_NAMES, extract_features

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CSV_PATH = os.path.join(DATA_DIR, "posture_dataset.csv")
WINDOW_NAME = "Pose Data Collector"

KEY_TO_LABEL = {
    ord("1"): "normal",
    ord("2"): "turtle_neck",
    ord("3"): "rounded_back",
    ord("4"): "shoulder_asymm",
    ord("5"): "pelvis_asymm",
    ord("6"): "leg_cross",
}

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils


def ensure_csv():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(FEATURE_NAMES + ["label"])


def append_row(feature_dict, label):
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([feature_dict[name] for name in FEATURE_NAMES] + [label])


def main():
    ensure_csv()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("카메라를 열 수 없습니다. 카메라 인덱스나 권한을 확인하세요.")
        return

    pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

    # 마우스 클릭 이벤트는 콜백에서 발생하므로, 메인 루프와 공유할 상태는
    # dict(mutable)에 담아서 클로저로 넘겨줍니다.
    state = {"selected_label": None, "capture_requested": False}

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["capture_requested"] = True

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    saved_count = 0
    print("=" * 70)
    print(" 자세 데이터 수집기 (숫자키로 라벨 선택 -> 마우스 클릭으로 저장)")
    print(" 1:정상  2:거북목  3:등굽음  4:어깨비대칭  5:골반비대칭  6:다리꼬기")
    print(" 라벨을 선택한 뒤, 화면을 마우스로 클릭하면 그 순간이 저장됩니다.")
    print(" q: 종료")
    print("=" * 70)

    last_saved_label = ""

    while True:
        success, frame = cap.read()
        if not success:
            continue

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)

        feature_dict = None
        if results.pose_landmarks:
            mp_drawing.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
            feature_dict = extract_features(results.pose_landmarks.landmark, w, h)

        selected_label = state["selected_label"]
        label_display = selected_label if selected_label else "(없음 - 숫자키로 선택하세요)"
        label_color = (0, 255, 0) if selected_label else (0, 165, 255)

        overlay_lines = [
            f"Selected label: {label_display}",
            f"Saved: {saved_count}  Last: {last_saved_label}",
            "1 normal | 2 turtle_neck | 3 rounded_back",
            "4 shoulder_asymm | 5 pelvis_asymm | 6 leg_cross | q quit",
            "Click anywhere on this window to capture & save",
        ]
        if feature_dict is None:
            overlay_lines.insert(0, "landmarks not detected")

        for i, line in enumerate(overlay_lines):
            color = label_color if i == (1 if feature_dict is None else 0) else (0, 255, 0)
            cv2.putText(frame, line, (10, 25 + i * 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, color, 1, cv2.LINE_AA)

        cv2.imshow(WINDOW_NAME, frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        elif key in KEY_TO_LABEL:
            state["selected_label"] = KEY_TO_LABEL[key]
            print(f"라벨 선택됨 -> '{state['selected_label']}'  (이제 클릭하면 저장됩니다)")

        if state["capture_requested"]:
            state["capture_requested"] = False
            if state["selected_label"] is None:
                print("⚠️  먼저 숫자 키(1~6)로 라벨을 선택한 뒤 클릭하세요.")
            elif feature_dict is None:
                print("⚠️  랜드마크가 인식되지 않아 저장하지 못했습니다. 카메라에 전신이 잘 나오는지 확인하세요.")
            else:
                label = state["selected_label"]
                append_row(feature_dict, label)
                saved_count += 1
                last_saved_label = label
                print(f"[{saved_count}] saved label='{label}'  features={feature_dict}")

    cap.release()
    cv2.destroyAllWindows()
    print(f"\n총 {saved_count}개 샘플 저장 완료 -> {CSV_PATH}")


if __name__ == "__main__":
    main()
