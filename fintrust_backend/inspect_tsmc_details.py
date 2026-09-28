from pathlib import Path
import json
import ast

root = Path.cwd()
results = root / "data/research-results"

vocab = results / "tsmc_vocabulary_analysis.json"

print("=== 1. 詞彙分析 ===")

if vocab.exists():
    data = json.loads(vocab.read_text(encoding="utf-8"))

    for key in [
        "training_periods",
        "evaluation_periods",
        "unknown_ratios",
        "top_unknown",
        "top_emerging",
        "top_disappearing"
    ]:
        value = data.get(key)

        print("\n", key)

        if isinstance(value, list):
            for item in value[:5]:
                print(str(item)[:400])
        else:
            print(str(value)[:600])

print("\n=== 2. 程式讀取方式 ===")

for name in [
    "build_tsmc_history.py",
    "analyze_tsmc_vocabulary.py"
]:
    path = root / "scripts" / name

    if not path.exists():
        continue

    tree = ast.parse(
        path.read_text(encoding="utf-8")
    )

    print("\n程式：", name)

    for node in tree.body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            print("函式：", node.name)

print("\n=== 3. 原始文字保存位置 ===")

data_dir = root / "data"

for folder in data_dir.iterdir():
    if folder.is_dir():
        txt = list(folder.rglob("*.txt"))
        pdf = list(folder.rglob("*.pdf"))

        if txt or pdf:
            print(
                folder.name,
                "TXT:", len(txt),
                "PDF:", len(pdf)
            )

print("\n檢查完成")
