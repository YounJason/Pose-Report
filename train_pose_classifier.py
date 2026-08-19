"""
collect_pose_data.py로 모은 CSV로 자세 분류 모델을 학습해 pose_model.pkl로
저장한다.

사용법:
    python train_pose_classifier.py --data pose_dataset.csv --output pose_model.pkl

RandomForest와 SVM(RBF 커널) 두 후보를 각각 K-fold 교차검증으로 비교한 뒤,
더 성능이 좋은 쪽을 최종 모델로 학습/저장한다.

main.py는 실행될 때 pose_model.pkl 파일이 존재하면 이를 자동으로 불러와,
기존의 각도 임계값(Threshold) 기반 채점 대신 이 모델의 예측 결과로 자세
상태와 척추 건강 점수를 계산한다. (파일이 없거나 로드에 실패하면 기존
방식으로 자동 대체(fallback)되므로 언제든 안전하게 재학습/교체할 수 있다.)
"""
import argparse
import sys

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from pose_features import FEATURE_COLUMNS


def main():
    parser = argparse.ArgumentParser(description="자세 분류 모델 학습")
    parser.add_argument("--data", default="pose_dataset.csv", help="collect_pose_data.py로 만든 CSV")
    parser.add_argument("--output", default="pose_model.pkl", help="저장할 모델 경로")
    parser.add_argument("--cv", type=int, default=5, help="교차검증 fold 수")
    args = parser.parse_args()

    df = pd.read_csv(args.data)
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        sys.exit(f"CSV에 필요한 컬럼이 없습니다 (예: {missing[:5]} ...). "
                  f"collect_pose_data.py로 만든 CSV인지 확인하세요.")

    X = df[FEATURE_COLUMNS].values
    y = df["label"].values

    print(f"총 {len(df)}개 샘플")
    print(df["label"].value_counts(), "\n")

    min_class_count = df["label"].value_counts().min()
    cv_folds = max(2, min(args.cv, int(min_class_count)))
    if cv_folds < args.cv:
        print(f"[안내] 가장 적은 클래스 샘플 수({min_class_count})에 맞춰 "
              f"교차검증 fold를 {args.cv} -> {cv_folds}로 줄였습니다.\n")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    candidates = {
        "random_forest": RandomForestClassifier(
            n_estimators=300, max_depth=None, min_samples_leaf=2,
            random_state=42, n_jobs=-1
        ),
        "svm_rbf": Pipeline([
            ("scaler", StandardScaler()),
            ("svc", SVC(kernel="rbf", C=10.0, gamma="scale", probability=True, random_state=42)),
        ]),
    }

    best_name, best_model, best_cv_acc = None, None, -1.0
    for name, model in candidates.items():
        scores = cross_val_score(model, X_train, y_train, cv=cv_folds, n_jobs=-1)
        print(f"[{name}] {cv_folds}-fold CV 정확도: {scores.mean():.4f} (+/- {scores.std():.4f})")
        if scores.mean() > best_cv_acc:
            best_name, best_model, best_cv_acc = name, model, scores.mean()

    print(f"\n선택된 모델: {best_name} (CV 정확도 {best_cv_acc:.4f})")
    best_model.fit(X_train, y_train)

    y_pred = best_model.predict(X_test)
    labels_sorted = sorted(set(y))
    print("\n=== 홀드아웃 테스트 세트 성능 ===")
    print(classification_report(y_test, y_pred))
    print("혼동 행렬(라벨 순서:", labels_sorted, ")")
    print(confusion_matrix(y_test, y_pred, labels=labels_sorted))

    classes = list(best_model.classes_) if hasattr(best_model, "classes_") else labels_sorted
    joblib.dump({
        "model": best_model,
        "model_name": best_name,
        "classes": classes,
        "feature_columns": FEATURE_COLUMNS,
    }, args.output)
    print(f"\n모델 저장 완료: {args.output}")
    print("main.py를 다시 실행하면 이 모델이 자동으로 로드되어 사용됩니다.")


if __name__ == "__main__":
    main()
