from pathlib import Path
import json
import re
import csv

root = Path.cwd()
data_dir = root / "data"
results = data_dir / "research-results"
history = json.loads(
    (results / "tsmc_history.json").read_text(encoding="utf-8")
)

terms = [
    "refinitiv",
    "lseg",
    "streetevents",
    "analyst",
]

rows = []
evidence = []

for doc in history["documents"]:
    period = doc["period"]
    if period not in ("2025Q3", "2025Q4"):
        continue

    sha = doc["sha256"]
    matches = list(data_dir.rglob(sha + ".txt"))

    if len(matches) != 1:
        raise SystemExit(
            f"{period}: 需要唯一文字檔，找到 {len(matches)} 個"
        )

    path = matches[0]
    content = path.read_text(
        encoding="utf-8",
        errors="replace"
    )

    # 依文字檔中的頁碼標記分段
    parts = re.split(
        r"(?im)^\s*\[page\s+(\d+)\]\s*$",
        content
    )

    if len(parts) < 3:
        raise SystemExit(
            f"{period}: 找不到頁碼標記，停止產生頁碼證據"
        )

    pages = {}
    for i in range(1, len(parts) - 1, 2):
        pages[int(parts[i])] = parts[i + 1]

    words = re.findall(r"\b[\w'-]+\b", content)
    total_words = len(words)

    for term in terms:
        pattern = re.compile(
            r"\b" + re.escape(term) + r"\b",
            re.IGNORECASE
        )

        matches_total = list(pattern.finditer(content))

        rows.append({
            "period": period,
            "term": term,
            "count": len(matches_total),
            "per_1000_words": round(
                len(matches_total) / total_words * 1000, 4
            ) if total_words else 0,
            "total_words": total_words,
            "sha256": sha
        })

        for page_number, page_text in pages.items():
            for match in pattern.finditer(page_text):
                start = max(0, match.start() - 90)
                end = min(
                    len(page_text),
                    match.end() + 90
                )

                snippet = " ".join(
                    page_text[start:end].split()
                )

                evidence.append({
                    "period": period,
                    "term": term,
                    "page": page_number,
                    "snippet": snippet,
                    "sha256": sha,
                    "source_url": doc["source_url"]
                })

    print(
        period,
        "文字數量:", len(content),
        "可辨識頁數:", len(pages)
    )

results.mkdir(parents=True, exist_ok=True)

with (results / "tsmc_provider_terms.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as f:
    writer = csv.DictWriter(
        f, fieldnames=list(rows[0])
    )
    writer.writeheader()
    writer.writerows(rows)

output = {
    "experiment": "TSMC provider vocabulary evidence",
    "scope": "Term frequency and located excerpts only",
    "documents": [
        d for d in history["documents"]
        if d["period"] in ("2025Q3", "2025Q4")
    ],
    "statistics": rows,
    "evidence": evidence,
    "causal_conclusion": "NOT_ESTABLISHED"
}

(results / "tsmc_provider_evidence.json").write_text(
    json.dumps(output, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print("\n=== 詞彙統計 ===")
for row in rows:
    print(
        row["period"],
        row["term"],
        "次數:", row["count"],
        "每千字:", row["per_1000_words"]
    )

print("\n=== 完成 ===")
print("CSV: data/research-results/tsmc_provider_terms.csv")
print("JSON: data/research-results/tsmc_provider_evidence.json")
