# Pose-Report — 아키텍처 및 로직 상세 문서

이 문서는 `Pose-Report`의 동작 방식, 아키텍처, 설계 이유를 정리한 참고 문서입니다.
이 프로젝트는 **코드에 주석을 두지 않는 방식(바이브 코딩)**으로 관리하기 때문에,
로직에 대한 설명·배경·주의사항은 모두 이 문서에 정리되어 있습니다. LLM이든 사람이든
코드를 수정하기 전에 관련 섹션을 먼저 확인하세요. 동작을 바꾸는 수정을 했다면
이 문서의 관련 섹션도 함께 갱신해야 합니다.

## 목차

- [개요](#개요)
  - [주요 기능](#주요-기능)
  - [배경](#배경)
  - [화면 구성](#화면-구성)
  - [파일 구조](#파일-구조)
- [시작하기](#시작하기)
  - [설치](#설치)
  - [환경 변수](#환경-변수-env)
  - [신뢰 채널 목록 설정](#신뢰-채널-목록-설정)
  - [서브커맨드 구조](#서브커맨드-구조)
  - [실행](#실행)
- [프런트엔드-백엔드 통신 구조](#프런트엔드-백엔드-통신-구조)
- [자세 분석 로직](#자세-분석-로직)
  - [각도 threshold 판정](#각도-threshold-판정)
  - [종합 점수 가중치](#종합-점수-가중치)
  - [다리 꼬기](#다리-꼬기)
- [Astra Pro 3D Depth 지원](#astra-pro-3d-depth-지원)
  - [메인 스레드 사전 초기화](#메인-스레드-사전-초기화)
  - [카메라 초기화 안정화 (레이스 컨디션/네이티브 크래시 대응)](#카메라-초기화-안정화-레이스-컨디션네이티브-크래시-대응)
  - [Depth 파이프라인 성능](#depth-파이프라인-성능)
- [측정 결과 처리 및 화면 동작](#측정-결과-처리-및-화면-동작)
  - [AI 피드백](#ai-피드백)
  - [최종 리포트 인쇄](#최종-리포트-인쇄)
  - [운영자 카메라 모니터링](#운영자-카메라-모니터링)
- [유튜브 쇼츠 자동 재생](#유튜브-쇼츠-자동-재생)
  - [ShortsPoolManager 동작 구조](#shortspoolmanager-동작-구조)
  - [프런트엔드 재생 구조](#프런트엔드-재생-구조)
  - [쇼츠 / 카메라 화면 전환 토글](#쇼츠--카메라-화면-전환-토글)
  - [배경: 왜 이 구조로 바뀌었는가](#배경-왜-이-구조로-바뀌었는가)
- [기타](#기타)

## 개요

카메라 앞에서 30초간 자세를 측정해 거북목 · 등/허리 · 어깨 · 골반을 점수화하고,
다리 꼬기는 별도의 기하학적 휴리스틱으로 감지합니다. 측정 결과는 Gemini API로 코칭
피드백을 생성한 뒤, 화면에서 바로 A4 용지로 인쇄해 확인할 수 있습니다.

카메라 캡처(OpenCV/Astra Pro)와 자세 분석은 Python(Flask) 백엔드에서 그대로 실행되고,
프런트엔드(`index.html`/`script.js`/`style.css`)는 **일반 웹 브라우저**에서 로컬 서버에
접속해 사용합니다.

### 주요 기능

- **실시간 자세 분석**: MediaPipe Pose로 신체 랜드마크를 추출해 프레임마다 자세를 채점
- **각도 threshold 기반 판정**: 목/머리, 등/허리, 어깨, 골반 각각에 대해 각도 threshold로 정상/위험을 판정
- **RULA 참고 가중 종합점수**: 프로젝트용 heuristic weighting으로 목 25 / 몸통 30 / 어깨 30 / 골반 15를 기본값으로 사용
- **다리 꼬기 휴리스틱**: 기존 선분 교차 기반 판정을 종합점수에 별도 감점으로 반영
- **Astra Pro 지원**: RGB + Depth / 3D skeleton 경로를 지원하며, 유효한 3D 좌표가 있으면 각도 계산에 3D 좌표를 사용
- **Depth 조회 벡터화**: 랜드마크별 depth 최근접 탐색을 프레임당 1회의 `cv2.distanceTransform` 호출로 처리 (자세한 내용은 [Astra Pro 3D Depth 지원](#astra-pro-3d-depth-지원) 참고)
- **유튜브 쇼츠 자동 재생**: 측정 중 참가자 화면에 신뢰 채널의 최신 쇼츠를 자동으로 순환 재생 (자세한 내용은 [유튜브 쇼츠 자동 재생](#유튜브-쇼츠-자동-재생) 참고)

### 배경

내성고등학교 '인공지능과 프로그래밍 동아리' 소속 학생들(윤재선, 윤재원, 최현수)이
2026년 9월 9일(수)~11일(금) 부산 벡스코(BEXCO) 제1전시장 3홀에서 열리는
'AI KOREA 2026(2026 K-ICT WEEK in BUSAN)' 부스 전시에 출품하기 위해 개발한 작품입니다.

스마트 기기 사용 증가로 인한 척추 건강·자세 불균형 문제에 대응해, 고가의 장비 없이도
누구나 자신의 자세를 측정하고 맞춤형 피드백을 받을 수 있는 시스템을 만드는 것이
개발 의도입니다. 전시 부스에서는 관람객이 카메라 앞에 착석해 자세를 측정하면, 측정이
진행되는 동안 디스플레이로 화면을 재생해 관람객의 집중을 유도하고, 측정이 끝나면 분석
결과와 AI 코칭 피드백을 화면에 표시하는 방식으로 운영합니다. 운영진(동아리 학생들)이
전시 기간 내내 부스에 상주하며 기기를 관리합니다.

### 화면 구성

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

### 파일 구조

```text
Pose-Report/
├── main.py               # Flask 서버 실행 + Astra Pro 캘리브레이션 서브커맨드 포함
├── config.py             # 각도 threshold / 종합 점수 가중치 / 신뢰 채널 목록 기본값
├── run.bat               # main.py 워치독 (Windows 전용, 예기치 않은 종료 시 자동 재시작)
├── index.html            # SPA 메인 화면 (screen 0~6)
├── frontend.html         # 개인정보 수집·이용 동의 안내 페이지 (정적 파일로 서빙)
├── script.js
├── style.css
├── requirements.txt
├── README.md             # 간단한 프로젝트 소개
└── AI_CONTEXT.md         # 이 문서
```

서버 실행 중 `shorts_pool.json`(쇼츠 후보 pool 캐시)이 프로젝트 루트에 자동 생성됩니다.
API 재호출 없이도 재시작 시 이전 pool을 바로 쓰기 위한 캐시 파일이므로 버전관리에는
포함하지 않는 것을 권장합니다.

## 시작하기

### 설치

```bash
pip install -r requirements.txt
```

Python 3.11.x 환경을 기준으로 작성되었습니다.

### 환경 변수 (`.env`)

프로젝트 루트에 `.env` 파일을 만들고 아래 값을 채워주세요.

```bash
GEMINI_API_KEY=여기에_Gemini_API_키
SUPABASE_ANON_KEY=여기에_Supabase_anon_key
YOUTUBE_API_KEY=여기에_YouTube_Data_API_v3_키
# 선택: 기본값은 127.0.0.1:8000
HOST=127.0.0.1
PORT=8000
```

`YOUTUBE_API_KEY`는 [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를
만들고 "YouTube Data API v3"를 활성화한 뒤 발급받는 일반 API 키입니다. Instagram oEmbed와
달리 별도의 앱 심사(App Review) 없이 즉시 발급되며, 무료 할당량(하루 10,000 유닛)으로
충분합니다. 키가 없으면 [ShortsPoolManager](#shortspoolmanager-동작-구조)가 콘솔에 경고를
남기고 쇼츠 재생 없이 나머지 기능(자세 분석 등)은 정상 동작합니다.

### 신뢰 채널 목록 설정

`config.py`의 `TRUSTED_YT_CHANNELS`에 자동 재생할 유튜브 채널을 넣어두세요. 채널 ID
(`UC`로 시작하는 24자, 예: `UCxxxxxxxxxxxxxxxxxxxxxx`)와 채널 핸들(`@`로 시작하는 표시
이름, 예: `@ChannelName`)을 섞어서 넣어도 됩니다.

```python
TRUSTED_YT_CHANNELS = ["UCxxxxxxxxxxxxxxxxxxxxxx", "@SomeChannelHandle"]
```

채널 ID는 `UC` + 22자 패턴으로 정규식 매칭해 바로 사용하고, 그 외의 값은 모두 핸들로
간주해 `channels.list(part=id, forHandle=...)`로 실제 채널 ID를 조회한 뒤 사용합니다
(`@` 접두사를 안 붙여도 자동으로 붙여서 조회). 핸들 → 채널 ID 조회 결과는
`ShortsPoolManager._handle_cache`에 프로세스가 살아있는 동안 캐시되므로, 갱신 주기마다
매번 다시 조회하며 API 할당량을 쓰지 않습니다. 목록이 비어 있거나 특정 항목의 조회가
실패하면 그 항목만 건너뛰고 콘솔에 경고를 남기며, 나머지 채널의 후보 수집은 계속됩니다.
자세한 배경은 [유튜브 쇼츠 자동 재생](#유튜브-쇼츠-자동-재생) 참고.

### 서브커맨드 구조

`main.py`는 인자 없이 실행하면 Flask 서버를 띄우고, 첫 번째 인자로 아래 서브커맨드를 받으면
해당 오프라인 파이프라인만 실행합니다.

```bash
python main.py                # 기본: Flask 서버 실행
python main.py calibrate [카메라 인덱스]   # Astra Pro 스테레오 캘리브레이션
```

### 실행

```bash
python main.py
```

Astra Pro를 쓰는 환경(Windows)에서는 `python main.py` 대신 `run.bat`으로 실행하는
것을 권장합니다. 이유는 [카메라 초기화 안정화](#카메라-초기화-안정화-레이스-컨디션네이티브-크래시-대응)
참고.

터미널에 출력되는 주소(기본 `http://127.0.0.1:8000`)를 웹 브라우저로 열면 됩니다.
카메라 장치 접근과 자세 분석은 서버 프로세스(Python)에서 그대로 수행하고, 프런트엔드는
프레임 이미지와 측정값을 SSE(Server-Sent Events, `/api/events`)로 실시간 전달받아
화면에 표시합니다. 즉 브라우저는 `getUserMedia`로 카메라에 직접 접근하지 않으며,
카메라 접근과 캡처는 서버 쪽 OpenCV/Astra 파이프라인에서만 수행합니다.

같은 네트워크의 다른 기기(예: 태블릿)에서 접속하려면 `HOST=0.0.0.0`으로 실행한 뒤
서버 PC의 IP로 접속하세요. 다만 이 앱은 서버가 로컬로 잡고 있는 카메라 하나만
스트리밍하는 1인용 구조이므로, 여러 브라우저 탭/기기에서 동시에 접속해도 모두
같은 카메라 피드를 보게 됩니다.

참가자가 보는 브라우저(키오스크 화면)에서 유튜브 쇼츠가 소리와 함께 자동 재생되게
하려면, 해당 브라우저를 `--autoplay-policy=no-user-gesture-required` 플래그로 실행하는
것을 권장합니다. 이 플래그 없이는 최초 진입 시 브라우저 자동재생 정책 때문에 첫 영상이
음소거 상태로 시작될 수 있습니다(자세한 내용은
[프런트엔드 재생 구조](#프런트엔드-재생-구조) 참고).

## 프런트엔드-백엔드 통신 구조

브라우저에는 파이썬 객체를 직접 호출할 수 있는 네이티브 브리지가 없으므로, JS ↔ Python
통신은 REST 엔드포인트와 SSE(Server-Sent Events) 스트림으로 이루어집니다.

- **JS → Python**: `fetch()`로 호출하는 일반 REST 엔드포인트.
  - `POST /api/setup_and_start` — 설정 화면 값으로 측정 설정 후 캡처 시작 (`CameraApp.setup_and_start`)
  - `POST /api/toggle_camera` — `{ "enabled": bool }`로 분석 on/off (`CameraApp.toggle_camera`)
  - `POST /api/stop_capture` — 카메라 캡처 자체를 완전히 정지(Astra `SkeletonViewer` /
    `WEBCAM_MONITOR_WINDOW` / 카메라 장치까지 모두 정리, `CameraApp.stop_capture`).
    운영자 단축키 Ctrl+↑(`resetToInitialSetup()`)에서 사용
  - `GET /api/supabase_key` — Supabase anon key 조회 (`CameraApp.get_supabase_key`)
  - `POST /api/generate_llm_advice` — 측정 결과로 Gemini 코칭 피드백 생성 (`CameraApp.generate_llm_advice`)
  - `GET /api/next_short` — 쇼츠 pool에서 다음 영상 ID 하나 조회 (`ShortsPoolManager.next_video_id`)
- **Python → JS**: `GET /api/events`로 여는 SSE(Server-Sent Events) 스트림 하나.
  카메라 프레임(`type: "frame"`)과 카메라 준비 완료(`type: "camera_ready"`) 메시지를
  JSON으로 브로드캐스트하며, `script.js`가 페이지 로드 시점에 `EventSource`로 구독해
  기존 `window.updateFrame(...)` / `window.onCameraReady()` 콜백을 그대로 호출합니다.
  `CameraApp._broadcast()`가 연결된 모든 SSE 클라이언트 큐에 메시지를 넣고,
  큐가 가득 차면(구독자가 프레임 처리 속도를 못 따라가면) 오래된 프레임을 버리고
  최신 프레임으로 교체합니다 (실시간 스트림이므로 최신 값만 의미 있음).

전체화면(F11)은 브라우저 표준 Fullscreen API로 처리하며, 브라우저 탭은 스크립트로 강제
종료할 수 없으므로 Escape 키로 창을 닫는 기능은 없습니다.

운영자용 키보드 단축키(`script.js`의 전역 `keydown` 리스너)로 Ctrl+→/←는 화면을
한 단계 앞/뒤로 전환하고, Ctrl+↑는 어느 화면에 있든 `resetToInitialSetup()`을 거쳐
초기 설정 화면(screen 0)으로 즉시 이동합니다. `resetToInitialSetup()`은 타이머/폴링
인터벌을 모두 정리하고 사전 카운트다운 오버레이를 닫은 뒤 `collectedMetrics` /
`finalReportData` / `currentUuid` / `captureLoopStarted` 등 세션 상태를 초기값으로
되돌리고 `backendApi.stop_capture()`로 카메라 캡처 자체를 완전히 종료합니다. 이렇게
어느 화면에서 넘어오든 상태를 리셋한 뒤 이동해야 다음에 다시 측정을 시작할 때 이전
세션의 타이머나 수집 중이던 지표가 섞여 들어오는 충돌을 피할 수 있습니다.

**Ctrl+↑는 카메라/모니터링 창까지 프로그램 최초 실행 시점 상태로 되돌립니다**:
`POST /api/stop_capture`(`CameraApp.stop_capture`)는 `screen-4`를 벗어날 때 쓰는
`toggle_camera(false)`(참가자 화면으로의 SSE 전송만 멈춤, [운영자 카메라
모니터링](#운영자-카메라-모니터링) 참고)와 달리 캡처 자체를 정지시킵니다.
`camera_enabled`/`capture_active`를 모두 끄고 `_capture_active_event`를 깨운 뒤,
`_stop_astra_capture()`로 Astra 디버그 스레드에 `stop_event`를 걸어 join합니다 —
`run_debug_skeleton_viewer`의 `finally` 블록이 실행되며 Open3D `SkeletonViewer` 창이
안전하게 `close()`됩니다. 이어서 `self.cap`(웹캠 `cv2.VideoCapture`)을 해제하고
`_close_webcam_monitor()`로 `WEBCAM_MONITOR_WINDOW`도 닫습니다(`capture_active`가
꺼지면 `start_camera_thread` 루프 자체도 다음 반복에서 동일하게 정리하므로 이중
안전장치입니다). `_astra_precreated`(사전 초기화된 Astra 카메라 핸들)는 해제하지
않고 그대로 남겨두므로, 다음에 `screen-1`(카메라 로딩)에 다시 진입해
`setup_and_start()`가 호출되면 `on_closing()`(앱 완전 종료)과 달리 카메라를 다시 열지
않고 재사용해 초기화 시간을 절약합니다. 즉 Ctrl+↑ 이후의 상태는 `CameraApp.__init__`
직후(`capture_active=False`, 카메라/뷰어/모니터링 창 모두 없음)와 동일하며, 다음
측정은 `screen-1` 진입 시 `startCaptureLoop()` → `setup_and_start()`로 프로그램을
맨 처음 켰을 때와 같은 경로를 그대로 다시 탑니다.

## 자세 분석 로직

### 각도 threshold 판정

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

**각도 threshold/가중치 기본값은 `config.py`가 유일한 소스입니다**: 각도 threshold와
종합 점수 가중치를 `config.py`에 모아두었고, `CameraApp.__init__`과 `setup_and_start()`의
기본 인자값이 이 값을 그대로 가져다 씁니다. `index.html`의 초기 설정 화면(`screen-1`)에는
더 이상 각도/가중치 입력 필드가 없으며, "설정 완료" 버튼은 카메라 소스/인덱스만 body에
실어 `POST /api/setup_and_start`를 호출합니다(`api_setup_and_start`는 `camera_idx`,
`camera_source`, `debug_cam_idx`만 body에서 읽습니다). 각도/가중치를 바꾸려면 서버를
재시작하기 전에 `config.py`를 수정하세요. 카메라 소스(`카메라 소스` select)와 웹캠/Astra
장치 인덱스는 여전히 `index.html` 설정 화면에서 매 실행마다 고를 수 있습니다.

### 종합 점수 가중치

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

### 다리 꼬기

`main.py`의 선분 교차 기반 `_detect_leg_cross()` (`is_intersect()` 이용) 결과를 그대로
사용해 종합점수에 별도 감점을 적용합니다. 측정 결과에는 다리 꼬기 지속 시간도
함께 기록합니다.

## Astra Pro 3D Depth 지원

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

### 카메라 초기화 안정화 (레이스 컨디션/네이티브 크래시 대응)

`AstraCamera.__init__`의 초기화 시퀀스(`openni2.initialize` → `Device.open_any` →
depth 스트림 생성/설정 → IR 스트림 생성/설정 → `cv2.VideoCapture`로 RGB 오픈)는 실제
운영 중 **파이썬 예외나 로그 없이 프로세스 자체가 죽는** 사례가 반복적으로 보고되었고,
재현율이 대략 50%에 달했습니다. 원인은 한 줄이 아니라 시퀀스 전체의 구조적 문제입니다.

- **RGB(UVC) 오픈 시 MSMF 백엔드 크래시**: `cv2.VideoCapture(index)`처럼 백엔드를 명시하지
  않으면 Windows에서는 기본적으로 MSMF(Media Foundation) 백엔드가 선택됩니다. MSMF는
  WinRT/COM 기반 비동기 장치 열거 과정에서 네이티브 예외로 프로세스 전체가 죽는 사례가
  OpenCV 공식 이슈 트래커에 다수 보고되어 있습니다.
- **depth/IR 스트림 경합**: Astra류 구조광(structured light) 센서는 물리적으로 IR 센서
  하나를 depth 계산용/raw IR용으로 시분할해서 씁니다(`start_depth`/`start_ir`가 서로를
  멈추고 시작하는 상호 배타 구조인 이유). 생성자에서 depth 스트림 설정 직후 곧바로 IR
  스트림을 만들고 설정하면, 드라이버가 이전 명령을 완전히 처리하기 전에 다음 네이티브
  호출이 들어가면서 크래시가 발생하는 사례가 있었습니다.
- **복합 USB 장치 타이밍**: Astra 카메라는 depth/IR과 RGB가 물리적으로 하나의 복합 USB
  장치라서, OpenNI2가 장치를 붙잡고 있는 상태에서 곧바로 `cv2.VideoCapture`로 같은 장치에
  접근하면 레이스 컨디션이 생기기 쉽습니다.

이를 줄이기 위해 `AstraCamera` 초기화에 다음 대응을 적용했습니다.

1. **MSMF 하드웨어 트랜스폼 비활성화**: `main.py` 최상단에서 `cv2`를 import하기 전에
   `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0`을 설정합니다. MSMF의 GPU 가속 경로에서
   발생하는 크래시/행을 줄이는 것으로 알려진 워크어라운드입니다.
2. **RGB 캡처 백엔드 우선순위 지정**: `_open_rgb_capture()`가 `cv2.CAP_DSHOW` →
   `cv2.CAP_MSMF` → `cv2.CAP_ANY` 순서로 오픈을 시도합니다. DirectShow가 MSMF보다
   훨씬 오래되고 안정적인 백엔드라 우선 시도하고, 실패하면 순서대로 폴백합니다.
3. **IR 스트림 지연 생성(lazy init)**: `__init__`에서는 depth 스트림만 만들고, IR
   스트림은 실제로 `start_ir()`이 호출되는 시점(`_ensure_ir_stream()`)에만 생성합니다.
   depth/IR은 어차피 동시에 쓰지 않으므로(상호 배타), 초기화 시 네이티브 호출 수 자체를
   줄여 크래시 가능 구간을 좁힙니다.
4. **settle delay**: openni2 초기화, 장치 열기, depth 설정, IR 생성 등 위험 구간 사이에
   `CAMERA_INIT_SETTLE_SEC`(기본 0.35초)만큼 짧게 대기해 드라이버가 이전 명령을 처리할
   시간을 줍니다. 초기화가 그만큼 느려지는 트레이드오프가 있으므로, 너무 느리다고 느껴지면
   이 값을 낮춰서 조정할 수 있습니다.
5. **생성 재시도**: `create_astra_camera_with_retry()`가 `AstraCamera(...)` 생성을
   감싸서, 파이썬 레벨에서 잡히는 예외(예: `OniError`)가 나면 정리 후 최대
   `CAMERA_INIT_MAX_ATTEMPTS`회(기본 3회, `CAMERA_INIT_RETRY_BACKOFF_SEC`=1.5초 간격)
   재시도합니다. `run_calibration`, `preinitialize_astra_camera`,
   `run_debug_skeleton_viewer` 세 호출부 모두 `AstraCamera(...)`를 직접 부르지 않고
   이 헬퍼를 거칩니다.

**중요한 한계**: 위 5가지는 전부 파이썬 레벨에서 잡히는 실패에만 대응합니다. 순수한
네이티브 하드 크래시(access violation 등으로 프로세스 자체가 죽는 경우)는 같은 프로세스
안에서는 원리적으로 복구할 수 없습니다. 그래서 프로세스가 죽으면 즉시 재시작하는
`run.bat`(Windows 배치 워치독)을 함께 제공합니다. `python main.py`를 직접
실행하는 대신 이 배치파일로 실행하면, 초기화 중 정상 종료가 아닌 종료(exit code != 0)를
감지해 2초 후 자동으로 다시 띄웁니다. Ctrl+C로 정상 종료하면 재시작 없이 그대로 창이
닫힙니다.

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

## 측정 결과 처리 및 화면 동작

### AI 피드백

측정 종료 후 종합 점수, 4개 부위별 threshold metric, 다리 꼬기 지속 시간을 Gemini에
전달해 한국어 코칭 피드백을 생성합니다. 생성된 피드백은 Supabase 등 외부 DB에 저장하지
않고, 최종 리포트 화면(`screen-6`)에만 표시됩니다.

### 최종 리포트 인쇄

기존에는 최종 리포트에서 QR 코드로 모바일 결과 페이지에 연결했지만, 현재는 앱 화면에서
바로 인쇄하는 방식으로 대체되었습니다. `screen-6`의 "리포트 인쇄하기" 버튼은
`window.print()`를 호출하며, `style.css`의 `@media print` 규칙이 리포트 카드들을
A4 한 페이지에 맞는 세로 1열 레이아웃으로 재배치합니다. 인쇄 시 숨겨야 하는 버튼 등의
UI 요소에는 `no-print` 클래스를 붙여 관리합니다.

### 운영자 카메라 모니터링

디버그 모드 옵션(체크박스)은 제거되었고, 카메라가 동작하는 동안(설정 이후 ~ 측정 종료까지)
운영자 PC에는 항상 모니터링 창이 뜹니다.

- **Astra Pro**: 기존 Open3D `SkeletonViewer` 3D 스켈레톤 창이 항상 실행되는 것에 더해
  (`run_debug_skeleton_viewer(show_viewer=True)` 고정), `CameraApp.start_camera_thread`가
  Astra 프레임 콜백(`_on_astra_frame`)에서 받은 RGB `frame`을 그대로
  `_show_webcam_monitor(frame)`에 넘겨 동일한 `CameraApp.WEBCAM_MONITOR_WINDOW`
  cv2 창도 함께 띄웁니다. 즉 Astra Pro 모드에서는 Open3D 3D 스켈레톤 창과
  `WEBCAM_MONITOR_WINDOW` 2D 창이 동시에 표시됩니다.
- **MediaPipe 웹캠**: `CameraApp.start_camera_thread`가 매 프레임마다 랜드마크를 그려
  `cv2.imshow(CameraApp.WEBCAM_MONITOR_WINDOW, frame)`으로 로컬 창을 띄웁니다.
- **공통(Astra Pro / MediaPipe 웹캠)**: `WEBCAM_MONITOR_WINDOW`는 참가자 화면(SSE)과
  무관하게 프레임이 들어올 때마다 항상 갱신되며, `camera_enabled`가 꺼져 있어도(측정
  일시정지 상태 등) 계속 표시됩니다. 참가자 화면으로의 SSE 프레임 전송(`_push_frame`,
  Astra의 경우 `_process_and_push_astra_frame`)만 `camera_enabled`를 따릅니다.
  카메라 소스 전환/캡처 중단/앱 종료 시 `CameraApp._close_webcam_monitor()`가
  `cv2.destroyWindow`로 창을 정리합니다.

**좌우 반전(서버 쪽은 모니터링 전용)**: 초기 설정 화면의 "카메라 좌우 반전" 체크박스
(`cfg-mirror`)는 `CameraApp.mirror_camera`로 전달되며, 서버(Python) 쪽에서는 운영자용
모니터링 화면에만 영향을 줍니다. SSE로 전송되는 원본 `frame` 이미지나 각도 계산에는
전혀 영향을 주지 않습니다. 다만 `script.js`가 같은 체크박스 값을 브라우저에서 다시 읽어,
[참가자 화면의 카메라 토글 뷰(`#camera-view`)](#쇼츠--카메라-화면-전환-토글)에
CSS로 별도 반전을 적용합니다 — 이는 서버 로직과 무관한 순수 프런트엔드 처리입니다.
- **MediaPipe 웹캠**: `_show_webcam_monitor()`가 `cv2.imshow`에 넘기기 직전에만
  `cv2.flip(frame, 1)`로 복사본을 만들어 표시합니다. `_push_frame()`으로 참가자에게 보내는
  원본 `frame`은 건드리지 않습니다.
- **Astra Pro**: `SkeletonViewer.update()`가 렌더링용으로 복사한 `pts` 배열에만
  `pts[:, 0] *= -1`을 적용합니다. 각도 계산에 쓰이는 원본 `points3d`와 참가자 화면으로
  전송되는 `disp` 프레임은 그대로 유지됩니다.

## 유튜브 쇼츠 자동 재생

`screen-4`(30초 측정 화면)에서 참가자의 시선을 끌기 위해 유튜브 쇼츠를 자동으로 순환
재생합니다. 자세 분석 자체는 기존과 동일하게 실제 카메라(웹캠/Astra)로 서버에서 계속
수행되며, 그 결과(점수/상태 텍스트)만 타이머·상태 오버레이에 반영됩니다.

### ShortsPoolManager 동작 구조

`main.py`의 `ShortsPoolManager`가 백그라운드 스레드에서 4시간(`YT_SHORTS_REFRESH_INTERVAL_SEC`)
마다 아래 순서로 재생 후보 pool을 갱신합니다.

1. `config.TRUSTED_YT_CHANNELS`의 각 항목을 채널 ID로 정규화합니다. `UC`로 시작하는 24자
   패턴이면 그대로 쓰고, 아니면 채널 핸들로 간주해 `channels.list(part=id, forHandle=...)`로
   실제 채널 ID를 조회합니다(결과는 메모리에 캐시). 조회에 실패한 항목은 건너뜁니다.
2. 정규화된 각 채널 ID에 대해 YouTube Data API v3의
   `search.list(channelId=..., order=date, type=video)`로 최신 업로드 영상 ID를 가져옵니다
   (채널당 `YT_SHORTS_PER_CHANNEL_FETCH`개).
3. 모은 영상 ID를 `videos.list(part=status,contentDetails)`로 다시 조회해
   `status.embeddable`(임베드 허용 여부), `status.madeForKids`(어린이용 여부),
   재생 길이(`YT_SHORTS_MAX_DURATION_SEC` = 60초 이하)를 기준으로 필터링합니다.
4. 필터링된 ID 목록을 pool로 저장하고 `shorts_pool.json`에 캐시합니다(재시작 시 API
   재호출 없이 즉시 재생 가능하도록).

`next_video_id()`는 pool을 무작위 순서로 섞은 큐에서 하나씩 꺼내 반환하고, 큐를 다 쓰면
다시 섞습니다(같은 영상이 바로 연달아 나오지 않도록). `YOUTUBE_API_KEY`가 없거나
`TRUSTED_YT_CHANNELS`가 비어 있으면 콘솔에 경고를 남기고 갱신을 건너뛰며, API 호출이
실패해도(`requests.RequestException`) 다음 주기(`YT_SHORTS_REFRESH_RETRY_SEC` = 5분 후)에
재시도합니다. 채널 조회는 채널별로 개별 예외 처리를 하므로, 채널 하나가 실패해도 나머지
채널의 후보 수집은 계속됩니다.

### 프런트엔드 재생 구조

`index.html`의 `#shorts-player`는 유튜브 IFrame Player API(`youtube.com/iframe_api`)로
생성된 플레이어를 담는 컨테이너입니다. `script.js`의 `onYouTubeIframeAPIReady()`가
API 로드 완료 시 자동 호출되어 플레이어를 생성하고(`controls: 0`, `modestbranding: 1`로
자체 UI를 최소화), `loadNextShort()`가 `GET /api/next_short`로 다음 영상 ID를 받아
`player.loadVideoById()`로 교체합니다.

**자동 전환 없이 참가자가 버튼으로만 다음 영상으로 넘어갑니다.** `screen-4` 진입 시 영상
하나를 자동으로 로드하지만, 그 이후 다음 영상으로의 전환은 `#btn-next-short`("다음 영상")
버튼을 눌러야만 일어납니다. 영상이 재생 중 끝나도 자동으로 다음 곡으로 넘어가지 않고
그대로 정지 상태로 남습니다. `screen-4`를 벗어나면(`showScreen`에서 이전 `currentIndex`가
4였던 경우) `shortsPlayer.stopVideo()`로 재생을 멈춥니다.

**자동재생 정책**: `loadVideoById()`는 즉시 재생을 시도하지만, 브라우저의 자동재생
정책상 사용자 제스처 없이 소리가 있는 채로 자동재생되지 않을 수 있습니다. `loadNextShort()`
안에서 `player.unMute()`를 함께 호출해 최대한 소리가 나도록 시도하지만, 완전히 보장하려면
[실행](#실행) 섹션에 안내된 대로 참가자용 브라우저를
`--autoplay-policy=no-user-gesture-required` 플래그로 실행하는 것을 권장합니다.

### 쇼츠 / 카메라 화면 전환 토글

`screen-4`(`.viewfinder-wrapper`)에는 `#shorts-player`(유튜브 쇼츠)와 `#camera-view`(실제
카메라 원본, 자세 분석에 쓰이는 것과 같은 프레임) 두 화면이 겹쳐 있고, 좌측 상단
`#btn-toggle-view` 버튼으로 둘 중 보여줄 화면을 전환합니다(`script.js`의
`setViewMode('shorts' | 'camera')`). `screen-4`에 진입할 때마다 쇼츠 화면으로
초기화됩니다. 카메라 화면이 보이는 동안에는 "다음 영상" 버튼(`.next-short-btn`)이
숨겨집니다(`.viewfinder-wrapper.mode-camera .next-short-btn { display: none; }`).

타이머·상태 오버레이·사전 카운트다운은 기존과 동일하게 두 화면 위에 그대로 얹힙니다.
`#camera-view`로의 카메라 프레임 렌더링은 [운영자 카메라 모니터링](#운영자-카메라-모니터링)에
설명된 좌우 반전 로직을 그대로 따르며, `createFrameRenderer`의 busy-drop 가드(이전 프레임
디코딩이 끝나지 않았으면 최신 프레임만 보관했다가 이어서 그리는 방식)도 동일하게 적용됩니다.

뷰파인더는 `screen-4` 전체(페이지 전체 영역)를 차지합니다. `#screen-4`가 다른 화면과
공유하는 `.screen`의 기본 `padding: 40px`를 id 선택자로 덮어써 `padding: 0`으로 만들고,
`.camera-layout`/`.viewfinder-wrapper`를 각각 `width: 100%; height: 100%;`로 채워서
화면 어디에도 여백 없이 꽉 차게 합니다. `.viewfinder-wrapper`의 배경은 흰색(`#ffffff`)이며,
`display: flex; align-items: center; justify-content: center;`로 자식(쇼츠/카메라)을
페이지 한가운데 배치합니다.

쇼츠(대체로 9:16)와 카메라 원본(대체로 4:3)은 이 흰 배경 위에 각자의 실제 비율 그대로,
꽉 채우지 않고 떠 있는 형태로 표시하며 각각 모서리를 둥글게(`border-radius: 24px`)
처리합니다. 레터박스/필러박스(미디어 배경색 띠)를 쓰지 않고 대신 두 방식으로 처리합니다.

- **`#camera-view`**: `<img>`에 `width: auto; height: auto; max-width: 100%; max-height: 100%;`를
  줘서 이미지 고유 해상도 비율 그대로 부모 공간에 맞을 때까지만 축소되도록 합니다(내용
  없는 여백이 박스 안에 남지 않으므로, `border-radius`가 실제 이미지 가장자리에 딱
  맞게 적용됩니다).
- **`#shorts-player`**: 유튜브 iframe에는 `object-fit`이나 내재적 크기 기반 자동 크기
  조절이 적용되지 않으므로, 부모 컨테이너(`.shorts-video-wrap`)를
  `aspect-ratio: 9/16; height: 100%;`인 박스로 만들어 실제 쇼츠 비율과 정확히 맞춘 뒤
  (`.viewfinder-wrapper`의 flex 중앙 정렬로 배치), `overflow: hidden`과 `border-radius`를
  이 컨테이너에 적용합니다. 컨테이너 비율이 영상과 정확히 일치하므로 유튜브 자체
  레터박스도 나타나지 않습니다.

다른 비율의 콘텐츠를 쓰게 되면 `aspect-ratio` 값들을 함께 조정해야 합니다.

### 쇼츠 휠 스크롤 탐색

마우스 휠로도 이전/다음 쇼츠로 이동할 수 있습니다(`setupShortsWheelNav`, `script.js`).
`document` 전체에 `wheel` 리스너를 걸어서 `shorts-stage` 바깥에 마우스가 있어도 동작하며,
`currentIndex === 4`(쇼츠 측정 화면)이고 `viewMode !== 'camera'`일 때만 반응합니다.
`deltaY`가 양수면 `goToNextShort()`, 음수면 `goToPrevShort()`를 호출하고, 연속 입력을
막기 위해 450ms 동안 `wheelLocked`로 잠급니다.

유튜브 iframe은 크로스오리진이라 마우스가 그 위에 있을 때 발생하는 `wheel` 이벤트는
부모 문서(`document`)로 전달되지 않는 브라우저 제약이 있습니다. 이를 우회하기 위해
`#shorts-player`(iframe) 위에 투명 오버레이 `.shorts-video-wrap > #shorts-scroll-shield`
(`z-index: 5`)를 겹쳐 두고, 여기에도 동일한 휠 핸들러를 직접 등록합니다. 이 오버레이는
`controls: 0`으로 유튜브 자체 컨트롤이 꺼져 있어 클릭 등 다른 상호작용을 가리지 않습니다.
`#shorts-player`(및 유튜브 API가 이를 대체한 iframe)와 `#shorts-scroll-shield`는
형제 관계로, 둘 다 `.shorts-video-wrap`을 기준으로 `position: absolute; inset` 형태로
꽉 채워집니다.

### 배경: 왜 이 구조로 바뀌었는가

원래는 서버가 Playwright(headless Chromium)로 인스타그램 브라우저 세션을 띄우고 화면을
스크린샷 스트리밍하는 방식이었습니다. 이 방식은 (1) CDP `Page.startScreencast`가 영상만
캡처하고 오디오 트랙이 없어 별도의 OS 레벨 오디오 캡처(VB-CABLE 가상 오디오 케이블 +
WASAPI 루프백)가 필요했고, (2) 인스타그램 로그인 세션을 자동화 도구로 조작하는 구조라
이용약관 리스크가 있었습니다. 유튜브 쇼츠 임베드(IFrame Player API)로 전환하면서 이 두
문제가 모두 사라졌습니다 — 브라우저가 재생하는 진짜 `<video>`이므로 소리가 기본으로
따라오고, 유튜브의 공식 임베드 방식이라 별도 세션 로그인이나 브라우저 자동화가
필요 없습니다. 대신 참가자가 인스타그램 피드처럼 자유롭게 스크롤하며 탐색하는 경험은
포기하고, 동아리가 미리 정한 신뢰 채널의 콘텐츠를 순환 재생하는 방식으로 바뀌었습니다.

## 기타

- 코드에는 주석을 두지 않는 것을 원칙으로 합니다. 동작을 바꾸는 수정을 할 때는 이 문서의
  관련 섹션도 함께 갱신해 주세요.

### requirements.txt 버전 고정 이유

`mediapipe==0.10.9`는 `numpy<2`를 요구하지만, `opencv-python`은 최근 버전부터
`numpy>=2`를 요구합니다. 두 패키지를 모두 버전 고정 없이 설치하면 pip가 서로
호환되지 않는 numpy 버전을 요구하는 상황(설치 실패 또는 "compiled against ABI
version..." 런타임 오류)이 발생할 수 있습니다. 그래서 `requirements.txt`에서
`opencv-python==4.9.0.80`(numpy 1.x 세대에서 빌드된 마지막 계열)과 `numpy<2`를
명시적으로 고정해 두었습니다. mediapipe를 다른 버전으로 올리려면 그 버전이
요구하는 numpy 상한을 먼저 확인하세요.