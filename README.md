# Pose-Report

카메라 앞에서 30초간 자세를 측정해 거북목 · 등/허리 · 어깨 · 골반을 점수화하고,
다리 꼬기는 별도의 기하학적 휴리스틱으로 감지합니다. 측정 결과는 Gemini API로 코칭
피드백을 생성한 뒤, 화면에서 바로 A4 용지로 인쇄해 확인할 수 있습니다.

카메라 캡처(OpenCV/Astra Pro)와 자세 분석은 Python(Flask) 백엔드에서 그대로 실행되고,
프런트엔드(`index.html`/`script.js`/`style.css`)는 **일반 웹 브라우저**에서 로컬 서버에
접속해 사용합니다. (예전에는 [pywebview](https://pywebview.flowrl.com/) 기반 데스크톱
창으로 실행됐지만, 환경별 webview 런타임 호환성 문제 때문에 브라우저 기반으로
전환했습니다.)

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
├── main.py          # Flask 서버 실행 + Astra Pro 캘리브레이션 서브커맨드 포함
├── index.html
├── script.js
├── style.css
├── requirements.txt
└── README.md
```

## 설치

```bash
pip install -r requirements.txt
```

Python 3.11.x 환경을 기준으로 작성되었습니다.

### 환경 변수 (`.env`)

프로젝트 루트에 `.env` 파일을 만들고 아래 값을 채워주세요.

```bash
GEMINI_API_KEY=여기에_Gemini_API_키
SUPABASE_ANON_KEY=여기에_Supabase_anon_key
# 선택: 기본값은 127.0.0.1:8000
HOST=127.0.0.1
PORT=8000
```

## 서브커맨드 구조

`main.py`는 인자 없이 실행하면 Flask 서버를 띄우고, 첫 번째 인자로 아래 서브커맨드를 받으면
해당 오프라인 파이프라인만 실행합니다.

```bash
python main.py                # 기본: Flask 서버 실행
python main.py calibrate [카메라 인덱스]   # Astra Pro 스테레오 캘리브레이션
```

## 실행

```bash
python main.py
```

터미널에 출력되는 주소(기본 `http://127.0.0.1:8000`)를 웹 브라우저로 열면 됩니다.
카메라 장치 접근과 자세 분석은 서버 프로세스(Python)에서 그대로 수행하고, 프런트엔드는
프레임 이미지와 측정값을 SSE(Server-Sent Events, `/api/events`)로 실시간 전달받아
화면에 표시합니다. 즉 브라우저는 `getUserMedia`로 카메라에 직접 접근하지 않으며,
기존 pywebview 버전과 동일하게 서버 쪽 OpenCV/Astra 캡처 파이프라인을 그대로 사용합니다.

같은 네트워크의 다른 기기(예: 태블릿)에서 접속하려면 `HOST=0.0.0.0`으로 실행한 뒤
서버 PC의 IP로 접속하세요. 다만 이 앱은 서버가 로컬로 잡고 있는 카메라 하나만
스트리밍하는 1인용 구조이므로, 여러 브라우저 탭/기기에서 동시에 접속해도 모두
같은 카메라 피드를 보게 됩니다.

## 프런트엔드 ↔ 백엔드 통신

pywebview 시절에는 `js_api`로 파이썬 객체 메서드를 JS에서 직접 호출하고(`window.pywebview.api.X()`),
파이썬 쪽에서는 `window.evaluate_js()`로 JS 함수를 직접 호출했습니다. 브라우저에는 이런 양방향
네이티브 브리지가 없으므로 아래처럼 대체했습니다.

- **JS → Python**: `fetch()`로 호출하는 일반 REST 엔드포인트.
  - `POST /api/setup_and_start` — 설정 화면 값으로 측정 설정 후 캡처 시작 (`CameraApp.setup_and_start`)
  - `POST /api/toggle_camera` — `{ "enabled": bool }`로 분석 on/off (`CameraApp.toggle_camera`)
  - `GET /api/supabase_key` — Supabase anon key 조회 (`CameraApp.get_supabase_key`)
  - `POST /api/generate_llm_advice` — 측정 결과로 Gemini 코칭 피드백 생성 (`CameraApp.generate_llm_advice`)
- **Python → JS**: `GET /api/events`로 여는 SSE(Server-Sent Events) 스트림 하나.
  카메라 프레임(`type: "frame"`)과 카메라 준비 완료(`type: "camera_ready"`) 메시지를
  JSON으로 브로드캐스트하며, `script.js`가 페이지 로드 시점에 `EventSource`로 구독해
  기존 `window.updateFrame(...)` / `window.onCameraReady()` 콜백을 그대로 호출합니다.
  `CameraApp._broadcast()`가 연결된 모든 SSE 클라이언트 큐에 메시지를 넣고,
  큐가 가득 차면(구독자가 프레임 처리 속도를 못 따라가면) 오래된 프레임을 버리고
  최신 프레임으로 교체합니다 (실시간 스트림이므로 최신 값만 의미 있음).

전체화면(F11)은 pywebview 창 API 대신 브라우저 표준 Fullscreen API로 처리하며, 창을 강제로
닫는 기능(Escape → `close_window`)은 브라우저 탭을 스크립트로 닫을 수 없어 제거했습니다.

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

### 메인 스레드 사전 초기화

일부 PC(특히 데스크톱의 서드파티 USB3 컨트롤러)에서는 OpenNI2의 device open /
`create_depth_stream` 호출을 메인 스레드가 아닌 스레드에서 수행하면 예외 없이 그대로
멈추거나 프로세스가 종료되는 문제가 있습니다. 그래서 `flask_app.run()`이 메인 스레드의
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

## 운영자 카메라 모니터링

디버그 모드 옵션(체크박스)은 제거되었고, 카메라가 동작하는 동안(설정 이후 ~ 측정 종료까지)
운영자 PC에는 항상 모니터링 창이 뜹니다.

- **Astra Pro**: 기존 Open3D `SkeletonViewer` 3D 스켈레톤 창이 항상 실행됩니다
  (`run_debug_skeleton_viewer(show_viewer=True)` 고정).
- **MediaPipe 웹캠**: `CameraApp.start_camera_thread`가 매 프레임마다 랜드마크를 그려
  `cv2.imshow(CameraApp.WEBCAM_MONITOR_WINDOW, frame)`으로 로컬 창을 띄웁니다. 이 창은
  참가자 화면(SSE)과 무관하게 항상 갱신되며, `camera_enabled`가 꺼져 있어도(측정 일시정지
  상태 등) 계속 표시됩니다. 참가자 화면으로의 SSE 프레임 전송(`_push_frame`)만
  `camera_enabled`를 따릅니다. 카메라 소스 전환/캡처 중단/앱 종료 시
  `CameraApp._close_webcam_monitor()`가 `cv2.destroyWindow`로 창을 정리합니다.

## 인스타그램 스트리밍 (Playwright)

기존에 참가자 화면(`#viewfinder`)에 표시하던 카메라 프리뷰 대신, 서버가 백그라운드로 띄운
Playwright(Chromium, headless) 인스타그램 브라우저 화면을 스트리밍합니다. 자세 분석 자체는
기존과 동일하게 실제 카메라(웹캠/Astra)로 서버에서 계속 수행되며, 그 결과(점수/상태 텍스트)만
타이머·상태 오버레이에 반영됩니다. 즉 참가자는 자신의 카메라 화면 대신 인스타그램 화면을
보면서 측정을 받습니다.

### 동작 구조

- `main.py`의 `InstagramStreamer`가 앱 시작 시(`run_app()`) 단 하나의 브라우저 세션을 열고,
  프로세스가 살아있는 동안 계속 재사용합니다(참가자별로 새로 만들지 않음 — 기존 카메라와
  동일하게 "1인용 공유" 구조).
- Chromium은 `headless=True`로 실행되어 운영자 PC 화면에는 뜨지 않습니다. 화면은 항상
  1200×900(4:3) 가상 뷰포트로 고정되며, 이는 `.viewfinder-wrapper`의 CSS
  `aspect-ratio: 4/3`과 정확히 일치하도록 맞춰졌으므로 프런트엔드에서 크롭/레터박스 없이
  좌표를 선형 변환만으로 매핑할 수 있습니다. 뷰포트 크기를 바꾸려면 `main.py`의
  `IG_VIEWPORT_WIDTH`/`IG_VIEWPORT_HEIGHT`와 `script.js`의 동일한 이름의 상수, 그리고
  `style.css`의 `.viewfinder-wrapper { aspect-ratio }`를 함께 맞춰야 합니다.
- 프레임은 CDP `Page.startScreencast`로 push 방식으로 받아 SSE로 `{"type": "ig_frame",
  "image": <base64 jpeg>}` 형태로 브로드캐스트합니다(기존 카메라 프레임과 같은
  `/api/events` 채널을 공유하되 타입으로 구분). `script.js`는 `ig_frame` 수신 시
  `#viewfinder`의 `src`를 갱신하고, 기존 카메라 `frame` 이벤트는 더 이상 `#viewfinder`를
  갱신하지 않고 점수/상태 계산에만 쓰입니다.
- 참가자의 탭(클릭)/드래그(스크롤) 입력은 `#ig-input-layer`(투명 레이어, `#viewfinder` 위,
  타이머·상태 오버레이 아래)에서 Pointer Events로 잡아 `/api/ig_click`,
  `/api/ig_scroll`로 서버에 전달합니다. 서버는 이 요청을 큐에 넣고, Playwright 객체를
  생성한 스레드(`InstagramStreamer._run`) 안에서만 `page.mouse.click` / `page.mouse.wheel`을
  호출합니다(Playwright sync API는 여러 스레드에서 동시에 호출하는 것을 보장하지 않으므로,
  입력 처리를 전용 스레드로 직렬화했습니다). 데스크톱 마우스 휠 이벤트도 동일하게
  `/api/ig_scroll`로 전달됩니다.
- 오버레이(`.timer-badge`, `.status-overlay`, `.precountdown-overlay`)는 기존과 동일하게
  `.viewfinder-wrapper` 안에서 인스타그램 스트림 위에 그대로 얹힙니다. 사전 카운트다운
  중에는 `.precountdown-overlay`가 `z-index: 3`으로 전체를 덮으므로 그 동안은 참가자
  입력이 자연스럽게 막힙니다(입력 레이어 자체를 막지는 않지만, 시각적으로는 카운트다운이
  화면을 덮습니다).

### 로그인 세션 저장 (최초 1회, 운영자가 직접 실행)

인스타그램 계정 로그인은 headless 브라우저 안에서 직접 할 수 없으므로, 별도로 만든
`login_instagram.py`를 헤드풀(창이 보이는) 모드로 한 번 실행해 로그인한 뒤 세션을
저장해야 합니다.

```bash
python login_instagram.py
```

브라우저 창이 뜨면 인스타그램에 로그인한 뒤, 터미널로 돌아와 Enter를 누르면
프로젝트 루트에 `instagram_state.json`이 저장됩니다. `main.py`는 서버 시작 시 이 파일이
있으면 자동으로 불러와 로그인된 상태로 스트리밍을 시작하고, 없으면 콘솔에 경고를 남기고
비로그인 상태로 진행합니다. `instagram_state.json`은 로그인 쿠키를 담고 있으므로
`.gitignore`에 추가하는 등 외부에 노출되지 않도록 관리하세요.

### 참가자 동시 접속에 대한 가정

카메라와 마찬가지로 인스타그램 브라우저 세션도 프로세스 전체에서 하나만 존재하고 모든
접속자가 공유합니다. 여러 명이 동시에 접속해 각자 스크롤/클릭을 보내면 하나의 화면에
그대로 섞여서 반영됩니다(현재는 사실상 1인용 키오스크 구조를 그대로 따른 것입니다).

### 의존성 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

Linux 서버에서 처음 설치하는 경우 Chromium 실행에 필요한 시스템 라이브러리가 없을 수
있습니다. 이 경우 아래 명령도 함께 실행하세요.

```bash
playwright install-deps chromium
```

### 참고: 인스타그램 이용약관

이 기능은 운영자가 사전 로그인한 세션을 브라우저 자동화(Playwright)로 조작해 여러
참가자가 돌아가며 사용하는 구조입니다. 인스타그램 이용약관은 자동화된 접근이나 계정
공유에 제한을 둘 수 있으므로, 실제 행사/전시에 배포하기 전에 운영 주체가 별도로
검토하는 것을 권장합니다.

## 알려진 제한사항

- 코드에는 주석을 두지 않는 것을 원칙으로 합니다. 동작을 바꾸는 수정을 할 때는 이 README의
  관련 섹션도 함께 갱신해 주세요.
