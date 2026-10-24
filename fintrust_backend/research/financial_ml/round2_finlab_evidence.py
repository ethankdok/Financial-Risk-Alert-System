"""Round 2 stage-2: source-safe event evidence and issuer-year adjudication queue.

Read a *locally held* FinLab important_info_announcement candidate CSV. Extract
risk-relevant evidence from announcement text, but NEVER issue supervised 0/1:
notices are an event lead, not proof of MOPS financial filing correction or its
original filing date. Licensed content remains only in local, private outputs.

From fintrust_backend:
python -m research.financial_ml.round2_finlab_evidence \
    --input-csv data/financial_ml/finlab_restatement_candidates.csv \
    --out data/financial_ml/round2_finlab_evidence
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from research.financial_ml.round2_finlab_events import annual_years, classify

CUTOFF = datetime(2026, 10, 24, 23, 59, 59)
YEARS = range(2013, 2024)
RESERVED_HOLDOUT = {"1785"}
REQUIRED = {"stock_id", "date", "title", "info"}

# Regexes are positive *cues*, never substitute for numeric old-new checks.
DONE = re.compile(r"已完成.{0,10}重編|重編.{0,20}(?:已完成|完成上傳)|董事會.{0,16}(?:通過|承認).{0,16}重編|重編後.{0,20}(?:重新上傳|重行公告)|(?:重編|更正)後.{0,10}已.{0,10}(?:上傳|申報)")
PENDING = re.compile(r"(?:擬|預計|評估|應評估|請.{0,12}評估|展延|延期|期限|尚待|研議).{0,20}(?:重編|更正)|(?:重編|更正).{0,20}(?:擬|預計|評估|展延|延期|期限|尚待)")
REGULATOR = re.compile(r"主管機關|金管會|證交所|櫃買中心|金管證審|金融監督管理委員會")
RESTATE = re.compile(r"重編|重行編製|重新編製")
AMEND = re.compile(r"更正|更補正|補正")
FIN_CORE = re.compile(r"資產總計|資產合計|負債總計|負債合計|權益總計|股東權益總計|本期淨利|稅後淨利|營業收入|營業利益|營業淨利|稅前淨利|營業成本|現金流量|綜合損益總額")
BEFORE_AFTER = re.compile(r"重編前.{0,350}重編後|更正前.{0,350}更正後|調整數|影響金額|原公告.{0,90}更正")
NO_PNL = re.compile(r"(?:不|無|未)(?:會|致)?影響.{0,16}(?:損益|淨利|權益)|(?:損益|淨利|權益).{0,16}無影響")
ANNEX = re.compile(r"附註|附表|iXBRL|會計師查核報告|目錄|頁次|誤植|文字")
MONTHLY = re.compile(r"自結|12月份|12月自結|月營收|月份財務|月合併財務資訊|12月份合併財務")
ONLY_INDIVIDUAL = re.compile(r"個體|個別|母公司")
CONSOLIDATED = re.compile(r"合併")
CONTINUE_RANGE = re.compile(r"(?:至|到|起|~|～|迄|間各期|各期).{0,20}(?:年度|財報|財務)|(?:年度|財報|財務).{0,30}(?:至|到|起|~|～|迄)")
TEMPLATE_SCOPE = re.compile(r"(?:更正且重編|更正或重編|重編|更補正)之財務報告年季[：:]?\s*(.{0,180}?)(?=\d{1,2}[.．]發生緣由|\d{1,2}[.．]請說明|$)")

NOTICE_COLS = (
    "notice_id", "ticker", "issuer_name", "notice_date", "title", "candidate_fys",
    "source_event_group", "statement_scope", "status", "status_cue", "scope_text",
    "restatement_fys_title_explicit",
    "regulator_cue", "core_line_item_cue", "comparison_table_cue", "pnl_no_effect_cue",
    "annex_only_risk", "monthly_report_risk", "multi_period_risk", "holdout",
    "source_market", "source_clause", "source_sequence", "content_sha256",
    "official_mops_notice_verified", "original_filing_date_verified", "annual_consolidated_verified",
    "actual_core_delta_verified", "training_y", "followup",
)
CASE_COLS = (
    "case_id", "ticker", "issuer_name", "fiscal_year", "rank", "review_reason",
    "notice_count", "first_notice_date", "last_notice_date", "statuses", "source_groups",
    "confirmed_in_notice_count", "pending_or_regulatory_count", "core_cue_count",
    "comparison_cue_count", "non_pnl_impact_count", "monthly_risk_count",
    "mixed_or_range_scope_count", "representative_title", "source_notice_ids", "holdout",
    "mops_notice_url", "original_financial_filing_url", "first_report_public_date",
    "verified_correction_date", "scope_verified", "line_items_old_new_verified",
    "within_24_months_verified", "adjudication", "training_y",
)


def _hash(s: bytes) -> str:
    return hashlib.sha256(s).hexdigest()


def _csv_blob(cols, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=cols, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def _write_immutable(path: Path, content: bytes):
    if path.exists() and path.read_bytes() != content:
        raise FileExistsError(f"immutable_output_collision:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(content)


def analyze_notice(title: str, info: str):
    group, _, title_years, _, procedural, subsidiary, _, _ = classify(title)
    match = TEMPLATE_SCOPE.search(info)
    scope = match.group(1).strip() if match else ""
    scope_years = annual_years(scope)
    combined_years = sorted(set(title_years + scope_years).intersection(YEARS))
    # In a mixed notice, years stated under "更正" do not imply they were "重編".
    rmatch = re.search(r"重編|重行編製|重新編製", title)
    if rmatch:
        restatement_span = re.split(
            r"(?:並|暨|及)?(?:更補正|補正|更正)", title[rmatch.start():],
            maxsplit=1,
        )[0]
        restate_fys = sorted(set(annual_years(restatement_span)).intersection(YEARS))
        if (not restate_fys and len(title_years) == 1 and
                not re.search(r"更正|更補正|補正", title)):
            restate_fys = sorted(set(title_years).intersection(YEARS))
    else:
        restate_fys = []
    monthly = bool(MONTHLY.search(title))
    restate = bool(RESTATE.search(title))
    amend = bool(AMEND.search(title))
    pending = bool(PENDING.search(title))
    done = bool(DONE.search(title))
    # Completion must appear in the title. An info-field future step is not proof.
    if pending or procedural or subsidiary:
        status = "PENDING_OR_SCOPE_UNCLEAR"
    elif done and restate:
        status = "RESTATEMENT_COMPLETED_STATED"
    elif restate and bool(RESTATE.search(scope)) and bool(re.search(r"重編後|重編完成|已完成", info[:900])):
        status = "RESTATEMENT_DESCRIBED"
    elif restate:
        status = "RESTATEMENT_ANNOUNCED_NOT_CONFIRMED"
    elif amend:
        status = "CORRECTION_ONLY"
    else:
        status = "NON_RESTATEMENT_CONTEXT"
    core = bool(FIN_CORE.search(info))
    compare = bool(BEFORE_AFTER.search(info))
    report_only = bool(ANNEX.search(title)) and not bool(FIN_CORE.search(title))
    mixed_or_range = bool(CONTINUE_RANGE.search(title) or CONTINUE_RANGE.search(scope))
    if monthly:
        combined_years = []
    if "一季" in title and "年度" not in title and not scope_years:
        combined_years = []
    scope_result = ("CONSOLIDATED_CUE" if CONSOLIDATED.search(title + " " + scope)
                    else "STANDALONE_CUE" if ONLY_INDIVIDUAL.search(title + " " + scope)
                    else "SCOPE_UNVERIFIED")
    return {
        "source_event_group": group, "candidate_fys": combined_years,
        "restatement_fys_title_explicit": restate_fys,
        "status": status, "status_cue": "TITLE_COMPLETION" if done else
                      "PENDING_OR_REQUEST" if pending else "NOT_CONFIRMED",
        "statement_scope": scope_result, "scope_text": scope[:150],
        "regulator_cue": bool(REGULATOR.search(title + " " + info[:650])),
        "core_line_item_cue": core, "comparison_table_cue": compare,
        "pnl_no_effect_cue": bool(NO_PNL.search(title + " " + info)),
        "annex_only_risk": report_only, "monthly_report_risk": monthly,
        "multi_period_risk": mixed_or_range,
    }


def _rank(notices: list[dict], fy: int):
    complete = any(n["status"] == "RESTATEMENT_COMPLETED_STATED" and
                   str(fy) in n["restatement_fys_title_explicit"].split(";")
                   for n in notices)
    described = any(n["status"] == "RESTATEMENT_DESCRIBED" and
                    str(fy) in n["restatement_fys_title_explicit"].split(";")
                    for n in notices)
    core_compare = any(n["core_line_item_cue"] == "true" and
                       n["comparison_table_cue"] == "true" and
                       (n["annex_only_risk"] == "false" or FIN_CORE.search(n["title"]))
                       for n in notices)
    monthly = any(n["monthly_report_risk"] == "true" for n in notices)
    uncertain = any(n["multi_period_risk"] == "true" for n in notices)
    if complete and core_compare and not monthly:
        return ("P0", "COMPLETION_ASSERTED_AND_CORE_COMPARE_CUES_MOPS_CHECK")
    if (complete or described) and not monthly:
        return ("P1", "RESTATEMENT_ASSERTION_REQUIRES_ORIGINAL_FILING_CHECK")
    if core_compare and not monthly:
        return ("P2", "CORE_MONETARY_CHANGE_CANDIDATE_CHECK_OLD_NEW")
    if uncertain:
        return ("P3", "MIXED_PERIODS_NEED_YEAR_BY_YEAR_CHECK")
    return ("P4", "EVENT_TYPE_AND_SCOPE_REQUIRE_REVIEW")


def build(input_csv: str | Path, out: str | Path) -> dict:
    raw = Path(input_csv).read_bytes()
    decoded = None
    for encoding in ("utf-8-sig", "cp950"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError("input_csv_encoding_unreadable")
    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
        raise ValueError("missing_required_finlab_columns")
    notices = []
    pairs = defaultdict(list)
    stats = Counter()
    seen = set()
    for lineno, source in enumerate(reader, 2):
        ticker = str(source.get("stock_id") or "").strip()
        date_string = str(source.get("date") or "").strip()
        title = str(source.get("title") or "").strip()
        info = str(source.get("info") or "")
        if not re.fullmatch(r"\d{4}", ticker) or not title:
            stats["invalid_ticker_or_title"] += 1
            continue
        try:
            when = datetime.fromisoformat(date_string)
        except ValueError:
            stats["invalid_date"] += 1
            continue
        if when > CUTOFF:
            stats["future_notice_skipped"] += 1
            continue
        unique_hash = _hash((ticker + "\n" + date_string + "\n" + title + "\n" + info).encode("utf-8"))
        if unique_hash in seen:
            stats["duplicate_announcement_skipped"] += 1
            continue
        seen.add(unique_hash)
        analysis = analyze_notice(title, info)
        n = {
            "notice_id": unique_hash[:24], "ticker": ticker,
            "issuer_name": str(source.get("name") or "").strip(),
            "notice_date": date_string, "title": title,
            "candidate_fys": ";".join(map(str, analysis["candidate_fys"])),
            "source_event_group": analysis["source_event_group"],
            "restatement_fys_title_explicit": ";".join(map(str, analysis["restatement_fys_title_explicit"])),
            "statement_scope": analysis["statement_scope"],
            "status": analysis["status"], "status_cue": analysis["status_cue"],
            "scope_text": analysis["scope_text"],
            "regulator_cue": str(analysis["regulator_cue"]).lower(),
            "core_line_item_cue": str(analysis["core_line_item_cue"]).lower(),
            "comparison_table_cue": str(analysis["comparison_table_cue"]).lower(),
            "pnl_no_effect_cue": str(analysis["pnl_no_effect_cue"]).lower(),
            "annex_only_risk": str(analysis["annex_only_risk"]).lower(),
            "monthly_report_risk": str(analysis["monthly_report_risk"]).lower(),
            "multi_period_risk": str(analysis["multi_period_risk"]).lower(),
            "holdout": str(ticker in RESERVED_HOLDOUT).lower(),
            "source_market": str(source.get("source_market") or ""),
            "source_clause": str(source.get("source_clause") or ""),
            "source_sequence": str(source.get("source_sequence") or ""),
            "content_sha256": unique_hash,
            "official_mops_notice_verified": "false",
            "original_filing_date_verified": "false",
            "annual_consolidated_verified": "false",
            "actual_core_delta_verified": "false",
            "training_y": "",
            "followup": "MOPS_ORIGINAL_FILING_AND_RESTATED_AMOUNTS"
                        if analysis["candidate_fys"] else "CLARIFY_ANNUAL_SCOPE",
        }
        notices.append(n)
        if analysis["source_event_group"] in (
            "A_RESTATEMENT_ANNUAL_REVIEW",
            "B_RESTATEMENT_CONTEXT_REVIEW",
            "C_ANNUAL_CORRECTION_REVIEW",
            "D_QUARTER_OR_YEAR_UNCLEAR",
        ):
            for year in analysis["candidate_fys"]:
                if year <= when.year:
                    pairs[(ticker, year)].append(n)
    notices.sort(key=lambda n: (n["ticker"], n["notice_date"], n["notice_id"]))
    cases = []
    for (ticker, fy), items in sorted(pairs.items()):
        items.sort(key=lambda n: (n["notice_date"], n["notice_id"]))
        if not any(x["source_event_group"] in (
            "A_RESTATEMENT_ANNUAL_REVIEW", "C_ANNUAL_CORRECTION_REVIEW"
        ) for x in items):
            continue
        rank, reason = _rank(items, fy)
        first = items[0]
        cases.append({
            "case_id": f"{ticker}-FY{fy}", "ticker": ticker,
            "issuer_name": first["issuer_name"], "fiscal_year": str(fy),
            "rank": rank, "review_reason": reason, "notice_count": str(len(items)),
            "first_notice_date": first["notice_date"], "last_notice_date": items[-1]["notice_date"],
            "statuses": ";".join(sorted({x["status"] for x in items})),
            "source_groups": ";".join(sorted({x["source_event_group"] for x in items})),
            "confirmed_in_notice_count": str(sum(x["status"] == "RESTATEMENT_COMPLETED_STATED" for x in items)),
            "pending_or_regulatory_count": str(sum(x["status"] == "PENDING_OR_SCOPE_UNCLEAR" for x in items)),
            "core_cue_count": str(sum(x["core_line_item_cue"] == "true" for x in items)),
            "comparison_cue_count": str(sum(x["comparison_table_cue"] == "true" for x in items)),
            "non_pnl_impact_count": str(sum(x["pnl_no_effect_cue"] == "true" for x in items)),
            "monthly_risk_count": str(sum(x["monthly_report_risk"] == "true" for x in items)),
            "mixed_or_range_scope_count": str(sum(x["multi_period_risk"] == "true" for x in items)),
            "representative_title": next(
                (x["title"] for x in items if x["status"] == "RESTATEMENT_COMPLETED_STATED"),
                first["title"],
            ),
            "source_notice_ids": ";".join(x["notice_id"] for x in items),
            "holdout": str(ticker in RESERVED_HOLDOUT).lower(),
            "mops_notice_url": "", "original_financial_filing_url": "",
            "first_report_public_date": "", "verified_correction_date": "",
            "scope_verified": "", "line_items_old_new_verified": "",
            "within_24_months_verified": "",
            "adjudication": "PENDING_OFFICIAL_AND_FILING_CHECK",
            "training_y": "",
        })
    cases.sort(key=lambda c: (int(c["rank"][1]), c["ticker"], c["fiscal_year"]))
    family = Counter(c["rank"] for c in cases)
    status_count = Counter(n["status"] for n in notices)
    summary = {
        "schema": "fintrust_round2_finlab_evidence_v1",
        "source_sha256": _hash(raw),
        "input_notice_count": len(notices),
        "unique_issuers": len({n["ticker"] for n in notices}),
        "notice_status_counts": dict(sorted(status_count.items())),
        "fy2013_2023_case_count": len(cases),
        "fy2013_2023_company_count": len({c["ticker"] for c in cases}),
        "case_review_rank_count": dict(sorted(family.items())),
        "case_holdout_1785_count": sum(c["holdout"] == "true" for c in cases),
        "reserved_holdout_notices": sum(n["holdout"] == "true" for n in notices),
        "source_skips": dict(sorted(stats.items())),
        "confirmed_official_mops_notice_count": 0,
        "confirmed_24m_supervised_positive_count": 0,
        "confirmed_24m_supervised_negative_count": 0,
        "label_semantics": (
            "Evidence cues only. Not proof of restatement or core delta. "
            "Manual official MOPS & first filing date required. Missing notice is NEVER a negative."
        ),
        "licenses": (
            "Private source data and title output must stay locally; public "
            "GitHub may contain only script/tests/sanitized aggregate summary."
        ),
    }
    out = Path(out)
    notice_b = _csv_blob(NOTICE_COLS, notices)
    case_b = _csv_blob(CASE_COLS, cases)
    summary["output_sha256"] = {
        "finlab_notice_evidence_private.csv": _hash(notice_b),
        "finlab_issuer_fy_review_private.csv": _hash(case_b),
    }
    _write_immutable(out / "finlab_notice_evidence_private.csv", notice_b)
    _write_immutable(out / "finlab_issuer_fy_review_private.csv", case_b)
    _write_immutable(
        out / "finlab_evidence_summary.json",
        (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    print(json.dumps(build(args.input_csv, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
