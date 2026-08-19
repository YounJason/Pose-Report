"""
자세별 학습 데이터 수집 스크립트.

사용법:
    python collect_pose_data.py --output pose_dataset.csv

웹캠 미리보기 창이 뜨면 숫자 키로 지금부터 기록할 라벨을 지정한다.
같은 라벨 키를 다시 누르기 전까지는 계속 그 라벨로 기록되므로(연속 기록
모드), 자세를 잡은 채로 잠깐 유지하면서 자연스러운 움직임(약간의 흔들림,
고개 돌림 등)까지 같이 담는 것이 좋다. 한 라벨당 1,000~2,000 프레임,
가능하면 여러 사람 / 여러 각도 / 여러 거리에서 모으는 것을 권장한다.

키 매핑:
    1 : normal        (바른 자세)
    2 : turtle_neck    (거북목)
    3 : slouch         (등 굽음)
    4 : shoulder_tilt  (어깨 비대칭)
    5 : pelvis_tilt    (골반 비대칭)
    6 : leg_cross      (다리 꼬기)
    space : 기록 일시정지
    q : 종료 및 저장
"""
import argparse
import csv
import os

import cv2
import mediapipe as mp

from pose_features import (
    FEATURE_COLUMNS,
    LABEL_TO_KOREAN,
    POSE_LABELS,
    extract_feature_vector,
    landmarks_to_array,
)

KEY_TO_LABEL = {
    ord('1'): "normal",
    ord('2'): "turtle_neck",
    ord('3'): "slouch",
    ord('4'): "shoulder_tilt",
    ord('5'): "pelvis_tilt",
    ord('6'): "leg_cross",
}


def main():
    parser = argparse.ArgumentParser(description="자세 데이터 수집기")
    parser.add_argument("--output", default="pose_dataset.csv", help="저장할 CSV 경로")
    parser.add_argument("--camera", type=int, default=0, help="웹캠 장치 인덱스")
    args = parser.parse_args()

    file_exists = os.path.exists(args.output)
    csv_file = open(args.output, "a", newline="", encoding="utf-8")
    writer = csv.writer(csv_file)
    if not file_exists:
        writer.writerow(["label"] + FEATURE_COLUMNS)

    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        model_complexity=1, min_detection_confidence=0.5, min_tracking_confidence=0.5
    )

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"카메라 {args.camera} 를 열 수 없습니다.")

    counts = {label: 0 for label in POSE_LABELS}
    current_label = None
    print("숫자 키(1~6)로 라벨을 선택하면 그 라벨로 계속 기록됩니다.")
    print("space: 일시정지 / q: 종료")
    for k, v in KEY_TO_LABEL.items():
        print(f"  {chr(k)} -> {v} ({LABEL_TO_KOREAN[v]})")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
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
                    features = extract_feature_vector(landmarks)
                    writer.writerow([current_label] + features.tolist())
                    counts[current_label] += 1

            status = (
                f"기록 중: {LABEL_TO_KOREAN[current_label]}"
                if current_label
                else "일시정지 (숫자 키를 누르세요)"
            )
            color = (0, 255, 0) if current_label else (0, 0, 255)
            cv2.putText(frame, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            y = 60
            for label, cnt in counts.items():
                cv2.putText(
                    frame, f"{LABEL_TO_KOREAN[label]}: {cnt}", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1
                )
                y += 22
            cv2.imshow("Pose Data Collector (q: quit)", frame)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        csv_file.close()
        print("수집 완료:", counts)


if __name__ == "__main__":
    main()
