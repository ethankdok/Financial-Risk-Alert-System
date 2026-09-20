from __future__ import annotations

import asyncio
import json

from app.services.company_master_repository import build_company_master_repository
from app.services.twse_company_universe import TwseCompanyUniverseService


async def main() -> None:
    repository = build_company_master_repository()
    result = await TwseCompanyUniverseService(repository=repository).sync()
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
