from pathlib import Path
import re
from textwrap import wrap
from typing import Any, Dict, Iterable, List

import fitz

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 48
LINE_HEIGHT = 14
FONT = "helv"
INK = (0.12, 0.16, 0.20)
MUTED = (0.42, 0.48, 0.55)
BLUE = (0.10, 0.28, 0.54)
GREEN = (0.07, 0.45, 0.28)
LIGHT_BG = (0.94, 0.97, 0.99)
BORDER = (0.78, 0.84, 0.90)


def build_case_report_pdf(case: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    case_id = case.get("case_id", "case")
    output_path = output_dir / f"{_safe_slug(case)}_{str(case_id)[:8]}_case_report.pdf"
    doc = fitz.open()
    state = {"page": doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT), "y": MARGIN}
    _header(state, case)
    _metrics(state, case)
    _section(state, "Extracted Fields")
    _field_rows(state, case.get("extraction", {}).get("fields", {}))
    _section(state, "Structured Metrics")
    _metric_table(state, case.get("extraction", {}).get("period_metrics", []))
    _section(state, "Visual Markers")
    _marker_rows(state, case.get("extraction", {}))
    _section(state, "Review Checklist")
    _checklist(state, case.get("review_checklist", {}).get("checks", []))
    _section(state, "Generated Report")
    _paragraph(state, case.get("generated_report", ""))
    _footer(state)
    doc.save(output_path)
    doc.close()
    return output_path


def build_generated_report_pdf(case: Dict[str, Any], report_text: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    case_id = case.get("case_id", "case")
    output_path = output_dir / f"{_safe_slug(case)}_{str(case_id)[:8]}_qwen_report.pdf"
    doc = fitz.open()
    state = {"page": doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT), "y": MARGIN}
    _header(state, case, title="Generated Document Report")
    _metrics(state, case)
    _section(state, "Verified Values")
    _key_value_rows(state, _verified_rows(case))
    _section(state, "Generated Report")
    _markdown_report(state, report_text)
    _footer(state)
    doc.save(output_path)
    doc.close()
    return output_path


def _new_page(state: Dict[str, Any]) -> None:
    doc = state["page"].parent
    state["page"] = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    state["y"] = MARGIN


def _ensure_space(state: Dict[str, Any], height: float) -> None:
    if state["y"] + height > PAGE_HEIGHT - MARGIN:
        _footer(state)
        _new_page(state)


def _text(state: Dict[str, Any], text: Any, x: float, y: float, size: float = 10, color=INK, bold: bool = False) -> None:
    state["page"].insert_text((x, y), str(text), fontsize=size, fontname=FONT, color=color)


def _header(state: Dict[str, Any], case: Dict[str, Any], title: str = "Document Case Report") -> None:
    page = state["page"]
    owner = case.get("metadata", {}).get("owner") or case.get("client_info", {}).get("company") or "DocumentOps"
    page.draw_rect(fitz.Rect(0, 0, PAGE_WIDTH, 118), color=BLUE, fill=BLUE)
    page.draw_rect(fitz.Rect(MARGIN, 28, MARGIN + 54, 82), color=(1, 1, 1), fill=(1, 1, 1))
    _text(state, "DOC", MARGIN + 13, 51, size=11, color=BLUE, bold=True)
    _text(state, "OPS", MARGIN + 14, 67, size=11, color=GREEN, bold=True)
    _text(state, title, MARGIN + 72, 45, size=20, color=(1, 1, 1), bold=True)
    _text(state, _clip(owner, 70), MARGIN + 72, 68, size=12, color=(0.90, 0.95, 1), bold=True)
    _text(state, _clip(case.get("source_filename", ""), 86), MARGIN + 72, 88, size=9, color=(0.86, 0.91, 0.96))
    state["y"] = 145


def _metrics(state: Dict[str, Any], case: Dict[str, Any]) -> None:
    summary = case.get("case_summary", {})
    metrics = [
        ("Type", _humanize(summary.get("document_type", "unknown"))),
        ("Completeness", f"{float(summary.get('data_completeness') or 0):.0%}"),
        ("Risk", _humanize(case.get("review_checklist", {}).get("risk_level", "unknown"))),
        ("Markers", summary.get("visual_markers_found", 0)),
    ]
    box_w = (PAGE_WIDTH - 2 * MARGIN - 18) / 4
    y = state["y"]
    for idx, (label, value) in enumerate(metrics):
        x = MARGIN + idx * (box_w + 6)
        state["page"].draw_rect(fitz.Rect(x, y, x + box_w, y + 58), color=BORDER, fill=LIGHT_BG)
        _text(state, label, x + 8, y + 19, size=8, color=MUTED, bold=True)
        _text(state, value, x + 8, y + 42, size=11, color=INK, bold=True)
    state["y"] += 82


def _section(state: Dict[str, Any], title: str) -> None:
    _ensure_space(state, 34)
    _text(state, title, MARGIN, state["y"], size=13, color=BLUE, bold=True)
    state["y"] += 18
    state["page"].draw_line((MARGIN, state["y"]), (PAGE_WIDTH - MARGIN, state["y"]), color=BORDER)
    state["y"] += 14


def _paragraph(state: Dict[str, Any], text: str) -> None:
    for line in _wrap(text, 88):
        _ensure_space(state, LINE_HEIGHT + 2)
        _text(state, line, MARGIN, state["y"], size=9, color=INK)
        state["y"] += LINE_HEIGHT
    state["y"] += 8


def _markdown_report(state: Dict[str, Any], text: str) -> None:
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            state["y"] += 6
            continue
        if line.startswith("###"):
            _ensure_space(state, 28)
            _text(state, line.lstrip("# ").strip(), MARGIN, state["y"], size=11, color=BLUE, bold=True)
            state["y"] += 17
            continue
        if line.startswith("##"):
            _section(state, line.lstrip("# ").strip())
            continue
        if line.startswith("#"):
            _ensure_space(state, 30)
            _text(state, line.lstrip("# ").strip(), MARGIN, state["y"], size=13, color=BLUE, bold=True)
            state["y"] += 18
            continue
        bullet = line.startswith(("- ", "* "))
        if bullet:
            line = line[2:].strip()
        prefix = "- " if bullet else ""
        for wrapped in _wrap(prefix + line, 88):
            _ensure_space(state, LINE_HEIGHT + 2)
            _text(state, wrapped, MARGIN, state["y"], size=9, color=INK)
            state["y"] += LINE_HEIGHT
    state["y"] += 8


def _field_rows(state: Dict[str, Any], fields: Dict[str, Any]) -> None:
    rows = []
    for name, payload in fields.items():
        if not isinstance(payload, dict):
            payload = {"value": payload, "confidence": 0}
        rows.append((_humanize(name), payload.get("value", ""), payload.get("confidence", 0)))
    _key_value_rows(state, [(name, f"{value} (confidence {confidence})") for name, value, confidence in rows])


def _key_value_rows(state: Dict[str, Any], rows: Iterable[tuple]) -> None:
    for label, value in rows:
        _ensure_space(state, 20)
        _text(state, label, MARGIN, state["y"], size=9, color=MUTED, bold=True)
        _text(state, value, MARGIN + 190, state["y"], size=9, color=INK)
        state["y"] += 18
    state["y"] += 6


def _metric_table(state: Dict[str, Any], metrics: List[Dict[str, Any]]) -> None:
    if not metrics:
        _paragraph(state, "No structured period metrics were extracted.")
        return
    headers = ["Period", "Value", "Unit", "Source"]
    col_w = (PAGE_WIDTH - 2 * MARGIN) / 4
    for idx, header in enumerate(headers):
        _text(state, header, MARGIN + idx * col_w, state["y"], size=8, color=MUTED, bold=True)
    state["y"] += 16
    for row in metrics[:18]:
        _ensure_space(state, 18)
        values = [_humanize(row.get("period", "")), _num(row.get("value")), _humanize(row.get("unit", "")), _humanize(row.get("source", ""))]
        for idx, value in enumerate(values):
            _text(state, value, MARGIN + idx * col_w, state["y"], size=8.5, color=INK)
        state["y"] += 16
    state["y"] += 8


def _marker_rows(state: Dict[str, Any], extraction: Dict[str, Any]) -> None:
    marker_types = extraction.get("visual_marker_types", {}) or {}
    if not marker_types:
        _paragraph(state, "No stamp, signature, or logo candidates were detected.")
        return
    rows = [(_humanize(kind), count) for kind, count in sorted(marker_types.items())]
    _key_value_rows(state, rows)


def _checklist(state: Dict[str, Any], checks: List[Dict[str, Any]]) -> None:
    for check in checks:
        if not isinstance(check, dict):
            check = {"name": str(check), "status": "needs_review", "evidence": "Imported legacy check format"}
        status = check.get("status", "needs_review")
        mark = "PASS" if status == "pass" else "REVIEW"
        color = GREEN if status == "pass" else (0.72, 0.35, 0.05)
        _ensure_space(state, 28)
        _text(state, mark, MARGIN, state["y"], size=8, color=color, bold=True)
        _text(state, _humanize(check.get("name", "check")), MARGIN + 70, state["y"], size=9, color=INK, bold=True)
        state["y"] += 13
        _text(state, check.get("evidence", ""), MARGIN + 70, state["y"], size=8, color=MUTED)
        state["y"] += 17


def _footer(state: Dict[str, Any]) -> None:
    page = state["page"]
    page.draw_line((MARGIN, PAGE_HEIGHT - 38), (PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 38), color=BORDER)
    page.insert_text((MARGIN, PAGE_HEIGHT - 22), "Generated by Local DocumentOps Automation", fontsize=8, fontname=FONT, color=MUTED)


def _verified_rows(case: Dict[str, Any]) -> List[tuple]:
    extraction = case.get("extraction", {})
    fields = extraction.get("fields", {})
    summary = case.get("case_summary", {})
    checklist = case.get("review_checklist", {})
    return [
        ("Source file", case.get("source_filename", "")),
        ("Document type", _humanize(summary.get("document_type") or extraction.get("document_type", "unknown"))),
        ("Counterparty", fields.get("counterparty", {}).get("value")),
        ("Document ID", fields.get("document_id_number", {}).get("value")),
        ("Document date", fields.get("document_date", {}).get("value")),
        ("Service / site", fields.get("service_or_site", {}).get("value")),
        ("Category / rate", fields.get("category_or_rate", {}).get("value")),
        ("Total amount", _num(summary.get("total_amount"))),
        ("Period values", summary.get("period_metric_count", 0)),
        ("Period total", _num(summary.get("period_metric_total"))),
        ("Risk", _humanize(checklist.get("risk_level", "unknown"))),
    ]


def _safe_slug(case: Dict[str, Any]) -> str:
    metadata = case.get("metadata", {}) or {}
    title = metadata.get("display_title") or case.get("source_filename") or "document_case"
    title = Path(str(title)).stem
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").lower()
    return (slug[:42].strip("_") or "document_case")


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[: max(limit - 3, 0)]}..."


def _humanize(value: Any) -> str:
    text = str(value or "")
    overrides = {"kwh": "kWh", "mwh": "MWh", "wh": "Wh"}
    if text.lower() in overrides:
        return overrides[text.lower()]
    words = re.sub(r"[_-]+", " ", text).split()
    acronyms = {"api", "crm", "id", "json", "pdf", "qr", "rag", "sla", "url"}
    return " ".join(word.upper() if word.lower() in acronyms else word.capitalize() for word in words) or "Unknown"


def _num(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _wrap(text: str, width: int) -> List[str]:
    lines: List[str] = []
    for paragraph in str(text).splitlines() or [""]:
        lines.extend(wrap(paragraph, width=width) or [""])
    return lines
