"""Repeated unlabeled Beneish/Dechow financial anomaly benchmark (research only).

Only original 15 paper-variable columns are accepted, not the legacy 15 generic ratios.
Repetitions compare fitting stability; they are NOT online learning or validation
of fraud-detection accuracy. Never uses 1785, writes production DBs, or calls APIs.
"""
import argparse
import csv
import hashlib
import json
import math
import warnings
from collections import Counter
from pathlib import Path

from .literature_dataset import FEATURES

METHODS = ("iforest_200", "iforest_400", "lof_8", "mlp_reconstruction")


def read_data(path):
    import numpy as np
    with Path(path).open(encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        required = {"ticker", "fiscal_year", "analysis_mode", "training_label",
                    "accounting_framework", "statement_scope", *FEATURES}
        if missing := required - set(reader.fieldnames or []):
            raise ValueError(f"literature_features_missing:{sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError("empty_input")
    seen = set()
    for r in rows:
        ticker, year = r["ticker"].strip(), int(r["fiscal_year"])
        if ticker == "1785" or r["training_label"] != "UNREVIEWED":
            raise ValueError("reserved_case_or_labelled_row_forbidden")
        if r["analysis_mode"] != "retrospective" or year not in (2013, 2014, 2015):
            raise ValueError("current_study_only_supports_2013_2015_retrospective")
        if r["accounting_framework"] != "TIFRS" or r["statement_scope"] != "consolidated":
            raise ValueError("inconsistent_financial_statement_scope")
        if (ticker, year) in seen:
            raise ValueError("duplicate_company_year")
        seen.add((ticker, year))
        for name in FEATURES:
            if r[name]:
                try:
                    assert math.isfinite(float(r[name]))
                except (AssertionError, ValueError, OverflowError):
                    raise ValueError(f"invalid_feature:{ticker}:{year}:{name}") from None
    rows.sort(key=lambda r: (int(r["fiscal_year"]), r["ticker"]))
    arr = np.array([[float(r[name]) if r[name] else np.nan for name in FEATURES]
                    for r in rows], dtype=float)
    return rows, arr


def split_indices(rows, policy, seed):
    if policy == "temporal":
        partitions = [[i for i, r in enumerate(rows) if int(r["fiscal_year"]) == year]
                      for year in (2013, 2014, 2015)]
    elif policy == "company_disjoint":
        firms = sorted({r["ticker"] for r in rows},
                       key=lambda ticker: hashlib.sha256(f"firm:{seed}:{ticker}".encode()).hexdigest())
        n_train = round(0.65 * len(firms))
        n_val = round(0.15 * len(firms))
        buckets = [set(firms[:n_train]), set(firms[n_train:n_train+n_val]),
                   set(firms[n_train+n_val:])]
        partitions = [[i for i, r in enumerate(rows)
                       if r["ticker"] in group and int(r["fiscal_year"]) == year]
                      for group, year in zip(buckets, (2013, 2014, 2015))]
    else:
        raise ValueError("unknown_split")
    if min(map(len, partitions)) < 3 or len({rows[i]["ticker"] for i in partitions[0]}) < 5:
        raise ValueError("insufficient_independent_train_validation_test")
    return partitions


def usable_paper_features(xtrain):
    import numpy as np
    included, excluded = [], {}
    for i, name in enumerate(FEATURES):
        vals = xtrain[:, i][np.isfinite(xtrain[:, i])]
        if len(vals) < 5 or len(vals) / len(xtrain) < 0.35:
            excluded[name] = "insufficient_training_coverage"
        elif float(np.std(vals)) < 1e-10:
            excluded[name] = "constant_in_training"
        else:
            included.append(i)
    if len(included) < 3:
        raise ValueError("insufficient_usable_paper_features")
    return included, excluded


def make_model(kind, seed, n_train):
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.neural_network import MLPRegressor
    if kind == "iforest_200":
        return IsolationForest(n_estimators=200, random_state=seed, n_jobs=1)
    if kind == "iforest_400":
        return IsolationForest(n_estimators=400, max_features=0.8, random_state=seed, n_jobs=1)
    if kind == "lof_8":
        return LocalOutlierFactor(n_neighbors=min(8, n_train-1), novelty=True)
    if kind == "mlp_reconstruction":
        return MLPRegressor(hidden_layer_sizes=(12, 6, 12), alpha=0.08, activation="tanh",
                            max_iter=450, n_iter_no_change=50, tol=1e-4, random_state=seed)
    raise ValueError("unknown_model")


def score(kind, model, x):
    import numpy as np
    if kind == "mlp_reconstruction":
        return np.mean((model.predict(x)-x)**2, axis=1)
    return -model.score_samples(x)


def percentile(reference, observations):
    import numpy as np
    ref = np.sort(reference)
    return np.searchsorted(ref, observations, side="right") / len(ref)


def stability(scores):
    import numpy as np
    from scipy.stats import spearmanr
    corrs = [float(spearmanr(scores[i], scores[j]).statistic)
             for i in range(len(scores)) for j in range(i)]
    corrs = [value for value in corrs if math.isfinite(value)]
    return (round(float(np.mean(corrs)), 5), round(float(np.min(corrs)), 5)) if corrs else (None, None)


def run(dataset, output, *, rounds=10, seed=42, policy="temporal"):
    import joblib
    import numpy as np
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import RobustScaler
    if not 2 <= rounds <= 40:
        raise ValueError("rounds_not_in_2_to_40")
    rows, matrix = read_data(dataset)
    train, val, test = split_indices(rows, policy, seed)
    feature_ids, dropped = usable_paper_features(matrix[train])
    out = Path(output)
    (out / "models").mkdir(parents=True, exist_ok=True)
    comparisons, predictions, sensitivities, combined = [], [], [], []
    for kind in METHODS:
        validation_runs, test_runs, convergences = [], [], []
        for rep in range(rounds):
            current_seed = seed + rep
            rng = np.random.default_rng(current_seed)
            sub = rng.choice(len(train), max(5, math.ceil(0.9 * len(train))), replace=False)
            imp = SimpleImputer(strategy="median")
            scale = RobustScaler()
            fitted_x = scale.fit_transform(imp.fit_transform(matrix[np.array(train)[sub]][:, feature_ids]))
            vx = scale.transform(imp.transform(matrix[val][:, feature_ids]))
            tx = scale.transform(imp.transform(matrix[test][:, feature_ids]))
            estimator = make_model(kind, current_seed, len(fitted_x))
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ConvergenceWarning)
                if kind == "mlp_reconstruction":
                    estimator.fit(fitted_x, fitted_x)
                else:
                    estimator.fit(fitted_x)
            convergences.append(not any(issubclass(w.category, ConvergenceWarning) for w in caught))
            vs = score(kind, estimator, vx)
            ts = score(kind, estimator, tx)
            if not (np.isfinite(vs).all() and np.isfinite(ts).all()):
                raise ValueError("nonfinite_scores")
            validation_runs.append(vs)
            test_runs.append(ts)
            if rep == 0:
                joblib.dump({"model": estimator, "imputer": imp, "scaler": scale,
                             "feature_names": [FEATURES[i] for i in feature_ids],
                             "model_kind": kind, "policy": policy, "unlabeled_retrospective_only": True},
                            out / "models" / (kind + "_seed0.joblib"))
                # Perturb each genuine literature feature on validation only.
                for j, col in enumerate(feature_ids):
                    differences = []
                    for _ in range(4):
                        changed = vx.copy()
                        changed[:, j] = rng.permutation(changed[:, j])
                        differences.append(float(np.mean(np.abs(score(kind, estimator, changed) - vs))))
                    sensitivities.append({"model": kind, "feature": FEATURES[col],
                        "validation_permutation_abs_score_change": round(float(np.mean(differences)), 9),
                        "interpretation": "model_score_sensitivity_NOT_importance_for_actual_fraud"})
            ps = percentile(vs, ts)
            for i, x in zip(test, range(len(test))):
                predictions.append({"model": kind, "round": rep+1,
                    "ticker": rows[i]["ticker"], "fiscal_year": rows[i]["fiscal_year"],
                    "anomaly_score": round(float(ts[x]), 9),
                    "validation_anchored_percentile_NOT_probability": round(float(ps[x]), 6)})
        cor, minimum = stability(test_runs)
        comparisons.append({"model": kind, "rounds": rounds,
            "fit_rows": len(train), "val_rows": len(val), "test_rows": len(test),
            "selected_features": len(feature_ids),
            "optimizer_converged_rounds": sum(convergences),
            "test_rank_stability_mean_spearman": cor,
            "test_rank_stability_min_spearman": minimum,
            "mean_score_sd_over_rounds": round(float(np.mean(np.std(test_runs, axis=0))), 8)})
        combined.append(np.mean([percentile(a,b) for a,b in zip(validation_runs, test_runs)], axis=0))
    ensemble = np.mean(combined, axis=0)
    for i, value in zip(test, ensemble):
        predictions.append({"model": "equal_weight_validation_percentile_ensemble", "round": "aggregated",
            "ticker": rows[i]["ticker"], "fiscal_year": rows[i]["fiscal_year"],
            "anomaly_score": "", "validation_anchored_percentile_NOT_probability": round(float(value),6)})
    def export(name, records):
        with (out / name).open("w", encoding="utf-8", newline="") as fp:
            writer=csv.DictWriter(fp,fieldnames=list(records[0]))
            writer.writeheader();writer.writerows(records)
    export("model_round_comparison.csv", comparisons)
    export("holdout_model_scores.csv", predictions)
    export("literature_feature_sensitivity.csv", sensitivities)
    report = {"status": "UNLABELED_REPEATED_FIT_DIAGNOSTIC_NOT_PREDICTIVE_ACCURACY",
        "dataset_sha256": hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
        "paper_features": "Beneish_1999_8_and_Dechow_2011_Model1_7",
        "company_years": len(rows), "companies": len({r["ticker"] for r in rows}),
        "split": policy, "fit_rows":len(train), "validation_rows":len(val), "holdout_rows":len(test),
        "fit_companies":len({rows[i]["ticker"] for i in train}),
        "val_companies":len({rows[i]["ticker"] for i in val}),
        "holdout_companies":len({rows[i]["ticker"] for i in test}),
        "rounds_per_model":rounds, "independent_fits":len(METHODS)*rounds,
        "models":list(METHODS), "ensemble":"validation_anchor_percentile_mean",
        "used_paper_features":[FEATURES[i] for i in feature_ids],
        "excluded_paper_features":dropped,
        "missing_values_by_feature":{key:int(np.isnan(matrix[:,i]).sum()) for i,key in enumerate(FEATURES)},
        "valid_accuracy_or_f1":False, "selected_best_fraud_detector":None,
        "feature_importance_kind":"validation score permutation sensitivity, NOT outcome importance or causality",
        "input_is_unreviewed_and_retroactive":True,
        "reserved_1785_never_used":True, "holdout_never_used_for_tuning":True,
        "supervised_rf_xgboost_catboost":"wait_for_independent_outcome_labels",
        "transformer":"wait_for_longer_sequences_and_data",
        "gnn":"wait_for_verified_supplier_ownership_or_transaction_edges",
        "production_database_writes":0,"network_requests":0}
    (out/"experiment_report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description="Repeated 8+7 literature-feature anomaly model comparison; no fraud labels")
    parser.add_argument("--dataset",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--rounds",type=int,default=10)
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--split",choices=("temporal","company_disjoint"),default="temporal")
    opts=parser.parse_args(argv)
    print(json.dumps(run(opts.dataset,opts.output,rounds=opts.rounds,seed=opts.seed,policy=opts.split),
                     indent=2,ensure_ascii=False))


if __name__=="__main__":
    main()
