"""Retrospective exploratory anomaly score diagnostic on UNREVIEWED financial data.

WARNING: This is NOT the normal-only research model or a fraud detection validation.
Does NOT create normal labels, cutoffs, predictions, flags, accuracy or F1.
Never use it to assert ex-ante fraud detection. Reserved 1785 is disallowed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from itertools import combinations
from pathlib import Path

# Non-duplicative, contemporaneous ratios. Gross margin + COGS ratio = 1,
# so including both implicitly doubles the same information.
FEATURES = (
    "gross_margin", "operating_margin", "net_margin",
    "inventory_to_assets", "receivables_sales_ratio",
    "debt_asset_ratio", "cashflow_assets_ratio",
)
SPLIT = {2013: "fit_2013", 2014: "diagnostic_2014", 2015: "untouched_2015"}
CSV_FIELDS = ["ticker", "fiscal_year", "split", "score_mean", "score_std", "rank_mean", "rank_std", "n_seeds"]


def _load_rows(csv_path: str | Path):
    path = Path(csv_path)
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = set(FEATURES) | {
            "ticker", "fiscal_year", "analysis_mode", "filing_version_type",
            "label", "label_source", "outcome_known_at",
        }
        if missing := required - set(reader.fieldnames or []):
            raise ValueError(f"Missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError("No rows to explore")
    seen: set[tuple[str, int]] = set()
    data = []
    for r in rows:
        ticker = r["ticker"].strip()
        try:
            year = int(r["fiscal_year"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid fiscal_year") from exc
        if ticker == "1785":
            raise ValueError("Reserved case 1785 cannot enter the exploratory reference cohort")
        if year not in SPLIT:
            raise ValueError(f"Only 2013-2015 temporal diagnostic is supported: {year}")
        if r["analysis_mode"] != "retrospective":
            raise ValueError("Only retrospective exploratory mode supported")
        if r["label"] or r["label_source"] or r["outcome_known_at"]:
            raise ValueError("Do not train this UNREVIEWED diagnostic on labeled records")
        key = (ticker, year)
        if key in seen:
            raise ValueError(f"Duplicate company year: {key}")
        seen.add(key)
        values = []
        for feat in FEATURES:
            try:
                v = float(r[feat])
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Missing/non-numeric feature {ticker}/{year}/{feat}") from exc
            if not math.isfinite(v):
                raise ValueError(f"Nonfinite feature {ticker}/{year}/{feat}")
            values.append(v)
        data.append((ticker, year, values, r["filing_version_type"]))
    data.sort(key=lambda z: (z[1], z[0]))
    for year in SPLIT:
        if not any(row[1] == year for row in data):
            raise ValueError(f"Missing required year: {year}")
    return data, hashlib.sha256(path.read_bytes()).hexdigest()


def _rank(x):
    """1 is largest anomaly score; deterministic ties by row position."""
    import numpy as np
    order = np.argsort(-x, kind="stable")
    ranks = np.empty(len(x), dtype=float)
    ranks[order] = np.arange(1, len(x) + 1)
    return ranks


def run(dataset, output, *, seeds=12, n_estimators=300):
    import numpy as np
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import RobustScaler

    if not 2 <= seeds <= 50 or not 50 <= n_estimators <= 1000:
        raise ValueError("Seeds 2..50 and n_estimators 50..1000 required")
    records, sha = _load_rows(dataset)
    partitions = {year: [r for r in records if r[1] == year] for year in SPLIT}
    if len(partitions[2013]) < 5 or len(partitions[2014]) < 3 or len(partitions[2015]) < 3:
        raise ValueError("Insufficient company-years even for this exploratory smoke test")
    X_train = np.array([r[2] for r in partitions[2013]], dtype=float)
    scale = RobustScaler()
    # All training-time transformation is fitted only with 2013 observations.
    X = {year: scale.fit_transform(X_train) if year == 2013 else None for year in SPLIT}
    for year in (2014, 2015):
        X[year] = scale.transform(np.array([r[2] for r in partitions[year]], dtype=float))
    scores = {year: [] for year in SPLIT}
    ranks = {year: [] for year in SPLIT}
    for seed in range(seeds):
        model = IsolationForest(
            n_estimators=n_estimators,
            max_samples="auto", contamination="auto", random_state=4000 + seed,
            n_jobs=1,
        )
        model.fit(X[2013])
        for year in SPLIT:
            sc = -model.score_samples(X[year])
            scores[year].append(sc)
            ranks[year].append(_rank(sc))
    def prepared(year):
        s = np.array(scores[year]); rk = np.array(ranks[year]); result = []
        for i, item in enumerate(partitions[year]):
            result.append({
                "ticker": item[0], "fiscal_year": item[1], "split": SPLIT[year],
                "score_mean": round(float(s[:, i].mean()), 9),
                "score_std": round(float(s[:, i].std(ddof=0)), 9),
                "rank_mean": round(float(rk[:, i].mean()), 5),
                "rank_std": round(float(rk[:, i].std(ddof=0)), 5),
                "n_seeds": seeds,
            })
        result.sort(key=lambda r: (r["rank_mean"], r["ticker"]))
        return result
    result = {year: prepared(year) for year in SPLIT}
    stabilities = {}
    for year in SPLIT:
        rr = np.array(ranks[year])
        coeffs = []
        for i, j in combinations(range(seeds), 2):
            coeff = np.corrcoef(rr[i], rr[j])[0, 1]
            if np.isfinite(coeff):
                coeffs.append(float(coeff))
        stabilities[str(year)] = {
            "mean_pairwise_spearman_seed_correlation": round(float(np.mean(coeffs)), 6),
            "min_pairwise_spearman_seed_correlation": round(float(np.min(coeffs)), 6),
        }
    report = {
        "status": "EXPLORATORY_FIT_ONLY_NOT_EVALUATION",
        "model": "IsolationForest", "dataset_sha256": sha,
        "observation_grain": "company_x_fiscal_year",
        "feature_names": list(FEATURES),
        "skipped_redundant_feature": "cogs_sales_ratio",
        "year_counts": {str(year): len(partitions[year]) for year in SPLIT},
        "unique_companies": len(set(x[0] for x in records)),
        "split": SPLIT, "fit_year": 2013,
        "preprocessing_fitted_on_fit_year_only": True,
        "same_issuers_can_appear_across_years": True,
        "company_disjoint_validation": False,
        "training_cohort_evidence_status": "UNREVIEWED_PROVISIONAL",
        "historical_original_and_asof": "UNVERIFIED",
        "reserved_case_used": False,
        "normal_labels_created": 0,
        "threshold": None, "flagged_companies": None,
        "accuracy": None, "f1": None, "recall": None, "precision": None,
        "seed_count": seeds, "n_estimators": n_estimators,
        "rank_stability": stabilities,
        "interpretation": "Technical ranking smoke test only. Do not interpret as fraud risk or detection; no admissible reference normals, historical PIT evidence, or labeled outcomes.",
    }
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    for year, fname in ((2014, "exploratory_2014_validation_scores.csv"), (2015, "exploratory_2015_holdout_scores.csv")):
        with (out / fname).open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(result[year])
    (out / "exploratory_diagnostic_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Exploratory 2013→2014→2015 Isolation Forest smoke test; no normal or fraud claims")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--n-estimators", type=int, default=300)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.dataset, args.output, seeds=args.seeds, n_estimators=args.n_estimators), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()