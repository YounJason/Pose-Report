"""
공통 특징 벡터(feature vector) 추출 모듈.

MediaPipe Pose가 반환하는 33개 랜드마크 (x, y, z)로부터, 카메라와의 거리나
프레임 내 위치에 최대한 영향을 받지 않는 정규화된 99차원 특징 벡터를 만든다.

collect_pose_data.py(데이터 수집) / train_pose_classifier.py(학습) /
main.py(실시간 추론) 세 곳 모두 반드시 이 모듈의 extract_feature_vector()만
사용해야 한다. 세 지점의 전처리가 조금이라도 어긋나면 학습된 모델이 실시간
입력에서 엉뚱한 결과를 낸다.
"""

import numpy as np

NUM_LANDMARKS = 33

# 데이터 수집 시 사람이 고르는 라벨들.
# main.py의 기존 threshold 기반 상태 문구(거북목/등 굽음/어깨 비대칭/
# 골반 비대칭)와 대응시켜 두었다. 다리 꼬기는 ML 분류 대상이 아니라 항상
# 별도의 각도 기반 휴리스틱(_detect_leg_cross)으로 판정하므로 여기 포함하지
# 않는다. 필요에 따라 추가/수정 가능하지만, 바꾼 뒤에는 반드시 새 데이터를
# 다시 모아 모델을 재학습해야 한다.
POSE_LABELS = [
    "normal",         # 바른 자세
    "turtle_neck",    # 거북목
    "slouch",         # 등 굽음 (상체 숙임)
    "shoulder_tilt",  # 어깨 비대칭
    "pelvis_tilt",    # 골반 비대칭
]

# 사람이 읽을 한국어 라벨 (UI/로그 표시용)
LABEL_TO_KOREAN = {
    "normal": "바른 자세",
    "turtle_neck": "거북목",
    "slouch": "등 굽음",
    "shoulder_tilt": "어깨 비대칭",
    "pelvis_tilt": "골반 비대칭",
}

LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12

FEATURE_COLUMNS = [
    f"lm{i}_{axis}" for i in range(NUM_LANDMARKS) for axis in ("x", "y", "z")
]


def landmarks_to_array(landmarks):
    """MediaPipe NormalizedLandmarkList -> (33, 3) ndarray [x, y, z]."""
    return np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float64)


def extract_feature_vector(landmarks_xyz):
    """
    (33, 3) ndarray 또는 MediaPipe landmark 리스트를 받아 정규화된 99차원
    벡터를 반환한다.

    정규화 방법:
      1. 좌/우 엉덩이 중점을 원점(origin)으로 평행이동한다.
      2. 어깨 중점 - 엉덩이 중점 사이 거리(상체 길이)로 좌표를 나눈다.
         -> 사용자가 카메라에서 멀든 가깝든, 체형이 크든 작든 특징 값이
            비슷한 범위에 들어와, 분류기가 '거리/체형'이 아니라 '자세'
            자체를 학습하도록 돕는다.
    """
    if not isinstance(landmarks_xyz, np.ndarray):
        landmarks_xyz = landmarks_to_array(landmarks_xyz)

    if landmarks_xyz.shape != (NUM_LANDMARKS, 3):
        raise ValueError(
            f"landmarks shape must be ({NUM_LANDMARKS}, 3), got {landmarks_xyz.shape}"
        )

    mid_hip = (landmarks_xyz[LEFT_HIP] + landmarks_xyz[RIGHT_HIP]) / 2.0
    mid_shoulder = (landmarks_xyz[LEFT_SHOULDER] + landmarks_xyz[RIGHT_SHOULDER]) / 2.0

    torso_length = float(np.linalg.norm(mid_shoulder - mid_hip))
    if torso_length < 1e-6:
        torso_length = 1e-6

    normalized = (landmarks_xyz - mid_hip) / torso_length
    return normalized.flatten()  # (99,)
