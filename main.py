import cv2
import mediapipe as mp
import webview
import threading
import base64
import time
import math
import os
import requests
from dotenv import load_dotenv

from ml.pose_classifier import LABEL_INFO, PostureClassifier
from ml.pose_features import extract_features, feature_dict_to_vector

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

class CameraApp:
    def __init__(self):
        self.camera_enabled = False
        self.running = True
        self.current_camera_idx = 0
        self.cap = None
        self.lock = threading.Lock()
        
        self.TURTLE_NECK_ANGLE_THRESHOLD = 10.0
        self.TORSO_ANGLE_THRESHOLD = 20.0
        self.SHOULDER_ANGLE_THRESHOLD = 5.0
        self.PELVIS_ANGLE_THRESHOLD = 4.0
        self.HEAD_TILT_ANGLE_THRESHOLD = 5.0
        self.SPINE_LEAN_ANGLE_THRESHOLD = 8.0
        
        raw_key = os.getenv("SUPABASE_ANON_KEY", "")
        self.supabase_anon_key = raw_key.strip().replace('"', '').replace("'", "")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()

        # ML 분류 모델이 model/posture_model.pkl 에 존재하면 자동으로 불러와서
        # 각도 기반 규칙(rule-based) 대신 ML 기반 분석을 사용합니다.
        # 아직 모델이 없다면(초기 상태) 기존 각도 기반 로직으로 자동 폴백(fallback)됩니다.
        self.ml_classifier = PostureClassifier.load_if_exists()
        self.use_ml = self.ml_classifier is not None
        if self.use_ml:
            print("[INFO] ML 모델을 로드했습니다. ML 기반 자세 분석을 사용합니다.")
        else:
            print("[INFO] 학습된 ML 모델이 없습니다 (model/posture_model.pkl). "
                  "각도 기반(rule-based) 분석을 사용합니다.")
            print("       -> collect_data.py 로 데이터 수집 후 train_model.py 로 학습하면 자동 전환됩니다.")

    def get_supabase_key(self):
        return self.supabase_anon_key

    def setup_and_start(self, turtle, torso, shoulder, pelvis, head, spine, camera_idx):
        with self.lock:
            self.TURTLE_NECK_ANGLE_THRESHOLD = float(turtle)
            self.TORSO_ANGLE_THRESHOLD = float(torso)
            self.SHOULDER_ANGLE_THRESHOLD = float(shoulder)
            self.PELVIS_ANGLE_THRESHOLD = float(pelvis)
            self.HEAD_TILT_ANGLE_THRESHOLD = float(head)
            self.SPINE_LEAN_ANGLE_THRESHOLD = float(spine)
            self.current_camera_idx = int(camera_idx)
            self.camera_enabled = True
            if self.cap:
                self.cap.release()
                self.cap = None

    def _analyze_pose(self, landmarks, w, h):
        status_list = []
        
        neck_score = 1
        trunk_score = 1
        symmetry_penalty = 0
        leg_cross_penalty = 0
        
        required_landmarks = [
            mp_pose.PoseLandmark.NOSE,
            mp_pose.PoseLandmark.LEFT_EAR, mp_pose.PoseLandmark.RIGHT_EAR,
            mp_pose.PoseLandmark.LEFT_SHOULDER, mp_pose.PoseLandmark.RIGHT_SHOULDER,
            mp_pose.PoseLandmark.LEFT_HIP, mp_pose.PoseLandmark.RIGHT_HIP,
            mp_pose.PoseLandmark.LEFT_KNEE, mp_pose.PoseLandmark.RIGHT_KNEE,
            mp_pose.PoseLandmark.LEFT_ANKLE, mp_pose.PoseLandmark.RIGHT_ANKLE
        ]
        
        if any(landmarks[lm].visibility < 0.5 for lm in required_landmarks):
            return "인식되지 않음", 2, 0, 0.0, 0.0, 0.0, 0.0

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
        
        if neck_angle <= 10:
            neck_score = 1
        elif 10 < neck_angle <= 20:
            neck_score = 2
        else:
            neck_score = 3
            status_list.append(f"거북목 위험 ({neck_angle:.1f}도)")
            
        head_tilt_angle = math.degrees(math.atan2(abs(le_y - re_y), abs(le_x - re_x))) if le_x != re_x else 90.0
        if head_tilt_angle > self.HEAD_TILT_ANGLE_THRESHOLD:
            neck_score += 1
            status_list.append(f"목 기울어짐 ({head_tilt_angle:.1f}도)")

        dy_torso = ((left_hip_lm.y + right_hip_lm.y) / 2) - ((left_shoulder.y + right_shoulder.y) / 2)
        dz_torso = ((left_hip_lm.z + right_hip_lm.z) / 2) - ((left_shoulder.z + right_shoulder.z) / 2)
        torso_angle = math.degrees(math.atan2(abs(dz_torso), dy_torso)) if dy_torso != 0 else 0
        
        if torso_angle <= 5:
            trunk_score = 1
        elif 5 < torso_angle <= 20:
            trunk_score = 2
        else:
            trunk_score = 3
            status_list.append(f"등 굽음 위험 ({torso_angle:.1f}도)")
            
        dx_spine = ((ls_x + rs_x) / 2) - ((lh_x + rh_x) / 2)
        dy_spine = ((lh_y + rh_y) / 2) - ((ls_y + rs_y) / 2)
        spine_lean_angle = math.degrees(math.atan2(abs(dx_spine), dy_spine)) if dy_spine != 0 else 90.0
        if spine_lean_angle > self.SPINE_LEAN_ANGLE_THRESHOLD:
            trunk_score += 1
            status_list.append(f"상체 불균형 ({spine_lean_angle:.1f}도)")

        shoulder_angle = math.degrees(math.atan2(abs(ls_y - rs_y), abs(ls_x - rs_x))) if ls_x != rs_x else 90.0
        if shoulder_angle > self.SHOULDER_ANGLE_THRESHOLD:
            symmetry_penalty += 1
            status_list.append(f"어깨 비대칭 위험 ({shoulder_angle:.1f}도)")
        
        pelvis_angle = math.degrees(math.atan2(abs(lh_y - rh_y), abs(lh_x - rh_x))) if lh_x != rh_x else 90.0
        if pelvis_angle > self.PELVIS_ANGLE_THRESHOLD:
            symmetry_penalty += 1
            status_list.append(f"골반 비대칭 위험 ({pelvis_angle:.1f}도)")
        
        left_hip = (int(lh_x), int(lh_y))
        right_hip = (int(rh_x), int(rh_y))
        left_knee = (int(landmarks[mp_pose.PoseLandmark.LEFT_KNEE].x * w), int(landmarks[mp_pose.PoseLandmark.LEFT_KNEE].y * h))
        right_knee = (int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].x * w), int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].y * h))
        left_ankle = (int(landmarks[mp_pose.PoseLandmark.LEFT_ANKLE].x * w), int(landmarks[mp_pose.PoseLandmark.LEFT_ANKLE].y * h))
        right_ankle = (int(landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE].x * w), int(landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE].y * h))
        
        if (is_intersect(left_hip, left_knee, right_hip, right_knee) or
            is_intersect(left_hip, left_knee, right_knee, right_ankle) or
            is_intersect(left_knee, left_ankle, right_hip, right_knee) or
            is_intersect(left_knee, left_ankle, right_knee, right_ankle)):
            leg_cross_penalty = 2
            status_list.append("다리 꼬기")
        
        total_risk_score = neck_score + trunk_score + symmetry_penalty + leg_cross_penalty
        
        health_score = int(100 - ((total_risk_score - 2) / 10 * 100))
        health_score = max(0, min(100, health_score))
        
        status_text = ", ".join(status_list) if status_list else "정상"
        is_normal = 1 if status_text == "정상" else 0
        return status_text, is_normal, health_score, abs(neck_angle), abs(torso_angle), abs(shoulder_angle), abs(pelvis_angle)

    def _analyze_pose_ml(self, landmarks, w, h):
        """
        ML 분류기를 사용한 자세 분석. 반환 형식은 _analyze_pose()와 동일하게 맞춰서
        프론트엔드(script.js)와 나머지 파이프라인을 수정하지 않고도 그대로 동작하게 합니다.
        """
        feature_dict = extract_features(landmarks, w, h)
        if feature_dict is None:
            return "인식되지 않음", 2, 0, 0.0, 0.0, 0.0, 0.0

        vector = feature_dict_to_vector(feature_dict)
        label, confidence, _proba = self.ml_classifier.predict(vector)

        info = LABEL_INFO.get(label, {"score": 50, "text": label})
        status_text = info["text"] if label != "normal" else "정상"
        is_normal = 1 if label == "normal" else 0
        health_score = int(info["score"])

        return (
            status_text,
            is_normal,
            health_score,
            feature_dict["neck_angle"],
            feature_dict["torso_angle"],
            feature_dict["shoulder_angle"],
            feature_dict["pelvis_angle"],
        )

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

        위 자세 측정 결과를 종합적으로 분석하여 사용자의 자세 습관과 문제점을 지적해 주세요.
        답변은 읽기 쉽게 단락을 나누어 한국어로 작성해 주세요.
        마크다운을 사용하지 말고 줄글로 작성하세요.
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
            if not self.camera_enabled:
                with self.lock:
                    if self.cap:
                        self.cap.release()
                        self.cap = None
                time.sleep(0.2)
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
                
            h, w, _ = frame.shape
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb)
            
            if results.pose_landmarks:
                analyze_fn = self._analyze_pose_ml if self.use_ml else self._analyze_pose
                status_text, is_normal, score, turtle_ang, torso_ang, shoulder_ang, pelvis_ang = analyze_fn(results.pose_landmarks.landmark, w, h)
                mp.solutions.drawing_utils.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
            else:
                status_text, is_normal, score, turtle_ang, torso_ang, shoulder_ang, pelvis_ang = "인식되지 않음", 2, 0, 0.0, 0.0, 0.0, 0.0

            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            b64_str = base64.b64encode(buffer).decode('utf-8')
            safe_text = status_text.replace("'", "\\'")
            
            try:
                window.evaluate_js(f"updateFrame('{b64_str}', '{safe_text}', {is_normal}, {score}, {turtle_ang:.1f}, {torso_ang:.1f}, {shoulder_ang:.1f}, {pelvis_ang:.1f})")
            except:
                break
                
        if self.cap:
            self.cap.release()

    def change_camera(self, index):
        with self.lock:
            if self.current_camera_idx != index:
                self.current_camera_idx = index
                if self.cap:
                    self.cap.release()

    def on_closing(self):
        self.running = False

    def toggle_fullscreen(self):
        window.toggle_fullscreen()
    
    def close_window(self):
        window.destroy()

    def set_analysis_mode(self, use_ml):
        """프론트엔드에서 ML/규칙기반 모드를 토글하고 싶을 때 사용 (선택 사항)."""
        with self.lock:
            if use_ml and self.ml_classifier is None:
                print("[WARN] ML 모델이 로드되어 있지 않아 규칙 기반 모드로 유지합니다.")
                return False
            self.use_ml = bool(use_ml)
            return True

    def toggle_camera(self, enabled):
        with self.lock:
            self.camera_enabled = enabled
            if not enabled and self.cap:
                self.cap.release()
                self.cap = None

if __name__ == '__main__':
    app_logic = CameraApp()
    window = webview.create_window('Pose Report', 'index.html', width=800, height=600, js_api=app_logic)
    window.events.closing += app_logic.on_closing
    threading.Thread(target=app_logic.start_camera_thread, daemon=True).start()
    webview.start()