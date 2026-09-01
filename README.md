# Pose-Report

카메라 앞에서 30초간 자세를 측정해 거북목 · 등/허리 · 어깨 · 골반을 점수화하고,
다리 꼬기는 별도의 기하학적 휴리스틱으로 감지합니다. 측정 중에는 인스타그램 릴스를
iframe으로 보여줘 "의식적으로 바른 자세를 취하는 것"을 방지하고, 측정 결과는 Gemini
API로 코칭 피드백을 생성한 뒤 그 자리에서 A4 한 장으로 인쇄해 확인할 수 있는
[pywebview](https://pywebview.flowrl.com/) 기반 데스크톱 앱입니다.

> 이 프로젝트는 코드에 주석을 두지 않는 방식(바이브 코딩)으로 관리합니다.
> 로직에 대한 설명, 배경, 주의사항은 모두 이 README에 정리되어 있으니,
> 코드를 수정하기 전에 관련 섹션을 먼저 확인하세요.

## 주요 기능

- **실시간 자세 분석**: MediaPipe Pose로 신체 랜드마크를 추출해 프레임마다 자세를 채점
- **부위별 독립 ML 분류기**: 목/머리, 등/허리, 어깨, 골반에 대해 각각 독립적인 binary classifier를 사용
- **구조적 shortcut learning 방지**: 각 분류기는 자기 부위에 해당하는 landmark subset만 입력으로 받음
- **부위별 안전 fallback**: 모델이 없거나 로드/추론에 실패한 부위만 angle threshold 방식으로 자동 전환
- **그룹 단위 학습 분리**: `person_id`를 기준으로 train / validation / test를 분리해 사람 단위 데이터 누수를 방지
- **RULA 참고 가중 종합점수**: 프로젝트용 heuristic weighting으로 목 25 / 몸통 30 / 어깨 30 / 골반 15를 기본값으로 사용
- **다리 꼬기 휴리스틱 유지**: ML 학습 대상이 아니며 기존 선분 교차 기반 판정을 종합점수에 별도 감점으로 반영
- **ML 기반 상세 리포트**: 리포트의 4개 progress bar와 값은 프레임별 ML/fallback 점수 평균을 사용
- **feature importance 진단**: 4개 부위 모델의 주요 feature를 모델별로 출력하는 서브커맨드 제공
- **Astra Pro 지원**: 기존 RGB + Depth / 3D skeleton 경로를 유지하며, 부위별 ML feature에도 가능한 경우 3D 좌표를 사용
- **Depth 조회 벡터화**: 랜드마크별 depth 최근접 탐색을 프레임당 1회의 `cv2.distanceTransform` 호출로 처리 (자세한 내용은 [Astra Pro depth 파이프라인](#astra-pro-3d-depth) 참고)

## 화면 구성

앱은 `index.html`의 `.screen` 7개를 `showScreen(index)`로 전환하는 SPA 구조입니다.

| index | 화면 |
|---|---|
| 0 | 초기 설정 |
| 1 | 카메라 로딩 |
| 2 | 메인 화면 |
| 3 | QR 개인정보 동의 |
| 4 | 30초 측정 (인스타그램 릴스 오버레이) |
| 5 | 리포트 생성 |
| 6 | 최종 리포트 (인쇄) |

## 측정 대기 화면 상태 (사람 인식 vs 착석)

기존에는 "필요한 33개 landmark 중 일부라도 안 보이면 전부 `인식되지 않음`" 하나의
상태로 뭉뚱그렸습니다. 지금은 두 단계로 나뉩니다 (`main.py`의 `_analyze_pose`,
`_analyze_pose_3d`).

1. **사람이 인식되지 않음** (`is_normal = 2`): 얼굴/어깨(`UPPER_BODY_REQUIRED_LANDMARKS`,
   코·양쪽 귀·양쪽 어깨)의 visibility가 기준(0.5) 미만이면 이 상태입니다.
   status-box에 "사람이 인식되지 않습니다"가 표시됩니다.
2. **자리에 착석해 주세요** (`is_normal = 3`): 얼굴/어깨는 보이지만 하반신
   (`SEATED_REQUIRED_LANDMARKS`, 양쪽 골반·무릎·발목)의 visibility가 기준 미만이면
   이 상태입니다. status-box에 "자리에 착석해 주세요"가 표시됩니다.

두 상태 모두 정면(`_no_person_result()`) 혹은 착석(`_not_seated_result()`) 헬퍼가
0점/threshold 소스로 채워진 동일한 반환 형식을 만들어주므로, 기존 채점 파이프라인의
반환값 형태는 그대로 유지됩니다.

사람이 인식되고(`is_normal = 0` 또는 `1`) 착석까지 확인되면 프런트(`script.js`의
`updateFrame`)가 status-box를 `hidden` 클래스로 즉시 숨기고, 기존의 3-2-1
프리카운트다운(`startPreCountdown`)이 끝나는 시점에 같은 창 위에 겹쳐지는 인스타그램
릴스 오버레이 창(`#reels-overlay` 자리에 겹치는 별도 pywebview 창)을 보여주고 음소거를
해제합니다. 측정 도중 사람이 일어서거나 화면을 벗어나면 오버레이 창을 음소거하고 잠깐
숨기며(재생 위치는 유지) status-box를 다시 표시하고 타이머를 일시정지합니다.

## 인스타그램 릴스 오버레이 & 로그인 유지

30초 측정 동안 사용자가 "바른 자세를 의식적으로 유지"하는 것을 막기 위해, 착석이
확인되고 3-2-1 카운트다운이 끝나면 인스타그램 릴스(`https://www.instagram.com/reels/`)를
보여줍니다.

> **왜 `<iframe>`이 아닌가**: 인스타그램은 `X-Frame-Options`/CSP `frame-ancestors`
> 헤더로 자사 페이지가 다른 페이지의 `<iframe>` 안에 삽입되는 것을 막습니다. 이 헤더는
> pywebview의 렌더링 엔진(Chromium/WebKit) 레벨에서 강제되므로 `sandbox` 속성이나 JS로는
> 우회할 수 없고, 실제로 iframe을 쓰면 빈 화면만 뜹니다. 다만 이 제약은 "iframe으로
> 삽입"할 때만 적용되고 페이지를 최상위 문서로 직접 열 때는 적용되지 않으므로, 릴스는
> `index.html` 안의 `#reels-overlay` div가 화면에서 차지하는 자리 위에 정확히 겹쳐지는
> 별도의 테두리 없는 pywebview 창(top-level window)으로 띄웁니다. `#reels-overlay`
> div 자체는 이제 빈 자리 표시자(placeholder)로만 쓰이며, 카메라 캡처/자세 분석
> (`updateFrame`)이 실행되는 메인 창의 문서와는 별개의 창입니다.

- `showReelsIframe()` / `hideReelsIframe(muteOnly)` (`script.js`): `#reels-overlay`의
  `getBoundingClientRect()`로 화면상 위치/크기를 계산해
  `pywebview.api.open_reels_overlay(x, y, width, height)` /
  `pywebview.api.hide_reels_overlay(muteOnly)`를 호출합니다(함수 이름은 하위 호환을
  위해 유지했습니다).
- `CameraApp.open_reels_overlay()` (`main.py`): 릴스 창이 없으면 새로 만들고, 있으면
  `resize()`/`move()`로 위치만 갱신합니다. 메인 창이 움직이거나 리사이즈되는 경우를
  대비해 매번 `self.window.x`/`self.window.y`를 기준으로 좌표를 다시 계산합니다.
  **참고(HiDPI)**: 좌표는 CSS px를 OS px로 그대로 사용하므로, 디스플레이 배율이 100%가
  아닌 환경(예: macOS Retina, Windows 배율 125%/150%)에서는 오버레이 위치가 약간
  어긋날 수 있습니다. 필요하면 `open_reels_overlay`에서 `window.devicePixelRatio`
  기반 보정을 추가하세요.
- 음소거 제어는 `iframe.muted` DOM 프로퍼티 대신, 별도 창의 페이지 안에서
  `video.muted`를 직접 조작하는 `evaluate_js()` 호출(`mute_reels_overlay`/
  `unmute_reels_overlay`)로 처리합니다. `evaluate_js`는 브라우저 자동화 API라서
  cross-origin 제약을 받지 않습니다.
- **사람이 인식되지 않거나 착석이 풀리면**(`is_normal` 2 또는 3): `hideReelsIframe(true)`를
  호출해 `hide_reels_overlay(True)`로 릴스 창을 **음소거하고 잠깐 숨기기만** 합니다
  (창은 유지, 재생 위치도 유지). 사람이 다시 앉으면 3-2-1 카운트다운 후
  `showReelsIframe()`이 음소거를 풀고 다시 보여줍니다.
- **측정 화면을 완전히 벗어나는 경우**(30초 종료, screen 4 이탈): `hideReelsIframe()`을
  인자 없이 호출해 `hide_reels_overlay(False)`로 릴스 창 자체를 닫습니다.
- 초기 설정 화면(index 0)의 "인스타그램 로그인" 버튼은 `CameraApp.open_instagram_login()`을
  호출해 별도의 pywebview 창으로 인스타그램 로그인 페이지를 엽니다.
- 로그인 유지: `run_app()`에서 `webview.start(private_mode=False, storage_path=...)`로
  실행합니다. `storage_path`는 프로젝트 폴더 아래 `.webview_data/`이며, 여기에 쿠키/세션이
  저장되므로 로그인 창과 릴스 오버레이 창이 같은 프로필을 공유해 프로그램을 껐다 켜도
  로그인 상태가 유지됩니다. 이 폴더는 개인 로그인 정보를 담고 있으므로 배포/버전관리 시
  반드시 제외해야 합니다.

### 알려진 제한사항

- 인스타그램이 봇/자동화로 의심되는 접속을 감지하면 로그인 상태여도 로그인 화면이나
  검증 화면을 다시 띄울 수 있습니다. 이 경우 "인스타그램 로그인" 버튼으로 다시 로그인
  창을 열어 확인해야 합니다.
- HiDPI 환경에서의 좌표 보정은 위에 설명한 대로 아직 자동화되어 있지 않습니다.

## 리포트: QR 대신 로컬 인쇄, DB 미전송

- 측정 결과(`finalReportData`, AI 피드백)는 더 이상 Supabase `main` 테이블에 PATCH되지
  않습니다. `screen-3`(개인정보 동의)에서 만든 `uuid` row는 그대로 남지만, 여기에는
  `result` 컬럼이 채워지지 않습니다.
- `frontend/result/`(모바일에서 QR로 결과를 보여주던 페이지)는 더 이상 사용하지 않으므로
  삭제했습니다.
- 최종 리포트 화면(index 6)에는 QR 코드 대신 "리포트 출력하기" 버튼이 있고,
  `window.print()`로 OS의 인쇄 대화상자를 엽니다. `style.css`의 `@page`/`@media print`
  규칙이 리포트를 A4 한 장에 맞도록 폰트 크기와 여백을 줄이고, `.no-print` 요소(뒤로가기
  버튼, 인쇄 버튼 자체)는 인쇄물에서 숨깁니다.

## 파일 구조

```text
Pose-Report/
├── main.py          # 앱 실행 + 데이터 수집/학습/진단 서브커맨드까지 전부 포함
├── index.html
├── script.js
├── style.css
├── models/
│   └── (학습 후 4개 .joblib + training_manifest.json 생성)
└── README.md
```

`collect_pose_data.py`, `train_pose_classifier.py`, `diagnose_feature_importance.py`,
`pose_features.py`는 모두 `main.py` 안으로 통합되었습니다. 각 스크립트가 하던 일은
아래 [서브커맨드](#서브커맨드-구조) 섹션의 `python main.py <command>` 형태로 그대로 실행할 수 있습니다.

`frontend/` 아래에는 QR 개인정보 동의 페이지(`frontend/index.html`)만 남아 있습니다.
결과를 보여주던 `frontend/result/`는 리포트를 더 이상 QR/DB로 배포하지 않으므로 삭제했습니다.

## 설치

```bash
pip install opencv-python mediapipe==0.10.9 pywebview numpy requests python-dotenv
pip install scikit-learn joblib pandas
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
해당 오프라인 파이프라인만 실행합니다. 각 서브커맨드는 기존 개별 스크립트와 동일한 옵션을
그대로 지원합니다.

```bash
python main.py                # 기본: pywebview 앱 실행
python main.py calibrate [카메라 인덱스]   # Astra Pro 스테레오 캘리브레이션
python main.py collect --output pose_dataset.csv --person-id person_001
python main.py train --data pose_dataset.csv --output-dir models
python main.py diagnose --model-dir models --top 10
```

## 실행

```bash
python main.py
```

## 데이터 수집: 기존 UI/라벨 방식 유지 (`python main.py collect`)

데이터 수집 UI는 숫자 키 1~5를 사용합니다.

```text
1 : normal
2 : turtle_neck
3 : slouch
4 : shoulder_tilt
5 : pelvis_tilt
space : 일시정지
q : 종료
```

사람 단위 누수를 막기 위해 수집 실행마다 `person_id`를 지정해야 하며,
`session_id`는 실행마다 자동 생성됩니다.

```bash
python main.py collect --output pose_dataset.csv --person-id person_001
```

`--person-id`를 생략하면 실행 중 터미널에서 입력받습니다.

```bash
python main.py collect --output pose_dataset.csv
```

CSV에는 `source_label`과 함께 다음 4개의 이진 target이 저장됩니다.

```text
neck_label
torso_label
shoulder_label
pelvis_label
```

예를 들어 `turtle_neck`으로 수집한 행은 `neck_label=1`, 나머지는 0입니다.
`normal`은 네 target이 모두 0입니다. 따라서 하나의 공통 CSV를 유지하면서도
학습 시에는 네 개의 독립 binary dataset으로 해석할 수 있습니다.

`session_id`, `person_id`, `frame_id`도 함께 저장됩니다. 같은 사람의 여러 세션은
같은 `person_id`를 사용하고, 실행마다 새로운 `session_id`가 생깁니다.

## 부위별 feature 설계

각 classifier는 전체 33개 landmark를 입력하지 않습니다.

| 분류기 | 입력 landmark |
|---|---|
| neck | nose, left/right eye, left/right ear, left/right shoulder |
| torso | left/right shoulder, left/right hip |
| shoulder | left/right shoulder, left/right elbow |
| pelvis | left/right hip, left/right knee |

각 부위 feature는 해당 부위의 anchor와 scale을 사용해 독립적으로 정규화합니다
(`extract_part_feature_vector`). 실시간 추론과 학습 데이터 생성 모두 `main.py` 안의
동일한 함수를 공유하므로 두 경로 간 feature 계산 방식이 어긋날 일이 없습니다.

## 모델 학습 (`python main.py train`)

```bash
python main.py train --data pose_dataset.csv --output-dir models
```

학습 후에는 다음 파일이 생성됩니다.

```text
models/
├── neck_classifier.joblib
├── torso_classifier.joblib
├── shoulder_classifier.joblib
├── pelvis_classifier.joblib
└── training_manifest.json
```

### 학습 안전장치

단순 `train_test_split`을 사용하지 않고 `person_id`를 group으로 사용합니다.

1. 전체 데이터를 사람 단위로 train / validation / test로 분리
2. train 세트 내부에서 `GroupKFold`로 후보 모델 비교
3. RandomForest와 SVM(RBF)을 비교한 뒤 각 부위에서 더 좋은 모델 선택
4. validation / test 성능과 confusion matrix를 기록
5. `training_manifest.json`에 사용된 사람 그룹과 모델 성능을 저장

사람 수가 3명 미만이면 안전을 위해 학습을 중단합니다. 사람 구분 정보가 없는 구형 CSV는
강제로 학습하지 않고 `python main.py collect`로 새 형식으로 다시 수집하도록 안내합니다.

## 실시간 ML 점수 계산

각 부위 모델은 binary class를 사용합니다.

```text
0 = 정상
1 = 해당 부위 문제
```

모델의 확률과 binary prediction을 함께 사용해 다음 범위로 점수를 매핑합니다.

```text
정상 prediction  → 90~100점
문제 prediction  → 0~89점
```

즉 확률을 단순히 `normal_probability * 100`으로 쓰지 않고, 모델이 어느 클래스를
실제로 선택했는지와 0.5 기준선에서 얼마나 떨어져 있는지를 함께 반영합니다
(`CameraApp._binary_ml_quality`).

리포트의 4개 metric은 다음 값을 프레임별로 수집한 뒤 평균냅니다.

```text
neck_score
torso_score
shoulder_score
pelvis_score
```

각 metric에는 내부적으로 `ml` 또는 `threshold` source도 함께 기록합니다.
모델이 없는 부위는 다른 부위의 ML 사용 여부와 무관하게 그 부위만 threshold fallback이 됩니다.

## Threshold fallback

ML 모델이 없거나 로드/추론에 실패하면 해당 부위는 기존 각도 기반 threshold를 사용합니다
(`CameraApp._threshold_quality`). Fallback 점수도 0~100 공통 스케일로 계산하고, 정상 영역은
90~100, 문제 영역은 0~89로 표현되도록 맞춥니다.

따라서 실행 중 모델 상태가 다음과 같아도 정상 동작합니다.

```text
neck     → ML
torso    → ML
shoulder → threshold fallback
pelvis   → ML
```

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
다리 꼬기가 감지된 프레임에는 기존 휴리스틱 감점을 별도로 적용합니다.

## 다리 꼬기

다리 꼬기는 ML feature/label에 포함하지 않습니다. `main.py`의 선분 교차 기반
`_detect_leg_cross()` (`is_intersect()` 이용) 결과를 그대로 사용하며, ML 사용 여부와
관계없이 종합점수에 동일한 별도 감점을 적용합니다. 측정 결과에는 다리 꼬기 지속 시간도
함께 기록합니다.

## Feature importance 진단 (`python main.py diagnose`)

```bash
python main.py diagnose --model-dir models --top 10
```

RandomForest는 내장 `feature_importances_`를, 선형 계열 모델은 가능한 경우 `coef_` 기반
절대 영향도를 출력합니다. SVM(RBF)의 경우 직접적인 feature importance가 없으므로
추후 별도의 permutation importance 분석을 권장합니다.

## Astra Pro (3D Depth)

기존 Astra Pro 캡처/캘리브레이션 경로는 그대로 유지합니다. ML 추론 시 유효한 3D landmark가
충분하면 3D 좌표를 부위별 feature 생성에 사용하고, 부족하면 기존 2D landmark를 사용합니다.

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

## AI 피드백

측정 종료 후 종합 점수, 4개 ML/threshold metric, 다리 꼬기 지속 시간을 Gemini에 전달해
한국어 코칭 피드백을 생성합니다. metric은 angle threshold 값을 리포트의 주 값으로 사용하지
않고, 부위별 ML score를 중심으로 전달합니다.

## 알려진 제한사항

- 새 binary 학습 데이터는 기존 UI의 단일 자세 라벨로 수집됩니다. 즉 동일 프레임에서 여러
  문제를 동시에 직접 라벨링하는 UI는 없습니다. 내부 CSV 스키마는 네 binary target을
  동시에 표현할 수 있도록 되어 있습니다.
- 실제 모델의 예측 품질은 데이터 수와 사람/세션 다양성에 크게 좌우됩니다. 최소 3명보다 훨씬
  많은 사람을 여러 세션에서 수집하는 것을 권장합니다.
- Astra Pro 3D 데이터와 일반 웹캠 2D 데이터는 분포가 다르므로, 실제 사용 장치와 비슷한 방식으로
  학습 데이터를 수집하는 것이 좋습니다.
- 코드에는 주석을 두지 않는 것을 원칙으로 합니다. 동작을 바꾸는 수정을 할 때는 이 README의
  관련 섹션도 함께 갱신해 주세요.

### CSV feature 컬럼 호환성

`python main.py train`은 기존 수집 CSV의 `lm0_x`, `lm0_y`, `lm0_z` 형식을 그대로 사용합니다.
부위별 모델은 `main.py`의 `PART_LANDMARKS`에 지정된 landmark 컬럼만 선택합니다.
따라서 기존 `pose_dataset_binary_grouped.csv`처럼 원본 landmark 컬럼을 가진 CSV를 바로 학습에
사용할 수 있습니다.