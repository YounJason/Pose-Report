"""저장된 부위별 모델의 feature importance를 진단한다."""

import argparse
import os

import joblib
import numpy as np

from pose_features import PARTS


def _importance(model):
    estimator = model
    if hasattr(estimator, "named_steps"):
        estimator = estimator.named_steps.get("svc", estimator)
    if hasattr(estimator, "feature_importances_"):
        return estimator.feature_importances_
    if hasattr(estimator, "coef_"):
        return np.abs(estimator.coef_).mean(axis=0)
    return None


def main():
    parser = argparse.ArgumentParser(description="부위별 feature importance 진단")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    for part in PARTS:
        path = os.path.join(args.model_dir, f"{part}_classifier.joblib")
        if not os.path.exists(path):
            print(f"[{part}] 모델 없음: {path}")
            continue
        bundle = joblib.load(path)
        importance = _importance(bundle["model"])
        columns = bundle["feature_columns"]
        print(f"\n=== {part} | {bundle.get('model_name', '?')} ===")
        if importance is None:
            print("이 모델 계열은 직접적인 feature importance를 제공하지 않습니다."
                  " permutation importance를 별도 데이터셋으로 수행하는 것을 권장합니다.")
            continue
        order = np.argsort(importance)[::-1][:args.top]
        for idx in order:
            print(f"{columns[idx]:32s} {importance[idx]:.6f}")


if __name__ == "__main__":
    main()
