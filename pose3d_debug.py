# -*- coding: utf-8 -*-
"""
pose3d_debug.py
=================
Pose-Report의 "디버그 모드"에서 사용하는 3D 스켈레톤 뷰어 모듈입니다.

원래 pose-viewer(Astra Pro + MediaPipe + Open3D 실시간 3D 스켈레톤 뷰어) 프로젝트의
config.py / camera.py / depth_align.py / skeleton_viewer.py / calibration.py 를
Pose-Report에 이식하기 위해 파일 1개로 통합했습니다. (추가 파일 수를 최소화하기 위함)

- Pose-Report 본 기능(설정 화면의 카메라 인덱스로 여는 2D 웹캠 + MediaPipe 자세 분석,
  main.CameraApp)은 이 모듈과 무관하게 그대로 동작합니다.
- 설정 화면(screen-1)에서 "디버그 모드"를 켜면, 계측 화면(screen-4)이 진행되는 동안
  이 모듈이 별도의 Orbbec Astra Pro 깊이 카메라를 열어 MediaPipe로 검출한 관절을
  3D로 역투영하고, Open3D 창에 실시간 스켈레톤을 "추가로" 띄웁니다.
  (Open3D 창은 pywebview 창과 별개의 네이티브 창입니다 - pose-viewer 원본과 동일)
- 이 모듈이 사용하는 카메라는 Pose-Report 본 기능이 사용하는 일반 웹캠과는 별개의
  장치(Astra Pro)이므로, 설정 화면에서 장치 인덱스를 따로 입력받습니다.
- 캘리브레이션 기능도 원본과 동일하게 유지됩니다:

      python main.py calibrate

  로 실행하면 RGB-Depth(IR) 스테레오 캘리브레이션 도구가 실행되고,
  결과가 calibration_data/stereo_calibration.json 에 저장됩니다.
  디버그 모드의 3D 스켈레톤 뷰어는 이 파일이 있어야 동작합니다.

필요 패키지 (디버그 모드/캘리브레이션을 사용할 때만 필요):
    pip install open3d openni
필요 SDK: OpenNI2 (Orbbec Astra Pro의 Depth/IR 스트림 접근용, 별도 설치)

주의: 위 패키지들은 이 파일을 import하는 시점이 아니라, 실제로 디버그 모드를
켜거나 calibrate 를 실행하는 시점에만 로드됩니다. 그래서 디버그 모드를 쓰지
않는 사용자는 openni/open3d를 설치하지 않아도 Pose-Report 본 기능을 그대로
사용할 수 있습니다.
"""
import os
import json

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# 설정 (원본 pose-viewer/config.py)
# ---------------------------------------------------------------------------
# 체커보드 내부 코너 개수 (가로, 세로). OpenCV 기준 "칸 수 - 1".
#   예) 가로 10칸 x 세로 7칸으로 인쇄한 체커보드 -> 내부 코너 = 9 x 6
CHECKERBOARD = (9, 6)
SQUARE_SIZE = 0.029  # 한 칸의 실제 크기 (미터). 29mm = 0.029m

RGB_RESOLUTION = (640, 480)    # Astra Pro RGB(UVC) 해상도
DEPTH_RESOLUTION = (640, 480)  # OpenNI2 Depth/IR 스트림 해상도
FPS = 30

# Astra Pro RGB(UVC) 카메라 기본 장치 인덱스.
# Pose-Report 설정 화면의 "디버그 카메라 인덱스" 값으로 덮어씁니다.
DEFAULT_DEBUG_RGB_DEVICE_INDEX = 1

# OpenNI2 redist(SDK) 경로. 환경변수 OPENNI2_REDIST 로 지정하거나 None이면 시스템 기본 경로 사용.
OPENNI_REDIST_PATH = os.environ.get("OPENNI2_REDIST", None)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CALIB_DIR = os.path.join(BASE_DIR, "calibration_data")
CALIB_FILE = os.path.join(CALIB_DIR, "stereo_calibration.json")


# ---------------------------------------------------------------------------
# Astra Pro 카메라 래퍼 (원본 pose-viewer/camera.py)
# ---------------------------------------------------------------------------
class AstraCamera:
    """
    Depth / IR 스트림: OpenNI2(openni 패키지)를 통해 접근
    RGB 스트림: Astra Pro는 컬러 카메라가 OpenNI2로 노출되지 않는 모델이 많아
                별도의 UVC(USB Video Class) 장치로 인식되므로 OpenCV VideoCapture로 엽니다.
    """

    def __init__(
        self,
        openni_redist=OPENNI_REDIST_PATH,
        rgb_device_index=DEFAULT_DEBUG_RGB_DEVICE_INDEX,
        depth_resolution=DEPTH_RESOLUTION,
        rgb_resolution=RGB_RESOLUTION,
        fps=FPS,
    ):
        # openni는 디버그 모드를 실제로 켰을 때만 필요하므로 여기서 지연 import 합니다.
        from openni import openni2
        from openni import _openni2 as c_api

        self._openni2 = openni2
        self._c_api = c_api

        openni2.initialize(openni_redist)
        self.dev = openni2.Device.open_any()

        # 주의: Astra류 구조광 카메라는 Depth와 IR이 동일한 물리 센서를 공유합니다.
        # 두 스트림을 동시에 start() 하면 read_frame()이 프레임을 받지 못해
        # 무한 대기(= "응답 없음")로 멈추는 경우가 많습니다. 그래서 스트림은
        # 생성만 해두고, 실제 시작/정지는 start_depth()/stop_depth(),
        # start_ir()/stop_ir() 로 필요한 시점에만 호출합니다.
        self.depth_stream = self.dev.create_depth_stream()
        self.depth_stream.set_video_mode(
            c_api.OniVideoMode(
                pixelFormat=c_api.OniPixelFormat.ONI_PIXEL_FORMAT_DEPTH_1_MM,
                resolutionX=depth_resolution[0],
                resolutionY=depth_resolution[1],
                fps=fps,
            )
        )
        self._depth_mirror_supported = True
        try:
            self.depth_stream.set_mirroring_enabled(False)
        except Exception as e:
            self._depth_mirror_supported = False
            print("[디버그 모드][경고] Depth 스트림 미러링 설정 API 미지원. 소프트웨어 flip으로 대체:", e)
        self._depth_started = False

        # IR 스트림 (캘리브레이션 및 depth 내부파라미터 대용)
        self.ir_stream = None
        self._ir_started = False
        self._ir_mirror_supported = True
        try:
            self.ir_stream = self.dev.create_ir_stream()
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
                print("[디버그 모드][경고] IR 스트림 미러링 설정 API 미지원. 소프트웨어 flip으로 대체:", e)
        except Exception as e:
            print("[디버그 모드][경고] IR 스트림을 생성할 수 없습니다:", e)

        # RGB: UVC(OpenCV)
        self.cap = cv2.VideoCapture(rgb_device_index)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, rgb_resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, rgb_resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS, fps)

        if not self.cap.isOpened():
            print("[디버그 모드][경고] RGB(UVC) 카메라를 열지 못했습니다. 디버그 카메라 인덱스를 확인하세요.")

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
        """반환: (H, W) uint16, 단위 mm. timeout_ms 안에 프레임이 안 오면 None."""
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
        """반환: (H, W) uint8 (정규화됨). timeout_ms 안에 프레임이 안 오면 None."""
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
        """반환: (H, W, 3) BGR uint8"""
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
            self.cap.release()
        except Exception:
            pass
        try:
            self._openni2.unload()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 캘리브레이션 로드 + Depth -> RGB 정렬 + 픽셀 역투영(3D) 유틸리티
# (원본 pose-viewer/depth_align.py)
# ---------------------------------------------------------------------------
def load_calibration(path=CALIB_FILE):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    K_rgb = np.array(data["rgb_camera_matrix"], dtype=np.float64)
    dist_rgb = np.array(data["rgb_dist_coeffs"], dtype=np.float64)
    K_ir = np.array(data["ir_camera_matrix"], dtype=np.float64)
    dist_ir = np.array(data["ir_dist_coeffs"], dtype=np.float64)
    # Depth(IR) -> RGB 변환: P_rgb = R @ P_depth + T
    R = np.array(data["R"], dtype=np.float64)
    T = np.array(data["T"], dtype=np.float64).reshape(3, 1)

    return K_rgb, dist_rgb, K_ir, dist_ir, R, T


def align_depth_to_color(depth_mm, K_depth, dist_depth, K_color, R, T, color_shape,
                          hole_fill_kernel_size=7):
    """depth_mm(H,W uint16, mm)을 RGB 이미지 픽셀 그리드에 정렬합니다.
    반환: (H_c, W_c) float32, 단위 m, 0=무효."""
    h_c, w_c = color_shape[:2]

    ys, xs = np.nonzero(depth_mm > 0)
    if len(xs) == 0:
        return np.zeros((h_c, w_c), dtype=np.float32)

    zs = depth_mm[ys, xs].astype(np.float32) / 1000.0  # mm -> m

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
    """시간축 홀필링(temporal hole-filling). 먼 거리에서 IR 반사가 약해
    depth가 프레임마다 깜빡이는 현상을 완화합니다."""

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
    """(u, v)에 depth가 없으면 반경을 넓혀가며 가장 가까운 유효 depth를 찾습니다."""
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
    """RGB 픽셀(u, v)과 정렬된 depth 값(m)으로 RGB 카메라 좌표계 3D 점을 계산합니다."""
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


# ---------------------------------------------------------------------------
# Open3D 실시간 3D 스켈레톤 뷰어 (원본 pose-viewer/skeleton_viewer.py)
# ---------------------------------------------------------------------------
class SkeletonViewer:
    def __init__(self, connections, window_name="Pose Report - Debug 3D Skeleton Viewer", width=960, height=720):
        # open3d는 디버그 모드를 실제로 켰을 때만 필요하므로 여기서 지연 import 합니다.
        import open3d as o3d
        self._o3d = o3d

        self.connections = list(connections)

        self.vis = o3d.visualization.Visualizer()
        self.vis.create_window(window_name, width=width, height=height)

        self.joint_cloud = o3d.geometry.PointCloud()
        self.bone_lines = o3d.geometry.LineSet()

        self.vis.add_geometry(self.joint_cloud)
        # lines가 0개인 상태로 add_geometry 하면 매 프레임 경고가 출력되므로,
        # 선이 1개 이상 생기는 순간에만 add_geometry 하도록 관리합니다.
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
        # 카메라 좌표계(y-down, z-forward) -> 보기 편한 좌표계(y-up, z-toward viewer)
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
        """이벤트 처리 및 렌더링. 창이 닫혔으면 False 반환."""
        alive = self.vis.poll_events()
        self.vis.update_renderer()
        return alive

    def close(self):
        self.vis.destroy_window()


# ---------------------------------------------------------------------------
# RGB - Depth(IR) 수동 스테레오 캘리브레이션 도구 (원본 pose-viewer/calibration.py)
# ---------------------------------------------------------------------------
class StereoCalibrator:
    """
    - RGB, IR 두 개의 창을 띄우고 체커보드를 비춥니다.
    - 두 화면 모두에서 체커보드가 검출된 상태에서 마우스 좌클릭 또는 스페이스바로 캡처합니다.
    - 최소 5장 이상 캡처한 뒤 'c' 키를 누르면 캘리브레이션을 실행하고
      결과를 calibration_data/stereo_calibration.json 으로 저장합니다.
    - 'q' 키로 종료합니다.
    """

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

        # cv2.stereoCalibrate가 반환하는 R, T는 "camera1(RGB) -> camera2(IR)" 변환이므로
        # 실사용에 필요한 "Depth(IR) -> RGB" 방향으로 역변환하여 저장합니다.
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


# ---------------------------------------------------------------------------
# 진입점 함수 (main.py에서 호출)
# ---------------------------------------------------------------------------
def run_calibration(rgb_device_index=None):
    """`python main.py calibrate` 로 호출되는 캘리브레이션 진입점."""
    cam = AstraCamera(
        rgb_device_index=rgb_device_index if rgb_device_index is not None else DEFAULT_DEBUG_RGB_DEVICE_INDEX
    )
    try:
        calibrator = StereoCalibrator(cam)
        calibrator.run()
    finally:
        cam.release()


def run_debug_skeleton_viewer(stop_event, rgb_device_index=None, frame_callback=None):
    """
    디버그 모드가 켜져 있을 때, 계측 화면(screen-4)이 진행되는 동안
    별도 스레드에서 호출되는 함수입니다. Astra Pro 카메라로 3D 스켈레톤을
    Open3D 창에 실시간으로 표시하다가, stop_event가 set 되거나 사용자가
    Open3D 창을 닫으면 종료합니다.

    frame_callback이 주어지면, 매 프레임마다 (관절이 그려진) BGR 프레임을
    인자로 호출합니다. main.py는 이를 이용해 pywebview 화면에도 Astra RGB
    영상을 함께 띄웁니다. frame_callback 실행 중 오류가 나도 3D 뷰어
    루프에는 영향을 주지 않습니다.

    Pose-Report 본 기능(2D 웹캠 분석)에는 영향을 주지 않도록, 모든 예외를
    내부에서 처리하고 실패하더라도 조용히 종료합니다.
    """
    if not os.path.exists(CALIB_FILE):
        print(f"[디버그 모드] 캘리브레이션 파일이 없습니다: {CALIB_FILE}")
        print("[디버그 모드] 먼저 'python main.py calibrate' 를 실행해 캘리브레이션을 완료하세요.")
        return

    try:
        K_rgb, dist_rgb, K_ir, dist_ir, R, T = load_calibration(CALIB_FILE)
    except Exception as e:
        print(f"[디버그 모드] 캘리브레이션 파일을 불러오지 못했습니다: {e}")
        return

    try:
        import mediapipe as mp
    except Exception as e:
        print(f"[디버그 모드] mediapipe를 불러오지 못했습니다: {e}")
        return

    mp_pose = mp.solutions.pose
    connections = list(mp_pose.POSE_CONNECTIONS)
    num_landmarks = 33

    cam = None
    pose_model = None
    viewer = None
    try:
        cam = AstraCamera(
            rgb_device_index=rgb_device_index if rgb_device_index is not None else DEFAULT_DEBUG_RGB_DEVICE_INDEX
        )
        cam.start_depth()
        pose_model = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
        viewer = SkeletonViewer(connections)
        depth_persist = DepthPersistence(max_age_frames=10)

        print("[디버그 모드] 3D 스켈레톤 뷰어 실행 중.")

        while not stop_event.is_set():
            rgb = cam.get_color_frame()
            depth = cam.get_depth_frame()
            if rgb is None or depth is None:
                cv2.waitKey(1)
                continue

            aligned_depth = align_depth_to_color(depth, K_ir, dist_ir, K_rgb, R, T, rgb.shape)
            aligned_depth = depth_persist.update(aligned_depth)

            rgb_input = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
            rgb_input.flags.writeable = False
            results = pose_model.process(rgb_input)

            if frame_callback is not None:
                try:
                    disp = rgb.copy()
                    if results.pose_landmarks:
                        mp.solutions.drawing_utils.draw_landmarks(disp, results.pose_landmarks, connections)
                    frame_callback(disp)
                except Exception:
                    pass

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

            viewer.update(points3d, valid)
            alive = viewer.poll()
            if not alive:
                break
            cv2.waitKey(1)
    except Exception as e:
        print(f"[디버그 모드] 3D 스켈레톤 뷰어 오류: {e}")
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
        print("[디버그 모드] 3D 스켈레톤 뷰어 종료.")
