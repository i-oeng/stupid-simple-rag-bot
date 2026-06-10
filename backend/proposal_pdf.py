from pathlib import Path
from textwrap import wrap
from typing import Any, Dict, Iterable, List

import fitz

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 48
LINE_HEIGHT = 14
FONT = "helv"
FONT_BOLD = "helv"
INK = (0.12, 0.16, 0.20)
MUTED = (0.42, 0.48, 0.55)
BLUE = (0.10, 0.28, 0.54)
GREEN = (0.07, 0.45, 0.28)
LIGHT_BG = (0.94, 0.97, 0.99)
BORDER = (0.78, 0.84, 0.90)


def build_proposal_pdf(proposal: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    proposal_id = proposal.get("proposal_id", "proposal")
    output_path = output_dir / f"proposal_{proposal_id}.pdf"

    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    state = {"page": page, "y": MARGIN}

    _header(state, proposal)
    _metrics(state, proposal)
    _section(state, "Consumption Review")
    _paragraph(state, _consumption_text(proposal))
    _monthly_table(state, proposal.get("extraction", {}).get("monthly_consumption", []))
    _section(state, "Commercial Estimate")
    _key_value_rows(state, _commercial_rows(proposal))
    _section(state, "Underwriting Checklist")
    _checklist(state, proposal.get("underwriting_checklist", {}).get("checks", []))
    _section(state, "Assumptions")
    _key_value_rows(state, _assumption_rows(proposal))
    _section(state, "Review Notes")
    _paragraph(state, "This proposal is generated from extracted utility bill data and editable commercial assumptions. It should be reviewed before sending to a client or investment committee.")
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


def _text(state: Dict[str, Any], text: str, x: float, y: float, size: float = 10, color=INK, bold: bool = False) -> None:
    state["page"].insert_text((x, y), str(text), fontsize=size, fontname=FONT_BOLD if bold else FONT, color=color)


def _header(state: Dict[str, Any], proposal: Dict[str, Any]) -> None:
    page = state["page"]
    client = proposal.get("client_info", {}).get("company") or proposal.get("source_filename") or "Client"
    site = proposal.get("site_data", {}).get("address") or _field_value(proposal, "service_address") or "Site under review"
    page.draw_rect(fitz.Rect(0, 0, PAGE_WIDTH, 118), color=BLUE, fill=BLUE)
    page.draw_rect(fitz.Rect(MARGIN, 28, MARGIN + 54, 82), color=(1, 1, 1), fill=(1, 1, 1))
    _text(state, "SOLAR", MARGIN + 9, 51, size=11, color=BLUE, bold=True)
    _text(state, "OPS", MARGIN + 15, 67, size=11, color=GREEN, bold=True)
    _text(state, "Commercial Solar Proposal", MARGIN + 72, 45, size=20, color=(1, 1, 1), bold=True)
    _text(state, client, MARGIN + 72, 68, size=12, color=(0.90, 0.95, 1), bold=True)
    _text(state, site, MARGIN + 72, 88, size=9, color=(0.86, 0.91, 0.96))
    state["y"] = 145


def _metrics(state: Dict[str, Any], proposal: Dict[str, Any]) -> None:
    calc = proposal.get("calculation", {})
    metrics = [
        ("Annual Use", f"{_num(calc.get('annual_kwh'))} kWh"),
        ("System Size", f"{_num(calc.get('estimated_system_size_kwp'), 1)} kWp"),
        ("Solar Output", f"{_num(calc.get('year_one_production_kwh'))} kWh"),
        ("Annual Savings", _money(calc.get("estimated_annual_savings"))),
    ]
    box_w = (PAGE_WIDTH - 2 * MARGIN - 18) / 4
    y = state["y"]
    for idx, (label, value) in enumerate(metrics):
        x = MARGIN + idx * (box_w + 6)
        rect = fitz.Rect(x, y, x + box_w, y + 58)
        state["page"].draw_rect(rect, color=BORDER, fill=LIGHT_BG)
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
        _text(state, line, MARGIN, state["y"], size=10, color=INK)
        state["y"] += LINE_HEIGHT
    state["y"] += 8


def _key_value_rows(state: Dict[str, Any], rows: Iterable[tuple]) -> None:
    for label, value in rows:
        _ensure_space(state, 20)
        _text(state, label, MARGIN, state["y"], size=9, color=MUTED, bold=True)
        _text(state, value, MARGIN + 210, state["y"], size=9, color=INK)
        state["y"] += 18
    state["y"] += 6


def _monthly_table(state: Dict[str, Any], monthly: List[Dict[str, Any]]) -> None:
    if not monthly:
        _paragraph(state, "No monthly consumption values were extracted yet.")
        return
    _ensure_space(state, 180)
    rows = monthly[:12]
    x = MARGIN
    y = state["y"]
    col_w = (PAGE_WIDTH - 2 * MARGIN) / 4
    headers = ["Month", "kWh", "Confidence", "Source"]
    for idx, header in enumerate(headers):
        _text(state, header, x + idx * col_w, y, size=8, color=MUTED, bold=True)
    state["y"] += 16
    for row in rows:
        _ensure_space(state, 18)
        y = state["y"]
        values = [row.get("month", ""), _num(row.get("kwh")), f"{float(row.get('confidence', 0)):.2f}", row.get("source", "")]
        for idx, value in enumerate(values):
            _text(state, value, x + idx * col_w, y, size=8.5, color=INK)
        state["y"] += 16
    state["y"] += 8


def _checklist(state: Dict[str, Any], checks: List[Dict[str, Any]]) -> None:
    if not checks:
        _paragraph(state, "No underwriting checks available.")
        return
    for check in checks:
        if not isinstance(check, dict):
            check = {"name": str(check), "status": "needs_review", "evidence": "Imported legacy check format"}
        status = check.get("status", "needs_review")
        mark = "PASS" if status == "pass" else "REVIEW"
        color = GREEN if status == "pass" else (0.72, 0.35, 0.05)
        _ensure_space(state, 28)
        _text(state, mark, MARGIN, state["y"], size=8, color=color, bold=True)
        _text(state, check.get("name", "check"), MARGIN + 70, state["y"], size=9, color=INK, bold=True)
        state["y"] += 13
        _text(state, check.get("evidence", ""), MARGIN + 70, state["y"], size=8, color=MUTED)
        state["y"] += 17
    state["y"] += 6


def _footer(state: Dict[str, Any]) -> None:
    page = state["page"]
    page.draw_line((MARGIN, PAGE_HEIGHT - 38), (PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 38), color=BORDER)
    page.insert_text((MARGIN, PAGE_HEIGHT - 22), "Generated by Solar Proposal Automation", fontsize=8, fontname=FONT, color=MUTED)


def _field_value(proposal: Dict[str, Any], name: str) -> str:
    fields = proposal.get("extraction", {}).get("fields", {})
    payload = fields.get(name, {}) if isinstance(fields, dict) else {}
    if isinstance(payload, dict):
        return payload.get("value") or ""
    return str(payload) if payload else ""

def _consumption_text(proposal: Dict[str, Any]) -> str:
    calc = proposal.get("calculation", {})
    extraction = proposal.get("extraction", {})
    confidence = extraction.get("confidence_summary", {}).get("overall", 0)
    return (
        f"The reviewed documents indicate annual consumption of {_num(calc.get('annual_kwh'))} kWh. "
        f"Extraction confidence is {confidence}. Low-confidence fields should be corrected before this proposal is sent."
    )


def _commercial_rows(proposal: Dict[str, Any]) -> List[tuple]:
    calc = proposal.get("calculation", {})
    return [
        ("Current annual energy cost", _money(calc.get("current_annual_cost"))),
        ("Estimated blended annual PPA cost", _money(calc.get("ppa_blended_annual_cost"))),
        ("Estimated annual savings", _money(calc.get("estimated_annual_savings"))),
        ("Estimated capex", _money(calc.get("estimated_capex"))),
        ("Estimated annual opex", _money(calc.get("estimated_annual_opex"))),
        ("Simple payback", f"{_num(calc.get('simple_payback_years'), 1)} years" if calc.get("simple_payback_years") else "N/A"),
    ]


def _assumption_rows(proposal: Dict[str, Any]) -> List[tuple]:
    assumptions = proposal.get("assumptions", {})
    keys = [
        "grid_tariff_per_kwh",
        "ppa_rate_per_kwh",
        "solar_yield_kwh_per_kwp_year",
        "target_offset_pct",
        "system_derate_pct",
        "payment_term_years",
        "capex_per_kwp",
    ]
    return [(key, str(assumptions.get(key, ""))) for key in keys]


def _num(value: Any, decimals: int = 0) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "0"


def _money(value: Any) -> str:
    return _num(value, 0)


def _wrap(text: str, width: int) -> List[str]:
    lines: List[str] = []
    for paragraph in str(text).splitlines() or [""]:
        lines.extend(wrap(paragraph, width=width) or [""])
    return lines