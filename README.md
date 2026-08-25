# Pose-Report

카메라 앞에서 30초간 자세를 측정해 거북목 · 등/허리 · 어깨 · 골반을 점수화하고,
다리 꼬기는 별도의 기하학적 휴리스틱으로 감지합니다. 측정 결과는 Gemini API로 코칭
피드백을 생성한 뒤 QR 코드로 연결된 모바일 리포트 페이지에서 확인할 수 있는
[pywebview](https://pywebview.flowrl.com/) 기반 데스크톱 앱입니다.

## 주요 기능

- **실시간 자세 분석**: MediaPipe Pose로 신체 랜드마크를 추출해 프레임마다 자세를 채점
- **부위별 독립 ML 분류기**: 목/머리, 등/허리, 어깨, 골반에 대해 각각 독립적인 binary classifier를 사용
- **구조적 shortcut learning 방지**: 각 분류기는 자기 부위에 해당하는 landmark subset만 입력으로 받음
- **부위별 안전 fallback**: 모델이 없거나 로드/추론에 실패한 부위만 angle threshold 방식으로 자동 전환
- **그룹 단위 학습 분리**: `person_id`를 기준으로 train / validation / test를 분리해 사람 단위 데이터 누수를 방지
- **RULA 참고 가중 종합점수**: 프로젝트용 heuristic weighting으로 목 25 / 몸통 30 / 어깨 30 / 골반 15를 기본값으로 사용
- **다리 꼬기 휴리스틱 유지**: ML 학습 대상이 아니며 기존 선분 교차 기반 판정을 종합점수에 별도 감점으로 반영
- **ML 기반 상세 리포트**: 리포트의 4개 progress bar와 값은 프레임별 ML/fallback 점수 평균을 사용
- **feature importance 진단**: 4개 부위 모델의 주요 feature를 모델별로 출력하는 진단 스크립트 제공
- **Astra Pro 지원**: 기존 RGB + Depth / 3D skeleton 경로를 유지하며, 부위별 ML feature에도 가능한 경우 3D 좌표를 사용

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
| 6 | 최종 리포트 |

## 파일 구조

```text
Pose-Report/
├── main.py
├── index.html
├── script.js
├── style.css
├── pose_features.py
├── collect_pose_data.py
├── train_pose_classifier.py
├── diagnose_feature_importance.py
├── models/
│   └── (학습 후 4개 .joblib + training_manifest.json 생성)
└── README.md
```

`frontend/` 아래 파일은 이 프로젝트의 이번 개편 대상에서 제외합니다.

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

## 실행

```bash
python main.py
```

## 데이터 수집: 기존 UI/라벨 방식 유지

데이터 수집 UI는 기존과 동일하게 숫자 키 1~5를 사용합니다.

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
python collect_pose_data.py --output pose_dataset.csv --person-id person_001
```

`--person-id`를 생략하면 실행 중 터미널에서 입력받습니다.

```bash
python collect_pose_data.py --output pose_dataset.csv
```

CSV에는 기존 `source_label`과 함께 다음 4개의 이진 target이 저장됩니다.

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

각 부위 feature는 해당 부위의 anchor와 scale을 사용해 독립적으로 정규화합니다.
학습/추론은 모두 `pose_features.py`의 동일한 함수로 처리합니다.

## 모델 학습

```bash
python train_pose_classifier.py --data pose_dataset.csv --output-dir models
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

사람 수가 3명 미만이면 안전을 위해 학습을 중단합니다. 기존에 사람 구분 정보가
없는 구형 CSV는 강제로 학습하지 않고 새 수집 방식으로 다시 수집하도록 안내합니다.

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
실제로 선택했는지와 0.5 기준선에서 얼마나 떨어져 있는지를 함께 반영합니다.

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

ML 모델이 없거나 로드/추론에 실패하면 해당 부위는 기존 각도 기반 threshold를 사용합니다.
Fallback 점수도 0~100 공통 스케일로 계산하고, 정상 영역은 90~100, 문제 영역은 0~89로
표현되도록 맞춥니다.

따라서 실행 중 모델 상태가 다음과 같아도 정상 동작합니다.

```text
neck     → ML
 torso   → ML
shoulder → threshold fallback
pelvis   → ML
```

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

다리 꼬기는 ML feature/label에 포함하지 않습니다.
`main.py`의 기존 선분 교차 기반 `_detect_leg_cross()` 결과를 그대로 사용하며,
ML 사용 여부와 관계없이 종합점수에 동일한 별도 감점을 적용합니다.
측정 결과에는 다리 꼬기 지속 시간도 함께 기록합니다.

## Feature importance 진단

```bash
python diagnose_feature_importance.py --model-dir models --top 10
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

## AI 피드백

측정 종료 후 종합 점수, 4개 ML/threshold metric, 다리 꼬기 지속 시간을 Gemini에 전달해
한국어 코칭 피드백을 생성합니다. metric은 더 이상 angle threshold 값을 리포트의 주 값으로
사용하지 않고, 부위별 ML score를 중심으로 전달합니다.

## 알려진 제한사항

- 새 binary 학습 데이터는 기존 UI의 단일 자세 라벨로 수집됩니다. 즉 동일 프레임에서 여러
  문제를 동시에 직접 라벨링하는 UI는 추가하지 않았습니다. 내부 CSV 스키마는 네 binary target을
  동시에 표현할 수 있도록 확장되어 있습니다.
- 실제 모델의 예측 품질은 데이터 수와 사람/세션 다양성에 크게 좌우됩니다. 최소 3명보다 훨씬 많은
  사람을 여러 세션에서 수집하는 것을 권장합니다.
- Astra Pro 3D 데이터와 일반 웹캠 2D 데이터는 분포가 다르므로, 실제 사용 장치와 비슷한 방식으로
  학습 데이터를 수집하는 것이 좋습니다.


### CSV feature 컬럼 호환성
`train_pose_classifier.py`는 기존 수집 CSV의 `lm0_x`, `lm0_y`, `lm0_z` 형식을 그대로 사용합니다.
부위별 모델은 `pose_features.py`의 `PART_LANDMARKS`에 지정된 landmark 컬럼만 선택합니다.
따라서 기존 `pose_dataset_binary_grouped.csv`처럼 원본 landmark 컬럼을 가진 CSV를 바로 학습에 사용할 수 있습니다.
