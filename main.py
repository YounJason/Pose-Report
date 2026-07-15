import cv2
import mediapipe as mp
import webview
import threading
import base64
import time
import math

mp_pose = mp.solutions.pose
pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

def ccw(A, B, C):
    val = (B[1] - A[1]) * (C[0] - B[0]) - (B[0] - A[0]) * (C[1] - B[1])
    if val > 0: return 1
    if val < 0: return -1
    return 0

def is_intersect(p1, q1, p2, q2):
    res1 = ccw(p1, q1, p2) * ccw(p1, q1, q2)
    res2 = ccw(p2, q2, p1) * ccw(p2, q2, q1)
    if res1 <= 0 and res2 <= 0:
        if res1 == 0 and res2 == 0:
            if (min(p1[0], q1[0]) <= max(p2[0], q2[0]) and min(p2[0], q2[0]) <= max(p1[0], q1[0]) and
                min(p1[1], q1[1]) <= max(p2[1], q2[1]) and min(p2[1], q2[1]) <= max(p1[1], q1[1])):
                return True
            return False
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
            
            status_list = []
            status_text = "정상"
            is_normal = 1

            if results.pose_landmarks:
                landmarks = results.pose_landmarks.landmark
                
                required_landmarks = [
                    mp_pose.PoseLandmark.NOSE,
                    mp_pose.PoseLandmark.LEFT_EAR, mp_pose.PoseLandmark.RIGHT_EAR,
                    mp_pose.PoseLandmark.LEFT_SHOULDER, mp_pose.PoseLandmark.RIGHT_SHOULDER,
                    mp_pose.PoseLandmark.LEFT_HIP, mp_pose.PoseLandmark.RIGHT_HIP,
                    mp_pose.PoseLandmark.LEFT_KNEE, mp_pose.PoseLandmark.RIGHT_KNEE,
                    mp_pose.PoseLandmark.LEFT_ANKLE, mp_pose.PoseLandmark.RIGHT_ANKLE
                ]
                
                unrecognized = any(landmarks[lm].visibility < 0.5 for lm in required_landmarks)
                
                if unrecognized:
                    status_text = "인식되지 않음"
                    is_normal = 2
                else:
                    nose = landmarks[mp_pose.PoseLandmark.NOSE]
                    left_ear = landmarks[mp_pose.PoseLandmark.LEFT_EAR]
                    right_ear = landmarks[mp_pose.PoseLandmark.RIGHT_EAR]
                    ear_center_y = (left_ear.y + right_ear.y) / 2
                    ear_center_z = (left_ear.z + right_ear.z) / 2
                    dy = nose.y - ear_center_y
                    dz = ear_center_z - nose.z
                    neck_angle = 90 - math.degrees(math.atan2(abs(dz), dy)) if dy != 0 else 0
                    if neck_angle > self.TURTLE_NECK_ANGLE_THRESHOLD:
                        status_list.append(f"거북목 위험 ({neck_angle:.1f}도)")
                        
                    left_shoulder = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER]
                    right_shoulder = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER]
                    left_hip_lm = landmarks[mp_pose.PoseLandmark.LEFT_HIP]
                    right_hip_lm = landmarks[mp_pose.PoseLandmark.RIGHT_HIP]
                    shoulder_center_y = (left_shoulder.y + right_shoulder.y) / 2
                    shoulder_center_z = (left_shoulder.z + right_shoulder.z) / 2
                    hip_center_y = (left_hip_lm.y + right_hip_lm.y) / 2
                    hip_center_z = (left_hip_lm.z + right_hip_lm.z) / 2
                    dy_torso = hip_center_y - shoulder_center_y
                    dz_torso = hip_center_z - shoulder_center_z
                    torso_angle = math.degrees(math.atan2(abs(dz_torso), dy_torso)) if dy_torso != 0 else 0
                    if torso_angle > self.TORSO_ANGLE_THRESHOLD:
                        status_list.append(f"등 굽음 위험 ({torso_angle:.1f}도)")
                        
                    ls_x = left_shoulder.x * w
                    ls_y = left_shoulder.y * h
                    rs_x = right_shoulder.x * w
                    rs_y = right_shoulder.y * h
                    shoulder_angle = math.degrees(math.atan2(abs(ls_y - rs_y), abs(ls_x - rs_x))) if ls_x != rs_x else 90.0
                    if shoulder_angle > self.SHOULDER_ANGLE_THRESHOLD:
                        status_list.append(f"어깨 비대칭 위험 ({shoulder_angle:.1f}도)")
                    
                    lh_x = left_hip_lm.x * w
                    lh_y = left_hip_lm.y * h
                    rh_x = right_hip_lm.x * w
                    rh_y = right_hip_lm.y * h
                    pelvis_angle = math.degrees(math.atan2(abs(lh_y - rh_y), abs(lh_x - rh_x))) if lh_x != rh_x else 90.0
                    if pelvis_angle > self.PELVIS_ANGLE_THRESHOLD:
                        status_list.append(f"골반 비대칭 위험 ({pelvis_angle:.1f}도)")
                    
                    le_x = left_ear.x * w
                    le_y = left_ear.y * h
                    re_x = right_ear.x * w
                    re_y = right_ear.y * h
                    head_tilt_angle = math.degrees(math.atan2(abs(le_y - re_y), abs(le_x - re_x))) if le_x != re_x else 90.0
                    if head_tilt_angle > self.HEAD_TILT_ANGLE_THRESHOLD:
                        status_list.append(f"목 기울어짐 ({head_tilt_angle:.1f}도)")
                    
                    m_shoulder_x = (ls_x + rs_x) / 2
                    m_shoulder_y = (ls_y + rs_y) / 2
                    m_hip_x = (lh_x + rh_x) / 2
                    m_hip_y = (lh_y + rh_y) / 2
                    dx_spine = m_shoulder_x - m_hip_x
                    dy_spine = m_hip_y - m_shoulder_y
                    spine_lean_angle = math.degrees(math.atan2(abs(dx_spine), dy_spine)) if dy_spine != 0 else 90.0
                    if spine_lean_angle > self.SPINE_LEAN_ANGLE_THRESHOLD:
                        status_list.append(f"상체 불균형 ({spine_lean_angle:.1f}도)")
                    
                    left_hip = (int(lh_x), int(lh_y))
                    right_hip = (int(rh_x), int(rh_y))
                    left_knee = (int(landmarks[mp_pose.PoseLandmark.LEFT_KNEE].x * w), int(landmarks[mp_pose.PoseLandmark.LEFT_KNEE].y * h))
                    right_knee = (int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].x * w), int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].y * h))
                    left_ankle = (int(landmarks[mp_pose.PoseLandmark.LEFT_ANKLE].x * w), int(landmarks[mp_pose.PoseLandmark.LEFT_ANKLE].y * h))
                    right_ankle = (int(landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE].x * w), int(landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE].y * h))
                    left_hip_knee = (left_hip, left_knee)
                    left_knee_ankle = (left_knee, left_ankle)
                    right_hip_knee = (right_hip, right_knee)
                    right_knee_ankle = (right_knee, right_ankle)
                    crossed = (
                        is_intersect(left_hip_knee[0], left_hip_knee[1], right_hip_knee[0], right_hip_knee[1]) or
                        is_intersect(left_hip_knee[0], left_hip_knee[1], right_knee_ankle[0], right_knee_ankle[1]) or
                        is_intersect(left_knee_ankle[0], left_knee_ankle[1], right_hip_knee[0], right_hip_knee[1]) or
                        is_intersect(left_knee_ankle[0], left_knee_ankle[1], right_knee_ankle[0], right_knee_ankle[1])
                    )
                    if crossed:
                        status_list.append("다리 꼬기")
                    
                    status_text = ", ".join(status_list) if status_list else "정상"
                    is_normal = 1 if status_text == "정상" else 0

                mp.solutions.drawing_utils.draw_landmarks(
                    frame,
                    results.pose_landmarks,
                    mp_pose.POSE_CONNECTIONS
                )
            else:
                status_text = "인식되지 않음"
                is_normal = 2

            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            b64_str = base64.b64encode(buffer).decode('utf-8')
            safe_text = status_text.replace("'", "\\'")
            try:
                window.evaluate_js(f"updateFrame('{b64_str}', '{safe_text}', {is_normal})")
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

    def toggle_camera(self, enabled):
        with self.lock:
            self.camera_enabled = enabled
            if not enabled and self.cap:
                self.cap.release()
                self.cap = None

if __name__ == '__main__':
    app_logic = CameraApp()
    window = webview.create_window(
        'MediaPipe Pose', 
        'index.html', 
        width=800, 
        height=600, 
        js_api=app_logic
    )
    window.events.closing += app_logic.on_closing
    threading.Thread(target=app_logic.start_camera_thread, daemon=True).start()
    webview.start()