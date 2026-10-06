"""Separate candidate calibration using vendor-name normalization.

Keeps original calibration results unchanged. This candidate is NOT automatically
merged into production; reviewers must confirm extracted transcript quality.
"""
import argparse
import json
import hashlib
from pathlib import Path
from calibrate_tsmc_shift import analyze, load, write_firestore
from sensitivity_tsmc_shift import clean_text

METHOD_VERSION = "earnings-en-full-pairwise-tfidf-v2-vendor-normalized"

def calibrate_clean(rows, period1, period2, min_history=30):
    # Every historical and target document receives EXACTLY the same transform.
    normalized = [{**r, "text": clean_text(r["text"], remove_vendor=True)}
                  for r in rows]
    result = analyze(normalized, period1, period2, min_pairs=min_history)
    result["method"]["version"] = METHOD_VERSION
    result["method"]["preprocessing"] = {
        "type": "regex_case_insensitive_word_boundary",
        "removed_document_provider_markers": ["refinitiv", "lseg", "thomson reuters"],
        "applies_to": "ALL historical and target documents; PDF SHA preserved from source",
        "original_baseline_preserved": True
    }
    result["warnings"].append(
        "Provider marker normalization is exploratory. Verify PDFs and other companies before deployment."
    )
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--csv",type=Path,default=Path("data/tsmc_corpus/tsmc_quarterly_text.csv"))
    p.add_argument("--period1",default="2025Q3")
    p.add_argument("--period2",default="2025Q4")
    p.add_argument("--out",type=Path,default=Path("data/tsmc_corpus/vendor_calibration_result.json"))
    p.add_argument("--upload-firestore",action="store_true")
    p.add_argument("--ack-reviewed-sources",action="store_true")
    p.add_argument("--gcp-project",default=None)
    args=p.parse_args()
    result=calibrate_clean(load(args.csv,"2330"),args.period1,args.period2)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"method":result["method"]["version"],"target":result["target"]["metrics"],
                      "thresholds":result["calibration"]["thresholds"],
                      "history_pairs":result["calibration"]["history_pair_count"],
                      "decision":result["drift_result"]},ensure_ascii=False,indent=2))
    if args.upload_firestore:
        if not args.ack_reviewed_sources:
            raise SystemExit("Blocked Firestore write: --ack-reviewed-sources required")
        if result["calibration"]["thresholds"] is None:
            raise SystemExit("Blocked Firestore write: insufficient historical sample")
        write_firestore(result,args.gcp_project)
