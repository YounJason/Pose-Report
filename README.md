pip install opencv-python pywebview mediapipe==0.10.9

python 3.11.7

## 디버그 모드 (3D 스켈레톤 뷰어)

설정 화면에서 "디버그 모드"를 켜면, 계측이 진행되는 동안 별도의 Orbbec Astra Pro
깊이 카메라로 3D 스켈레톤을 Open3D 창에 추가로 띄웁니다. (기존 2D 자세 분석/리포트
흐름에는 영향을 주지 않습니다.) 이 기능은 pose-viewer 프로젝트에서 이식되었으며,
`pose3d_debug.py`에 통합되어 있습니다.

디버그 모드를 사용하려면 추가로 아래를 설치하세요.

```bash
pip install open3d openni
```

그리고 OpenNI2 SDK(redist)를 설치하고 `OPENNI2_REDIST` 환경변수로 경로를 지정하세요.

### 캘리브레이션 (디버그 모드 최초 1회 필수)

디버그 모드의 3D 스켈레톤 뷰어는 RGB-Depth(IR) 스테레오 캘리브레이션이 먼저 되어 있어야
동작합니다. 아래 명령으로 실행하세요.

```bash
python main.py calibrate
# 필요하면 디버그 카메라 장치 인덱스를 직접 지정할 수 있습니다.
python main.py calibrate 1
```

캘리브레이션 결과는 `calibration_data/stereo_calibration.json`에 저장됩니다.
디버그 모드를 켜지 않으면 이 파일이나 위 패키지들이 없어도 Pose-Report 본 기능은
그대로 동작합니다.