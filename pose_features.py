"""부위별 자세 ML feature 추출 공통 모듈."""

import numpy as np

NUM_LANDMARKS = 33

POSE_LABELS = [
    "normal",
    "turtle_neck",
    "slouch",
    "shoulder_tilt",
    "pelvis_tilt",
]

LABEL_TO_KOREAN = {
    "normal": "바른 자세",
    "turtle_neck": "거북목",
    "slouch": "등 굽음",
    "shoulder_tilt": "어깨 비대칭",
    "pelvis_tilt": "골반 비대칭",
}

BINARY_TARGETS = {
    "neck": "neck_label",
    "torso": "torso_label",
    "shoulder": "shoulder_label",
    "pelvis": "pelvis_label",
}

# MediaPipe Pose landmark indices.
NOSE = 0
LEFT_EYE = 2
RIGHT_EYE = 5
LEFT_EAR = 7
RIGHT_EAR = 8
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_KNEE = 25
RIGHT_KNEE = 26

# 각 모델은 아래 부위와 관련된 랜드마크만 입력받는다.
# 모델 간 입력이 겹칠 수는 있지만, 서로 무관한 신체 하위 영역은 포함하지 않는다.
PART_LANDMARKS = {
    "neck": [NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR, LEFT_SHOULDER, RIGHT_SHOULDER],
    "torso": [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP],
    "shoulder": [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW],
    "pelvis": [LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE],
}

PART_KOREAN = {
    "neck": "거북목",
    "torso": "등·허리",
    "shoulder": "어깨",
    "pelvis": "골반",
}

PARTS = tuple(PART_LANDMARKS.keys())

PART_ANCHORS = {
    "neck": (LEFT_SHOULDER, RIGHT_SHOULDER),
    "torso": (LEFT_HIP, RIGHT_HIP),
    "shoulder": (LEFT_SHOULDER, RIGHT_SHOULDER),
    "pelvis": (LEFT_HIP, RIGHT_HIP),
}

PART_SCALES = {
    "neck": (LEFT_SHOULDER, RIGHT_SHOULDER),
    "torso": (LEFT_SHOULDER, RIGHT_SHOULDER),
    "shoulder": (LEFT_SHOULDER, RIGHT_SHOULDER),
    "pelvis": (LEFT_HIP, RIGHT_HIP),
}

# CSV 학습 데이터는 기존 수집기와 호환되도록 lm{index}_{axis} 컬럼명을 사용한다.
# 각 부위 모델은 아래 목록의 원본 landmark 컬럼만 선택해 사용한다.
FEATURE_COLUMNS_BY_PART = {}
FEATURE_COLUMNS = []
for _part, _indices in PART_LANDMARKS.items():
    cols = [f"lm{idx}_{axis}" for idx in _indices for axis in ("x", "y", "z")]
    FEATURE_COLUMNS_BY_PART[_part] = cols
    FEATURE_COLUMNS.extend(cols)


def landmarks_to_array(landmarks):
    """MediaPipe landmark 리스트 -> (33, 3) ndarray [x, y, z]."""
    return np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float64)


def _ensure_array(landmarks_xyz):
    if not isinstance(landmarks_xyz, np.ndarray):
        landmarks_xyz = landmarks_to_array(landmarks_xyz)
    if landmarks_xyz.shape != (NUM_LANDMARKS, 3):
        raise ValueError(
            f"landmarks shape must be ({NUM_LANDMARKS}, 3), got {landmarks_xyz.shape}"
        )
    return landmarks_xyz.astype(np.float64, copy=False)


def extract_part_feature_vector(landmarks_xyz, part):
    """한 부위의 독립 feature vector를 반환한다."""
    if part not in PART_LANDMARKS:
        raise ValueError(f"unknown part: {part}")

    arr = _ensure_array(landmarks_xyz)
    anchor_a, anchor_b = PART_ANCHORS[part]
    scale_a, scale_b = PART_SCALES[part]

    origin = (arr[anchor_a] + arr[anchor_b]) / 2.0
    scale = float(np.linalg.norm(arr[scale_a] - arr[scale_b]))
    if scale < 1e-6:
        scale = 1e-6

    indices = PART_LANDMARKS[part]
    normalized = (arr[indices] - origin) / scale
    return normalized.flatten()


def extract_all_part_features(landmarks_xyz):
    """4개 부위의 feature를 dict로 반환한다."""
    return {part: extract_part_feature_vector(landmarks_xyz, part) for part in PARTS}


def extract_feature_vector(landmarks_xyz):
    """하위 호환용: 4개 부위 feature를 이어 붙인 전체 벡터."""
    return np.concatenate([extract_part_feature_vector(landmarks_xyz, part) for part in PARTS])
