"""부위별 독립 이진분류기 학습.

출력 구조:
    models/neck_classifier.joblib
    models/torso_classifier.joblib
    models/shoulder_classifier.joblib
    models/pelvis_classifier.joblib

데이터 누수를 막기 위해 person_id를 그룹으로 사용해 train/validation/test를 분리하고,
가능한 경우 GroupKFold 교차검증으로 모델 후보를 비교한다.
"""

import argparse
import json
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, roc_auc_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from pose_features import BINARY_TARGETS, FEATURE_COLUMNS_BY_PART, PARTS

RANDOM_STATE = 42


def _split_by_group(df, test_size=0.2, val_size=0.2):
    """사람 단위 split을 반복 시도해 train에 모든 binary target의 두 class가 들어오게 한다."""
    groups = df["person_id"].astype(str).values
    unique_groups = np.unique(groups)
    if len(unique_groups) < 3:
        raise ValueError("person_id가 최소 3명 이상 필요합니다. 사람 단위 train/validation/test 분리를 보장할 수 없습니다.")

    rel_val = val_size / (1.0 - test_size)
    best = None
    for attempt in range(100):
        gss_test = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=RANDOM_STATE + attempt)
        train_val_idx, test_idx = next(gss_test.split(df, groups=groups))
        train_val = df.iloc[train_val_idx].copy()
        test = df.iloc[test_idx].copy()
        gss_val = GroupShuffleSplit(n_splits=1, test_size=rel_val, random_state=RANDOM_STATE + 1000 + attempt)
        tv_groups = train_val["person_id"].astype(str).values
        train_idx, val_idx = next(gss_val.split(train_val, groups=tv_groups))
        train = train_val.iloc[train_idx].copy()
        val = train_val.iloc[val_idx].copy()
        coverage = 0
        for target in BINARY_TARGETS.values():
            if set(train[target].astype(int).unique()) == {0, 1}:
                coverage += 1
        candidate = (coverage, train, val, test)
        if best is None or coverage > best[0]:
            best = candidate
        if coverage == len(BINARY_TARGETS):
            return train, val, test

    assert best is not None
    print(f"[경고] 100회 grouped split 시도 후에도 모든 target의 train class coverage를 확보하지 못했습니다. "
          f"coverage={best[0]}/{len(BINARY_TARGETS)}")
    return best[1], best[2], best[3]


def _candidate_models():
    return {
        "random_forest": RandomForestClassifier(
            n_estimators=350, min_samples_leaf=2, random_state=RANDOM_STATE, n_jobs=-1
        ),
        "svm_rbf": Pipeline([
            ("scaler", StandardScaler()),
            ("svc", SVC(kernel="rbf", C=10.0, gamma="scale", probability=True, random_state=RANDOM_STATE)),
        ]),
    }


def _group_cv_score(model, X, y, groups, requested_folds):
    n_groups = len(np.unique(groups))
    folds = min(requested_folds, n_groups)
    if folds < 2:
        raise ValueError("GroupKFold를 수행하기 위한 그룹 수가 부족합니다.")
    cv = GroupKFold(n_splits=folds)
    scores = cross_val_score(model, X, y, cv=cv, groups=groups, scoring="accuracy", n_jobs=-1)
    return folds, float(scores.mean()), float(scores.std())


def _validate_binary(y, part):
    counts = pd.Series(y).value_counts().to_dict()
    if set(counts) != {0, 1}:
        raise ValueError(f"{part}: 0/1 두 클래스가 모두 필요합니다. 현재 분포: {counts}")


def main():
    parser = argparse.ArgumentParser(description="부위별 자세 이진분류기 학습")
    parser.add_argument("--data", default="pose_dataset.csv")
    parser.add_argument("--output-dir", default="models")
    parser.add_argument("--cv", type=int, default=5)
    args = parser.parse_args()

    df = pd.read_csv(args.data)
    required_base = ["person_id", "session_id"]
    missing_base = [c for c in required_base if c not in df.columns]
    if missing_base:
        sys.exit("CSV에 그룹 분할용 컬럼이 없습니다: " + ", ".join(missing_base) + ". collect_pose_data.py를 새 버전으로 다시 실행하세요.")

    if df["person_id"].nunique() < 3:
        sys.exit("person_id가 3명 미만입니다. 사람 단위 train/validation/test 분리를 위해 최소 3명이 필요합니다.")

    train_df, val_df, test_df = _split_by_group(df)
    print(f"전체={len(df)}, train={len(train_df)}, validation={len(val_df)}, test={len(test_df)}")
    print(f"그룹 수: train={train_df.person_id.nunique()}, val={val_df.person_id.nunique()}, test={test_df.person_id.nunique()}")

    os.makedirs(args.output_dir, exist_ok=True)
    manifest = {"random_state": RANDOM_STATE, "parts": {}, "split": {
        "train_people": sorted(train_df.person_id.astype(str).unique().tolist()),
        "validation_people": sorted(val_df.person_id.astype(str).unique().tolist()),
        "test_people": sorted(test_df.person_id.astype(str).unique().tolist()),
    }}

    for part in PARTS:
        feature_cols = FEATURE_COLUMNS_BY_PART[part]
        target = BINARY_TARGETS[part]
        missing = [c for c in feature_cols + [target] if c not in df.columns]
        if missing:
            sys.exit(f"{part}: CSV에 필요한 컬럼이 없습니다: {missing[:8]}")

        train = train_df.dropna(subset=feature_cols + [target]).copy()
        val = val_df.dropna(subset=feature_cols + [target]).copy()
        test = test_df.dropna(subset=feature_cols + [target]).copy()
        _validate_binary(train[target].astype(int).values, part)
        if set(val[target].astype(int).unique()) != {0, 1}:
            print(f"[경고] {part}: validation 세트에 두 클래스가 모두 존재하지 않습니다: {val[target].value_counts().to_dict()}")
        if set(test[target].astype(int).unique()) != {0, 1}:
            print(f"[경고] {part}: test 세트에 두 클래스가 모두 존재하지 않습니다: {test[target].value_counts().to_dict()}")

        X_train = train[feature_cols].values
        y_train = train[target].astype(int).values
        groups = train["person_id"].astype(str).values

        print(f"\n=== {part} ({target}) ===")
        print("train label:", train[target].value_counts().to_dict())
        candidates = _candidate_models()
        best_name, best_model, best_score = None, None, -1.0
        for name, model in candidates.items():
            folds, mean, std = _group_cv_score(model, X_train, y_train, groups, args.cv)
            print(f"[{name}] GroupKFold({folds}) accuracy={mean:.4f} (+/- {std:.4f})")
            if mean > best_score:
                best_name, best_model, best_score = name, model, mean

        best_model.fit(X_train, y_train)

        metrics = {}
        for split_name, split_df in (("validation", val), ("test", test)):
            if split_df.empty:
                continue
            X = split_df[feature_cols].values
            y = split_df[target].astype(int).values
            pred = best_model.predict(X)
            metrics[split_name] = {
                "accuracy": float(accuracy_score(y, pred)),
                "classification_report": classification_report(y, pred, output_dict=True, zero_division=0),
                "confusion_matrix": confusion_matrix(y, pred, labels=[0, 1]).tolist(),
            }
            if len(np.unique(y)) == 2 and hasattr(best_model, "predict_proba"):
                try:
                    metrics[split_name]["roc_auc"] = float(roc_auc_score(y, best_model.predict_proba(X)[:, 1]))
                except Exception:
                    pass
            print(f"{split_name} accuracy={metrics[split_name]['accuracy']:.4f}")

        bundle = {
            "model": best_model,
            "model_name": best_name,
            "classes": [0, 1],
            "feature_columns": feature_cols,
            "part": part,
            "target": target,
            "normal_class": 0,
            "problem_class": 1,
            "cv_accuracy": best_score,
            "metrics": metrics,
        }
        out_path = os.path.join(args.output_dir, f"{part}_classifier.joblib")
        joblib.dump(bundle, out_path)
        manifest["parts"][part] = {"model": os.path.basename(out_path), "model_name": best_name, "cv_accuracy": best_score, "metrics": metrics}
        print(f"저장: {out_path}")

    with open(os.path.join(args.output_dir, "training_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("\n모든 부위 모델 학습 및 저장 완료.")


if __name__ == "__main__":
    main()
