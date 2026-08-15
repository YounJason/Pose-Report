
import os
import json

import cv2
import numpy as np

CHECKERBOARD = (9, 6)
SQUARE_SIZE = 0.029

RGB_RESOLUTION = (640, 480)
DEPTH_RESOLUTION = (640, 480)
FPS = 30

DEFAULT_DEBUG_RGB_DEVICE_INDEX = 1

OPENNI_REDIST_PATH = os.environ.get("OPENNI2_REDIST", None)

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
                print("[Astra 캡처][진단]   openni2.initialize 시작...", flush=True)
            openni2.initialize(openni_redist)
            if self._debug:
                print("[Astra 캡처][진단]   openni2.initialize 완료", flush=True)

            if self._debug:
                print("[Astra 캡처][진단]   Device.open_any() 시작...", flush=True)
            self.dev = openni2.Device.open_any()
            if self._debug:
                print("[Astra 캡처][진단]   Device.open_any() 완료", flush=True)

            if self._debug:
                print("[Astra 캡처][진단]   create_depth_stream() 시작...", flush=True)
            self.depth_stream = self.dev.create_depth_stream()
            if self._debug:
                print("[Astra 캡처][진단]   create_depth_stream() 완료", flush=True)

            if self._debug:
                print("[Astra 캡처][진단]   depth_stream.set_video_mode() 시작...", flush=True)
            self.depth_stream.set_video_mode(
                c_api.OniVideoMode(
                    pixelFormat=c_api.OniPixelFormat.ONI_PIXEL_FORMAT_DEPTH_1_MM,
                    resolutionX=depth_resolution[0],
                    resolutionY=depth_resolution[1],
                    fps=fps,
                )
            )
            if self._debug:
                print("[Astra 캡처][진단]   depth_stream.set_video_mode() 완료", flush=True)
            try:
                self.depth_stream.set_mirroring_enabled(False)
            except Exception as e:
                self._depth_mirror_supported = False
                print("[Astra 캡처][경고] Depth 스트림 미러링 설정 API 미지원. 소프트웨어 flip으로 대체:", e)

            if self._debug:
                print("[Astra 캡처][진단]   create_ir_stream() 시작...", flush=True)
            try:
                self.ir_stream = self.dev.create_ir_stream()
                if self._debug:
                    print("[Astra 캡처][진단]   create_ir_stream() 완료", flush=True)
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
                    print("[Astra 캡처][경고] IR 스트림 미러링 설정 API 미지원. 소프트웨어 flip으로 대체:", e)
            except Exception as e:
                print("[Astra 캡처][경고] IR 스트림을 생성할 수 없습니다:", e)

            if self._debug:
                print(f"[Astra 캡처][진단]   RGB cv2.VideoCapture({rgb_device_index}) 시작...", flush=True)
            self.cap = cv2.VideoCapture(rgb_device_index)
            if self._debug:
                print("[Astra 캡처][진단]   RGB cv2.VideoCapture(...) 생성자 반환됨", flush=True)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, rgb_resolution[0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, rgb_resolution[1])
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            if self._debug:
                print(f"[Astra 캡처][진단]   RGB cap.isOpened()={self.cap.isOpened()}", flush=True)

            if not self.cap.isOpened():
                print("[Astra 캡처][경고] RGB(UVC) 카메라를 열지 못했습니다. 디버그 카메라 인덱스를 확인하세요.")
        except Exception:
            print("[Astra 캡처][오류] 초기화 도중 예외 발생. 지금까지 만든 핸들을 정리합니다...", flush=True)
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
                    print(f"[대기중] {'/'.join(missing)} 프레임을 받지 못했습니다... "
                          f"(카메라 연결/드라이버/장치 인덱스를 확인하세요)")
                key = cv2.waitKey(30) & 0xFF
                if key == ord("q"):
                    print("사용자 종료.")
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
                print("사용자 종료.")
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
        print("\n[1/2] 개별 카메라 내부파라미터 계산 중...")
        ret_rgb, K_rgb, dist_rgb, _, _ = cv2.calibrateCamera(
            self.obj_points, self.rgb_points, rgb_size, None, None
        )
        ret_ir, K_ir, dist_ir, _, _ = cv2.calibrateCamera(
            self.obj_points, self.ir_points, ir_size, None, None
        )
        print(f"  RGB 재투영 오차: {ret_rgb:.4f} px")
        print(f"  IR  재투영 오차: {ret_ir:.4f} px")

        print("[2/2] 스테레오 캘리브레이션 (RGB <-> IR/Depth) 중...")
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

def run_debug_skeleton_viewer(stop_event, rgb_device_index=None, frame_callback=None, show_viewer=True, debug=False):

    if not os.path.exists(CALIB_FILE):
        print(f"[Astra 캡처] 캘리브레이션 파일이 없습니다: {CALIB_FILE}")
        print("[Astra 캡처] 먼저 'python main.py calibrate' 를 실행해 캘리브레이션을 완료하세요.")
        return

    try:
        K_rgb, dist_rgb, K_ir, dist_ir, R, T = load_calibration(CALIB_FILE)
    except Exception as e:
        print(f"[Astra 캡처] 캘리브레이션 파일을 불러오지 못했습니다: {e}")
        return

    try:
        import mediapipe as mp
    except Exception as e:
        print(f"[Astra 캡처] mediapipe를 불러오지 못했습니다: {e}")
        return

    mp_pose = mp.solutions.pose
    connections = list(mp_pose.POSE_CONNECTIONS)
    num_landmarks = 33

    cam = None
    pose_model = None
    viewer = None
    try:
        if debug:
            print("[Astra 캡처][진단] 1/4 AstraCamera 생성 시작...", flush=True)
        cam = AstraCamera(
            rgb_device_index=rgb_device_index if rgb_device_index is not None else DEFAULT_DEBUG_RGB_DEVICE_INDEX,
            debug=debug,
        )
        if debug:
            print("[Astra 캡처][진단] 1/4 AstraCamera 생성 완료", flush=True)

        if debug:
            print("[Astra 캡처][진단] 2/4 depth 스트림 시작...", flush=True)
        cam.start_depth()
        if debug:
            print("[Astra 캡처][진단] 2/4 depth 스트림 시작 완료", flush=True)

        pose_model = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

        if show_viewer:
            if debug:
                print("[디버그 모드][진단] 3/4 SkeletonViewer(Open3D 창) 생성 시작...", flush=True)
            viewer = SkeletonViewer(connections)
            if debug:
                print("[디버그 모드][진단] 3/4 SkeletonViewer 생성 완료", flush=True)
        else:
            if debug:
                print("[디버그 모드][진단] 3/4 SkeletonViewer 생략 (Open3D 창 표시 안 함)", flush=True)

        depth_persist = DepthPersistence(max_age_frames=10)

        print("[Astra 캡처] 캡처 루프 실행 중 (Open3D 뷰어 유무와 무관하게 항상 동작).", flush=True)

        frame_count = 0
        while not stop_event.is_set():
            frame_count += 1
            if frame_count <= 5 or frame_count % 60 == 0:
                if debug:
                    print(f"[Astra 캡처][진단] 4/4 루프 프레임 #{frame_count} 시작", flush=True)

            rgb = cam.get_color_frame()
            depth = cam.get_depth_frame()
            if rgb is None or depth is None:
                if frame_count <= 5:
                    if debug:
                        print(f"[Astra 캡처][진단] 프레임 #{frame_count}: rgb={rgb is None and 'None' or 'OK'}, depth={depth is None and 'None' or 'OK'} -> skip", flush=True)
                cv2.waitKey(1)
                continue

            aligned_depth = align_depth_to_color(depth, K_ir, dist_ir, K_rgb, R, T, rgb.shape)
            aligned_depth = depth_persist.update(aligned_depth)

            rgb_input = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
            rgb_input.flags.writeable = False
            results = pose_model.process(rgb_input)

            points3d = np.zeros((num_landmarks, 3), dtype=np.float32)
            valid = np.zeros(num_landmarks, dtype=bool)
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
        print(f"[Astra 캡처] 오류: {e}")
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
        if cam is not None:
            try:
                cam.release()
            except Exception:
                pass
        print("[Astra 캡처] 종료.")
