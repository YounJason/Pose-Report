"""
pose_classifier.py
-------------------
각도 기반 규칙 대신, 학습된 머신러닝 모델로 자세를 분류하는 래퍼(wrapper) 클래스.

- 알고리즘: RandomForestClassifier (scikit-learn)
  * 표본 수가 적어도 잘 동작하고, 과적합에 비교적 강하며, 특징 중요도(feature_importances_)를
    바로 확인할 수 있어서 "왜 이렇게 판단했는지" 피드백 문구를 만들 때도 활용하기 좋습니다.
  * main.py 쪽 코드를 거의 안 건드리고 다른 모델(SVM, XGBoost 등)로 바꾸고 싶다면
    이 클래스 내부의 `_build_model()`만 교체하면 됩니다.

- 라벨(label): collect_data.py 에서 사용자가 직접 태깅한 자세 클래스 문자열.
  기본 라벨 세트는 아래 LABEL_INFO 를 참고하세요. (직접 추가/수정 가능)

사용 흐름:
    1) collect_data.py 로 데이터 수집 -> data/posture_dataset.csv
    2) train_model.py 로 학습 -> model/posture_model.pkl 저장
    3) main.py 가 시작 시 model/posture_model.pkl 이 있으면 자동으로 ML 모드로 전환
"""

import os

import joblib
import numpy as np

from .pose_features import FEATURE_NAMES

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "model", "posture_model.pkl",
)

# 라벨별 메타 정보: 점수 차감 정도(0=정상)와 사용자에게 보여줄 한글 문구.
# collect_data.py 에서 사용하는 단축키(1~6)와 순서를 맞춰두었습니다.
# 필요에 따라 자유롭게 라벨을 추가/수정하세요 (예: 다중 라벨/복합 자세 등).
LABEL_INFO = {
    "normal":          {"score": 100, "text": "정상"},
    "turtle_neck":      {"score": 60,  "text": "거북목 위험"},
    "rounded_back":     {"score": 55,  "text": "등 굽음 위험"},
    "shoulder_asymm":   {"score": 65,  "text": "어깨 비대칭 위험"},
    "pelvis_asymm":     {"score": 65,  "text": "골반 비대칭 위험"},
    "leg_cross":        {"score": 70,  "text": "다리 꼬기"},
    "not_detected":     {"score": 0,   "text": "인식되지 않음"},
}


class PostureClassifier:
    """학습/저장/로드/추론을 담당하는 래퍼 클래스."""

    def __init__(self, model_path=None):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.model = None          # sklearn Pipeline (StandardScaler + RandomForest)
        self.classes_ = None       # 학습된 라벨 목록

    # ------------------------------------------------------------------
    # 모델 구조 정의
    # ------------------------------------------------------------------
    @staticmethod
    def _build_model():
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        return Pipeline([
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                n_estimators=200,
                max_depth=8,
                random_state=42,
                class_weight="balanced",
            )),
        ])

    # ------------------------------------------------------------------
    # 학습
    # ------------------------------------------------------------------
    def train(self, X, y, test_size=0.2, random_state=42):
        """
        X: shape (n_samples, len(FEATURE_NAMES))
        y: shape (n_samples,) - 문자열 라벨 리스트

        Returns: dict (평가 리포트)
        """
        from sklearn.metrics import classification_report
        from sklearn.model_selection import train_test_split

        X = np.asarray(X, dtype=float)
        y = np.asarray(y)

        stratify = y if len(set(y)) > 1 and min(np.unique(y, return_counts=True)[1]) >= 2 else None
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=stratify
        )

        self.model = self._build_model()
        self.model.fit(X_train, y_train)
        self.classes_ = list(self.model.named_steps["clf"].classes_)

        y_pred = self.model.predict(X_test)
        report = classification_report(y_test, y_pred, zero_division=0, output_dict=True)
        report_text = classification_report(y_test, y_pred, zero_division=0)
        return {"report_dict": report, "report_text": report_text, "n_train": len(X_train), "n_test": len(X_test)}

    # ------------------------------------------------------------------
    # 저장 / 로드
    # ------------------------------------------------------------------
    def save(self, path=None):
        path = path or self.model_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({
            "model": self.model,
            "classes_": self.classes_,
            "feature_names": FEATURE_NAMES,
        }, path)
        return path

    def load(self, path=None):
        path = path or self.model_path
        bundle = joblib.load(path)
        self.model = bundle["model"]
        self.classes_ = bundle["classes_"]
        saved_features = bundle.get("feature_names")
        if saved_features and saved_features != FEATURE_NAMES:
            raise ValueError(
                "저장된 모델의 특징(feature) 구성이 pose_features.py의 FEATURE_NAMES와 다릅니다. "
                "특징을 바꿨다면 데이터를 다시 모으고 재학습하세요."
            )
        return self

    def is_loaded(self):
        return self.model is not None

    @classmethod
    def load_if_exists(cls, path=None):
        """모델 파일이 있으면 로드해서 반환, 없으면 None."""
        path = path or DEFAULT_MODEL_PATH
        if not os.path.exists(path):
            return None
        clf = cls(model_path=path)
        clf.load(path)
        return clf

    # ------------------------------------------------------------------
    # 추론
    # ------------------------------------------------------------------
    def predict(self, feature_vector):
        """
        feature_vector: list/np.array, FEATURE_NAMES 순서

        Returns: (label:str, confidence:float, proba_dict:dict)
        """
        if self.model is None:
            raise RuntimeError("모델이 로드되지 않았습니다. load() 또는 train()을 먼저 호출하세요.")

        X = np.asarray([feature_vector], dtype=float)
        proba = self.model.predict_proba(X)[0]
        classes = self.model.named_steps["clf"].classes_
        proba_dict = {cls: float(p) for cls, p in zip(classes, proba)}
        best_idx = int(np.argmax(proba))
        label = classes[best_idx]
        confidence = float(proba[best_idx])
        return label, confidence, proba_dict
