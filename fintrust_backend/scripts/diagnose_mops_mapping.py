from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


# When a file under backend/scripts is executed directly, Python adds the
# scripts directory—not backend—to sys.path. Add the backend project root so
# imports such as `from app...` work in Codespaces and local terminals without
# relying on a manually configured PYTHONPATH.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.company_registry import get_company
from app.services.robust_mops_inline_xbrl import RobustMopsInlineXbrlClient


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect live/cached MOPS iXBRL concepts, labels and contexts for mapping gaps."
    )
    parser.add_argument("--ticker", default="2330")
    parser.add_argument("--roc-year", type=int, default=113)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    profile = get_company(args.ticker)
    if profile is None:
        raise SystemExit(f"Ticker {args.ticker} is not in the semiconductor registry.")

    payload = await RobustMopsInlineXbrlClient().diagnose_annual(profile, args.roc_year)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
