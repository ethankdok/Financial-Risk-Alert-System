"""Deterministic, PDF-native semantic evidence for conference slides.

Visual primitives are filtered for layout noise (page backgrounds, repeated
logos, separators, header/footer marks) and clustered locally so a slide is
described by its meaningful regions instead of one page-sized box. Regions the
parser cannot settle are flagged ``gemini_eligible``; an optional multimodal
interpreter may then read the cropped region, but its output is validated
against the PDF text before any verification status is granted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol


NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?(?![A-Za-z0-9])")
PERIOD_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"20\d{2}[EF]?|FY\s?(?:20)?\d{2}[EF]?|[1-4]Q\s?'?\d{2}[EF]?|Q[1-4]\s?'?(?:20)?\d{2}|Q[1-4]|"
    r"H[12]\s?'?\d{2}|[12]H\s?'?\d{2}|20\d{2}\s?年(?:第?[一二三四1-4]季)?|第[一二三四1-4]季"
    r")(?![A-Za-z0-9])",
    re.I,
)
UNIT_RE = re.compile(r"(?:NT\$|US\$|\$|%|bps|億|百萬|千|billion|million|thousand|\bB\b|\bM\b|\bK\b)", re.I)
FINANCIAL_CONTEXT_RE = re.compile(
    r"(?:revenue|sales|margin|profit|income|eps|cash|capex|inventory|asset|liabilit|equity|"
    r"shipment|capacity|wafer|node|market|share|growth|quarter|outlook|dividend|"
    r"營收|營業|毛利|淨利|獲利|現金|資本支出|存貨|股利|出貨|產能|季)",
    re.I,
)

BACKGROUND_AREA_RATIO = 0.85
PANEL_AREA_RATIO = 0.30
TINY_AREA_RATIO = 0.002
DECORATIVE_AREA_RATIO = 0.012
MEANINGFUL_AREA_RATIO = 0.03
CLUSTER_GAP = 14.0
CONTEXT_MARGIN = 20.0
REPEAT_PAGE_SHARE = 0.5


def load_pymupdf():
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        import fitz

        return fitz


BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class Word:
    text: str
    bbox: BBox

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2


@dataclass(frozen=True)
class TextLine:
    text: str
    bbox: BBox
    words: tuple[Word, ...] = ()


@dataclass
class Primitive:
    bbox: BBox
    kind: str  # "drawing" | "image"
    thin: bool = False
    repeated: bool = False


@dataclass
class RegionContext:
    """Source material for one region; kept out of the serialized record."""

    page_no: int
    bbox: BBox
    page_title: str | None
    caption: str | None
    region_text: str
    page_text: str
    words: list[Word] = field(default_factory=list)
    # Local OCR tokens for raster regions (conference_pdf_ocr.OcrToken); never PDF text.
    ocr_tokens: list[Any] = field(default_factory=list)


class RegionInterpreter(Protocol):
    def interpret_page(self, page: Any, items: list[tuple[dict[str, Any], RegionContext]]) -> None: ...


class RegionOcr(Protocol):
    def process_page(self, page: Any, items: list[tuple[dict[str, Any], RegionContext]]) -> None: ...


RASTER_SHARE_FOR_OCR = 0.3


def render_region_png(page: Any, bbox: BBox, *, dpi: int, padding: float = 8.0) -> tuple[bytes, BBox]:
    """Render one padded region of the original page; returns the PNG and the clip actually used."""
    fitz = load_pymupdf()
    clip = fitz.Rect(
        max(page.rect.x0, bbox[0] - padding), max(page.rect.y0, bbox[1] - padding),
        min(page.rect.x1, bbox[2] + padding), min(page.rect.y1, bbox[3] + padding),
    )
    return page.get_pixmap(clip=clip, dpi=dpi).tobytes("png"), rect_tuple(clip)


def ocr_eligible(record: dict[str, Any], images: list["Primitive"], words: list[Word]) -> bool:
    """OCR only meaningful regions whose evidence is in pixels, not selectable text."""
    if not record.get("gemini_eligible") or record.get("evidence_type") not in {"chart", "image", "unknown"}:
        return False
    box = (record["region"]["x0"], record["region"]["y0"], record["region"]["x1"], record["region"]["y1"])
    area = bbox_area(box) or 1.0
    raster = sum(bbox_area(item.bbox) * overlap_ratio(item.bbox, box) for item in images)
    if raster / area >= RASTER_SHARE_FOR_OCR:
        return True
    # Vector marks with (almost) no selectable text, e.g. labels drawn as outlines.
    return len(words) < 3


def bbox_dict(bbox: BBox) -> dict[str, float]:
    return {"x0": round(bbox[0], 2), "y0": round(bbox[1], 2), "x1": round(bbox[2], 2), "y1": round(bbox[3], 2)}


def union_bbox(boxes: list[BBox]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def rect_tuple(rect: Any) -> BBox:
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def bbox_area(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def intersects_or_near(a: BBox, b: BBox, margin: float = 24) -> bool:
    return not (a[2] + margin < b[0] or b[2] + margin < a[0] or a[3] + margin < b[1] or b[3] + margin < a[1])


def contains(outer: BBox, inner: BBox, tolerance: float = 1.0) -> bool:
    return (
        outer[0] - tolerance <= inner[0] and outer[1] - tolerance <= inner[1]
        and outer[2] + tolerance >= inner[2] and outer[3] + tolerance >= inner[3]
    )


def overlap_ratio(inner: BBox, outer: BBox) -> float:
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = bbox_area(inner)
    return (ix * iy / area) if area else 0.0


def expand(bbox: BBox, margin: float) -> BBox:
    return (bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin)


def text_lines(page: Any) -> list[TextLine]:
    payload = page.get_text("dict")
    raw_lines: list[tuple[str, BBox]] = []
    for block in payload.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            parts = [span.get("text", "") for span in line.get("spans", [])]
            text = " ".join("".join(parts).split())
            if text:
                raw_lines.append((text, tuple(float(v) for v in line.get("bbox", block.get("bbox")))))
    words = [Word(str(item[4]), tuple(float(v) for v in item[:4])) for item in page.get_text("words")]
    lines = []
    for text, bbox in raw_lines:
        inside = tuple(sorted(
            (word for word in words if contains(bbox, word.bbox, tolerance=1.5)),
            key=lambda word: word.bbox[0],
        ))
        lines.append(TextLine(text=text, bbox=bbox, words=inside))
    return lines


def page_title(lines: list[TextLine]) -> str | None:
    if not lines:
        return None
    top = sorted(lines, key=lambda line: (line.bbox[1], line.bbox[0]))[:5]
    candidates = [line.text for line in top if len(line.text) >= 3 and not NUMBER_RE.fullmatch(line.text)]
    return candidates[0] if candidates else top[0].text


def nearby_text(lines: list[TextLine], bbox: BBox, *, limit: int = 8) -> str | None:
    selected = [line.text for line in lines if intersects_or_near(line.bbox, bbox, margin=48)]
    if not selected:
        selected = [line.text for line in lines[:limit]]
    return " ".join(selected[:limit]) or None


def numeric_values(text: str) -> list[str]:
    return NUMBER_RE.findall(text)


def is_year(value: str) -> bool:
    return bool(re.fullmatch(r"20\d{2}", value.replace(",", "").replace("%", "")))


def chart_numeric_values(text: str) -> list[str]:
    return [value for value in numeric_values(text) if not is_year(value)]


def period_candidates(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in PERIOD_RE.finditer(text)))


def unit_candidates(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in UNIT_RE.finditer(text)))


def labels_from_text(text: str) -> list[str]:
    labels = []
    for token in re.split(r"\s{2,}|[|;/]", text):
        cleaned = NUMBER_RE.sub("", token).strip(" :-\t")
        if cleaned and len(cleaned) >= 2:
            labels.append(cleaned)
    return labels[:20]


def numeric_value(value: str) -> float | None:
    cleaned = value.replace(",", "").replace("%", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        return None


def infer_trend_from_pairs(labels: list[str], values: list[str]) -> str | None:
    if len(values) < 3:
        return None
    numeric = []
    for value in values:
        parsed = numeric_value(value)
        if parsed is None:
            return None
        numeric.append(parsed)
    deltas = [right - left for left, right in zip(numeric, numeric[1:])]
    tolerance = max(max(abs(item) for item in numeric) * 0.02, 0.01)
    if all(delta > tolerance for delta in deltas):
        return "increasing"
    if all(delta < -tolerance for delta in deltas):
        return "decreasing"
    if all(abs(delta) <= tolerance for delta in deltas):
        return "stable"
    return "mixed"


def semantic_record(
    *,
    filename: str,
    page_no: int,
    evidence_type: str,
    bbox: BBox,
    title: str | None,
    source_text: str | None,
    labels: list[str] | None = None,
    values: list[Any] | None = None,
    trend: str | None = None,
    extraction_method: str = "pdf_structure",
    confidence: float = 0.0,
    verification_status: str = "needs_review",
    **extra: Any,
) -> dict[str, Any]:
    record = {
        "filename": filename,
        "page": page_no,
        "evidence_type": evidence_type,
        "region": bbox_dict(bbox),
        "title": title,
        "labels": labels or [],
        "values": values or [],
        "trend": trend,
        "source_text": source_text,
        "extraction_method": extraction_method,
        "confidence": round(float(confidence), 3),
        "verification_status": verification_status,
        "gemini_eligible": False,
        "semantic_provider": "deterministic",
        "semantic_provider_status": "not_requested",
        "ocr_eligible": False,
        "ocr_status": "not_requested",
    }
    record.update(extra)
    return record


# --- tables -----------------------------------------------------------------

_NUM = r"[-+]?\(?[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\)?"
NUMERIC_TOKEN_RE = re.compile(rf"{_NUM}(?:[-~–]{_NUM})?")
UNIT_WORDS = frozenset({"ppt", "ppts", "pts", "bps", "x", "%"})
ROW_GAP = 34.0


def is_numeric_token(text: str) -> bool:
    token = text.strip(",;:*")
    return bool(NUMERIC_TOKEN_RE.fullmatch(token)) and not PERIOD_RE.fullmatch(token)


def visual_rows(words: list[Word]) -> list[list[Word]]:
    """Group page words into visual rows by vertical center (cells of a table
    row are often separate PDF text lines)."""
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda item: (item.cy, item.bbox[0])):
        if rows:
            row = rows[-1]
            row_cy = sum(item.cy for item in row) / len(row)
            height = max(row[0].bbox[3] - row[0].bbox[1], 4.0)
            if abs(word.cy - row_cy) <= max(3.0, height * 0.45):
                row.append(word)
                continue
        rows.append([word])
    return [sorted(row, key=lambda item: item.bbox[0]) for row in rows]


def _table_row(row: list[Word]) -> dict[str, Any] | None:
    text = " ".join(word.text for word in row)
    if text.lstrip().startswith("*") or len(text) > 140:
        return None
    numeric = [index for index, word in enumerate(row) if is_numeric_token(word.text)]
    if len(numeric) < 2:
        return None
    first = numeric[0]
    label_words = [word for word in row[:first] if not is_numeric_token(word.text)]
    label = " ".join(word.text for word in label_words).strip(" :-\t")
    if not label or PERIOD_RE.fullmatch(label):
        return None
    for word in row[first:]:
        if not is_numeric_token(word.text) and word.text.strip("()*.,").lower() not in UNIT_WORDS:
            return None  # prose such as "between 59% and 61%"
    values = []
    for index in numeric:
        text, bbox = row[index].text.strip(",;:*"), row[index].bbox
        following = row[index + 1] if index + 1 < len(row) else None
        if following is not None and following.text.strip("()*.,").lower() in UNIT_WORDS - {"%"}:
            # Keep the printed unit ("+0.9 ppts") so value_text stays exactly as shown.
            text, bbox = f"{text} {following.text.strip('*')}", union_bbox([bbox, following.bbox])
        values.append(Word(text, bbox))
    return {"label": label, "values": values, "words": row, "bbox": union_bbox([word.bbox for word in row])}


def _columns(rows: list[dict[str, Any]]) -> list[list[float]]:
    intervals = sorted([value.bbox[0], value.bbox[2]] for row in rows for value in row["values"])
    merged: list[list[float]] = []
    for x0, x1 in intervals:
        if merged and x0 <= merged[-1][1] + 2.0:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    return merged


def _header_words(words: list[Word], columns: list[list[float]], top: float, used: set[int]) -> list[Word]:
    """Words in the contiguous block of rows directly above the table that sit over a column."""
    candidates = [
        word for word in words
        if id(word) not in used and word.bbox[3] <= top + 1 and top - word.bbox[3] < 60
        and any(word.bbox[0] < x1 + 4 and word.bbox[2] > x0 - 4 for x0, x1 in columns)
    ]
    selected: list[Word] = []
    edge = top
    for row in reversed(visual_rows(candidates)):
        row_bottom = max(word.bbox[3] for word in row)
        if edge - row_bottom > (30.0 if not selected else 14.0):
            break
        selected.extend(row)
        edge = min(word.bbox[1] for word in row)
    return selected


def _column_headers(header_words: list[Word], columns: list[list[float]]) -> list[str | None]:
    headers: list[str | None] = []
    for x0, x1 in columns:
        parts = [word for word in header_words if word.bbox[0] < x1 + 4 and word.bbox[2] > x0 - 4]
        text = " ".join(word.text for word in sorted(parts, key=lambda item: (round(item.cy), item.bbox[0])))
        headers.append(text or None)
    return headers


def extract_table_evidence(filename: str, page_no: int, lines: list[TextLine]) -> list[dict[str, Any]]:
    words = [word for line in lines for word in line.words]
    rows = [item for item in (_table_row(row) for row in visual_rows(words)) if item]
    if not rows:
        return []
    groups: list[list[dict[str, Any]]] = [[rows[0]]]
    for row in rows[1:]:
        if row["bbox"][1] - groups[-1][-1]["bbox"][3] <= ROW_GAP:
            groups[-1].append(row)
        else:
            groups.append([row])

    evidence: list[dict[str, Any]] = []
    for group in groups:
        if len(group) == 1 and len(group[0]["values"]) < 3:
            continue
        bbox = union_bbox([row["bbox"] for row in group])
        used = {id(word) for row in group for word in row["words"]}
        columns = _columns(group)
        header_words = _header_words(words, columns, bbox[1], used)
        headers = _column_headers(header_words, columns)
        title_candidates = [line for line in lines if line.bbox[3] <= bbox[1] and bbox[1] - line.bbox[3] < 70]
        title = sorted(title_candidates, key=lambda line: bbox[1] - line.bbox[3])[0].text if title_candidates else None
        has_headers = bool(columns) and all(headers)
        row_values = []
        ambiguous = 0
        for row in group:
            item: dict[str, Any] = {"row_label": row["label"], "values": [value.text for value in row["values"]]}
            slots = [
                next((index for index, (x0, x1) in enumerate(columns) if x0 - 1 <= value.cx <= x1 + 1), None)
                for value in row["values"]
            ]
            if None in slots or len(set(slots)) != len(slots):
                ambiguous += 1
            elif has_headers:
                item["cells"] = [
                    {"column": headers[slot], "value_text": value.text} for slot, value in zip(slots, row["values"])
                ]
            row_values.append(item)
        if ambiguous:
            mapping_status = "partial" if ambiguous < len(group) else "uncertain"
        else:
            mapping_status = "aligned" if has_headers else "row_only"
        if header_words:
            bbox = union_bbox([bbox, union_bbox([word.bbox for word in header_words])])
        status = "needs_review" if mapping_status in {"partial", "uncertain"} else "partially_verified"
        source_text = "\n".join(
            ([" | ".join(header or "" for header in headers)] if has_headers else [])
            + [" ".join(word.text for word in row["words"]) for row in group]
        )
        evidence.append(semantic_record(
            filename=filename,
            page_no=page_no,
            evidence_type="table",
            bbox=bbox,
            title=title,
            source_text=source_text,
            labels=[row["label"] for row in group],
            values=row_values,
            extraction_method="pdf_text_layout",
            confidence=(0.82 if mapping_status == "aligned" else 0.74 if len(group) > 1 else 0.62),
            verification_status=status,
            columns=headers if has_headers else [],
            mapping_status=mapping_status,
            gemini_eligible=mapping_status in {"partial", "uncertain"},
        ))
    return evidence[:12]


# --- visual regions -----------------------------------------------------------

def _primitive_key(bbox: BBox) -> tuple[int, ...]:
    return tuple(int(round(value / 2.0)) for value in bbox)


def visual_primitives(page: Any) -> list[Primitive]:
    page_area = float(page.rect.width * page.rect.height) or 1.0
    primitives: list[Primitive] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is None:
            continue
        bbox = rect_tuple(rect)
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if width <= 0 and height <= 0:
            continue
        thin = min(width, height) < 2.0 or (max(width, height) / max(min(width, height), 0.1)) > 40
        if bbox_area(bbox) / page_area >= BACKGROUND_AREA_RATIO:
            continue
        primitives.append(Primitive(bbox=bbox, kind="drawing", thin=thin))
    for image in page.get_image_info(xrefs=True):
        raw = image.get("bbox")
        if raw is None:
            continue
        bbox = tuple(float(v) for v in raw)
        if bbox_area(bbox) <= 0 or bbox_area(bbox) / page_area >= BACKGROUND_AREA_RATIO:
            continue
        primitives.append(Primitive(bbox=bbox, kind="image"))
    return primitives


def visual_bboxes(page: Any) -> tuple[list[BBox], list[BBox]]:
    primitives = visual_primitives(page)
    return (
        [item.bbox for item in primitives if item.kind == "drawing"],
        [item.bbox for item in primitives if item.kind == "image"],
    )


def repeated_primitive_keys(document: Any) -> set[tuple[int, ...]]:
    """Visual elements at the same position on most pages (logos, footer marks)."""
    page_count = len(document)
    if page_count < 2:
        return set()
    counts: dict[tuple[int, ...], int] = {}
    for page in document:
        page_area = float(page.rect.width * page.rect.height) or 1.0
        keys = {
            _primitive_key(item.bbox) for item in visual_primitives(page)
            if bbox_area(item.bbox) / page_area < 0.1 or item.thin
        }
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    threshold = max(2, int(page_count * REPEAT_PAGE_SHARE + 0.999))
    return {key for key, count in counts.items() if count >= threshold}


def _drop_panels(primitives: list[Primitive], page_area: float) -> list[Primitive]:
    """Large filled frames that merely hold other content are layout, not evidence."""
    kept = []
    for item in primitives:
        if item.kind == "drawing" and bbox_area(item.bbox) / page_area >= PANEL_AREA_RATIO:
            inner = sum(1 for other in primitives if other is not item and contains(item.bbox, other.bbox, 2))
            if inner >= 2:
                continue
        kept.append(item)
    return kept


def _is_isolated_separator(item: Primitive, primitives: list[Primitive], page_width: float) -> bool:
    if not item.thin or item.kind != "drawing":
        return False
    if (item.bbox[2] - item.bbox[0]) < page_width * 0.45 and (item.bbox[3] - item.bbox[1]) < 60:
        return False
    return not any(
        other is not item and intersects_or_near(item.bbox, other.bbox, margin=2) for other in primitives
    )


def cluster_primitives(primitives: list[Primitive], gap: float = CLUSTER_GAP) -> list[list[Primitive]]:
    parent = list(range(len(primitives)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def linked(left: Primitive, right: Primitive) -> bool:
        if left.kind == "image" and right.kind == "image":
            # Adjacent pictures are separate figures unless one mostly covers the other.
            small, large = sorted((left.bbox, right.bbox), key=bbox_area)
            return overlap_ratio(small, large) >= 0.5
        return intersects_or_near(left.bbox, right.bbox, margin=gap)

    for i, left in enumerate(primitives):
        for j in range(i + 1, len(primitives)):
            if linked(left, primitives[j]):
                parent[find(i)] = find(j)
    groups: dict[int, list[Primitive]] = {}
    for index, item in enumerate(primitives):
        groups.setdefault(find(index), []).append(item)
    clusters = list(groups.values())
    return _merge_aligned_siblings(clusters)


def _merge_aligned_siblings(clusters: list[list[Primitive]]) -> list[list[Primitive]]:
    """Bars of one chart often float apart but share a baseline or a left edge."""
    changed = True
    while changed:
        changed = False
        for i in range(len(clusters)):
            a = union_bbox([item.bbox for item in clusters[i]])
            for j in range(i + 1, len(clusters)):
                b = union_bbox([item.bbox for item in clusters[j]])
                width = max(a[2] - a[0], b[2] - b[0], 1.0)
                height = max(a[3] - a[1], b[3] - b[1], 1.0)
                horizontal_gap = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
                vertical_gap = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
                same_baseline = abs(a[3] - b[3]) <= 2.0 and horizontal_gap <= max(3 * width, 60)
                same_left = abs(a[0] - b[0]) <= 2.0 and vertical_gap <= max(3 * height, 40)
                similar = min(a[2] - a[0], b[2] - b[0]) / width > 0.5 or min(a[3] - a[1], b[3] - b[1]) / height > 0.5
                if similar and (same_baseline or same_left) and not all(p.thin for p in clusters[i] + clusters[j]):
                    clusters[i] = clusters[i] + clusters[j]
                    del clusters[j]
                    changed = True
                    break
            if changed:
                break
    return clusters


def _region_words(lines: list[TextLine], bbox: BBox) -> list[Word]:
    # Data labels and axis periods usually sit just above or below the marks.
    x0, y0, x1, y1 = bbox[0] - CONTEXT_MARGIN, bbox[1] - 2 * CONTEXT_MARGIN, bbox[2] + CONTEXT_MARGIN, bbox[3] + 2 * CONTEXT_MARGIN
    return [word for line in lines for word in line.words if x0 <= word.cx <= x1 and y0 <= word.cy <= y1]


def _caption_above(lines: list[TextLine], bbox: BBox) -> str | None:
    above = [line for line in lines if line.bbox[3] <= bbox[1] + 2 and bbox[1] - line.bbox[3] < 50
             and line.bbox[2] > bbox[0] and line.bbox[0] < bbox[2]
             and NUMBER_RE.sub("", PERIOD_RE.sub("", line.text)).strip(" %()+-.,")]
    if not above:
        return None
    return sorted(above, key=lambda line: bbox[1] - line.bbox[3])[0].text


def _aligned_pairs(words: list[Word]) -> tuple[list[str], list[str], str]:
    """Pair period labels with the value in the same column (x-aligned)."""
    periods = [Word(w.text.strip(",;:"), w.bbox) for w in words if PERIOD_RE.fullmatch(w.text.strip(",;:"))]
    values = [
        Word(w.text.strip(",;:"), w.bbox) for w in words
        if NUMBER_RE.fullmatch(w.text.strip(",;:")) and not is_year(w.text.strip(",;:"))
    ]
    periods.sort(key=lambda w: w.cx)
    values.sort(key=lambda w: w.cx)
    if len(periods) < 2 or len(periods) != len(values):
        return [p.text for p in periods], [v.text for v in values], "candidates_only"
    centers = [p.cx for p in periods]
    spacing = min((b - a for a, b in zip(centers, centers[1:])), default=100.0)
    tolerance = max(spacing / 2, 10.0)
    if all(abs(p.cx - v.cx) <= tolerance for p, v in zip(periods, values)):
        return [p.text for p in periods], [v.text for v in values], "aligned"
    return [p.text for p in periods], [v.text for v in values], "candidates_only"


def _band_decorative(bbox: BBox, page_height: float, area_ratio: float) -> bool:
    return area_ratio < 0.05 and (bbox[1] >= page_height * 0.9 or bbox[3] <= page_height * 0.1)


def extract_visual_evidence(
    filename: str,
    page_no: int,
    page: Any,
    lines: list[TextLine],
    *,
    repeated: set[tuple[int, ...]] | None = None,
    contexts: list[tuple[dict[str, Any], RegionContext]] | None = None,
    tables: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    page_area = float(page.rect.width * page.rect.height) or 1.0
    page_width, page_height = float(page.rect.width), float(page.rect.height)
    primitives = visual_primitives(page)
    if not primitives:
        return []
    repeated = repeated or set()
    for item in primitives:
        item.repeated = _primitive_key(item.bbox) in repeated
    primitives = _drop_panels(primitives, page_area)
    separators = [item for item in primitives if _is_isolated_separator(item, primitives, page_width)]
    fixed = [item for item in primitives if item.repeated and item not in separators]
    content = [item for item in primitives if item not in separators and item not in fixed]

    title = page_title(lines)
    page_text = " ".join(line.text for line in lines)
    results: list[dict[str, Any]] = []

    def decorative(bbox: BBox, reason: str, confidence: float, status: str) -> None:
        results.append(semantic_record(
            filename=filename, page_no=page_no, evidence_type="decorative", bbox=bbox, title=title,
            source_text=None, extraction_method="pdf_visual_structure", confidence=confidence,
            verification_status=status, decorative_reason=reason,
        ))

    if fixed:
        decorative(union_bbox([item.bbox for item in fixed]), "repeated_layout_element", 0.9, "verified")
    if separators:
        decorative(union_bbox([item.bbox for item in separators]), "separator", 0.88, "verified")

    table_boxes = [
        (table["region"]["x0"], table["region"]["y0"], table["region"]["x1"], table["region"]["y1"])
        for table in tables or []
    ]
    for cluster in cluster_primitives(content)[:40]:
        bbox = union_bbox([item.bbox for item in cluster])
        area_ratio = bbox_area(bbox) / page_area
        drawings = [item for item in cluster if item.kind == "drawing"]
        images = [item for item in cluster if item.kind == "image"]
        words = _region_words(lines, bbox)
        region_text = " ".join(word.text for word in sorted(words, key=lambda w: (round(w.cy / 6), w.bbox[0])))
        caption = _caption_above(lines, bbox)
        numbers = chart_numeric_values(region_text)
        periods = period_candidates(region_text)
        units = unit_candidates(region_text)
        context_text = " ".join(filter(None, [title, caption, region_text]))

        if _band_decorative(bbox, page_height, area_ratio) and len(numbers) < 2:
            decorative(bbox, "header_footer_band", 0.84, "verified")
            continue
        if all(item.thin for item in cluster) and (
            (len(cluster) <= 2 and len(numbers) < 2) or area_ratio < 0.005
        ):
            decorative(bbox, "separator", 0.82, "verified")
            continue
        if area_ratio < DECORATIVE_AREA_RATIO and len(numbers) < 2:
            decorative(bbox, "small_icon", 0.8, "verified")
            continue
        absorbed = False
        for table, table_box in zip(tables or [], table_boxes):
            if not images and (overlap_ratio(table_box, bbox) >= 0.6 or overlap_ratio(bbox, table_box) >= 0.6):
                # Ruling, shading, or highlight boxes of a table already captured from its text grid.
                table["ruled"] = True
                absorbed = True
        if absorbed:
            continue
        word_area = sum(bbox_area(word.bbox) for word in words if contains(bbox, word.bbox, tolerance=2))
        if not images and len(drawings) <= 6 and len(words) >= 4 and word_area / (bbox_area(bbox) or 1) >= 0.2:
            # Highlight or underline boxes around prose: the evidence is the selectable text.
            inside = " ".join(word.text for word in words if contains(bbox, word.bbox, tolerance=2))
            results.append(semantic_record(
                filename=filename, page_no=page_no, evidence_type="text", bbox=bbox, title=title,
                source_text=inside or region_text, extraction_method="pdf_text_layout", confidence=0.84,
                verification_status="verified", text_role="emphasized_text", numeric_candidates=numbers[:40],
            ))
            continue

        base = dict(
            filename=filename, page_no=page_no, bbox=bbox, title=caption or title,
            source_text=region_text or None, extraction_method="pdf_visual_structure",
            numeric_candidates=numbers[:40], period_candidates=periods[:20], unit_candidates=units[:10],
            primitive_count={"drawings": len(drawings), "images": len(images)},
            region_area_ratio=round(area_ratio, 4),
        )
        chart_like = (
            (len(drawings) >= 3 or (images and area_ratio >= 0.05))
            and area_ratio >= MEANINGFUL_AREA_RATIO
            and len(numbers) >= 2
            and (len(periods) >= 2 or FINANCIAL_CONTEXT_RE.search(context_text))
        )
        if chart_like:
            labels, values, mapping = _aligned_pairs(words)
            if mapping == "aligned":
                pairs = [{"label": label, "value_text": value} for label, value in zip(labels, values)]
                trend = infer_trend_from_pairs(labels, values)
            else:
                pairs = []  # unpaired numbers stay in numeric_candidates, not asserted as chart values
                trend = None
            record = semantic_record(
                evidence_type="chart", labels=labels or labels_from_text(region_text), values=pairs,
                trend=trend, confidence=0.72 if mapping == "aligned" else 0.6,
                verification_status="partially_verified" if mapping == "aligned" and trend else "needs_review",
                chart_type=None, unit=units[0] if len(units) == 1 else None,
                is_forecast=any(re.search(r"\d[EF]$", p, re.I) for p in periods) or None,
                mapping_status=mapping, trend_source="deterministic" if trend else None,
                gemini_eligible=not (mapping == "aligned" and trend),
                **base,
            )
        elif images and not drawings and len(numbers) == 0 and area_ratio >= MEANINGFUL_AREA_RATIO:
            record = semantic_record(
                evidence_type="image", confidence=0.58, verification_status="needs_review",
                gemini_eligible=area_ratio >= 0.05, **base,
            )
        elif area_ratio < MEANINGFUL_AREA_RATIO and len(numbers) <= 1:
            decorative(bbox, "minor_graphic", 0.64, "partially_verified")
            continue
        else:
            record = semantic_record(
                evidence_type="unknown", confidence=0.35, verification_status="needs_review",
                gemini_eligible=True, **base,
            )
        record["ocr_eligible"] = ocr_eligible(record, images, words)
        results.append(record)
        if contexts is not None and record["gemini_eligible"]:
            contexts.append((record, RegionContext(
                page_no=page_no, bbox=bbox, page_title=title, caption=caption,
                region_text=region_text, page_text=page_text, words=words,
            )))
    return results


def extract_text_evidence(filename: str, page_no: int, lines: list[TextLine]) -> list[dict[str, Any]]:
    if not lines:
        return []
    title = page_title(lines)
    first_lines = lines[: min(6, len(lines))]
    bbox = union_bbox([line.bbox for line in first_lines])
    source_text = " ".join(line.text for line in first_lines)
    return [semantic_record(
        filename=filename,
        page_no=page_no,
        evidence_type="text",
        bbox=bbox,
        title=title,
        source_text=source_text,
        labels=[title] if title else [],
        values=[],
        extraction_method="pdf_text_layout",
        confidence=0.86,
        verification_status="verified",
    )]


def extract_semantic_evidence(
    raw: bytes,
    *,
    filename: str,
    interpreter: RegionInterpreter | None = None,
    region_ocr: RegionOcr | None = None,
) -> list[list[dict[str, Any]]]:
    fitz = load_pymupdf()
    document = fitz.open(stream=raw, filetype="pdf")
    repeated = repeated_primitive_keys(document)
    pages: list[list[dict[str, Any]]] = []
    for index, page in enumerate(document):
        page_no = index + 1
        lines = text_lines(page)
        contexts: list[tuple[dict[str, Any], RegionContext]] = []
        semantic = []
        semantic.extend(extract_text_evidence(filename, page_no, lines))
        tables = extract_table_evidence(filename, page_no, lines)
        semantic.extend(tables)
        semantic.extend(extract_visual_evidence(
            filename, page_no, page, lines, repeated=repeated, contexts=contexts, tables=tables,
        ))
        for table in tables:
            if table["gemini_eligible"]:
                contexts.append((table, RegionContext(
                    page_no=page_no, bbox=(table["region"]["x0"], table["region"]["y0"],
                                           table["region"]["x1"], table["region"]["y1"]),
                    page_title=page_title(lines), caption=table["title"], region_text=table["source_text"] or "",
                    page_text=" ".join(line.text for line in lines),
                    words=[word for line in lines for word in line.words],
                )))
        for number, record in enumerate(semantic, start=1):
            record["region_id"] = f"{filename}#p{page_no}r{number}"
        # OCR first so its tokens reach both the Gemini request and the validator.
        if region_ocr is not None and contexts:
            region_ocr.process_page(page, [item for item in contexts if item[0].get("ocr_eligible")])
        if interpreter is not None and contexts:
            interpreter.interpret_page(page, contexts)
        pages.append(semantic)
    return pages
