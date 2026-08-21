"""
자세별 학습 데이터 수집 스크립트.

사용법:
    python collect_pose_data.py --output pose_dataset.csv

웹캠 미리보기 창이 뜨면 숫자 키로 지금부터 기록할 라벨을 지정한다.
같은 라벨 키를 다시 누르기 전까지는 계속 그 라벨로 기록되므로(연속 기록
모드), 자세를 잡은 채로 잠깐 유지하면서 자연스러운 움직임(약간의 흔들림,
고개 돌림 등)까지 같이 담는 것이 좋다. 한 라벨당 1,000~2,000 프레임,
가능하면 여러 사람 / 여러 각도 / 여러 거리에서 모으는 것을 권장한다.

같은 --output 경로로 여러 번 실행하면 데이터는 계속 이어서(append) 쌓이고,
화면 좌측 상단의 라벨별 카운트도 이번 실행분만이 아니라 그 CSV에 지금까지
누적된 전체 개수로 시작한다.

키 매핑:
    1 : normal        (바른 자세)
    2 : turtle_neck    (거북목)
    3 : slouch         (등 굽음)
    4 : shoulder_tilt  (어깨 비대칭)
    5 : pelvis_tilt    (골반 비대칭)
    space : 기록 일시정지
    q : 종료 및 저장

다리 꼬기는 이 수집기/ML 분류 대상이 아니다. main.py에서 항상 각도 기반
휴리스틱(_detect_leg_cross)으로만 판정하므로 여기서 라벨을 모을 필요가
없다.
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
}


def main():
    parser = argparse.ArgumentParser(description="자세 데이터 수집기")
    parser.add_argument("--output", default="pose_dataset.csv", help="저장할 CSV 경로")
    parser.add_argument("--camera", type=int, default=0, help="웹캠 장치 인덱스")
    args = parser.parse_args()

    file_exists = os.path.exists(args.output)

    # 기존 CSV(있다면)에 이미 쌓여 있는 라벨별 행 수를 먼저 세어둔다. 화면에
    # 표시되는 누적 카운트가 "이번 실행에서 기록한 개수"가 아니라 "이 CSV에
    # 지금까지 모인 전체 개수"를 보여주도록 하기 위함이다. (CSV 자체는
    # 이전부터 append 모드로 열려 있어 여러 번 실행해도 파일 내용은 이미
    # 누적되고 있었지만, 화면 카운터는 매번 0부터 시작해 사용자가 실제
    # 누적량을 알기 어려웠다.)
    existing_counts = {label: 0 for label in POSE_LABELS}
    if file_exists:
        try:
            with open(args.output, "r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if not row:
                        continue
                    label = row[0]
                    if label in existing_counts:
                        existing_counts[label] += 1
            total_existing = sum(existing_counts.values())
            if total_existing:
                print(f"[누적] 기존 '{args.output}'에서 {total_existing}개 프레임을 이어서 시작합니다: "
                      f"{existing_counts}")
        except Exception as e:
            print(f"[경고] 기존 CSV의 누적 개수를 읽는 중 오류가 발생해 0부터 시작합니다: {e}")
            existing_counts = {label: 0 for label in POSE_LABELS}

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

    # 이번 실행에서 새로 기록되는 개수도 기존 누적 개수 위에 계속 더해진다.
    counts = dict(existing_counts)
    current_label = None
    print("숫자 키(1~5)로 라벨을 선택하면 그 라벨로 계속 기록됩니다.")
    print("space: 일시정지 / q: 종료")
    for k, v in KEY_TO_LABEL.items():
        print(f"  {chr(k)} -> {v} ({LABEL_TO_KOREAN[v]})")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            # 주의: main.py의 실시간 캡처 루프(start_camera_thread)는 프레임을
            # 좌우 반전하지 않는다. 여기서 flip을 하면 MediaPipe가 판정하는
            # "왼쪽/오른쪽" 랜드마크의 의미가 실제 추론 시점과 뒤바뀌어, 어깨/
            # 골반 비대칭처럼 좌우 방향성이 있는 라벨의 학습 데이터가 왜곡된다.
            # 따라서 학습 데이터 수집 시에도 flip을 적용하지 않아 main.py와
            # 동일한 원본(비반전) 프레임 기준으로 랜드마크를 추출한다.
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
