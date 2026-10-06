"""Material-event state contract for the official evidence card.

An empty material-event list has several different meanings, so the card states
which one applies instead of letting the frontend guess:

- available: persisted official announcements exist.
- no_recent_events: a bounded MOPS history check succeeded and listed nothing in its window.
- needs_refresh: only the current-day TWSE feed was checked, or the history check is stale.
- source_unavailable: the most informative check could not read its official source.
- not_synced: no material-event check has been recorded for this company.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.official_event_models import MaterialEventRecord, MaterialEventStatus, OfficialEventSyncStatus

logger = logging.getLogger("fintrust.official_events")

# A "no events in the window" answer is trusted for this long before it needs re-checking.
RECENT_WINDOW_MAX_AGE = timedelta(days=7)

STATE_MESSAGES = {
    "available": "已取得 {count} 筆近期重大訊息",
    "no_recent_events": "目前查詢期間內未發現重大訊息",
    "not_synced": "重大訊息尚未完成同步",
    "source_unavailable": "官方來源目前無法取得，請稍後再試",
    "needs_refresh": "重大訊息尚未完成同步（已檢查當日公告，尚未完成近期歷史查詢）",
}


def record_material_event_sync(repository: Any, statuses: list[OfficialEventSyncStatus]) -> None:
    """Persist check outcomes; never let status bookkeeping fail an ingestion run."""
    save = getattr(repository, "save_official_event_sync_status", None)
    if save is None:
        return
    for status in statuses:
        try:
            save(status)
        except Exception as exc:  # pragma: no cover - storage availability is external
            logger.warning("material_event_sync_status_save_failed ticker=%s error=%s", status.ticker, type(exc).__name__)


def read_material_event_sync(repository: Any, ticker: str) -> list[OfficialEventSyncStatus]:
    reader = getattr(repository, "list_official_event_sync_status", None)
    if reader is None:
        return []
    try:
        return list(reader(ticker))
    except Exception as exc:  # pragma: no cover - storage availability is external
        logger.warning("material_event_sync_status_read_failed ticker=%s error=%s", ticker, type(exc).__name__)
        return []


def _source_summary(status: OfficialEventSyncStatus) -> dict[str, Any]:
    return {
        "coverage": status.coverage,
        "source_name": status.source_name,
        "source_url": status.source_url,
        "outcome": status.outcome,
        "checked_at": status.checked_at.isoformat(),
        "window_start": status.window_start,
        "window_end": status.window_end,
        "records_found": status.records_found,
        "error": status.error,
    }


def material_event_status(
    records: list[MaterialEventRecord],
    statuses: list[OfficialEventSyncStatus],
    *,
    now: datetime | None = None,
) -> MaterialEventStatus:
    now = now or datetime.now(timezone.utc)
    available = [record for record in records if record.status == "available"]
    by_coverage = {
        coverage: max((item for item in statuses if item.coverage == coverage), key=lambda item: item.checked_at, default=None)
        for coverage in ("recent_window", "current_day")
    }
    window, current = by_coverage["recent_window"], by_coverage["current_day"]
    checked = [item for item in (window, current) if item is not None]
    common = {
        "record_count": len(available),
        "latest_event_date": max((record.event_date for record in available if record.event_date), default=None),
        "last_checked_at": max((item.checked_at for item in checked), default=None),
        "window_start": window.window_start if window else None,
        "window_end": window.window_end if window else None,
        "checked_sources": [_source_summary(item) for item in checked],
    }
    limitations: list[str] = []
    if current and not window:
        limitations.append("TWSE OpenAPI 每日重大訊息只列出當日公告；當日未出現本公司不代表近期沒有重大訊息。")

    if available:
        state = "available"
    elif window is not None and window.outcome == "no_records_in_window":
        state = "no_recent_events" if now - window.checked_at <= RECENT_WINDOW_MAX_AGE else "needs_refresh"
        if state == "needs_refresh":
            limitations.append("近期歷史查詢已超過 7 天，需重新確認。")
    elif window is not None and window.outcome == "source_unavailable":
        state = "source_unavailable"
    elif window is not None:
        # records_found but nothing is persisted (for example a failed write): re-sync.
        state = "needs_refresh"
    elif current is not None:
        state = "source_unavailable" if current.outcome == "source_unavailable" else "needs_refresh"
    else:
        state = "not_synced"

    message = STATE_MESSAGES[state].format(count=len(available))
    return MaterialEventStatus(state=state, message=message, limitations=limitations, **common)
