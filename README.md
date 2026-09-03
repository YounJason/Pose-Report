# Pose-Report

카메라 앞에서 30초간 자세를 측정해 거북목 · 등/허리 · 어깨 · 골반을 점수화하고,
다리 꼬기는 별도의 기하학적 휴리스틱으로 감지합니다. 측정 결과는 Gemini API로 코칭
피드백을 생성한 뒤, 앱 화면에서 바로 A4 용지로 인쇄해 확인할 수 있는
[pywebview](https://pywebview.flowrl.com/) 기반 데스크톱 앱입니다.

> 이 프로젝트는 코드에 주석을 두지 않는 방식(바이브 코딩)으로 관리합니다.
> 로직에 대한 설명, 배경, 주의사항은 모두 이 README에 정리되어 있으니,
> 코드를 수정하기 전에 관련 섹션을 먼저 확인하세요.

## 주요 기능

- **실시간 자세 분석**: MediaPipe Pose로 신체 랜드마크를 추출해 프레임마다 자세를 채점
- **각도 threshold 기반 판정**: 목/머리, 등/허리, 어깨, 골반 각각에 대해 각도 threshold로 정상/위험을 판정
- **RULA 참고 가중 종합점수**: 프로젝트용 heuristic weighting으로 목 25 / 몸통 30 / 어깨 30 / 골반 15를 기본값으로 사용
- **다리 꼬기 휴리스틱**: 기존 선분 교차 기반 판정을 종합점수에 별도 감점으로 반영
- **Astra Pro 지원**: RGB + Depth / 3D skeleton 경로를 지원하며, 유효한 3D 좌표가 있으면 각도 계산에 3D 좌표를 사용
- **Depth 조회 벡터화**: 랜드마크별 depth 최근접 탐색을 프레임당 1회의 `cv2.distanceTransform` 호출로 처리 (자세한 내용은 [Astra Pro depth 파이프라인](#astra-pro-3d-depth) 참고)

## 화면 구성

앱은 `index.html`의 `.screen` 7개를 `showScreen(index)`로 전환하는 SPA 구조입니다.

| index | 화면 |
|---|---|
| 0 | 초기 설정 |
| 1 | 카메라 로딩 |
| 2 | 메인 화면 |
| 3 | QR 개인정보 동의 |
| 4 | 30초 측정 |
| 5 | 리포트 생성 |
| 6 | 최종 리포트 (A4 인쇄) |

## 파일 구조

```text
Pose-Report/
├── main.py          # 앱 실행 + Astra Pro 캘리브레이션 서브커맨드 포함
├── index.html
├── script.js
├── style.css
└── README.md
```

## 설치

```bash
pip install opencv-python mediapipe==0.10.9 pywebview numpy requests python-dotenv
```

Python 3.11.x 환경을 기준으로 작성되었습니다.

### 환경 변수 (`.env`)

프로젝트 루트에 `.env` 파일을 만들고 아래 값을 채워주세요.

```bash
GEMINI_API_KEY=여기에_Gemini_API_키
SUPABASE_ANON_KEY=여기에_Supabase_anon_key
```

## 서브커맨드 구조

`main.py`는 인자 없이 실행하면 pywebview 앱을 띄우고, 첫 번째 인자로 아래 서브커맨드를 받으면
해당 오프라인 파이프라인만 실행합니다.

```bash
python main.py                # 기본: pywebview 앱 실행
python main.py calibrate [카메라 인덱스]   # Astra Pro 스테레오 캘리브레이션
```

## 실행

```bash
python main.py
```

## 자세 판정: 각도 threshold

각 부위는 `CameraApp._threshold_quality`를 이용해 측정 각도와 threshold의 차이를
0~100 점수로 변환합니다. 정상 영역은 90~100, 문제 영역은 0~89로 표현됩니다.

```text
neck     → TURTLE_NECK_ANGLE_THRESHOLD, HEAD_TILT_ANGLE_THRESHOLD
torso    → TORSO_ANGLE_THRESHOLD, SPINE_LEAN_ANGLE_THRESHOLD
shoulder → SHOULDER_ANGLE_THRESHOLD
pelvis   → PELVIS_ANGLE_THRESHOLD
```

리포트의 4개 metric(`neck_score`, `torso_score`, `shoulder_score`, `pelvis_score`)은
이 점수를 프레임별로 수집한 뒤 평균냅니다.

### 임계값/가중치 기본값과 index.html 동기화 주의

`CameraApp.__init__`의 각도 threshold와 가중치 기본값(`TURTLE_NECK_ANGLE_THRESHOLD`,
`WEIGHT_NECK` 등)은 `index.html` 설정 화면의 input `value` 속성과 항상 동일하게
맞춰야 합니다. 실사용 시에는 프런트가 `setup_and_start()`로 자신의 DOM 값을 넘기므로
파이썬 쪽 기본값이 실제 동작에 영향을 주진 않지만, 두 값이 어긋나면 코드/문서를 읽는
사람이 혼란을 겪을 수 있습니다. threshold나 가중치 기본값을 변경할 때는 반드시
`index.html`도 함께 확인하세요.

## 종합 점수 가중치

RULA는 부위별 raw score를 단순 가중평균하는 공식 체계가 아니므로, 본 프로젝트에서는
RULA의 신체 부위 평가 우선순위를 참고한 heuristic weighting을 사용합니다.
공식 RULA 가중치로 해석하면 안 되며, 프로젝트 설정용 기본값입니다.

| 부위 | 기본 가중치 |
|---|---:|
| 목 | 25 |
| 등/허리(몸통) | 30 |
| 어깨 | 30 |
| 골반 | 15 |

프레임별 종합점수는 위 4개 점수의 가중평균으로 계산합니다.
다리 꼬기가 감지된 프레임에는 별도 감점을 추가로 적용합니다.

## 다리 꼬기

`main.py`의 선분 교차 기반 `_detect_leg_cross()` (`is_intersect()` 이용) 결과를 그대로
사용해 종합점수에 별도 감점을 적용합니다. 측정 결과에는 다리 꼬기 지속 시간도
함께 기록합니다.

## Astra Pro (3D Depth)

Astra Pro 캡처/캘리브레이션 경로를 지원합니다. 유효한 3D landmark가 충분하면 3D 좌표로
각도를 계산하고, 부족하면 기존 2D landmark로 계산합니다.

캘리브레이션:

```bash
python main.py calibrate
```

### 창 표시 지연 (hidden → show)

일부 Windows PC에서 `webview.start()` 직후 창이 화면에 뜨자마자 몇 초간
"응답 없음"으로 표시되는 문제가 보고되었습니다. 원인은 이 프로젝트 코드가 아니라
WebView2 초기화 시점에 외부 프로세스(클립보드 제안된 작업, GPU/게임 오버레이 등)가
UI Automation으로 창을 조회하면서 pywebview의 `window.native.AccessibilityObject.Bounds`
접근성 브리지가 재귀적으로 값을 못 풀어내는 것으로 보이는 pywebview/WinForms 쪽 이슈입니다.
정확한 재현 조건은 환경마다 달라 확정하지 못했습니다.

이를 우회하기 위해 `run_app()`에서 `webview.create_window(..., hidden=True)`로 창을 숨긴
채 생성한 뒤, `loaded` 이벤트에서 `window.show()`를 호출해 로드가 끝난 뒤에만 창을
화면에 표시합니다. 문제가 되는 구간(WebView2 초기화 중 접근성 스캔)이 창이 아직
보이지 않는 상태에서 지나가므로, 사용자 입장에서 "응답 없음" 깜빡임이 보이지 않게 됩니다.
근본 원인 해결이 아니라 증상을 가리는 우회책이므로, pywebview/WebView2 쪽에서 더 나은
해결책이 나오면 이 부분을 다시 검토하세요.

### 메인 스레드 사전 초기화

일부 PC(특히 데스크톱의 서드파티 USB3 컨트롤러)에서는 OpenNI2의 device open /
`create_depth_stream` 호출을 메인 스레드가 아닌 스레드에서 수행하면 예외 없이 그대로
멈추거나 프로세스가 종료되는 문제가 있습니다. 그래서 `webview.start()`가 메인 스레드의
이벤트 루프를 가져가기 전에, `run_app()`에서 미리 Astra 카메라를 열어 둡니다
(`preinitialize_astra_camera`). 캘리브레이션 파일이 없거나 Astra Pro가 연결되어 있지
않으면 조용히 `None`을 반환하며, 이 경우 웹캠 모드는 평소처럼 정상 동작합니다.

### Depth 파이프라인 성능

Astra Pro 프레임 처리 루프(`run_debug_skeleton_viewer`)는 매 프레임마다 최대 33개
랜드마크의 depth 값을 정렬된 depth map에서 조회해야 합니다. 조회 지점이 depth가 비어있는
구멍(hole)에 걸리면 원래는 랜드마크마다 반경을 늘려가며(최대 15px) 주변을 다시 검색하는
방식이었는데, 이는 프레임당 최대 33 × 15² 회의 numpy 슬라이싱을 유발할 수 있는 순수 Python
루프였습니다.

지금은 프레임당 `cv2.distanceTransformWithLabels` 호출 1회로 depth map 전체에 대해
"가장 가까운 유효 픽셀" 룩업 테이블을 한 번에 만들고(`build_nearest_valid_lookup`),
그 결과를 모든 랜드마크에 대해 한 번에 벡터 연산으로 조회합니다(`batch_sample_depth_near`,
`batch_backproject_points`). 랜드마크별 Python 루프 자체가 사라지므로 사람이 화면에
가득 잡혀 유효 landmark 수가 많을수록, 그리고 depth 구멍이 많을수록 상대적 이득이 커집니다.

### 창이 뜨지 않고 멈추는 문제 (외부 리소스 로드 지연)

Astra Pro 메인 스레드 사전 초기화가 성공적으로 끝난 직후 프로그램이 완전히 먹통처럼
보이는 문제가 보고되었습니다. 원인은 `index.html`의 `<head>`가 외부 네트워크 리소스
(Google Fonts, 그리고 과거에는 cdnjs의 `qrcode.min.js`)를 동기적으로 불러오고 있었기
때문입니다. `run_app()`은 창을 `hidden=True`로 생성한 뒤 `loaded` 이벤트가 와야
`window.show()`를 호출하는데, 학교/기관 네트워크 방화벽이 해당 도메인을 막거나 DNS가
지연되면 `loaded` 이벤트가 영원히 오지 않아 창이 숨겨진 채로 멈춘 것처럼 보입니다.
콘솔에는 파이썬 쪽 예외가 전혀 없으므로 Astra 초기화 로그가 마지막으로 출력된 뒤
아무 것도 안 찍히는 것처럼 보이는 것도 이 때문입니다.

대응:

- `qrcode.min.js`는 `vendor/qrcode.min.js`로 로컬에 내려받아 CDN 의존성을 제거했습니다.
- Google Fonts `<link rel="stylesheet">`는 `media="print" onload="this.media='all'"`
  패턴으로 렌더링을 막지 않도록(non-blocking) 변경했습니다.
- `run_app()`에 워치독 스레드를 추가해, 15초 안에 `loaded` 이벤트가 오지 않으면
  진단 메시지를 남기고 창을 강제로 표시합니다. 완전한 해결책은 아니지만, 같은 문제가
  다시 발생해도 화면이 하얗게라도 보이므로 "완전히 먹통"처럼 느껴지지 않고 원인 파악이
  쉬워집니다.

## AI 피드백

측정 종료 후 종합 점수, 4개 부위별 threshold metric, 다리 꼬기 지속 시간을 Gemini에
전달해 한국어 코칭 피드백을 생성합니다. 생성된 피드백은 Supabase 등 외부 DB에 저장하지
않고, 최종 리포트 화면(`screen-6`)에만 표시됩니다.

## 최종 리포트 인쇄

기존에는 최종 리포트에서 QR 코드로 모바일 결과 페이지에 연결했지만, 현재는 앱 화면에서
바로 인쇄하는 방식으로 대체되었습니다. `screen-6`의 "리포트 인쇄하기" 버튼은
`window.print()`를 호출하며, `style.css`의 `@media print` 규칙이 리포트 카드들을
A4 한 페이지에 맞는 세로 1열 레이아웃으로 재배치합니다. 인쇄 시 숨겨야 하는 버튼 등의
UI 요소에는 `no-print` 클래스를 붙여 관리합니다.

## 알려진 제한사항

- 코드에는 주석을 두지 않는 것을 원칙으로 합니다. 동작을 바꾸는 수정을 할 때는 이 README의
  관련 섹션도 함께 갱신해 주세요.
