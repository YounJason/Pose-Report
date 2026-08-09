# -*- coding: utf-8 -*-
"""
train_model.py
---------------
data/posture_dataset.csv (collect_data.py 로 모은 데이터) 를 읽어
RandomForest 분류 모델을 학습하고 model/posture_model.pkl 로 저장합니다.

실행:
    python train_model.py

옵션:
    python train_model.py --csv data/posture_dataset.csv --out model/posture_model.pkl --test-size 0.2
"""

import argparse
import os

import pandas as pd

from ml.pose_classifier import DEFAULT_MODEL_PATH, PostureClassifier
from ml.pose_features import FEATURE_NAMES

DEFAULT_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "posture_dataset.csv")


def main():
    parser = argparse.ArgumentParser(description="자세 분류 ML 모델 학습")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="학습 데이터 CSV 경로")
    parser.add_argument("--out", default=DEFAULT_MODEL_PATH, help="학습된 모델 저장 경로")
    parser.add_argument("--test-size", type=float, default=0.2, help="테스트셋 비율 (0~1)")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"데이터 파일을 찾을 수 없습니다: {args.csv}")
        print("먼저 `python collect_data.py` 로 데이터를 수집하세요.")
        return

    df = pd.read_csv(args.csv)

    missing = [c for c in FEATURE_NAMES if c not in df.columns]
    if missing:
        print(f"CSV에 필요한 컬럼이 없습니다: {missing}")
        return
    if "label" not in df.columns:
        print("CSV에 'label' 컬럼이 없습니다.")
        return

    df = df.dropna(subset=FEATURE_NAMES + ["label"])

    label_counts = df["label"].value_counts()
    print("클래스별 샘플 수:")
    print(label_counts)
    print()

    too_few = label_counts[label_counts < 5]
    if len(too_few) > 0:
        print(f"⚠️  샘플이 5개 미만인 클래스가 있습니다 (학습 품질 저하 가능): {list(too_few.index)}")
        print("   더 많은 데이터를 모으는 걸 권장합니다.\n")

    if df["label"].nunique() < 2:
        print("클래스가 1개뿐입니다. 최소 2개 이상의 라벨(예: normal / turtle_neck)로 데이터를 모아주세요.")
        return

    X = df[FEATURE_NAMES].values
    y = df["label"].values

    clf = PostureClassifier(model_path=args.out)
    result = clf.train(X, y, test_size=args.test_size)

    print(f"학습 샘플: {result['n_train']}개, 테스트 샘플: {result['n_test']}개\n")
    print("=== 평가 리포트 (테스트셋) ===")
    print(result["report_text"])

    saved_path = clf.save(args.out)
    print(f"\n✅ 모델 저장 완료: {saved_path}")
    print("이제 main.py를 실행하면 자동으로 이 모델을 사용해 ML 기반으로 자세를 분석합니다.")


if __name__ == "__main__":
    main()
