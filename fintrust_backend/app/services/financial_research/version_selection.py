"""Deterministic, version-aware selection of exactly one filed fact per identity key (finding F05).

A research computation may use a filed fact only when the snapshot holds exactly one *identity* for its key
``(period, statement_scope, metric)``. The identity of a candidate is its exact value, unit, accounting framework,
filing version id/type, taxonomy concept and artifact SHA-256. Rules:

- one candidate, or several byte-identical candidates (same identity) → that identity is selected;
- two or more different identities → the key is **ambiguous** and is never resolved by input order, recency or value
  equality: callers must report it as ``ambiguous_version`` / ``not_comparable``. Two versions with equal amounts
  but different filing identities are still ambiguous.

The result never depends on the order of the input list, so neither the computed outcome nor any digest built from
the sorted inputs can change when the facts are permuted. The same policy is applied to the literature-model inputs.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

SELECTION_POLICY_VERSION = "fact_selection_v1"
FACT_KEY_FIELDS = ("period", "statement_scope", "metric_code")
IDENTITY_FIELDS = ("value", "unit", "accounting_framework", "filing_version_id", "filing_version_type",
                   "taxonomy_concept", "artifact_sha256")
AMBIGUOUS_REASON = "ambiguous_filed_fact_versions"


def identity(fact: dict[str, Any], fields: tuple[str, ...] = IDENTITY_FIELDS) -> str:
    return json.dumps({name: fact.get(name) for name in fields}, sort_keys=True, ensure_ascii=False, default=str)


def fact_sort_key(fact: dict[str, Any]) -> tuple[Any, ...]:
    """Canonical order of snapshot facts (equal to the reader's order for one fact per key)."""
    return (fact.get("fiscal_year") or 0, fact.get("period") or "", fact.get("metric_code") or "",
            fact.get("statement_scope") or "", fact.get("unit") or "", fact.get("filing_version_id") or "",
            fact.get("fact_id") or "")


class FactIndex(dict):
    """``key → selected fact``; ambiguous keys are absent from the mapping and listed in ``ambiguous``."""

    def __init__(self) -> None:
        super().__init__()
        self.ambiguous: dict[tuple, list[dict[str, Any]]] = {}

    def lookup(self, key: tuple) -> tuple[dict[str, Any] | None, str | None]:
        if key in self.ambiguous:
            return None, AMBIGUOUS_REASON
        return self.get(key), None

    def candidates(self, key: tuple) -> list[dict[str, Any]]:
        return [{name: fact.get(name) for name in ("fact_id", *IDENTITY_FIELDS)} for fact in self.ambiguous.get(key, [])]


def build_index(facts: Iterable[dict[str, Any]], key: Callable[[dict[str, Any]], tuple] | None = None,
                identity_fields: tuple[str, ...] = IDENTITY_FIELDS) -> FactIndex:
    key = key or (lambda fact: tuple(fact[name] for name in FACT_KEY_FIELDS))
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for fact in facts:
        groups.setdefault(key(fact), []).append(fact)
    index = FactIndex()
    for group_key, group in groups.items():
        ordered = sorted(group, key=lambda f: (identity(f, identity_fields), str(f.get("fact_id") or "")))
        if len({identity(f, identity_fields) for f in ordered}) == 1:
            index[group_key] = ordered[0]
        else:
            index.ambiguous[group_key] = ordered
    return index
