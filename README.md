# Pose-Report

카메라 앞에서 60초간 자세를 측정해 거북목 · 등 굽음 · 어깨/골반 비대칭 · 다리 꼬기를
점수화하고, Gemini API로 코칭 피드백을 생성한 뒤 QR 코드로 연결된 모바일 리포트
페이지에서 결과를 확인할 수 있는 [pywebview](https://pywebview.flowrl.com/) 기반
데스크톱 앱입니다.

## 주요 기능

- **실시간 자세 분석**: MediaPipe Pose로 신체 랜드마크를 추출해 프레임마다 자세를 채점
- **두 가지 카메라 소스**
  - **일반 웹캠**: 2D 랜드마크(x, y, 상대 z)로 각도를 근사 계산
  - **Orbbec Astra Pro (RGB-Depth)**: RGB + Depth를 정합해 관절의 실제 3D 좌표로
    더 정밀하게 각도를 계산 (최초 1회 스테레오 캘리브레이션 필요)
- **점진적 채점**: 기준 각도를 얼마나 크게 벗어났는지에 비례해 점수가 연속적으로
  낮아지는 방식 (특정 구간에서 점수가 멈추지 않음)
- **다리 꼬기 감지**: 60초 측정 동안 다리를 꼰 시간(초)을 함께 집계해 AI 피드백에 반영
- **AI 코칭 피드백**: Google Gemini API로 측정 결과를 바탕으로 한 자연어 피드백 생성
- **모바일 연동**: QR 코드로 개인정보 수집 동의 → 측정 → 모바일에서 결과 확인까지
  이어지는 흐름 (Supabase로 동의/결과 데이터 동기화)

## 화면 구성

앱은 `index.html`의 `.screen` 7개를 `showScreen(index)`로 전환하는 SPA 구조입니다.

| index | id | 화면 |
|---|---|---|
| 0 | `screen-1` | 초기 설정 (기준 각도, 카메라 소스, 디버그 모드) |
| 1 | `screen-camera-loading` | 카메라 로딩 대기 — **여기 진입 시 카메라 캡처 루프(3D 카메라 로드)가 시작되고, 첫 프레임이 도착하면 자동으로 메인 화면으로 전환됩니다** |
| 2 | `screen-2` | 메인 화면 ("시작하기") |
| 3 | `screen-3` | QR 개인정보 동의 (모바일 스캔 대기) |
| 4 | `screen-4` | 60초 측정 (카메라 프리뷰 + 실시간 점수). 착석이 확인되면 3초 카운트다운 후 타이머가 시작됩니다 |
| 5 | `screen-5` | 리포트 생성 중 (AI 피드백 요청 + 업로드) |
| 6 | `screen-6` | 최종 리포트 (점수, 세부 항목, AI 피드백, 다운로드용 QR) |

## 파일 구조

```
Pose-Report/
├── main.py                  # pywebview 진입점, CameraApp(js_api): 자세 분석/점수 계산/Gemini 호출
│                              #   + Astra Pro 캡처, 3D 역투영, 스테레오 캘리브레이션, Open3D 뷰어
│                              #   (구 pose3d_debug.py 내용이 이 파일에 통합됨)
├── index.html                # 데스크톱 앱 UI (화면 7개, SPA)
├── script.js                  # 화면 전환, 측정 로직, Supabase 연동
├── style.css                  # 데스크톱 앱 스타일
├── frontend/
│   ├── index.html            # (별도 배포) 모바일 개인정보 동의 페이지
│   └── result/index.html     # (별도 배포) 모바일 결과 리포트 페이지
└── README.md
```

> `frontend/` 아래 두 HTML은 데스크톱 앱과 별개로 Netlify 등에 독립 배포되는
> 웹페이지입니다. Supabase 테이블(`main`)을 매개로만 데스크톱 앱과 연결됩니다.

## 설치

```bash
pip install opencv-python mediapipe==0.10.9 pywebview numpy requests python-dotenv
```

Python 3.11.7 기준으로 개발/테스트되었습니다.

### 환경 변수 (`.env`)

프로젝트 루트에 `.env` 파일을 만들고 아래 값을 채워주세요.

```bash
GEMINI_API_KEY=여기에_Gemini_API_키
SUPABASE_ANON_KEY=여기에_Supabase_anon_key
```

- `GEMINI_API_KEY`: AI 피드백 생성(`gemini-3.1-flash-lite`)에 사용됩니다.
- `SUPABASE_ANON_KEY`: QR 동의 확인 및 리포트 업로드에 사용되는 Supabase 프로젝트의
  anon key입니다. Supabase 프로젝트 URL은 `script.js`에 하드코딩되어 있습니다.

### 실행

```bash
python main.py
```

## Astra Pro (3D Depth) 모드

설정 화면에서 카메라 소스를 "Astra Pro (Depth)"로 선택하면, 웹캠 대신 Orbbec
Astra Pro의 RGB+Depth 스트림으로 관절의 실제 3D 좌표를 계산해 더 정확한 각도를
얻습니다. `main.py`에 통합된 Astra Pro 캡처 코드(구 `pose3d_debug.py`)가 이 경로를
전담하며, `open3d`/`openni`는 Astra Pro를 실제로 사용할 때만 지연 import되므로
웹캠만 쓴다면 설치하지 않아도 됩니다.

```bash
pip install open3d openni
```

추가로 OpenNI2 SDK(redist)를 설치하고 `OPENNI2_REDIST` 환경 변수로 그 경로를
지정해야 합니다.

### 캘리브레이션 (Astra Pro 사용 시 최초 1회 필수)

```bash
python main.py calibrate
# 디버그 카메라 장치 인덱스를 직접 지정하려면
python main.py calibrate 1
```

캘리브레이션 결과는 `calibration_data/stereo_calibration.json`에 저장됩니다.
이 파일이 없으면 Astra Pro 경로는 자동으로 비활성화되고(에러 없이 스킵), 웹캠
경로는 그대로 사용할 수 있습니다.

### 디버그 모드 (3D 스켈레톤 뷰어)

설정 화면에서 "디버그 모드"를 켜면(Astra Pro 선택 시에만 노출), 측정 중 Open3D
창에 3D 스켈레톤을 추가로 띄워줍니다. 순수 부가 시각화이며 꺼도 측정 자체에는
영향이 없습니다.

## 점수 계산 방식

각 항목(거북목/등 굽음/목 기울어짐/상체 불균형/어깨 비대칭/골반 비대칭)은 설정
화면에서 지정한 기준 각도를 얼마나 초과했는지에 **비례해 연속적으로** 감점되며,
다리 꼬기가 감지되면 별도로 감점됩니다. 모든 항목의 감점을 합산해 0~100점
사이의 종합 점수로 환산합니다. 기준 각도 이내면 100점입니다.

| 기준 | 기본값 |
|---|---|
| 거북목 | 18.0° |
| 등 굽음 | 28.0° |
| 어깨 비대칭 | 8.0° |
| 골반 비대칭 | 7.0° |
| 목 기울어짐 | 7.0° |
| 상체 좌우 기울기 | 10.0° |

기준 각도는 설정 화면에서 사용자가 직접 조정할 수 있습니다.

## AI 피드백

측정 종료 후 종합 점수, 항목별 평균 각도, 다리 꼬기 지속 시간(초)을 Gemini에
전달해 자세 습관에 대한 한국어 피드백을 생성합니다. 생성된 피드백은 화면에
표시되는 동시에 Supabase에 업로드되어 QR로 스캔한 모바일 리포트 페이지에서도
확인할 수 있습니다.

## 알려진 제한사항

- 다리 꼬기 지속 시간은 실제 초 단위 타임스탬프 누적이 아니라, 60초 측정 동안
  인식된 프레임 중 다리를 꼰 프레임의 비율을 60초에 곱해 근사한 값입니다.
- Astra Pro는 물리 장치가 1대뿐이라 앱 내에서 이를 여는 스레드는 항상 하나로
  제한됩니다. 초기화(OpenNI2)는 최대 10초가량 걸릴 수 있으며, 이 시간이 지나도
  첫 프레임이 오지 않으면 화면에 지연 안내가 표시됩니다.
- Astra Pro 실기기에서의 전체 플로우(초기화 → 화면 전환 반복 → 종료) 검증은
  아직 완료되지 않았습니다. 실제 장치 보유 시 재검증이 필요합니다.
