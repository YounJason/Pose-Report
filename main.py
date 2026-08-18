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
import json
import requests
from dotenv import load_dotenv

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

# ============================================================
# Astra Pro (depth) capture, calibration, and 3D skeleton debug
# viewer support. Originally in pose3d_debug.py, merged here.
# ============================================================

CHECKERBOARD = (9, 6)
SQUARE_SIZE = 0.029

RGB_RESOLUTION = (640, 480)
DEPTH_RESOLUTION = (640, 480)
FPS = 30

DEFAULT_DEBUG_RGB_DEVICE_INDEX = 1

OPENNI_REDIST_PATH = os.environ.get("OPENNI2_REDIST", r"C:\Program Files\OpenNI2\Redist")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CALIB_DIR = os.path.join(BASE_DIR, "calibration_data")
CALIB_FILE = os.path.join(CALIB_DIR, "stereo_calibration.json")

class AstraCamera:

    def __init__(
        self,
        openni_redist=OPENNI_REDIST_PATH,
        rgb_device_index=DEFAULT_DEBUG_RGB_DEVICE_INDEX,
        depth_resolution=DEPTH_RESOLUTION,
        rgb_resolution=RGB_RESOLUTION,
        fps=FPS,
        debug=False,
    ):
        self._debug = debug

        from openni import openni2
        from openni import _openni2 as c_api

        self._openni2 = openni2
        self._c_api = c_api

        self.dev = None
        self.depth_stream = None
        self.ir_stream = None
        self.cap = None
        self._depth_started = False
        self._ir_started = False
        self._depth_mirror_supported = True
        self._ir_mirror_supported = True

        try:
            if self._debug:
                print("[Astra][진단]   openni2.initialize 시작", flush=True)
            openni2.initialize(openni_redist)
            if self._debug:
                print("[Astra][진단]   openni2.initialize 완료", flush=True)

            if self._debug:
                print("[Astra][진단]   Device.open_any() 시작", flush=True)
            self.dev = openni2.Device.open_any()
            if self._debug:
                print("[Astra][진단]   Device.open_any() 완료", flush=True)

            if self._debug:
                print("[Astra][진단]   create_depth_stream() 시작", flush=True)
            self.depth_stream = self.dev.create_depth_stream()
            if self._debug:
                print("[Astra][진단]   create_depth_stream() 완료", flush=True)

            if self._debug:
                print("[Astra][진단]   depth_stream.set_video_mode() 시작", flush=True)
            self.depth_stream.set_video_mode(
                c_api.OniVideoMode(
                    pixelFormat=c_api.OniPixelFormat.ONI_PIXEL_FORMAT_DEPTH_1_MM,
                    resolutionX=depth_resolution[0],
                    resolutionY=depth_resolution[1],
                    fps=fps,
                )
            )
            if self._debug:
                print("[Astra][진단]   depth_stream.set_video_mode() 완료", flush=True)
            try:
                self.depth_stream.set_mirroring_enabled(False)
            except Exception as e:
                self._depth_mirror_supported = False
                print("[Astra][경고] Depth 스트림 미러링 설정 API 미지원. 소프트웨어 flip으로 대체:", e)

            if self._debug:
                print("[Astra][진단]   create_ir_stream() 시작", flush=True)
            try:
                self.ir_stream = self.dev.create_ir_stream()
                if self._debug:
                    print("[Astra][진단]   create_ir_stream() 완료", flush=True)
                self.ir_stream.set_video_mode(
                    c_api.OniVideoMode(
                        pixelFormat=c_api.OniPixelFormat.ONI_PIXEL_FORMAT_GRAY16,
                        resolutionX=640,
                        resolutionY=480,
                        fps=fps,
                    )
                )
                try:
                    self.ir_stream.set_mirroring_enabled(False)
                except Exception as e:
                    self._ir_mirror_supported = False
                    print("[Astra][경고] IR 스트림 미러링 설정 API 미지원. 소프트웨어 flip으로 대체:", e)
            except Exception as e:
                print("[Astra][경고] IR 스트림을 생성할 수 없습니다:", e)

            if self._debug:
                print(f"[Astra][진단]   RGB cv2.VideoCapture({rgb_device_index}) 시작", flush=True)
            self.cap = cv2.VideoCapture(rgb_device_index)
            if self._debug:
                print("[Astra][진단]   RGB cv2.VideoCapture() 생성자 반환됨", flush=True)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, rgb_resolution[0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, rgb_resolution[1])
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            if self._debug:
                print(f"[Astra][진단]   RGB cap.isOpened()={self.cap.isOpened()}", flush=True)

            if not self.cap.isOpened():
                print("[Astra][경고] RGB(UVC) 카메라를 열지 못했습니다. 디버그 카메라 인덱스를 확인하세요.")
        except Exception:
            print("[Astra][오류] 초기화 도중 예외 발생. 지금까지 만든 핸들을 정리합니다", flush=True)
            self.release()
            raise

    def start_depth(self):
        if self._ir_started:
            self.stop_ir()
        if not self._depth_started:
            self.depth_stream.start()
            self._depth_started = True

    def stop_depth(self):
        if self._depth_started:
            self.depth_stream.stop()
            self._depth_started = False

    def start_ir(self):
        if self.ir_stream is None:
            return
        if self._depth_started:
            self.stop_depth()
        if not self._ir_started:
            self.ir_stream.start()
            self._ir_started = True

    def stop_ir(self):
        if self.ir_stream is not None and self._ir_started:
            self.ir_stream.stop()
            self._ir_started = False

    def get_depth_frame(self, timeout_ms=1000):

        if not self._depth_started:
            return None
        ready = self._openni2.wait_for_any_stream([self.depth_stream], timeout=timeout_ms)
        if ready is None:
            return None
        frame = self.depth_stream.read_frame()
        buf = np.frombuffer(frame.get_buffer_as_uint16(), dtype=np.uint16)
        buf = buf.reshape(frame.height, frame.width).copy()
        if not self._depth_mirror_supported:
            buf = cv2.flip(buf, 1)
        return buf

    def get_ir_frame(self, timeout_ms=1000):

        if self.ir_stream is None or not self._ir_started:
            return None
        ready = self._openni2.wait_for_any_stream([self.ir_stream], timeout=timeout_ms)
        if ready is None:
            return None
        frame = self.ir_stream.read_frame()
        buf = np.frombuffer(frame.get_buffer_as_uint16(), dtype=np.uint16)
        buf = buf.reshape(frame.height, frame.width)
        img8 = cv2.normalize(buf, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        if not self._ir_mirror_supported:
            img8 = cv2.flip(img8, 1)
        return img8

    def get_color_frame(self):

        if not self.cap.isOpened():
            return None
        ret, frame = self.cap.read()
        if not ret:
            return None
        return frame

    def release(self):

        try:
            self.stop_depth()
        except Exception:
            pass
        try:
            self.stop_ir()
        except Exception:
            pass
        try:
            if self.depth_stream is not None:
                self.depth_stream.close()
        except Exception:
            pass
        try:
            if self.ir_stream is not None:
                self.ir_stream.close()
        except Exception:
            pass
        try:
            if self.dev is not None:
                self.dev.close()
        except Exception:
            pass
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        try:
            self._openni2.unload()
        except Exception:
            pass

        self.depth_stream = None
        self.ir_stream = None
        self.dev = None

def load_calibration(path=CALIB_FILE):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    K_rgb = np.array(data["rgb_camera_matrix"], dtype=np.float64)
    dist_rgb = np.array(data["rgb_dist_coeffs"], dtype=np.float64)
    K_ir = np.array(data["ir_camera_matrix"], dtype=np.float64)
    dist_ir = np.array(data["ir_dist_coeffs"], dtype=np.float64)

    R = np.array(data["R"], dtype=np.float64)
    T = np.array(data["T"], dtype=np.float64).reshape(3, 1)

    return K_rgb, dist_rgb, K_ir, dist_ir, R, T

def align_depth_to_color(depth_mm, K_depth, dist_depth, K_color, R, T, color_shape,
                          hole_fill_kernel_size=7):

    h_c, w_c = color_shape[:2]

    ys, xs = np.nonzero(depth_mm > 0)
    if len(xs) == 0:
        return np.zeros((h_c, w_c), dtype=np.float32)

    zs = depth_mm[ys, xs].astype(np.float32) / 1000.0

    pts = np.stack([xs, ys], axis=1).astype(np.float32).reshape(-1, 1, 2)
    undist = cv2.undistortPoints(pts, K_depth, dist_depth, P=K_depth).reshape(-1, 2)

    fx_d, fy_d = K_depth[0, 0], K_depth[1, 1]
    cx_d, cy_d = K_depth[0, 2], K_depth[1, 2]

    x = (undist[:, 0] - cx_d) / fx_d * zs
    y = (undist[:, 1] - cy_d) / fy_d * zs
    z = zs
    pts_depth = np.stack([x, y, z], axis=1)

    pts_color = (R @ pts_depth.T + T).T

    fx_c, fy_c = K_color[0, 0], K_color[1, 1]
    cx_c, cy_c = K_color[0, 2], K_color[1, 2]

    valid = pts_color[:, 2] > 0
    pts_color = pts_color[valid]
    if len(pts_color) == 0:
        return np.zeros((h_c, w_c), dtype=np.float32)

    u = pts_color[:, 0] * fx_c / pts_color[:, 2] + cx_c
    v = pts_color[:, 1] * fy_c / pts_color[:, 2] + cy_c
    z_c = pts_color[:, 2]

    u_i = u.astype(np.int32)
    v_i = v.astype(np.int32)

    aligned = np.zeros((h_c, w_c), dtype=np.float32)
    in_bounds = (u_i >= 0) & (u_i < w_c) & (v_i >= 0) & (v_i < h_c)
    u_i, v_i, z_c = u_i[in_bounds], v_i[in_bounds], z_c[in_bounds]

    order = np.argsort(-z_c)
    u_i, v_i, z_c = u_i[order], v_i[order], z_c[order]
    aligned[v_i, u_i] = z_c

    aligned = _fill_small_holes(aligned, kernel_size=hole_fill_kernel_size)
    return aligned

def _fill_small_holes(depth_map, kernel_size=5):
    valid_mask = (depth_map > 0).astype(np.uint8)
    kernel = np.ones((kernel_size, kernel_size), np.uint8)

    dilated_mask = cv2.dilate(valid_mask, kernel)
    inf_filled = np.where(depth_map > 0, depth_map, np.float32(1e6))
    nearest = cv2.erode(inf_filled, kernel)

    fill_target = (depth_map == 0) & (dilated_mask > 0)
    out = depth_map.copy()
    out[fill_target] = nearest[fill_target]
    return out

class DepthPersistence:

    def __init__(self, max_age_frames=10):
        self.max_age_frames = max_age_frames
        self.buffer = None
        self.age = None

    def update(self, aligned_depth):
        if self.buffer is None or self.buffer.shape != aligned_depth.shape:
            self.buffer = np.zeros_like(aligned_depth)
            self.age = np.zeros(aligned_depth.shape, dtype=np.int32)

        valid = aligned_depth > 0
        self.buffer[valid] = aligned_depth[valid]
        self.age[valid] = 0
        self.age[~valid] += 1

        stale = self.age > self.max_age_frames
        self.buffer[stale] = 0

        return np.where(aligned_depth > 0, aligned_depth, self.buffer)

    def reset(self):
        self.buffer = None
        self.age = None

def sample_depth_near(aligned_depth, u, v, max_radius=15):

    h, w = aligned_depth.shape
    if not (0 <= v < h and 0 <= u < w):
        return 0.0
    if aligned_depth[v, u] > 0:
        return float(aligned_depth[v, u])

    for r in range(1, max_radius + 1):
        y0, y1 = max(0, v - r), min(h, v + r + 1)
        x0, x1 = max(0, u - r), min(w, u + r + 1)
        patch = aligned_depth[y0:y1, x0:x1]
        valid = patch > 0
        if np.any(valid):
            return float(patch[valid].min())
    return 0.0

def backproject_point(u, v, depth_m, K_color, dist_color=None):

    if depth_m is None or depth_m <= 0:
        return None

    if dist_color is not None:
        pt = np.array([[[u, v]]], dtype=np.float32)
        undist = cv2.undistortPoints(pt, K_color, dist_color, P=K_color).reshape(2)
        u, v = float(undist[0]), float(undist[1])

    fx, fy = K_color[0, 0], K_color[1, 1]
    cx, cy = K_color[0, 2], K_color[1, 2]

    x = (u - cx) / fx * depth_m
    y = (v - cy) / fy * depth_m
    z = depth_m
    return np.array([x, y, z], dtype=np.float32)

class SkeletonViewer:
    def __init__(self, connections, window_name="Pose Report - Debug 3D Skeleton Viewer", width=960, height=720):

        import open3d as o3d
        self._o3d = o3d

        self.connections = list(connections)

        self.vis = o3d.visualization.Visualizer()
        self.vis.create_window(window_name, width=width, height=height)

        self.joint_cloud = o3d.geometry.PointCloud()
        self.bone_lines = o3d.geometry.LineSet()

        self.vis.add_geometry(self.joint_cloud)

        self._bone_lines_added = False

        opt = self.vis.get_render_option()
        if opt is not None:
            opt.point_size = 8.0
            opt.line_width = 3.0
            opt.background_color = np.asarray([0.05, 0.05, 0.05])

        self._first_update = True

    def update(self, points3d, valid_mask):
        o3d = self._o3d
        pts = points3d.copy().astype(np.float64)

        pts[:, 1] *= -1
        pts[:, 2] *= -1

        valid_idx = np.where(valid_mask)[0]
        if len(valid_idx) > 0:
            self.joint_cloud.points = o3d.utility.Vector3dVector(pts[valid_idx])
            self.joint_cloud.paint_uniform_color([1.0, 0.2, 0.2])
        else:
            self.joint_cloud.points = o3d.utility.Vector3dVector(np.zeros((0, 3)))

        lines = []
        for (a, b) in self.connections:
            if a < len(valid_mask) and b < len(valid_mask) and valid_mask[a] and valid_mask[b]:
                lines.append([a, b])

        self.bone_lines.points = o3d.utility.Vector3dVector(pts)
        if len(lines) > 0:
            self.bone_lines.lines = o3d.utility.Vector2iVector(np.array(lines))
            self.bone_lines.colors = o3d.utility.Vector3dVector(
                np.tile([0.2, 1.0, 0.3], (len(lines), 1))
            )
        else:
            self.bone_lines.lines = o3d.utility.Vector2iVector(np.zeros((0, 2), dtype=np.int32))

        self.vis.update_geometry(self.joint_cloud)

        if len(lines) > 0:
            if not self._bone_lines_added:
                self.vis.add_geometry(self.bone_lines, reset_bounding_box=False)
                self._bone_lines_added = True
            else:
                self.vis.update_geometry(self.bone_lines)
        else:
            if self._bone_lines_added:
                self.vis.remove_geometry(self.bone_lines, reset_bounding_box=False)
                self._bone_lines_added = False

        if self._first_update and len(valid_idx) > 0:
            self.vis.reset_view_point(True)
            self._first_update = False

    def poll(self):

        alive = self.vis.poll_events()
        self.vis.update_renderer()
        return alive

    def close(self):
        self.vis.destroy_window()

class StereoCalibrator:

    def __init__(self, camera: AstraCamera):
        self.camera = camera
        self.objp = self._make_object_points()

        self.obj_points = []
        self.rgb_points = []
        self.ir_points = []

        self._capture_requested = False

    @staticmethod
    def _make_object_points():
        cols, rows = CHECKERBOARD
        objp = np.zeros((cols * rows, 3), np.float32)
        objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
        objp *= SQUARE_SIZE
        return objp

    def _mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self._capture_requested = True

    def run(self):
        self.camera.start_ir()

        win_rgb = "RGB - click / space to capture, c: calibrate, q: quit"
        win_ir = "IR - click / space to capture, c: calibrate, q: quit"
        cv2.namedWindow(win_rgb)
        cv2.namedWindow(win_ir)
        cv2.setMouseCallback(win_rgb, self._mouse_callback)
        cv2.setMouseCallback(win_ir, self._mouse_callback)

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        cols, rows = CHECKERBOARD
        n_captured = 0

        print("=" * 60)
        print(f"체커보드 내부 코너: {cols} x {rows},  한 칸 크기: {SQUARE_SIZE*1000:.1f} mm")
        print("마우스 좌클릭 또는 스페이스바로 캡처 / c: 캘리브레이션 실행 / q: 종료")
        print("=" * 60)

        last_rgb_gray_shape = None
        last_ir_shape = None
        no_frame_count = 0

        while True:
            rgb = self.camera.get_color_frame()
            ir = self.camera.get_ir_frame()
            if rgb is None or ir is None:
                no_frame_count += 1
                if no_frame_count == 1 or no_frame_count % 60 == 0:
                    missing = []
                    if rgb is None:
                        missing.append("RGB")
                    if ir is None:
                        missing.append("IR")
                    print(f"[대기중] {'/'.join(missing)} 프레임을 받지 못했습니다 "
                          f"(카메라 연결/드라이버/장치 인덱스를 확인하세요)")
                key = cv2.waitKey(30) & 0xFF
                if key == ord("q"):
                    print("사용자 종료")
                    break
                continue
            no_frame_count = 0

            rgb_disp = rgb.copy()
            ir_disp = cv2.cvtColor(ir, cv2.COLOR_GRAY2BGR)

            gray_rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
            last_rgb_gray_shape = gray_rgb.shape[::-1]
            last_ir_shape = ir.shape[::-1]

            found_rgb, corners_rgb = cv2.findChessboardCorners(
                gray_rgb, (cols, rows),
                cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE,
            )
            found_ir, corners_ir = cv2.findChessboardCorners(
                ir, (cols, rows),
                cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE,
            )

            if found_rgb:
                corners_rgb = cv2.cornerSubPix(gray_rgb, corners_rgb, (11, 11), (-1, -1), criteria)
                cv2.drawChessboardCorners(rgb_disp, (cols, rows), corners_rgb, found_rgb)

            if found_ir:
                corners_ir = cv2.cornerSubPix(ir, corners_ir, (11, 11), (-1, -1), criteria)
                cv2.drawChessboardCorners(ir_disp, (cols, rows), corners_ir, found_ir)

            status = (
                f"Captured: {n_captured}   "
                f"RGB:{'OK' if found_rgb else '--'}  IR:{'OK' if found_ir else '--'}"
            )
            color = (0, 255, 0) if (found_rgb and found_ir) else (0, 0, 255)
            cv2.putText(rgb_disp, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            cv2.putText(ir_disp, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            cv2.imshow(win_rgb, rgb_disp)
            cv2.imshow(win_ir, ir_disp)

            key = cv2.waitKey(1) & 0xFF
            do_capture = self._capture_requested or key == ord(" ")
            self._capture_requested = False

            if do_capture:
                if found_rgb and found_ir:
                    self.obj_points.append(self.objp.copy())
                    self.rgb_points.append(corners_rgb)
                    self.ir_points.append(corners_ir)
                    n_captured += 1
                    print(f"[캡처됨] 총 {n_captured}장")
                else:
                    print("체커보드가 RGB/IR 양쪽 모두에서 검출되지 않아 캡처를 건너뜁니다.")

            if key == ord("q"):
                print("사용자 종료")
                break

            if key == ord("c"):
                if n_captured < 5:
                    print(f"최소 5장 이상 캡처해야 합니다. (현재 {n_captured}장)")
                else:
                    self._calibrate(last_rgb_gray_shape, last_ir_shape)
                    break

        cv2.destroyAllWindows()
        self.camera.stop_ir()

    def _calibrate(self, rgb_size, ir_size):
        print("\n[1/2] 개별 카메라 내부파라미터 계산 중")
        ret_rgb, K_rgb, dist_rgb, _, _ = cv2.calibrateCamera(
            self.obj_points, self.rgb_points, rgb_size, None, None
        )
        ret_ir, K_ir, dist_ir, _, _ = cv2.calibrateCamera(
            self.obj_points, self.ir_points, ir_size, None, None
        )
        print(f"  RGB 재투영 오차: {ret_rgb:.4f} px")
        print(f"  IR  재투영 오차: {ret_ir:.4f} px")

        print("[2/2] 스테레오 캘리브레이션 (RGB <-> IR/Depth) 중")
        flags = cv2.CALIB_FIX_INTRINSIC
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-5)

        ret, K_rgb, dist_rgb, K_ir, dist_ir, R, T, E, F = cv2.stereoCalibrate(
            self.obj_points,
            self.rgb_points,
            self.ir_points,
            K_rgb, dist_rgb,
            K_ir, dist_ir,
            rgb_size,
            criteria=criteria,
            flags=flags,
        )
        print(f"  스테레오 RMS 재투영 오차: {ret:.4f} px")

        R_d2c = R.T
        T_d2c = -R.T @ T

        data = {
            "description": "R, T는 Depth(IR) 좌표계를 RGB 좌표계로 변환합니다: P_rgb = R @ P_depth + T",
            "rgb_camera_matrix": K_rgb.tolist(),
            "rgb_dist_coeffs": dist_rgb.tolist(),
            "ir_camera_matrix": K_ir.tolist(),
            "ir_dist_coeffs": dist_ir.tolist(),
            "R": R_d2c.tolist(),
            "T": T_d2c.reshape(3).tolist(),
            "rgb_size": list(rgb_size),
            "ir_size": list(ir_size),
            "reproj_error_rgb": ret_rgb,
            "reproj_error_ir": ret_ir,
            "reproj_error_stereo": ret,
            "num_captures": len(self.obj_points),
        }

        os.makedirs(CALIB_DIR, exist_ok=True)
        with open(CALIB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"\n캘리브레이션 결과 저장 완료: {CALIB_FILE}")

def run_calibration(rgb_device_index=None):

    cam = AstraCamera(
        rgb_device_index=rgb_device_index if rgb_device_index is not None else DEFAULT_DEBUG_RGB_DEVICE_INDEX
    )
    try:
        calibrator = StereoCalibrator(cam)
        calibrator.run()
    finally:
        cam.release()

def preinitialize_astra_camera(rgb_device_index=None, debug=False):
    """AstraCamera 생성과 depth 스트림 시작을 메인 스레드에서 미리 수행한다.

    일부 PC(특히 데스크톱의 서드파티 USB3 컨트롤러)에서는 OpenNI2의
    device open / create_depth_stream 호출을 메인 스레드가 아닌 스레드에서
    수행하면 예외 없이 그대로 멈추거나 프로세스가 종료되는 문제가 있다.
    따라서 이 함수는 webview.start() 로 메인 스레드가 이벤트 루프에
    진입하기 전에 호출되어야 한다.

    성공하면 (cam, K_rgb, dist_rgb, K_ir, dist_ir, R, T) 튜플을,
    실패하면 None을 반환한다.
    """
    if not os.path.exists(CALIB_FILE):
        print(f"[Astra] 캘리브레이션 파일이 없습니다: {CALIB_FILE}")
        print("[Astra] 먼저 'python main.py calibrate' 를 실행해 캘리브레이션을 완료하세요.")
        return None

    try:
        calib = load_calibration(CALIB_FILE)
    except Exception as e:
        print(f"[Astra] 캘리브레이션 파일을 불러오지 못했습니다: {e}")
        return None

    try:
        if debug:
            print("[Astra][진단][메인스레드] AstraCamera 생성 시작", flush=True)
        cam = AstraCamera(
            rgb_device_index=rgb_device_index if rgb_device_index is not None else DEFAULT_DEBUG_RGB_DEVICE_INDEX,
            debug=debug,
        )
        if debug:
            print("[Astra][진단][메인스레드] AstraCamera 생성 완료", flush=True)

        if debug:
            print("[Astra][진단][메인스레드] depth 스트림 시작", flush=True)
        cam.start_depth()
        if debug:
            print("[Astra][진단][메인스레드] depth 스트림 시작 완료", flush=True)
    except Exception as e:
        print(f"[Astra] 메인 스레드 사전 초기화 실패: {e}")
        return None

    return (cam, *calib)


def run_debug_skeleton_viewer(stop_event, rgb_device_index=None, frame_callback=None, show_viewer=True,
                               debug=False, inference_enabled=None, precreated=None):

    if precreated is not None:
        cam, K_rgb, dist_rgb, K_ir, dist_ir, R, T = precreated
    else:
        if not os.path.exists(CALIB_FILE):
            print(f"[Astra] 캘리브레이션 파일이 없습니다: {CALIB_FILE}")
            print("[Astra] 먼저 'python main.py calibrate' 를 실행해 캘리브레이션을 완료하세요.")
            return

        try:
            K_rgb, dist_rgb, K_ir, dist_ir, R, T = load_calibration(CALIB_FILE)
        except Exception as e:
            print(f"[Astra] 캘리브레이션 파일을 불러오지 못했습니다: {e}")
            return

    try:
        import mediapipe as mp
    except Exception as e:
        print(f"[Astra] mediapipe를 불러오지 못했습니다: {e}")
        return

    mp_pose = mp.solutions.pose
    connections = list(mp_pose.POSE_CONNECTIONS)
    num_landmarks = 33

    pose_model = None
    viewer = None
    cam = precreated[0] if precreated is not None else None
    try:
        if precreated is not None:
            if debug:
                print("[Astra][진단] 1/4 사전 생성된 AstraCamera 재사용 (메인 스레드에서 초기화됨)", flush=True)
        else:
            if debug:
                print("[Astra][진단] 1/4 AstraCamera 생성 시작", flush=True)
            cam = AstraCamera(
                rgb_device_index=rgb_device_index if rgb_device_index is not None else DEFAULT_DEBUG_RGB_DEVICE_INDEX,
                debug=debug,
            )
            if debug:
                print("[Astra][진단] 1/4 AstraCamera 생성 완료", flush=True)

            if debug:
                print("[Astra][진단] 2/4 depth 스트림 시작", flush=True)
            cam.start_depth()
            if debug:
                print("[Astra][진단] 2/4 depth 스트림 시작 완료", flush=True)

        pose_model = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

        if show_viewer:
            if debug:
                print("[디버그 모드][진단] 3/4 SkeletonViewer(Open3D 창) 생성 시작", flush=True)
            viewer = SkeletonViewer(connections)
            if debug:
                print("[디버그 모드][진단] 3/4 SkeletonViewer 생성 완료", flush=True)
        else:
            if debug:
                print("[디버그 모드][진단] 3/4 SkeletonViewer 생략", flush=True)

        depth_persist = DepthPersistence(max_age_frames=10)

        print("[Astra] 캡처 시작", flush=True)

        frame_count = 0
        while not stop_event.is_set():
            frame_count += 1
            if frame_count <= 5 or frame_count % 60 == 0:
                if debug:
                    print(f"[Astra][진단] 4/4 루프 프레임 #{frame_count} 시작", flush=True)

            rgb = cam.get_color_frame()
            depth = cam.get_depth_frame()
            if rgb is None or depth is None:
                if frame_count <= 5:
                    if debug:
                        print(f"[Astra][진단] 프레임 #{frame_count}: rgb={rgb is None and 'None' or 'OK'}, depth={depth is None and 'None' or 'OK'} -> skip", flush=True)
                cv2.waitKey(1)
                continue

            inference_active = True if inference_enabled is None else bool(inference_enabled())

            points3d = np.zeros((num_landmarks, 3), dtype=np.float32)
            valid = np.zeros(num_landmarks, dtype=bool)
            results = None

            if inference_active:
                aligned_depth = align_depth_to_color(depth, K_ir, dist_ir, K_rgb, R, T, rgb.shape)
                aligned_depth = depth_persist.update(aligned_depth)

                rgb_input = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
                rgb_input.flags.writeable = False
                results = pose_model.process(rgb_input)

                h_c, w_c = aligned_depth.shape

                if results.pose_landmarks:
                    h, w = rgb.shape[:2]
                    for i, lm in enumerate(results.pose_landmarks.landmark):
                        if lm.visibility < 0.5:
                            continue
                        u, v = int(round(lm.x * w)), int(round(lm.y * h))
                        if u < 0 or v < 0 or u >= w_c or v >= h_c:
                            continue
                        d = sample_depth_near(aligned_depth, u, v, max_radius=15)
                        if d <= 0:
                            continue
                        p3d = backproject_point(u, v, float(d), K_rgb, dist_rgb)
                        if p3d is not None:
                            points3d[i] = p3d
                            valid[i] = True

                if frame_callback is not None:
                    try:
                        disp = rgb.copy()
                        if results.pose_landmarks:
                            mp.solutions.drawing_utils.draw_landmarks(disp, results.pose_landmarks, connections)

                        h_disp, w_disp = rgb.shape[:2]
                        frame_callback(disp, results.pose_landmarks, w_disp, h_disp, points3d, valid)
                    except Exception:
                        pass

            if show_viewer:
                viewer.update(points3d, valid)
                alive = viewer.poll()
                if not alive:
                    break
            cv2.waitKey(1)
    except Exception as e:
        print(f"[Astra] 오류: {e}")
    finally:
        if viewer is not None:
            try:
                viewer.close()
            except Exception:
                pass
        if pose_model is not None:
            try:
                pose_model.close()
            except Exception:
                pass
        if cam is not None and precreated is None:
            # precreated 카메라는 메인 스레드에서 앱 수명 동안 유지되는
            # 객체이므로 여기서 release 하지 않는다 (재시작 시 재사용).
            try:
                cam.release()
            except Exception:
                pass
        print("[Astra] 종료")


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

        self.debug_cam_idx = DEFAULT_DEBUG_RGB_DEVICE_INDEX
        self._debug_thread = None
        self._debug_stop_event = None

        self._debug_latest_frame = None
        self._debug_frame_lock = threading.Lock()

        self._debug_first_frame_event = threading.Event()
        self.ASTRA_INIT_WATCHDOG_TIMEOUT_SEC = 10.0

        # Tracks whether the frontend has already been told the camera is
        # ready to stream (used to drive the "카메라를 불러오는 중입니다" screen).
        self._camera_ready_fired = False

        # Astra 카메라를 메인 스레드에서 미리 초기화해둔 결과.
        # (cam, K_rgb, dist_rgb, K_ir, dist_ir, R, T) 튜플 또는 None.
        # 일부 PC에서는 OpenNI2 depth stream 생성을 메인 스레드가 아닌
        # 스레드에서 하면 멈추거나 죽기 때문에, main() 에서 webview.start()
        # 호출 전에 preinitialize_astra_camera() 로 채워 넣는다.
        self._astra_precreated = None
        self._astra_precreated_idx = None

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
            self._camera_ready_fired = False

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

            self._notify_camera_ready()

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

    def _notify_camera_ready(self):
        with self.lock:
            if self._camera_ready_fired:
                return
            self._camera_ready_fired = True
        try:
            window.evaluate_js("window.onCameraReady && window.onCameraReady()")
        except Exception as e:
            print(f"[camera] ready 콜백 전송 실패: {e}")

    def _is_camera_enabled(self):
        with self.lock:
            return self.camera_enabled

    def _on_astra_frame(self, frame, landmarks, w, h, points3d, valid):

        with self._debug_frame_lock:
            self._debug_latest_frame = (frame, landmarks, w, h, points3d, valid)

        self._debug_first_frame_event.set()
        self._notify_camera_ready()

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

        if self._astra_precreated is not None:
            try:
                self._astra_precreated[0].release()
            except Exception:
                pass
            self._astra_precreated = None

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

        if not os.path.exists(CALIB_FILE):
            print(f"[Astra Pro] 캘리브레이션 파일이 없습니다: {CALIB_FILE}")
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

        # 메인 스레드에서 미리 초기화해둔 카메라가 있고, 지금 요청한
        # 인덱스와 일치하면 그걸 재사용한다 (백그라운드 스레드에서
        # OpenNI2 device/stream을 새로 여는 것이 일부 PC에서 멈추는
        # 문제를 피하기 위함).
        precreated = None
        if (self._astra_precreated is not None and
                self._astra_precreated_idx == self.debug_cam_idx):
            precreated = self._astra_precreated
            print("[Astra] 사전 초기화된 카메라 재사용 (index="
                  f"{self.debug_cam_idx})", flush=True)
        else:
            print("[Astra][경고] 사전 초기화된 카메라와 인덱스가 다르거나 없음. "
                  "백그라운드 스레드에서 새로 여는 것을 시도합니다 "
                  "(일부 PC에서 멈출 수 있음).", flush=True)

        self._debug_thread = threading.Thread(
            target=run_debug_skeleton_viewer,
            args=(self._debug_stop_event,),
            kwargs={
                "rgb_device_index": self.debug_cam_idx,

                "frame_callback": self._on_astra_frame,

                "show_viewer": self.debug_mode_enabled,

                "inference_enabled": self._is_camera_enabled,

                "debug": self.debug_mode_enabled,

                "precreated": precreated,
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
            f"[Astra][감시] {self.ASTRA_INIT_WATCHDOG_TIMEOUT_SEC:.0f}초 안에 첫 프레임을 받지 못했습니다.",
            flush=True,
        )
        try:
            window.evaluate_js(
                "updateFrame('', 'Astra Pro 초기화가 지연되고 있습니다', 2, 0, 0.0, 0.0, 0.0, 0.0, false)"
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
        run_calibration(rgb_device_index=cam_idx)
    else:
        app_logic = CameraApp()

        # 일부 PC(특히 데스크톱의 서드파티 USB3 컨트롤러)에서는 OpenNI2의
        # device open / create_depth_stream 호출을 메인 스레드가 아닌
        # 스레드에서 수행하면 예외 없이 그대로 멈추거나 프로세스가
        # 종료되는 문제가 있다. 그래서 webview.start() 가 메인 스레드의
        # 이벤트 루프를 가져가기 전에, 여기서 미리 Astra 카메라를 열어
        # 둔다. 캘리브레이션 파일이 없거나 Astra Pro가 연결되어 있지
        # 않으면 조용히 None을 반환하며, 이 경우 웹캠 모드는 평소처럼
        # 정상 동작한다.
        preinit_idx = DEFAULT_DEBUG_RGB_DEVICE_INDEX
        precreated = preinitialize_astra_camera(rgb_device_index=preinit_idx, debug=True)
        if precreated is not None:
            app_logic._astra_precreated = precreated
            app_logic._astra_precreated_idx = preinit_idx
            print(f"[Astra] 메인 스레드 사전 초기화 성공 (index={preinit_idx})", flush=True)
        else:
            print("[Astra] 메인 스레드 사전 초기화를 건너뜀 (캘리브레이션 없음/Astra 미연결/실패). "
                  "Astra Pro 모드 선택 시 백그라운드 스레드에서 초기화를 시도합니다.", flush=True)

        window = webview.create_window('Pose Report', 'index.html', width=800, height=600, js_api=app_logic)
        window.events.closing += app_logic.on_closing
        threading.Thread(target=app_logic.start_camera_thread, daemon=True).start()
        webview.start()