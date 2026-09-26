from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?(?![A-Za-z0-9])")
PERIOD_RE = re.compile(r"\b(?:20\d{2}|Q[1-4]|[12]Q\d{2}|FY\d{2}|FY20\d{2}|20\d{2}E?)\b", re.I)
FINANCIAL_CONTEXT_RE = re.compile(
    r"\b(?:revenue|sales|margin|profit|income|eps|cash|capex|inventory|asset|liabilit|equity|"
    r"shipment|capacity|wafer|node|market|share|growth|quarter|outlook)\b",
    re.I,
)


def load_pymupdf():
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        import fitz

        return fitz


@dataclass(frozen=True)
class TextLine:
    text: str
    bbox: tuple[float, float, float, float]


def bbox_dict(bbox: tuple[float, float, float, float]) -> dict[str, float]:
    return {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]}


def union_bbox(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def rect_tuple(rect: Any) -> tuple[float, float, float, float]:
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def bbox_area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def intersects_or_near(a: tuple[float, float, float, float], b: tuple[float, float, float, float], margin: float = 24) -> bool:
    return not (a[2] + margin < b[0] or b[2] + margin < a[0] or a[3] + margin < b[1] or b[3] + margin < a[1])


def text_lines(page: Any) -> list[TextLine]:
    payload = page.get_text("dict")
    lines: list[TextLine] = []
    for block in payload.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            parts = [span.get("text", "") for span in line.get("spans", [])]
            text = " ".join("".join(parts).split())
            if text:
                lines.append(TextLine(text=text, bbox=tuple(float(v) for v in line.get("bbox", block.get("bbox")))))
    return lines


def page_title(lines: list[TextLine]) -> str | None:
    if not lines:
        return None
    top = sorted(lines, key=lambda line: (line.bbox[1], line.bbox[0]))[:5]
    candidates = [line.text for line in top if len(line.text) >= 3 and not NUMBER_RE.fullmatch(line.text)]
    return candidates[0] if candidates else top[0].text


def nearby_text(lines: list[TextLine], bbox: tuple[float, float, float, float], *, limit: int = 8) -> str | None:
    selected = [line.text for line in lines if intersects_or_near(line.bbox, bbox, margin=48)]
    if not selected:
        selected = [line.text for line in lines[:limit]]
    return " ".join(selected[:limit]) or None


def numeric_values(text: str) -> list[str]:
    return NUMBER_RE.findall(text)


def chart_numeric_values(text: str) -> list[str]:
    values = []
    for value in numeric_values(text):
        normalized = value.replace(",", "").replace("%", "")
        if re.fullmatch(r"20\d{2}", normalized):
            continue
        values.append(value)
    return values


def labels_from_text(text: str) -> list[str]:
    labels = []
    for token in re.split(r"\s{2,}|[|;/]", text):
        cleaned = NUMBER_RE.sub("", token).strip(" :-\t")
        if cleaned and len(cleaned) >= 2:
            labels.append(cleaned)
    return labels[:20]


def infer_trend_from_pairs(labels: list[str], values: list[str]) -> str | None:
    if len(values) < 3:
        return None
    numeric = []
    for value in values:
        try:
            numeric.append(float(value.replace(",", "").replace("%", "")))
        except ValueError:
            return None
    if len(numeric) < 2:
        return None
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
    bbox: tuple[float, float, float, float],
    title: str | None,
    source_text: str | None,
    labels: list[str] | None = None,
    values: list[Any] | None = None,
    trend: str | None = None,
    extraction_method: str = "pdf_structure",
    confidence: float = 0.0,
    verification_status: str = "needs_review",
) -> dict[str, Any]:
    return {
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
    }


def extract_table_evidence(filename: str, page_no: int, lines: list[TextLine]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    rows = []
    for line in lines:
        if line.text.lstrip().startswith("*"):
            continue
        if len(line.text) > 90:
            continue
        values = numeric_values(line.text)
        if len(values) < 2:
            continue
        label = NUMBER_RE.split(line.text, maxsplit=1)[0].strip(" :-\t")
        if not label:
            continue
        rows.append({"line": line, "label": label, "values": values})
    if not rows:
        return evidence

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    previous_y: float | None = None
    for row in rows:
        y = row["line"].bbox[1]
        if previous_y is None or y - previous_y <= 34:
            current.append(row)
        else:
            if current:
                groups.append(current)
            current = [row]
        previous_y = y
    if current:
        groups.append(current)

    for group in groups:
        if len(group) == 1 and len(group[0]["values"]) < 3:
            continue
        boxes = [item["line"].bbox for item in group]
        bbox = union_bbox(boxes)
        title = None
        title_candidates = [line for line in lines if line.bbox[3] <= bbox[1] and bbox[1] - line.bbox[3] < 70]
        if title_candidates:
            title = sorted(title_candidates, key=lambda line: bbox[1] - line.bbox[3])[0].text
        row_values = [
            {"row_label": item["label"], "values": item["values"]}
            for item in group
        ]
        source_text = "\n".join(item["line"].text for item in group)
        labels = [item["label"] for item in group]
        evidence.append(semantic_record(
            filename=filename,
            page_no=page_no,
            evidence_type="table",
            bbox=bbox,
            title=title,
            source_text=source_text,
            labels=labels,
            values=row_values,
            extraction_method="pdf_text_layout",
            confidence=0.74 if len(group) > 1 else 0.62,
            verification_status="partially_verified",
        ))
    return evidence[:12]


def visual_bboxes(page: Any) -> tuple[list[tuple[float, float, float, float]], list[tuple[float, float, float, float]]]:
    drawing_boxes = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is not None and rect.width > 0 and rect.height > 0:
            drawing_boxes.append(rect_tuple(rect))
    image_boxes = []
    for image in page.get_image_info(xrefs=True):
        bbox = image.get("bbox")
        if bbox is not None:
            image_boxes.append(tuple(float(v) for v in bbox))
    return drawing_boxes, image_boxes


def cluster_visual_boxes(boxes: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    clusters: list[list[tuple[float, float, float, float]]] = []
    for box in sorted(boxes, key=lambda item: (item[1], item[0])):
        placed = False
        for cluster in clusters:
            if intersects_or_near(union_bbox(cluster), box, margin=30):
                cluster.append(box)
                placed = True
                break
        if not placed:
            clusters.append([box])
    return [union_bbox(cluster) for cluster in clusters]


def classify_visual_region(
    *,
    page_area: float,
    bbox: tuple[float, float, float, float],
    lines: list[TextLine],
    has_image: bool,
    has_drawing: bool,
) -> tuple[str, float, str]:
    area_ratio = bbox_area(bbox) / page_area if page_area else 0
    context = nearby_text(lines, bbox) or ""
    numbers = chart_numeric_values(context)
    periods = PERIOD_RE.findall(context)
    text_len = len(context)
    if area_ratio < 0.015 and len(numbers) == 0:
        return "decorative", 0.82, "verified"
    if has_drawing and len(numbers) >= 2 and FINANCIAL_CONTEXT_RE.search(context) and area_ratio >= 0.04:
        return "chart", 0.66, "needs_review"
    if has_image and len(numbers) == 0 and text_len < 80:
        return "image", 0.58, "needs_review"
    if area_ratio < 0.04 and len(numbers) <= 1:
        return "decorative", 0.64, "partially_verified"
    return "unknown", 0.35, "needs_review"


def extract_visual_evidence(filename: str, page_no: int, page: Any, lines: list[TextLine]) -> list[dict[str, Any]]:
    drawings, images = visual_bboxes(page)
    if not drawings and not images:
        return []
    page_area = float(page.rect.width * page.rect.height)
    page_label = page_title(lines)
    results: list[dict[str, Any]] = []
    if len(drawings) >= 2:
        drawing_region = union_bbox(drawings)
        context = nearby_text(lines, drawing_region)
        values = chart_numeric_values(context or "")
        labels = labels_from_text(context or "")
        periods = PERIOD_RE.findall(context or "")
        if (
            len(values) >= 2
            and bbox_area(drawing_region) / page_area >= 0.04
            and FINANCIAL_CONTEXT_RE.search(context or "")
        ):
            trend = infer_trend_from_pairs(labels, values)
            results.append(semantic_record(
                filename=filename,
                page_no=page_no,
                evidence_type="chart",
                bbox=drawing_region,
                title=page_label,
                source_text=context,
                labels=labels,
                values=[{"value_text": value} for value in values],
                trend=trend,
                extraction_method="pdf_visual_structure",
                confidence=0.68,
                verification_status="partially_verified" if trend else "needs_review",
            ))
            return results

    regions = cluster_visual_boxes(drawings + images)
    for bbox in regions[:30]:
        has_image = any(intersects_or_near(bbox, box, margin=2) for box in images)
        has_drawing = any(intersects_or_near(bbox, box, margin=2) for box in drawings)
        evidence_type, confidence, status = classify_visual_region(
            page_area=page_area,
            bbox=bbox,
            lines=lines,
            has_image=has_image,
            has_drawing=has_drawing,
        )
        context = nearby_text(lines, bbox)
        values = chart_numeric_values(context or "") if evidence_type == "chart" else numeric_values(context or "")
        labels = labels_from_text(context or "")
        trend = infer_trend_from_pairs(labels, values) if evidence_type == "chart" else None
        results.append(semantic_record(
            filename=filename,
            page_no=page_no,
            evidence_type=evidence_type,
            bbox=bbox,
            title=page_label,
            source_text=context,
            labels=labels,
            values=[{"value_text": value} for value in values],
            trend=trend,
            extraction_method="pdf_visual_structure",
            confidence=confidence,
            verification_status=status if trend is None else "partially_verified",
        ))
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


def extract_semantic_evidence(raw: bytes, *, filename: str) -> list[list[dict[str, Any]]]:
    fitz = load_pymupdf()
    document = fitz.open(stream=raw, filetype="pdf")
    pages: list[list[dict[str, Any]]] = []
    for index, page in enumerate(document):
        page_no = index + 1
        lines = text_lines(page)
        semantic = []
        semantic.extend(extract_text_evidence(filename, page_no, lines))
        semantic.extend(extract_table_evidence(filename, page_no, lines))
        semantic.extend(extract_visual_evidence(filename, page_no, page, lines))
        pages.append(semantic)
    return pages
