import cv2
import mediapipe as mp
import numpy as np
import webview
import threading
import base64
import time
import math
import os
import sys
import requests
from dotenv import load_dotenv

import pose3d_debug

current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')
load_dotenv(dotenv_path=env_path) if os.path.exists(env_path) else load_dotenv()

mp_pose = mp.solutions.pose
pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

def is_intersect(p1, q1, p2, q2):
    def ccw(A, B, C):
        val = (B[1] - A[1]) * (C[0] - B[0]) - (B[0] - A[0]) * (C[1] - B[1])
        return (val > 0) - (val < 0)

    res1 = ccw(p1, q1, p2) * ccw(p1, q1, q2)
    res2 = ccw(p2, q2, p1) * ccw(p2, q2, q1)
    if res1 <= 0 and res2 <= 0:
        if res1 == 0 and res2 == 0:
            return (min(p1[0], q1[0]) <= max(p2[0], q2[0]) and min(p2[0], q2[0]) <= max(p1[0], q1[0]) and
                    min(p1[1], q1[1]) <= max(p2[1], q2[1]) and min(p2[1], q2[1]) <= max(p1[1], q1[1]))
        return True
    return False

def _vector_angle_deg(v1, v2):

    v1 = np.asarray(v1, dtype=np.float64)
    v2 = np.asarray(v2, dtype=np.float64)
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0
    cos_val = float(np.dot(v1, v2) / (n1 * n2))
    cos_val = max(-1.0, min(1.0, cos_val))
    return math.degrees(math.acos(cos_val))

def _axis_deviation_deg(v, axis):

    angle = _vector_angle_deg(v, axis)
    return angle if angle <= 90.0 else 180.0 - angle

def _detect_leg_cross(landmarks, w, h):

    left_hip = (int(landmarks[mp_pose.PoseLandmark.LEFT_HIP].x * w), int(landmarks[mp_pose.PoseLandmark.LEFT_HIP].y * h))
    right_hip = (int(landmarks[mp_pose.PoseLandmark.RIGHT_HIP].x * w), int(landmarks[mp_pose.PoseLandmark.RIGHT_HIP].y * h))
    left_knee = (int(landmarks[mp_pose.PoseLandmark.LEFT_KNEE].x * w), int(landmarks[mp_pose.PoseLandmark.LEFT_KNEE].y * h))
    right_knee = (int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].x * w), int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].y * h))
    left_ankle = (int(landmarks[mp_pose.PoseLandmark.LEFT_ANKLE].x * w), int(landmarks[mp_pose.PoseLandmark.LEFT_ANKLE].y * h))
    right_ankle = (int(landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE].x * w), int(landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE].y * h))

    return (is_intersect(left_hip, left_knee, right_hip, right_knee) or
            is_intersect(left_hip, left_knee, right_knee, right_ankle) or
            is_intersect(left_knee, left_ankle, right_hip, right_knee) or
            is_intersect(left_knee, left_ankle, right_knee, right_ankle))

class CameraApp:
    def __init__(self):
        self.camera_enabled = False

        self.capture_active = False
        self.running = True
        self.current_camera_idx = 0
        self.cap = None
        self.lock = threading.Lock()

        self.TURTLE_NECK_ANGLE_THRESHOLD = 18.0
        self.TORSO_ANGLE_THRESHOLD = 28.0
        self.SHOULDER_ANGLE_THRESHOLD = 8.0
        self.PELVIS_ANGLE_THRESHOLD = 7.0
        self.HEAD_TILT_ANGLE_THRESHOLD = 7.0
        self.SPINE_LEAN_ANGLE_THRESHOLD = 10.0

        self.camera_source = 'webcam'

        self.debug_mode_enabled = False

        self.debug_cam_idx = pose3d_debug.DEFAULT_DEBUG_RGB_DEVICE_INDEX
        self._debug_thread = None
        self._debug_stop_event = None

        self._debug_latest_frame = None
        self._debug_frame_lock = threading.Lock()

        self._debug_first_frame_event = threading.Event()
        self.ASTRA_INIT_WATCHDOG_TIMEOUT_SEC = 10.0

        raw_key = os.getenv("SUPABASE_ANON_KEY", "")
        self.supabase_anon_key = raw_key.strip().replace('"', '').replace("'", "")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()

    def get_supabase_key(self):
        return self.supabase_anon_key

    def setup_and_start(self, turtle, torso, shoulder, pelvis, head, spine, camera_idx,
                         camera_source='webcam', debug_mode_enabled=False, debug_cam_idx=None):
        with self.lock:
            self.TURTLE_NECK_ANGLE_THRESHOLD = float(turtle)
            self.TORSO_ANGLE_THRESHOLD = float(torso)
            self.SHOULDER_ANGLE_THRESHOLD = float(shoulder)
            self.PELVIS_ANGLE_THRESHOLD = float(pelvis)
            self.HEAD_TILT_ANGLE_THRESHOLD = float(head)
            self.SPINE_LEAN_ANGLE_THRESHOLD = float(spine)

            self.camera_source = (camera_source or 'webcam').strip().lower()
            if self.camera_source not in ('webcam', 'astra'):
                self.camera_source = 'webcam'

            self.debug_mode_enabled = bool(debug_mode_enabled) and self.camera_source == 'astra'
            if debug_cam_idx not in (None, ""):
                self.debug_cam_idx = int(debug_cam_idx)

            if self.camera_source == 'webcam' and camera_idx not in (None, ""):
                self.current_camera_idx = int(camera_idx)
            self.camera_enabled = True

        self._stop_astra_capture()
        with self.lock:
            if self.cap:
                self.cap.release()
                self.cap = None
            self.capture_active = True

        if self.camera_source == 'astra':
            self._start_astra_capture()

    def _score_from_angles(self, neck_angle, head_tilt_angle, torso_angle, spine_lean_angle,
                            shoulder_angle, pelvis_angle, leg_cross):

        status_list = []

        def graded_score(angle, warn_threshold, severe_gap):
            over = angle - warn_threshold
            if over <= 0.0:
                return 1.0
            return 1.0 + (over / severe_gap) * 2.0

        def excess_penalty(angle, threshold):
            if threshold <= 0:
                return 0.0
            over = angle - threshold
            return (over / threshold) if over > 0.0 else 0.0

        turtle_warn_threshold = self.TURTLE_NECK_ANGLE_THRESHOLD
        turtle_severe_threshold = turtle_warn_threshold + 8.0
        neck_score = graded_score(neck_angle, turtle_warn_threshold, 8.0)
        if neck_angle > turtle_severe_threshold:
            status_list.append(f"거북목 위험 ({neck_angle:.1f}도)")

        head_tilt_penalty = excess_penalty(head_tilt_angle, self.HEAD_TILT_ANGLE_THRESHOLD)
        if head_tilt_penalty > 0.0:
            status_list.append(f"목 기울어짐 ({head_tilt_angle:.1f}도)")
        neck_score += head_tilt_penalty

        torso_warn_threshold = self.TORSO_ANGLE_THRESHOLD
        torso_severe_threshold = torso_warn_threshold + 10.0
        trunk_score = graded_score(torso_angle, torso_warn_threshold, 10.0)
        if torso_angle > torso_severe_threshold:
            status_list.append(f"등 굽음 위험 ({torso_angle:.1f}도)")

        spine_penalty = excess_penalty(spine_lean_angle, self.SPINE_LEAN_ANGLE_THRESHOLD)
        if spine_penalty > 0.0:
            status_list.append(f"상체 불균형 ({spine_lean_angle:.1f}도)")
        trunk_score += spine_penalty

        shoulder_penalty = excess_penalty(shoulder_angle, self.SHOULDER_ANGLE_THRESHOLD)
        if shoulder_penalty > 0.0:
            status_list.append(f"어깨 비대칭 위험 ({shoulder_angle:.1f}도)")

        pelvis_penalty = excess_penalty(pelvis_angle, self.PELVIS_ANGLE_THRESHOLD)
        if pelvis_penalty > 0.0:
            status_list.append(f"골반 비대칭 위험 ({pelvis_angle:.1f}도)")

        symmetry_penalty = shoulder_penalty + pelvis_penalty

        leg_cross_penalty = 0.0
        if leg_cross:
            leg_cross_penalty = 2.0
            status_list.append("다리 꼬기")

        total_risk_score = neck_score + trunk_score + symmetry_penalty + leg_cross_penalty

        health_score = int(round(100 - ((total_risk_score - 2) / 10 * 100)))
        health_score = max(0, min(100, health_score))

        status_text = ", ".join(status_list) if status_list else "정상"
        is_normal = 1 if status_text == "정상" else 0
        return status_text, is_normal, health_score

    def _analyze_pose(self, landmarks, w, h):

        required_landmarks = [
            mp_pose.PoseLandmark.NOSE,
            mp_pose.PoseLandmark.LEFT_EAR, mp_pose.PoseLandmark.RIGHT_EAR,
            mp_pose.PoseLandmark.LEFT_SHOULDER, mp_pose.PoseLandmark.RIGHT_SHOULDER,
            mp_pose.PoseLandmark.LEFT_HIP, mp_pose.PoseLandmark.RIGHT_HIP,
            mp_pose.PoseLandmark.LEFT_KNEE, mp_pose.PoseLandmark.RIGHT_KNEE,
            mp_pose.PoseLandmark.LEFT_ANKLE, mp_pose.PoseLandmark.RIGHT_ANKLE
        ]

        if any(landmarks[lm].visibility < 0.5 for lm in required_landmarks):
            return "인식되지 않음", 2, 0, 0.0, 0.0, 0.0, 0.0, False

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

        dy = nose.y - (left_ear.y + right_ear.y) / 2
        dz = ((left_ear.z + right_ear.z) / 2) - nose.z
        neck_angle = 90 - math.degrees(math.atan2(abs(dz), dy)) if dy != 0 else 0

        head_tilt_angle = math.degrees(math.atan2(abs(le_y - re_y), abs(le_x - re_x))) if le_x != re_x else 90.0

        dy_torso = ((left_hip_lm.y + right_hip_lm.y) / 2) - ((left_shoulder.y + right_shoulder.y) / 2)
        dz_torso = ((left_hip_lm.z + right_hip_lm.z) / 2) - ((left_shoulder.z + right_shoulder.z) / 2)
        torso_angle = math.degrees(math.atan2(abs(dz_torso), dy_torso)) if dy_torso != 0 else 0

        dx_spine = ((ls_x + rs_x) / 2) - ((lh_x + rh_x) / 2)
        dy_spine = ((lh_y + rh_y) / 2) - ((ls_y + rs_y) / 2)
        spine_lean_angle = math.degrees(math.atan2(abs(dx_spine), dy_spine)) if dy_spine != 0 else 90.0

        shoulder_angle = math.degrees(math.atan2(abs(ls_y - rs_y), abs(ls_x - rs_x))) if ls_x != rs_x else 90.0

        pelvis_angle = math.degrees(math.atan2(abs(lh_y - rh_y), abs(lh_x - rh_x))) if lh_x != rh_x else 90.0

        leg_cross = _detect_leg_cross(landmarks, w, h)

        status_text, is_normal, health_score = self._score_from_angles(
            neck_angle, head_tilt_angle, torso_angle, spine_lean_angle,
            shoulder_angle, pelvis_angle, leg_cross
        )
        return status_text, is_normal, health_score, abs(neck_angle), abs(torso_angle), abs(shoulder_angle), abs(pelvis_angle), bool(leg_cross)

    def _analyze_pose_3d(self, landmarks, points3d, valid, w, h):

        required_landmarks = [
            mp_pose.PoseLandmark.NOSE,
            mp_pose.PoseLandmark.LEFT_EAR, mp_pose.PoseLandmark.RIGHT_EAR,
            mp_pose.PoseLandmark.LEFT_SHOULDER, mp_pose.PoseLandmark.RIGHT_SHOULDER,
            mp_pose.PoseLandmark.LEFT_HIP, mp_pose.PoseLandmark.RIGHT_HIP,
            mp_pose.PoseLandmark.LEFT_KNEE, mp_pose.PoseLandmark.RIGHT_KNEE,
            mp_pose.PoseLandmark.LEFT_ANKLE, mp_pose.PoseLandmark.RIGHT_ANKLE
        ]
        if landmarks is None or any(landmarks[lm].visibility < 0.5 for lm in required_landmarks):
            return "인식되지 않음", 2, 0, 0.0, 0.0, 0.0, 0.0, False

        angle_landmarks_3d = [
            mp_pose.PoseLandmark.LEFT_EAR, mp_pose.PoseLandmark.RIGHT_EAR,
            mp_pose.PoseLandmark.LEFT_SHOULDER, mp_pose.PoseLandmark.RIGHT_SHOULDER,
            mp_pose.PoseLandmark.LEFT_HIP, mp_pose.PoseLandmark.RIGHT_HIP,
        ]
        if points3d is None or valid is None or any(not valid[lm.value] for lm in angle_landmarks_3d):
            return "인식되지 않음", 2, 0, 0.0, 0.0, 0.0, 0.0, False

        def p3(lm):
            return points3d[lm.value].astype(np.float64)

        le3d = p3(mp_pose.PoseLandmark.LEFT_EAR)
        re3d = p3(mp_pose.PoseLandmark.RIGHT_EAR)
        ls3d = p3(mp_pose.PoseLandmark.LEFT_SHOULDER)
        rs3d = p3(mp_pose.PoseLandmark.RIGHT_SHOULDER)
        lh3d = p3(mp_pose.PoseLandmark.LEFT_HIP)
        rh3d = p3(mp_pose.PoseLandmark.RIGHT_HIP)

        mid_ear = (le3d + re3d) / 2.0
        mid_shoulder = (ls3d + rs3d) / 2.0
        mid_hip = (lh3d + rh3d) / 2.0

        neck_vec = mid_ear - mid_shoulder
        neck_angle = math.degrees(math.atan2(abs(neck_vec[2]), abs(neck_vec[1])))

        head_tilt_angle = math.degrees(
            math.atan2(abs(re3d[1] - le3d[1]), abs(re3d[0] - le3d[0]))
        ) if abs(re3d[0] - le3d[0]) > 1e-6 else 90.0

        torso_vec = mid_hip - mid_shoulder
        torso_angle = math.degrees(math.atan2(abs(torso_vec[2]), abs(torso_vec[1])))

        spine_lean_angle = math.degrees(math.atan2(abs(torso_vec[0]), abs(torso_vec[1])))

        shoulder_angle = math.degrees(
            math.atan2(abs(rs3d[1] - ls3d[1]), abs(rs3d[0] - ls3d[0]))
        ) if abs(rs3d[0] - ls3d[0]) > 1e-6 else 90.0

        pelvis_angle = math.degrees(
            math.atan2(abs(rh3d[1] - lh3d[1]), abs(rh3d[0] - lh3d[0]))
        ) if abs(rh3d[0] - lh3d[0]) > 1e-6 else 90.0

        leg_cross = _detect_leg_cross(landmarks, w, h)

        status_text, is_normal, health_score = self._score_from_angles(
            neck_angle, head_tilt_angle, torso_angle, spine_lean_angle,
            shoulder_angle, pelvis_angle, leg_cross
        )
        return status_text, is_normal, health_score, abs(neck_angle), abs(torso_angle), abs(shoulder_angle), abs(pelvis_angle), bool(leg_cross)

    def generate_llm_advice(self, metrics):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={self.gemini_api_key}"

        prompt = f"""
        당신은 자세 교정 전문 AI 트레이너입니다.
        사용자의 60초간 측정한 자세 데이터는 다음과 같습니다:

        - 종합 자세 점수: {metrics.get('score')}점 / 100점
        - 거북목 평균 각도: {metrics.get('turtle')}° (기준치: {self.TURTLE_NECK_ANGLE_THRESHOLD}° 이하)
        - 등/허리 굽음 평균 각도: {metrics.get('torso')}° (기준치: {self.TORSO_ANGLE_THRESHOLD}° 이하)
        - 어깨 비대칭 평균 각도: {metrics.get('shoulder')}° (기준치: {self.SHOULDER_ANGLE_THRESHOLD}° 이하)
        - 골반 비대칭 평균 각도: {metrics.get('pelvis')}° (기준치: {self.PELVIS_ANGLE_THRESHOLD}° 이하)
        - 다리 꼬기 지속 시간: 측정 60초 중 약 {metrics.get('legCrossSeconds', 0)}초 동안 다리를 꼰 상태였습니다.

        위 자세 측정 결과를 종합적으로 분석하여 사용자의 자세 습관과 문제점, 추천하는 방향을 조언하세요.
        답변은 읽기 쉽게 1문단 정도로 간결하게 한국어로 작성하세요.
        마크다운을 사용하지 말고 줄글로 작성하세요.
        사용자는 이미 해당 수치를 알고 있습니다. 조언만 출력하세요.
        """

        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }

        try:
            res = requests.post(url, headers=headers, json=payload, timeout=12)
            if res.status_code == 200:
                data = res.json()
                return data['candidates'][0]['content']['parts'][0]['text']
            else:
                print(f"Error: {res.text}")
                return f"피드백 생성 중 오류가 발생했습니다: {res.text}"
        except Exception as e:
            print(f"Error: {str(e)}")
            return f"피드백 생성 중 오류가 발생했습니다: {str(e)}"

    def start_camera_thread(self):

        while self.running:
            time.sleep(0.01)
            if not self.capture_active:
                with self.lock:
                    if self.cap:
                        self.cap.release()
                        self.cap = None
                time.sleep(0.2)
                continue

            if self.camera_source == 'astra':
                with self._debug_frame_lock:
                    pending = self._debug_latest_frame
                    self._debug_latest_frame = None
                if pending is None:
                    time.sleep(0.01)
                    continue
                if self.camera_enabled:
                    frame, landmarks, w, h, points3d, valid = pending
                    self._process_and_push_astra_frame(frame, landmarks, w, h, points3d, valid)
                continue

            with self.lock:
                if self.cap is None or not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.current_camera_idx)
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 800)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 600)

            success, frame = self.cap.read()
            if not success:
                time.sleep(0.03)
                continue

            if not self.camera_enabled:
                continue

            h, w, _ = frame.shape
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb)
            landmarks = results.pose_landmarks
            if landmarks:
                mp.solutions.drawing_utils.draw_landmarks(frame, landmarks, mp_pose.POSE_CONNECTIONS)
                status_text, is_normal, score, turtle_ang, torso_ang, shoulder_ang, pelvis_ang, leg_cross = self._analyze_pose(landmarks.landmark, w, h)
            else:
                status_text, is_normal, score, turtle_ang, torso_ang, shoulder_ang, pelvis_ang, leg_cross = "인식되지 않음", 2, 0, 0.0, 0.0, 0.0, 0.0, False
            self._push_frame_to_webview(frame, status_text, is_normal, score, turtle_ang, torso_ang, shoulder_ang, pelvis_ang, leg_cross)

        with self.lock:
            if self.cap:
                self.cap.release()
                self.cap = None

    def _process_and_push_astra_frame(self, frame, landmarks, w, h, points3d, valid):

        if landmarks is not None and points3d is not None:
            status_text, is_normal, score, turtle_ang, torso_ang, shoulder_ang, pelvis_ang, leg_cross =\
                self._analyze_pose_3d(landmarks.landmark, points3d, valid, w, h)
        else:
            status_text, is_normal, score, turtle_ang, torso_ang, shoulder_ang, pelvis_ang, leg_cross = "인식되지 않음", 2, 0, 0.0, 0.0, 0.0, 0.0, False

        self._push_frame_to_webview(frame, status_text, is_normal, score, turtle_ang, torso_ang, shoulder_ang, pelvis_ang, leg_cross)

    def _push_frame_to_webview(self, frame, status_text, is_normal, score, turtle_ang, torso_ang, shoulder_ang, pelvis_ang, leg_cross):

        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        b64_str = base64.b64encode(buffer).decode('utf-8')
        safe_text = status_text.replace("'", "\\'")
        leg_cross_js = 'true' if leg_cross else 'false'

        try:
            window.evaluate_js(f"updateFrame('{b64_str}', '{safe_text}', {is_normal}, {score}, {turtle_ang:.1f}, {torso_ang:.1f}, {shoulder_ang:.1f}, {pelvis_ang:.1f}, {leg_cross_js})")
        except Exception as e:

            print(f"[camera] evaluate_js 실패, 이번 프레임은 건너뜀: {e}")

    def _is_camera_enabled(self):
        with self.lock:
            return self.camera_enabled

    def _on_astra_frame(self, frame, landmarks, w, h, points3d, valid):

        with self._debug_frame_lock:
            self._debug_latest_frame = (frame, landmarks, w, h, points3d, valid)

        self._debug_first_frame_event.set()

    def change_camera(self, index):
        with self.lock:
            if self.current_camera_idx != index:
                self.current_camera_idx = index
                if self.cap:
                    self.cap.release()

    def on_closing(self):
        self.running = False
        self.capture_active = False
        self._stop_astra_capture()

    def toggle_fullscreen(self):
        window.toggle_fullscreen()

    def close_window(self):
        window.destroy()

    def toggle_camera(self, enabled):

        with self.lock:
            self.camera_enabled = enabled

    def _start_astra_capture(self):

        if self.camera_source != 'astra':
            return
        if self._debug_thread is not None and self._debug_thread.is_alive():
            return

        if not os.path.exists(pose3d_debug.CALIB_FILE):
            print(f"[Astra Pro] 캘리브레이션 파일이 없습니다: {pose3d_debug.CALIB_FILE}")
            print("[Astra Pro] 먼저 'python main.py calibrate' 를 실행해 캘리브레이션을 완료하세요.")
            try:
                window.evaluate_js(
                    "updateFrame('', 'Astra Pro 캘리브레이션 필요 (python main.py calibrate)', 2, 0, 0.0, 0.0, 0.0, 0.0, false)"
                )
            except Exception:
                pass
            return

        self._debug_stop_event = threading.Event()
        with self._debug_frame_lock:
            self._debug_latest_frame = None
        self._debug_first_frame_event.clear()
        self._debug_thread = threading.Thread(
            target=pose3d_debug.run_debug_skeleton_viewer,
            args=(self._debug_stop_event,),
            kwargs={
                "rgb_device_index": self.debug_cam_idx,

                "frame_callback": self._on_astra_frame,

                "show_viewer": self.debug_mode_enabled,

                "inference_enabled": self._is_camera_enabled,

                "debug": self.debug_mode_enabled,
            },
            daemon=True,
        )
        self._debug_thread.start()

        threading.Thread(target=self._watch_astra_capture_startup, daemon=True).start()

    def _watch_astra_capture_startup(self):

        got_frame = self._debug_first_frame_event.wait(timeout=self.ASTRA_INIT_WATCHDOG_TIMEOUT_SEC)
        if got_frame or self._debug_stop_event is None or self._debug_stop_event.is_set():
            return
        print(
            f"[Astra 캡처][감시] {self.ASTRA_INIT_WATCHDOG_TIMEOUT_SEC:.0f}초 안에 "
            "첫 프레임을 받지 못했습니다. AstraCamera 초기화(OpenNI2 호출) 도중 "
            "멈춰있을 가능성이 있습니다. 장치를 재연결하거나 앱을 재시작해보세요.",
            flush=True,
        )
        try:
            window.evaluate_js(
                "updateFrame('', 'Astra Pro 초기화가 지연되고 있습니다 (장치 재연결/재시작 필요할 수 있음)', 2, 0, 0.0, 0.0, 0.0, 0.0, false)"
            )
        except Exception:
            pass

    def _stop_astra_capture(self):
        if self._debug_stop_event is not None:
            self._debug_stop_event.set()
        if self._debug_thread is not None:
            self._debug_thread.join(timeout=3.0)
        self._debug_thread = None
        self._debug_stop_event = None

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'calibrate':

        cam_idx = int(sys.argv[2]) if len(sys.argv) > 2 else None
        pose3d_debug.run_calibration(rgb_device_index=cam_idx)
    else:
        app_logic = CameraApp()
        window = webview.create_window('Pose Report', 'index.html', width=800, height=600, js_api=app_logic)
        window.events.closing += app_logic.on_closing
        threading.Thread(target=app_logic.start_camera_thread, daemon=True).start()
        webview.start()