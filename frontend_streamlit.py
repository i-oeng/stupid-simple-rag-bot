import os
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
STATUS_FLOW = ["New", "Parsed", "Needs Review", "Approved", "Sent"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
SOLAR_WEIGHTS = [0.078, 0.079, 0.086, 0.087, 0.087, 0.083, 0.080, 0.081, 0.084, 0.087, 0.086, 0.082]

st.set_page_config(page_title="Solar Proposal Automation", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.25rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {background: #f7f9fc; border: 1px solid #e2e8f0; padding: 0.85rem; border-radius: 8px;}
    div[data-testid="stMetric"] label {color: #475569;}
    .workflow-card {border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.8rem; margin-bottom: 0.7rem; background: #ffffff;}
    .muted {color: #64748b; font-size: 0.9rem;}
    .badge {display: inline-block; border-radius: 999px; padding: 0.15rem 0.55rem; font-size: 0.8rem; font-weight: 700;}
    .badge-green {background: #dcfce7; color: #166534;}
    .badge-amber {background: #fef3c7; color: #92400e;}
    .badge-red {background: #fee2e2; color: #991b1b;}
    .badge-blue {background: #dbeafe; color: #1e40af;}
    </style>
    """,
    unsafe_allow_html=True,
)


def api_get(path: str, **params):
    response = requests.get(f"{API_URL}{path}", params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def api_post(path: str, json: Optional[Dict[str, Any]] = None, files=None, timeout=180):
    response = requests.post(f"{API_URL}{path}", json=json, files=files, timeout=timeout)
    response.raise_for_status()
    return response.json()


def api_download(path: str):
    response = requests.get(f"{API_URL}{path}", timeout=120)
    response.raise_for_status()
    return response.content


def api_patch(path: str, json: Dict[str, Any]):
    response = requests.patch(f"{API_URL}{path}", json=json, timeout=60)
    response.raise_for_status()
    return response.json()


def fmt_number(value: Any, decimals: int = 0) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "0"


def fmt_money(value: Any) -> str:
    return fmt_number(value, 0)


def badge(label: str, tone: str = "blue") -> str:
    return f'<span class="badge badge-{tone}">{label}</span>'


def risk_tone(risk: str) -> str:
    return {"low": "green", "medium": "amber", "high": "red"}.get(str(risk).lower(), "blue")


def load_proposals() -> List[Dict[str, Any]]:
    return api_get("/solar/proposals").get("proposals", [])


def proposal_label(proposal: Dict[str, Any]) -> str:
    client = proposal.get("client_info", {}).get("company") or proposal.get("source_filename") or "Proposal"
    short_id = str(proposal.get("proposal_id", ""))[:8]
    return f"{client} | {short_id}"


def select_proposal(proposals: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    if not proposals:
        return None
    options = {proposal_label(p): p.get("proposal_id") for p in proposals}
    preferred = st.session_state.get("selected_proposal_id")
    labels = list(options.keys())
    default_index = 0
    if preferred in options.values():
        default_index = list(options.values()).index(preferred)
    label = st.selectbox("Proposal", labels, index=default_index, key=key)
    proposal_id = options[label]
    st.session_state["selected_proposal_id"] = proposal_id
    return api_get(f"/solar/proposals/{proposal_id}")


def make_field_rows(fields: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, payload in fields.items():
        if not isinstance(payload, dict):
            payload = {"value": payload, "confidence": 0.0}
        rows.append({
            "field": name,
            "value": payload.get("value"),
            "confidence": float(payload.get("confidence", 0)),
        })
    return pd.DataFrame(rows, columns=["field", "value", "confidence"])


def make_monthly_rows(monthly: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = monthly or [{"month": month, "kwh": 0.0, "confidence": 1.0, "source": "manual"} for month in MONTHS]
    return pd.DataFrame(rows, columns=["month", "kwh", "confidence", "source"])


def clean_cell(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value


def average_confidence(proposal: Dict[str, Any]) -> float:
    summary = proposal.get("extraction", {}).get("confidence_summary", {})
    try:
        return float(summary.get("overall") or 0)
    except (TypeError, ValueError):
        return 0.0


def pipeline_rows(proposals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for proposal in proposals:
        calc = proposal.get("calculation", {})
        review = proposal.get("review", {})
        rows.append({
            "client": proposal.get("client_info", {}).get("company") or proposal.get("source_filename") or "Unknown",
            "status": proposal.get("status"),
            "risk": proposal.get("underwriting_checklist", {}).get("risk_level", "unknown"),
            "system_mw": round(float(calc.get("estimated_system_size_kwp") or 0) / 1000, 3),
            "annual_kwh": round(float(calc.get("annual_kwh") or 0), 0),
            "annual_savings": round(float(calc.get("estimated_annual_savings") or 0), 0),
            "confidence": average_confidence(proposal),
            "document_type": proposal.get("extraction", {}).get("document_type", "unknown"),
            "next_action": review.get("next_action", ""),
        })
    return rows


def monthly_performance_rows(proposal: Dict[str, Any]) -> List[Dict[str, Any]]:
    assumptions = proposal.get("assumptions", {})
    calc = proposal.get("calculation", {})
    monthly = {row.get("month"): float(row.get("kwh") or 0) for row in proposal.get("extraction", {}).get("monthly_consumption", [])}
    annual_production = float(calc.get("year_one_production_kwh") or 0)
    grid_tariff = float(assumptions.get("grid_tariff_per_kwh") or 0)
    ppa_rate = float(assumptions.get("ppa_rate_per_kwh") or 0)
    rows = []
    for month, weight in zip(MONTHS, SOLAR_WEIGHTS):
        consumption = monthly.get(month, 0.0)
        solar = min(annual_production * weight, consumption) if consumption else annual_production * weight
        grid = max(consumption - solar, 0)
        current_cost = consumption * grid_tariff
        blended_cost = solar * ppa_rate + grid * grid_tariff
        rows.append({
            "month": month,
            "consumption_kwh": round(consumption, 2),
            "solar_kwh": round(solar, 2),
            "grid_kwh": round(grid, 2),
            "estimated_savings": round(current_cost - blended_cost, 2),
        })
    return rows


def integration_rows() -> List[Dict[str, str]]:
    return [
        {"system": "FastAPI", "purpose": "Document and proposal workflow API", "status": "implemented"},
        {"system": "Streamlit", "purpose": "Internal ops, underwriting, and client views", "status": "implemented"},
        {"system": "Ollama/Qwen", "purpose": "Local proposal text and document Q&A", "status": "implemented"},
        {"system": "Telegram", "purpose": "Lightweight proposal notifications and bot access", "status": "implemented"},
        {"system": "n8n", "purpose": "Workflow automation for upload, review, and notifications", "status": "workflow drafted"},
        {"system": "Supabase", "purpose": "Postgres, auth, storage, and CRM-grade persistence", "status": "planned"},
        {"system": "CRM", "purpose": "Lead/proposal records and pipeline visibility", "status": "planned"},
    ]


st.title("Solar Proposal Automation")
st.caption(f"Backend: {API_URL}")

try:
    health = api_get("/health")
except Exception as exc:
    st.error(f"Backend unavailable: {exc}")
    st.stop()

with st.sidebar:
    st.subheader("Connection")
    st.success(f"{health.get('mode')} | proposals: {health.get('proposal_count', 0)}")
    st.caption(f"Ollama model: {health.get('ollama_model')}")

    st.subheader("Client")
    company = st.text_input("Company", value="")
    contact = st.text_input("Contact name", value="")
    email = st.text_input("Email", value="")

    st.subheader("Site")
    address = st.text_input("Site address", value="")
    country = st.text_input("Country / region", value="")
    roof_area = st.number_input("Usable roof area m2", min_value=0.0, value=0.0, step=50.0)

    st.subheader("Default Assumptions")
    grid_tariff = st.number_input("Grid tariff per kWh", min_value=0.0, value=0.16, step=0.01)
    ppa_rate = st.number_input("PPA rate per kWh", min_value=0.0, value=0.115, step=0.005, format="%.3f")
    yield_kwh = st.number_input("Solar yield kWh/kWp/year", min_value=1.0, value=1450.0, step=25.0)
    offset = st.slider("Target offset", min_value=0.1, max_value=1.0, value=0.75, step=0.05)

try:
    proposals = load_proposals()
except Exception as exc:
    st.error(f"Could not load proposals: {exc}")
    proposals = []

pipeline = pipeline_rows(proposals)
pipeline_df = pd.DataFrame(pipeline)
counts = {status: len([p for p in proposals if p.get("status") == status]) for status in STATUS_FLOW}
portfolio_mw = sum(float(p.get("calculation", {}).get("estimated_system_size_kwp") or 0) for p in proposals) / 1000
approved_mw = sum(float(p.get("calculation", {}).get("estimated_system_size_kwp") or 0) for p in proposals if p.get("status") in ["Approved", "Sent"]) / 1000
annual_savings = sum(float(p.get("calculation", {}).get("estimated_annual_savings") or 0) for p in proposals)
review_backlog = counts.get("Needs Review", 0)

summary_cols = st.columns(5)
summary_cols[0].metric("Pipeline MW", fmt_number(portfolio_mw, 2))
summary_cols[1].metric("Approved MW", fmt_number(approved_mw, 2))
summary_cols[2].metric("Needs Review", review_backlog)
summary_cols[3].metric("Sent", counts.get("Sent", 0))
summary_cols[4].metric("Est. Savings", fmt_money(annual_savings))

intake_tab, ops_tab, board_tab, review_tab, assumptions_tab, client_tab, draft_tab, integrations_tab, audit_tab = st.tabs([
    "Intake",
    "Operations",
    "Status Board",
    "Review Queue",
    "Assumptions & Diff",
    "Client View",
    "Proposal Draft",
    "Integrations",
    "Audit",
])

with intake_tab:
    left, right = st.columns([1.4, 1])
    with left:
        st.subheader("Upload Documents")
        uploads = st.file_uploader("Utility bills, contracts, or financial statements", type=["pdf"], accept_multiple_files=True)
        if st.button("Process uploads and create proposals", type="primary", disabled=not uploads):
            files = [("files", (upload.name, upload.getvalue(), "application/pdf")) for upload in uploads]
            try:
                processed = api_post("/process", files=files, timeout=300)
                assumptions = {
                    "grid_tariff_per_kwh": grid_tariff,
                    "ppa_rate_per_kwh": ppa_rate,
                    "solar_yield_kwh_per_kwp_year": yield_kwh,
                    "target_offset_pct": offset,
                }
                client_info = {"company": company, "name": contact, "email": email}
                site_data = {"address": address, "country": country, "usable_roof_area_m2": roof_area}
                created = []
                for doc in processed.get("documents", []):
                    proposal = api_post(
                        f"/solar/proposals/from-document/{doc['document_id']}",
                        json={"client_info": client_info, "site_data": site_data, "assumptions": assumptions, "actor": "streamlit"},
                        timeout=120,
                    )
                    created.append(proposal)
                if created:
                    st.session_state["selected_proposal_id"] = created[-1].get("proposal_id")
                st.success(f"Created {len(created)} proposal(s)")
                st.rerun()
            except Exception as exc:
                st.error(f"Processing failed: {exc}")
    with right:
        st.subheader("Demo")
        if st.button("Create demo proposal"):
            try:
                result = api_post("/demo/seed", timeout=120)
                st.session_state["selected_proposal_id"] = result.get("proposal", {}).get("proposal_id")
                st.success("Demo proposal created")
                st.rerun()
            except Exception as exc:
                st.error(f"Demo seed failed: {exc}")
        st.markdown("#### Document Signals")
        signal_rows = [
            {"signal": "PDF text extraction", "status": "active" if health.get("tables_enabled") is not None else "unknown"},
            {"signal": "Table extraction", "status": "active" if health.get("tables_enabled") else "off"},
            {"signal": "Vector search", "status": "active" if health.get("embeddings_enabled") else "off"},
            {"signal": "QR/signature/logo detection", "status": "available in backend document workflow"},
        ]
        st.dataframe(pd.DataFrame(signal_rows), use_container_width=True, hide_index=True)

with ops_tab:
    st.subheader("Operations Dashboard")
    target_mw = st.number_input("Portfolio target MW", min_value=1.0, value=50.0, step=1.0)
    ops_cols = st.columns(5)
    ops_cols[0].metric("Target Progress", f"{portfolio_mw / target_mw * 100:.1f}%")
    ops_cols[1].metric("Pipeline", f"{portfolio_mw:.2f} MW")
    ops_cols[2].metric("Approved/Sent", f"{approved_mw:.2f} MW")
    ops_cols[3].metric("Review Backlog", review_backlog)
    avg_conf = sum(average_confidence(p) for p in proposals) / len(proposals) if proposals else 0
    ops_cols[4].metric("Avg Confidence", f"{avg_conf:.2f}")

    if not pipeline_df.empty:
        status_counts = pipeline_df.groupby("status").size().reindex(STATUS_FLOW, fill_value=0)
        risk_counts = pipeline_df.groupby("risk").size()
        chart_left, chart_right = st.columns(2)
        chart_left.bar_chart(status_counts)
        chart_right.bar_chart(risk_counts)
        st.markdown("#### CRM Pipeline")
        st.dataframe(
            pipeline_df.sort_values(["status", "risk", "system_mw"], ascending=[True, True, False]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No proposals yet.")

with board_tab:
    st.subheader("Proposal Status Board")
    board_cols = st.columns(len(STATUS_FLOW))
    for column, status in zip(board_cols, STATUS_FLOW):
        with column:
            st.markdown(f"**{status}**")
            status_items = [p for p in proposals if p.get("status") == status]
            if not status_items:
                st.caption("No proposals")
            for proposal in status_items:
                calc = proposal.get("calculation", {})
                risk = proposal.get("underwriting_checklist", {}).get("risk_level", "unknown")
                st.markdown(
                    f"""
                    <div class="workflow-card">
                    <strong>{proposal.get('client_info', {}).get('company') or proposal.get('source_filename')}</strong><br>
                    <span class="muted">{str(proposal.get('proposal_id'))[:8]}</span><br>
                    {badge(risk.upper(), risk_tone(risk))}<br><br>
                    <span class="muted">{fmt_number(calc.get('estimated_system_size_kwp'), 1)} kWp</span><br>
                    <span class="muted">Savings {fmt_money(calc.get('estimated_annual_savings'))}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

with review_tab:
    st.subheader("Review Queue")
    selected = select_proposal(proposals, "review_proposal")
    if not selected:
        st.info("Create a proposal from the Intake tab first.")
    else:
        calc = selected.get("calculation", {})
        risk = selected.get("underwriting_checklist", {}).get("risk_level", "unknown")
        top = st.columns(5)
        top[0].metric("Annual kWh", fmt_number(calc.get("annual_kwh")))
        top[1].metric("System kWp", fmt_number(calc.get("estimated_system_size_kwp"), 1))
        top[2].metric("Year 1 kWh", fmt_number(calc.get("year_one_production_kwh")))
        top[3].metric("Savings", fmt_money(calc.get("estimated_annual_savings")))
        top[4].markdown(f"Risk<br>{badge(str(risk).upper(), risk_tone(risk))}", unsafe_allow_html=True)

        low_conf = selected.get("review", {}).get("low_confidence_fields", [])
        if low_conf:
            st.warning(f"{len(low_conf)} field(s) need review before approval.")
            st.dataframe(pd.DataFrame(low_conf), use_container_width=True, hide_index=True)
        else:
            st.success("No low-confidence extraction fields detected.")

        edit_left, edit_right = st.columns([1.1, 1])
        with edit_left:
            st.markdown("#### Extracted Fields")
            field_df = make_field_rows(selected.get("extraction", {}).get("fields", {}))
            edited_fields = st.data_editor(
                field_df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                column_config={
                    "field": st.column_config.TextColumn("Field", required=True),
                    "value": st.column_config.TextColumn("Value"),
                    "confidence": st.column_config.NumberColumn("Confidence", min_value=0.0, max_value=1.0, step=0.01),
                },
                key=f"fields_{selected['proposal_id']}",
            )
        with edit_right:
            st.markdown("#### Monthly Consumption")
            monthly_df = make_monthly_rows(selected.get("extraction", {}).get("monthly_consumption", []))
            edited_monthly = st.data_editor(
                monthly_df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                column_config={
                    "month": st.column_config.SelectboxColumn("Month", options=MONTHS, required=True),
                    "kwh": st.column_config.NumberColumn("kWh", min_value=0.0, step=100.0),
                    "confidence": st.column_config.NumberColumn("Confidence", min_value=0.0, max_value=1.0, step=0.01),
                    "source": st.column_config.TextColumn("Source"),
                },
                key=f"monthly_{selected['proposal_id']}",
            )

        action_cols = st.columns([1, 1, 2])
        if action_cols[0].button("Save corrections and recalculate", type="primary"):
            fields_payload = {}
            for _, row in edited_fields.iterrows():
                name = str(clean_cell(row.get("field")) or "").strip()
                if not name:
                    continue
                fields_payload[name] = {
                    "value": clean_cell(row.get("value")),
                    "confidence": float(row.get("confidence") or 1.0),
                }
            monthly_payload = []
            for _, row in edited_monthly.iterrows():
                month = str(clean_cell(row.get("month")) or "").strip().lower()[:3]
                if month not in MONTHS:
                    continue
                monthly_payload.append({
                    "month": month,
                    "kwh": float(row.get("kwh") or 0),
                    "confidence": float(row.get("confidence") or 1.0),
                    "source": clean_cell(row.get("source")) or "manual",
                })
            api_patch(
                f"/solar/proposals/{selected['proposal_id']}/extraction",
                {"fields": fields_payload, "monthly_consumption": monthly_payload, "actor": "streamlit"},
            )
            st.success("Corrections saved")
            st.rerun()

        status_index = STATUS_FLOW.index(selected.get("status", "New")) if selected.get("status") in STATUS_FLOW else 0
        new_status = action_cols[1].selectbox("Move status", STATUS_FLOW, index=status_index)
        note = action_cols[2].text_input("Status note", value="")
        if st.button("Update proposal status"):
            api_patch(f"/solar/proposals/{selected['proposal_id']}/status", {"status": new_status, "actor": "streamlit", "note": note})
            st.rerun()

        st.markdown("#### Underwriting Checklist")
        checklist = selected.get("underwriting_checklist", {}).get("checks", [])
        st.dataframe(pd.DataFrame(checklist), use_container_width=True, hide_index=True)

with assumptions_tab:
    st.subheader("Assumptions & Diff")
    selected = select_proposal(proposals, "assumptions_proposal")
    if selected:
        current = selected.get("assumptions", {})
        col_a, col_b, col_c, col_d = st.columns(4)
        new_grid = col_a.number_input("Grid tariff", value=float(current.get("grid_tariff_per_kwh", 0.16)), step=0.01, key="assump_grid")
        new_ppa = col_b.number_input("PPA rate", value=float(current.get("ppa_rate_per_kwh", 0.115)), step=0.005, format="%.3f", key="assump_ppa")
        new_yield = col_c.number_input("Solar yield", value=float(current.get("solar_yield_kwh_per_kwp_year", 1450)), step=25.0, key="assump_yield")
        new_offset = col_d.slider("Target offset", 0.1, 1.0, float(current.get("target_offset_pct", 0.75)), step=0.05, key="assump_offset")
        col_e, col_f, col_g, col_h = st.columns(4)
        new_derate = col_e.number_input("Derate", value=float(current.get("system_derate_pct", 0.86)), step=0.01, key="assump_derate")
        new_capex = col_f.number_input("Capex per kWp", value=float(current.get("capex_per_kwp", 780)), step=10.0, key="assump_capex")
        new_opex = col_g.number_input("Opex pct", value=float(current.get("opex_pct_of_capex", 0.015)), step=0.001, format="%.3f", key="assump_opex")
        new_term = col_h.number_input("Term years", value=int(current.get("payment_term_years", 15)), step=1, key="assump_term")
        if st.button("Create recalculated version", type="primary"):
            api_patch(
                f"/solar/proposals/{selected['proposal_id']}/assumptions",
                {
                    "actor": "streamlit",
                    "assumptions": {
                        "grid_tariff_per_kwh": new_grid,
                        "ppa_rate_per_kwh": new_ppa,
                        "solar_yield_kwh_per_kwp_year": new_yield,
                        "target_offset_pct": new_offset,
                        "system_derate_pct": new_derate,
                        "capex_per_kwp": new_capex,
                        "opex_pct_of_capex": new_opex,
                        "payment_term_years": new_term,
                    },
                },
            )
            st.rerun()

        versions = selected.get("versions", [])
        if len(versions) >= 2:
            version_ids = [version["version_id"] for version in versions]
            diff_left, diff_right = st.columns(2)
            left_version = diff_left.selectbox("Left version", version_ids, index=0)
            right_version = diff_right.selectbox("Right version", version_ids, index=len(version_ids) - 1)
            diff = api_get(f"/solar/proposals/{selected['proposal_id']}/diff", left=left_version, right=right_version)
            diff_rows = []
            for key, payload in diff.get("calculation_delta", {}).items():
                diff_rows.append({"metric": key, "left": payload.get("left"), "right": payload.get("right"), "delta": payload.get("delta")})
            st.dataframe(pd.DataFrame(diff_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Create at least one recalculated version to compare assumptions.")

with client_tab:
    st.subheader("Client Energy View")
    selected = select_proposal(proposals, "client_proposal")
    if selected:
        calc = selected.get("calculation", {})
        client_metrics = st.columns(5)
        client_metrics[0].metric("Annual Use", f"{fmt_number(calc.get('annual_kwh'))} kWh")
        client_metrics[1].metric("Solar Size", f"{fmt_number(calc.get('estimated_system_size_kwp'), 1)} kWp")
        client_metrics[2].metric("Solar Production", f"{fmt_number(calc.get('year_one_production_kwh'))} kWh")
        client_metrics[3].metric("Annual Savings", fmt_money(calc.get("estimated_annual_savings")))
        client_metrics[4].metric("Payback", f"{fmt_number(calc.get('simple_payback_years'), 1)} yrs")

        performance = pd.DataFrame(monthly_performance_rows(selected))
        if not performance.empty:
            st.bar_chart(performance.set_index("month")[["consumption_kwh", "solar_kwh", "grid_kwh"]])
            st.dataframe(performance, use_container_width=True, hide_index=True)

        if not pipeline_df.empty:
            st.markdown("#### Portfolio Visibility")
            st.dataframe(
                pipeline_df[["client", "status", "system_mw", "annual_kwh", "annual_savings", "risk"]],
                use_container_width=True,
                hide_index=True,
            )

with draft_tab:
    st.subheader("Proposal Draft")
    selected = select_proposal(proposals, "draft_proposal")
    if selected:
        st.text_area("Deterministic draft", selected.get("proposal_draft", ""), height=360)
        export_cols = st.columns([1, 1, 3])
        if export_cols[0].button("Prepare PDF export"):
            try:
                st.session_state["proposal_pdf_bytes"] = api_download(f"/solar/proposals/{selected['proposal_id']}/export-pdf")
                st.session_state["proposal_pdf_name"] = f"proposal_{selected['proposal_id']}.pdf"
                st.success("PDF export is ready")
            except Exception as exc:
                st.error(f"PDF export failed: {exc}")
        if st.session_state.get("proposal_pdf_bytes"):
            export_cols[1].download_button(
                "Download PDF",
                data=st.session_state["proposal_pdf_bytes"],
                file_name=st.session_state.get("proposal_pdf_name", "proposal.pdf"),
                mime="application/pdf",
            )
        if st.button("Generate polished draft with Ollama/Qwen"):
            try:
                result = api_post(f"/solar/proposals/{selected['proposal_id']}/proposal-text", timeout=180)
                st.text_area("Polished draft", result.get("proposal_text", ""), height=420)
            except Exception as exc:
                st.error(f"Qwen draft failed: {exc}")

with integrations_tab:
    st.subheader("Integrations")
    st.dataframe(pd.DataFrame(integration_rows()), use_container_width=True, hide_index=True)
    webhook_payload = {
        "event": "proposal_needs_review",
        "proposal_id": "{proposal_id}",
        "client": "{client_name}",
        "status": "Needs Review",
        "next_action": "Review low-confidence fields and assumptions",
    }
    st.json(webhook_payload)

with audit_tab:
    st.subheader("Audit")
    selected = select_proposal(proposals, "audit_proposal")
    if selected:
        audit = api_get(f"/solar/proposals/{selected['proposal_id']}/audit").get("events", [])
        if audit:
            st.dataframe(pd.DataFrame(audit), use_container_width=True, hide_index=True)
        else:
            st.info("No audit events yet.")