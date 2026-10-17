"""Leakage-aware supervised baseline for the OFFLINE pilot, not a production risk model."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from .pilot import FEATURES, _date


def train(dataset, output, *, train_through, test_from, label_known_by, exclude_ticker=None):
    # Imported here so audit/feature export can run without scikit-learn.
    import numpy as np
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, average_precision_score, confusion_matrix, precision_recall_fscore_support
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if train_through >= test_from:
        raise ValueError("Training years must end before the test years begin")
    gate = _date(label_known_by)
    with Path(dataset).open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    train_rows, test_rows, case_rows = [], [], []
    for r in rows:
        if r["label"] not in {"0", "1"} or not r["label_source"] or not r["outcome_known_at"]:
            continue
        year = int(r["fiscal_year"])
        if r["ticker"] == exclude_ticker:
            case_rows.append(r)
            continue
        if year <= train_through and _date(r["outcome_known_at"]) < gate:
            train_rows.append(r)
        elif year >= test_from:
            test_rows.append(r)
    if len(train_rows) < 20 or len(test_rows) < 10:
        raise ValueError(f"INSUFFICIENT_SAMPLE: train={len(train_rows)}, test={len(test_rows)}; no model is fitted")
    y_train = np.array([int(r["label"]) for r in train_rows])
    y_test = np.array([int(r["label"]) for r in test_rows])
    if len(set(y_train)) != 2 or len(set(y_test)) != 2:
        raise ValueError("BOTH_CLASSES_REQUIRED: train and test each need confirmed positive and negative cases")
    def matrix(records):
        return np.array([[float(r[f]) if r[f] not in {"", None} else np.nan for f in FEATURES] for r in records])
    X_train, X_test = matrix(train_rows), matrix(test_rows)
    valid = [i for i in range(len(FEATURES)) if np.isfinite(X_train[:, i]).any()]
    if not valid:
        raise ValueError("NO_VALID_TRAIN_FEATURES")
    kept = [FEATURES[i] for i in valid]
    X_train, X_test = X_train[:, valid], X_test[:, valid]
    model = Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=False)),
                      ("scale", StandardScaler()),
                      ("classifier", LogisticRegression(class_weight="balanced", max_iter=2000, random_state=42))])
    model.fit(X_train, y_train)
    prob = model.predict_proba(X_test)[:, 1]
    pred = (prob >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(y_test, pred, average="binary", zero_division=0)
    result = {"status": "evaluated", "analysis_mode": rows[0]["analysis_mode"] if rows else "",
              "warning": "Historical evaluation only; NEVER an audited as-of prediction without PIT validation",
              "train_samples": len(train_rows), "test_samples": len(test_rows), "case_rows_held_out": len(case_rows),
              "positive_train": int(y_train.sum()), "positive_test": int(y_test.sum()),
              "train_through": train_through, "test_from": test_from, "label_known_by": label_known_by,
              "features": kept, "threshold": 0.5, "accuracy": float(accuracy_score(y_test, pred)),
              "precision_positive": float(precision), "recall_positive": float(recall),
              "f1_positive": float(f1), "average_precision": float(average_precision_score(y_test, prob)),
              "confusion_matrix_0_1": confusion_matrix(y_test, pred, labels=[0, 1]).tolist()}
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "baseline_metrics.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (dest / "baseline_test_predictions.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ticker", "fiscal_year", "true_label", "score", "prediction"])
        for r, label, p, c in zip(test_rows, y_test, prob, pred):
            writer.writerow([r["ticker"], r["fiscal_year"], int(label), float(p), int(c)])
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Offline basic logistic-regression research benchmark")
    p.add_argument("--dataset", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--train-through", required=True, type=int)
    p.add_argument("--test-from", required=True, type=int)
    p.add_argument("--label-known-by", required=True, help="ISO timezone-aware time; enforce training label availability")
    p.add_argument("--exclude-ticker", default="1785", help="reserve case company from ALL model fitting/evaluation")
    a = p.parse_args(argv)
    result = train(a.dataset, a.output, train_through=a.train_through, test_from=a.test_from,
                   label_known_by=a.label_known_by, exclude_ticker=a.exclude_ticker)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()