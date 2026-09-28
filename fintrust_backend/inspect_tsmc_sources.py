from pathlib import Path
import json

root = Path.cwd()
research = root / "data/research-results"

print("=== 1. 研究結果檔案 ===")

names = [
    "tsmc_history.json",
    "tsmc_vocabulary_analysis.json",
    "tsmc_provider_impact.json",
    "tsmc_recalibrated.json",
    "research_snapshots.sqlite3",
]

for name in names:
    path = research / name
    print(
        name,
        "FOUND" if path.is_file() else "MISSING"
    )

print("\n=== 2. 台積電歷史資料結構 ===")

history = research / "tsmc_history.json"

if history.is_file():
    data = json.loads(
        history.read_text(encoding="utf-8")
    )

    print("主要欄位：", list(data.keys()))

    for doc in data.get("documents", []):
        if doc.get("period") in (
            "2025Q3", "2025Q4"
        ):
            print(json.dumps(
                doc,
                ensure_ascii=False,
                indent=2
            ))

print("\n=== 3. 既有文字分析資料 ===")

vocab = research / "tsmc_vocabulary_analysis.json"

if vocab.is_file():
    data = json.loads(
        vocab.read_text(encoding="utf-8")
    )

    print("主要欄位：", list(data.keys()))

    for key, value in data.items():
        print(
            key,
            "資料類型：",
            type(value).__name__
        )

print("\n=== 4. 本機逐字稿檔案 ===")

found = []

for folder in [
    root / "data",
    root / "docs"
]:
    if not folder.exists():
        continue

    for path in folder.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in (
            ".pdf", ".txt"
        ):
            continue

        name = str(path).lower()

        if any(word in name for word in [
            "tsmc",
            "transcript",
            "逐字稿"
        ]):
            found.append(path)

for path in found[:30]:
    print(path.relative_to(root))

print("找到相關檔案數量：", len(found))

print("\n=== 檢查完成 ===")
