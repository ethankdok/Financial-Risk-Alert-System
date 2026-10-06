"""Controlled robustness check; never overwrite production/JSD baselines.

Ablate vendor/platform markup and repeated long lines separately and together,
then re-estimate the *same-variant* historical thresholds from prior pairs.
This is exploratory only; not a new validated anti-fraud score.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_shift import calculate_cosine_similarity, calculate_jsd
from calibrate_tsmc_shift import load, quarter_number, quality

VENDOR = re.compile(r"\b(?:refinitiv|lseg|thomson[\s-]*reuters)\b", re.I)


def clean_text(text: str, *, remove_vendor: bool = False, remove_repeated: bool = False) -> str:
    """Transparent, deliberately conservative *diagnostic* text transformation."""
    lines = text.splitlines()
    if remove_repeated:
        normalized = [re.sub(r"\s+", " ", line).strip().lower() for line in lines]
        counts = Counter(line for line in normalized if len(line) >= 25)
        lines = [line for line, key in zip(lines, normalized)
                 if counts.get(key, 0) < 3 or len(key) < 25]
    out = "\n".join(lines)
    if remove_vendor:
        out = VENDOR.sub(" ", out)
    return out


def metric(a: str, b: str) -> dict | None:
    passed, q = quality(a, b)
    if not passed:
        return None
    return {
        "jsd": float(calculate_jsd(a, b)),
        "cosine": float(calculate_cosine_similarity(a, b)),
        "length_ratio": q["length_ratio"],
    }


def compare_versions(rows: list[dict], q1="2025Q3", q2="2025Q4", min_history=30) -> dict:
    by = {r["period"]: r["text"] for r in rows}
    periods = sorted(by, key=quarter_number)
    variants = {
        "original": (False, False),
        "vendor_only": (True, False),
        "repeated_lines_only": (False, True),
        "vendor_plus_repeated_lines": (True, True),
    }
    result = {}
    for name, (vendor, repeated) in variants.items():
        cleaned = {
            key: clean_text(value, remove_vendor=vendor, remove_repeated=repeated)
            for key, value in by.items()
        }
        target = metric(cleaned[q1], cleaned[q2])
        historical = []
        for a, b in zip(periods, periods[1:]):
            if quarter_number(b) != quarter_number(a) + 1:
                continue
            if quarter_number(b) >= quarter_number(q1):
                continue
            m = metric(cleaned[a], cleaned[b])
            if m:
                historical.append(m)
        thresholds = None
        decision = "insufficient_history_or_quality"
        if len(historical) >= min_history:
            jsd = np.array([x["jsd"] for x in historical])
            cos = np.array([x["cosine"] for x in historical])
            if len(set(np.round(jsd, 6))) >= 3 and len(set(np.round(cos, 6))) >= 3:
                thresholds = {
                    "jsd_p90": round(float(np.quantile(jsd, 0.90)), 6),
                    "cosine_p10": round(float(np.quantile(cos, 0.10)), 6),
                    "cosine_p05": round(float(np.quantile(cos, 0.05)), 6),
                }
                if target is not None:
                    high = target["jsd"] >= thresholds["jsd_p90"] and target["jsd"] > 0
                    low = target["cosine"] <= thresholds["cosine_p10"] and target["cosine"] < 1
                    decision = "both" if high and low else "one" if high or low else "none"
        result[name] = {
            "period1": q1, "period2": q2,
            "target": {k: round(v,6) for k,v in target.items()} if target else None,
            "cleaned_characters": [len(cleaned[q1]), len(cleaned[q2])],
            "removed_chars": [len(by[q1])-len(cleaned[q1]), len(by[q2])-len(cleaned[q2])],
            "history_pairs": len(historical),
            "historical_cosine_median": round(float(np.median([x["cosine"] for x in historical])),6) if historical else None,
            "thresholds": thresholds,
            "decision": decision,
        }
    return {
        "disclaimer": "Exploratory cleaning variants; original metrics remain unchanged. Human checks required.",
        "method": "Original paired English JSD / pairwise TF-IDF cosine, full transcript",
        "results": result,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, default=Path("data/tsmc_corpus/tsmc_quarterly_text.csv"))
    p.add_argument("--out", type=Path, default=Path("data/tsmc_corpus/sensitivity_report.json"))
    args = p.parse_args()
    report = compare_versions(load(args.csv, "2330"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("SENSITIVITY_REPORT", json.dumps(report, ensure_ascii=False))
