"""Self-contained parser for official MOPS XBRL evidence.

The vendored twmops parsers drop context dimensions (segment/scenario) and the
lxml iXBRL fallback ignores ``scale``/``sign``. Both matter for an audit
archive: a dimensional equity-component fact must never be merged with the
consolidated total, and an iXBRL value shown in thousands must not be stored
1,000x too small. This module therefore reads the raw bytes directly.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree


XBRLI = "http://www.xbrl.org/2003/instance"
LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
IX_NAMESPACES = (
    "http://www.xbrl.org/2013/inlineXBRL",
    "http://www.xbrl.org/2008/inlineXBRL",
)

_SKIP_NAMESPACES = {XBRLI, LINK}
# "重編後(之)(合併|個體)財務報表/報告" or "重編後民國…年…資產負債表": the auditor names the
# statements themselves as restated. Used only together with a late audit date.
_RESTATED_STATEMENT_PATTERN = re.compile(
    r"重編後(?:之)?(?:合併|個體)?(?:財務報[表告]|民國)|restated (?:consolidated )?financial (?:statements|report)",
    re.IGNORECASE,
)


class XbrlDocumentError(ValueError):
    pass


@dataclass(frozen=True)
class XbrlContext:
    context_id: str
    entity: str
    instant: date | None
    start: date | None
    end: date | None
    dimensional: bool


@dataclass(frozen=True)
class XbrlFact:
    namespace: str
    prefix: str
    local_name: str
    context_ref: str
    unit_ref: str | None
    decimals: str | None
    value_text: str | None
    value: Decimal | None
    is_nil: bool

    @property
    def concept(self) -> str:
        return f"{self.prefix}:{self.local_name}" if self.prefix else self.local_name


@dataclass
class ParsedXbrlDocument:
    document_format: str
    schema_refs: list[str] = field(default_factory=list)
    contexts: dict[str, XbrlContext] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    numeric_facts: list[XbrlFact] = field(default_factory=list)
    text_facts: list[XbrlFact] = field(default_factory=list)

    @property
    def entity_identifiers(self) -> set[str]:
        return {context.entity for context in self.contexts.values() if context.entity}

    def statement_scope(self) -> tuple[str, str | None]:
        """Scope from the Taiwan IFRS taxonomy entry point (…-cr-… / …-ir-…), else unknown."""
        for ref in self.schema_refs:
            name = ref.rsplit("/", 1)[-1].lower()
            if re.search(r"-cr-\d{4}-\d{2}-\d{2}\.xsd$", name):
                return "consolidated", f"taxonomy entry point {name} (consolidated report)"
            if re.search(r"-ir-\d{4}-\d{2}-\d{2}\.xsd$", name):
                return "individual", f"taxonomy entry point {name} (individual report)"
        return "unknown", None

    def audit_report_facts(self) -> list[XbrlFact]:
        return [fact for fact in self.text_facts if "/ar/" in fact.namespace]

    def audit_report_date(self) -> date | None:
        for fact in self.audit_report_facts():
            if "AuditDate" in fact.local_name and fact.value_text:
                parsed = _parse_date(fact.value_text)
                if parsed is not None:
                    return parsed
        return None

    def restatement_evidence(self) -> list[str]:
        evidence: list[str] = []
        for fact in self.audit_report_facts():
            text = (fact.value_text or "").strip()
            match = _RESTATED_STATEMENT_PATTERN.search(text)
            if match:
                start = max(0, match.start() - 40)
                snippet = re.sub(r"\s+", "", text[start:match.end() + 80])
                evidence.append(f"{fact.concept}: …{snippet}…")
        return evidence


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group())
    except ValueError:
        return None


def _parse_decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    cleaned = text.replace(",", "").strip()
    if cleaned in {"", "-", "—"}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _contexts(root: etree._Element) -> dict[str, XbrlContext]:
    contexts: dict[str, XbrlContext] = {}
    for node in root.iter(f"{{{XBRLI}}}context"):
        context_id = node.get("id") or ""
        identifier = node.find(f"{{{XBRLI}}}entity/{{{XBRLI}}}identifier")
        period = node.find(f"{{{XBRLI}}}period")
        dimensional = (
            node.find(f"{{{XBRLI}}}entity/{{{XBRLI}}}segment") is not None
            or node.find(f"{{{XBRLI}}}scenario") is not None
        )
        instant = start = end = None
        if period is not None:
            instant = _parse_date(period.findtext(f"{{{XBRLI}}}instant"))
            start = _parse_date(period.findtext(f"{{{XBRLI}}}startDate"))
            end = _parse_date(period.findtext(f"{{{XBRLI}}}endDate"))
        contexts[context_id] = XbrlContext(
            context_id=context_id,
            entity=(identifier.text or "").strip() if identifier is not None else "",
            instant=instant,
            start=start,
            end=end,
            dimensional=dimensional,
        )
    return contexts


def _measure(node: etree._Element | None) -> str:
    if node is None:
        return ""
    return " ".join((measure.text or "").strip() for measure in node.iter(f"{{{XBRLI}}}measure"))


def _units(root: etree._Element) -> dict[str, str]:
    units: dict[str, str] = {}
    for node in root.iter(f"{{{XBRLI}}}unit"):
        divide = node.find(f"{{{XBRLI}}}divide")
        if divide is not None:
            numerator = _measure(divide.find(f"{{{XBRLI}}}unitNumerator"))
            denominator = _measure(divide.find(f"{{{XBRLI}}}unitDenominator"))
            units[node.get("id") or ""] = f"{numerator}/{denominator}"
        else:
            units[node.get("id") or ""] = _measure(node)
    return units


def _prefix_for(node: etree._Element, namespace: str) -> str:
    for prefix, uri in (node.nsmap or {}).items():
        if uri == namespace and prefix:
            return prefix
    return ""


def _schema_refs(root: etree._Element) -> list[str]:
    return [
        node.get(f"{{{XLINK}}}href") or ""
        for node in root.iter(f"{{{LINK}}}schemaRef")
    ]


def _parse_instance(content: bytes) -> ParsedXbrlDocument:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError as exc:
        raise XbrlDocumentError(f"XBRL instance is not well-formed XML: {exc}") from exc
    if etree.QName(root).namespace != XBRLI:
        raise XbrlDocumentError("Document root is not an XBRL instance.")
    document = ParsedXbrlDocument(
        document_format="xbrl_instance",
        schema_refs=_schema_refs(root),
        contexts=_contexts(root),
        units=_units(root),
    )
    for node in root:
        if not isinstance(node.tag, str):
            continue
        qname = etree.QName(node)
        if qname.namespace in _SKIP_NAMESPACES or node.get("contextRef") is None:
            continue
        is_nil = node.get(f"{{{XSI}}}nil") == "true"
        unit_ref = node.get("unitRef")
        text = node.text
        fact = XbrlFact(
            namespace=qname.namespace or "",
            prefix=_prefix_for(node, qname.namespace or ""),
            local_name=qname.localname,
            context_ref=node.get("contextRef") or "",
            unit_ref=unit_ref,
            decimals=node.get("decimals"),
            value_text=text.strip() if text is not None else None,
            value=None if is_nil or unit_ref is None else _parse_decimal(text),
            is_nil=is_nil,
        )
        (document.numeric_facts if unit_ref is not None else document.text_facts).append(fact)
    return document


def _ix_value(node: etree._Element) -> Decimal | None:
    text = "".join(node.itertext()).strip()
    fmt = (node.get("format") or "").split(":")[-1].lower()
    if fmt in {"zerodash", "fixed-zero", "numdash"} or (text in {"-", "—"} and "zero" in fmt):
        value = Decimal(0)
    elif fmt in {"numcommadecimal", "num-comma-decimal", "numdotcomma"}:
        value = _parse_decimal(text.replace(".", "").replace(" ", "").replace(",", "."))
    else:
        value = _parse_decimal(text.replace(" ", ""))
    if value is None:
        return None
    scale = node.get("scale")
    if scale:
        try:
            value = value.scaleb(int(scale))
        except ValueError as exc:
            raise XbrlDocumentError(f"Invalid iXBRL scale {scale!r}") from exc
    if node.get("sign") == "-":
        value = -value
    return value


def _parse_inline(content: bytes) -> ParsedXbrlDocument:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, recover=True)
    root = etree.fromstring(content, parser)
    if root is None:
        raise XbrlDocumentError("Inline XBRL document could not be parsed.")
    document = ParsedXbrlDocument(
        document_format="inline_xbrl",
        schema_refs=_schema_refs(root),
        contexts=_contexts(root),
        units=_units(root),
    )
    for namespace in IX_NAMESPACES:
        for tag, numeric in (("nonFraction", True), ("nonNumeric", False)):
            for node in root.iter(f"{{{namespace}}}{tag}"):
                name = node.get("name") or ""
                prefix, _, local = name.rpartition(":")
                concept_namespace = (node.nsmap or {}).get(prefix or None, "")
                is_nil = node.get(f"{{{XSI}}}nil") == "true"
                text = "".join(node.itertext()).strip()
                fact = XbrlFact(
                    namespace=concept_namespace,
                    prefix=prefix,
                    local_name=local,
                    context_ref=node.get("contextRef") or "",
                    unit_ref=node.get("unitRef"),
                    decimals=node.get("decimals"),
                    value_text=text,
                    value=None if is_nil or not numeric else _ix_value(node),
                    is_nil=is_nil,
                )
                (document.numeric_facts if numeric else document.text_facts).append(fact)
    if not document.numeric_facts:
        raise XbrlDocumentError("Inline XBRL document contains no ix:nonFraction facts.")
    return document


def _instance_from_zip(content: bytes) -> tuple[bytes, str]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise XbrlDocumentError(f"Invalid XBRL ZIP package: {exc}") from exc
    with archive:
        names = archive.namelist()
        for name in names:
            lowered = name.lower()
            if lowered.endswith((".htm", ".html", ".xhtml")):
                return archive.read(name), "inline_xbrl"
        for name in names:
            lowered = name.lower()
            if lowered.endswith(".xml") and not any(
                marker in lowered for marker in ("_cal", "_pre", "_lab", "_def", "_ref")
            ):
                return archive.read(name), "xbrl_instance"
    raise XbrlDocumentError("XBRL ZIP package contains no instance document.")


def detect_format(content: bytes) -> str | None:
    head = content[:4096].lstrip()
    if content[:2] == b"PK":
        return "zip"
    if b"ix:nonFraction" in content or b"inlineXBRL" in head:
        return "inline_xbrl"
    if head.startswith(b"<?xml") or head.startswith(b"<xbrl") or b"xbrl.org/2003/instance" in head:
        return "xbrl_instance"
    if head[:5] == b"%PDF-":
        return "pdf"
    return None


def parse_xbrl_document(content: bytes) -> ParsedXbrlDocument:
    kind = detect_format(content)
    if kind == "zip":
        inner, kind = _instance_from_zip(content)
        document = _parse_inline(inner) if kind == "inline_xbrl" else _parse_instance(inner)
        document.document_format = f"zip/{document.document_format}"
        return document
    if kind == "inline_xbrl":
        return _parse_inline(content)
    if kind == "xbrl_instance":
        return _parse_instance(content)
    raise XbrlDocumentError("Content is not an XBRL instance, inline XBRL or XBRL ZIP package.")
