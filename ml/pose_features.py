"""
pose_features.py
-----------------
MediaPipe Pose 랜드마크로부터 자세 분석용 특징 벡터(feature vector)를 추출하는 모듈.

기존 main.py의 각도 기반 규칙(rule-based)에서 사용하던 계산식을 그대로 재사용하여
"특징 추출" 로직만 별도로 분리했습니다. 이렇게 하면:
  1) 규칙 기반 코드와 ML 코드가 동일한 특징(feature) 정의를 공유하고,
  2) 데이터 수집(collect_data.py) / 학습(train_model.py) / 추론(main.py) 세 곳에서
     동일한 함수를 import 해서 쓰기 때문에 전처리 불일치가 생기지 않습니다.

FEATURE_NAMES 의 순서가 곧 모델 입력 벡터의 순서입니다. 특징을 추가/삭제할 경우
이 파일만 수정하면 데이터 수집, 학습, 추론 코드에 모두 자동으로 반영됩니다.
"""

import math

import mediapipe as mp

mp_pose = mp.solutions.pose

# 특징 벡터에 사용할 랜드마크 (신뢰도 체크용)
REQUIRED_LANDMARKS = [
    mp_pose.PoseLandmark.NOSE,
    mp_pose.PoseLandmark.LEFT_EAR, mp_pose.PoseLandmark.RIGHT_EAR,
    mp_pose.PoseLandmark.LEFT_SHOULDER, mp_pose.PoseLandmark.RIGHT_SHOULDER,
    mp_pose.PoseLandmark.LEFT_HIP, mp_pose.PoseLandmark.RIGHT_HIP,
    mp_pose.PoseLandmark.LEFT_KNEE, mp_pose.PoseLandmark.RIGHT_KNEE,
    mp_pose.PoseLandmark.LEFT_ANKLE, mp_pose.PoseLandmark.RIGHT_ANKLE,
]

# 모델 입력으로 사용할 특징 이름 (순서 중요!)
FEATURE_NAMES = [
    "neck_angle",        # 거북목 각도
    "head_tilt_angle",   # 목(머리) 좌우 기울기
    "torso_angle",       # 등/허리 굽음 각도
    "spine_lean_angle",  # 상체 좌우 불균형
    "shoulder_angle",    # 어깨 좌우 비대칭
    "pelvis_angle",      # 골반 좌우 비대칭
    "leg_cross",         # 다리 꼬임 여부 (0 또는 1)
]


def _is_intersect(p1, q1, p2, q2):
    """두 선분(p1-q1, p2-q2)의 교차 여부. main.py의 로직과 동일."""
    def ccw(A, B, C):
        val = (B[1] - A[1]) * (C[0] - B[0]) - (B[0] - A[0]) * (C[1] - B[1])
        return (val > 0) - (val < 0)

    res1 = ccw(p1, q1, p2) * ccw(p1, q1, q2)
    res2 = ccw(p2, q2, p1) * ccw(p2, q2, q1)
    if res1 <= 0 and res2 <= 0:
        if res1 == 0 and res2 == 0:
            return (min(p1[0], q1[0]) <= max(p2[0], q2[0]) and
                    min(p2[0], q2[0]) <= max(p1[0], q1[0]) and
                    min(p1[1], q1[1]) <= max(p2[1], q2[1]) and
                    min(p2[1], q2[1]) <= max(p1[1], q1[1]))
        return True
    return False


def landmarks_visible(landmarks, min_visibility=0.5):
    """분석에 필요한 랜드마크가 충분히 인식되었는지 확인."""
    return all(landmarks[lm].visibility >= min_visibility for lm in REQUIRED_LANDMARKS)


def extract_features(landmarks, w, h):
    """
    MediaPipe pose landmarks -> dict(feature_name -> value)

    Args:
        landmarks: results.pose_landmarks.landmark (MediaPipe 결과)
        w, h: 프레임 너비/높이 (픽셀 좌표 계산용)

    Returns:
        dict 또는, 인식 실패 시 None
    """
    if not landmarks_visible(landmarks):
        return None

    nose = landmarks[mp_pose.PoseLandmark.NOSE]
    left_ear = landmarks[mp_pose.PoseLandmark.LEFT_EAR]
    right_ear = landmarks[mp_pose.PoseLandmark.RIGHT_EAR]
    left_shoulder = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER]
    right_shoulder = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER]
    left_hip_lm = landmarks[mp_pose.PoseLandmark.LEFT_HIP]
    right_hip_lm = landmarks[mp_pose.PoseLandmark.RIGHT_HIP]

    ls_x, ls_y = left_shoulder.x * w, left_shoulder.y * h
    rs_x, rs_y = right_shoulder.x * w, right_shoulder.y * h
    lh_x, lh_y = left_hip_lm.x * w, left_hip_lm.y * h
    rh_x, rh_y = right_hip_lm.x * w, right_hip_lm.y * h
    le_x, le_y = left_ear.x * w, left_ear.y * h
    re_x, re_y = right_ear.x * w, right_ear.y * h

    # 거북목 각도
    dy = nose.y - (left_ear.y + right_ear.y) / 2
    dz = ((left_ear.z + right_ear.z) / 2) - nose.z
    neck_angle = 90 - math.degrees(math.atan2(abs(dz), dy)) if dy != 0 else 0

    # 머리 좌우 기울기
    head_tilt_angle = math.degrees(math.atan2(abs(le_y - re_y), abs(le_x - re_x))) if le_x != re_x else 90.0

    # 등/허리 굽음 각도
    dy_torso = ((left_hip_lm.y + right_hip_lm.y) / 2) - ((left_shoulder.y + right_shoulder.y) / 2)
    dz_torso = ((left_hip_lm.z + right_hip_lm.z) / 2) - ((left_shoulder.z + right_shoulder.z) / 2)
    torso_angle = math.degrees(math.atan2(abs(dz_torso), dy_torso)) if dy_torso != 0 else 0

    # 상체 좌우 불균형(척추 기울기)
    dx_spine = ((ls_x + rs_x) / 2) - ((lh_x + rh_x) / 2)
    dy_spine = ((lh_y + rh_y) / 2) - ((ls_y + rs_y) / 2)
    spine_lean_angle = math.degrees(math.atan2(abs(dx_spine), dy_spine)) if dy_spine != 0 else 90.0

    # 어깨 비대칭
    shoulder_angle = math.degrees(math.atan2(abs(ls_y - rs_y), abs(ls_x - rs_x))) if ls_x != rs_x else 90.0

    # 골반 비대칭
    pelvis_angle = math.degrees(math.atan2(abs(lh_y - rh_y), abs(lh_x - rh_x))) if lh_x != rh_x else 90.0

    # 다리 꼬임 여부
    left_hip = (int(lh_x), int(lh_y))
    right_hip = (int(rh_x), int(rh_y))
    left_knee = (int(landmarks[mp_pose.PoseLandmark.LEFT_KNEE].x * w),
                 int(landmarks[mp_pose.PoseLandmark.LEFT_KNEE].y * h))
    right_knee = (int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].x * w),
                  int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].y * h))
    left_ankle = (int(landmarks[mp_pose.PoseLandmark.LEFT_ANKLE].x * w),
                  int(landmarks[mp_pose.PoseLandmark.LEFT_ANKLE].y * h))
    right_ankle = (int(landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE].x * w),
                   int(landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE].y * h))

    leg_cross = 1 if (
        _is_intersect(left_hip, left_knee, right_hip, right_knee) or
        _is_intersect(left_hip, left_knee, right_knee, right_ankle) or
        _is_intersect(left_knee, left_ankle, right_hip, right_knee) or
        _is_intersect(left_knee, left_ankle, right_knee, right_ankle)
    ) else 0

    return {
        "neck_angle": abs(neck_angle),
        "head_tilt_angle": abs(head_tilt_angle),
        "torso_angle": abs(torso_angle),
        "spine_lean_angle": abs(spine_lean_angle),
        "shoulder_angle": abs(shoulder_angle),
        "pelvis_angle": abs(pelvis_angle),
        "leg_cross": leg_cross,
    }


def feature_dict_to_vector(feature_dict):
    """dict -> FEATURE_NAMES 순서의 list. 모델 입력 직전에 사용."""
    return [feature_dict[name] for name in FEATURE_NAMES]
