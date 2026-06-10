import os
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
STATUS_FLOW = ["New", "Parsed", "Needs Review", "Approved", "Sent"]
DEMO_CASES = ["utility_bill", "contract", "invoice", "incomplete"]

st.set_page_config(page_title="Local DocumentOps Automation", layout="wide", initial_sidebar_state="expanded")

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


def api_patch(path: str, json: Dict[str, Any]):
    response = requests.patch(f"{API_URL}{path}", json=json, timeout=60)
    response.raise_for_status()
    return response.json()


def api_download(path: str) -> bytes:
    response = requests.get(f"{API_URL}{path}", timeout=120)
    response.raise_for_status()
    return response.content


def fmt_number(value: Any, decimals: int = 0) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "0"


def badge(label: str, tone: str = "blue") -> str:
    return f'<span class="badge badge-{tone}">{label}</span>'


def risk_tone(risk: str) -> str:
    return {"low": "green", "medium": "amber", "high": "red"}.get(str(risk).lower(), "blue")


def load_cases() -> List[Dict[str, Any]]:
    return api_get("/cases").get("cases", [])


def case_label(case: Dict[str, Any]) -> str:
    owner = case.get("client_info", {}).get("company") or case.get("metadata", {}).get("owner") or case.get("source_filename") or "Case"
    return f"{owner} | {str(case.get('case_id', ''))[:8]}"


def select_case(cases: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    if not cases:
        return None
    options = {case_label(item): item.get("case_id") for item in cases}
    preferred = st.session_state.get("selected_case_id")
    labels = list(options.keys())
    default_index = 0
    if preferred in options.values():
        default_index = list(options.values()).index(preferred)
    label = st.selectbox("Case", labels, index=default_index, key=key)
    case_id = options[label]
    st.session_state["selected_case_id"] = case_id
    return api_get(f"/cases/{case_id}")


def make_field_rows(fields: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, payload in fields.items():
        if not isinstance(payload, dict):
            payload = {"value": payload, "confidence": 0}
        rows.append({"field": name, "value": payload.get("value"), "confidence": float(payload.get("confidence", 0))})
    return pd.DataFrame(rows, columns=["field", "value", "confidence"])


def make_metric_rows(metrics: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = metrics or [{"period": "", "value": 0.0, "unit": "value", "confidence": 1.0, "source": "manual"}]
    return pd.DataFrame(rows, columns=["period", "value", "unit", "confidence", "source"])


def clean_cell(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value


def pipeline_rows(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for item in cases:
        summary = item.get("case_summary", {})
        rows.append({
            "owner": item.get("client_info", {}).get("company") or item.get("metadata", {}).get("owner") or item.get("source_filename") or "Unknown",
            "status": item.get("status"),
            "type": summary.get("document_type", "unknown"),
            "risk": item.get("review_checklist", {}).get("risk_level", "unknown"),
            "completeness": summary.get("data_completeness", 0),
            "low_confidence": summary.get("low_confidence_count", 0),
            "total_amount": summary.get("total_amount", 0),
            "period_values": summary.get("period_metric_count", 0),
            "visual_markers": summary.get("visual_markers_found", 0),
            "next_action": item.get("review", {}).get("next_action", ""),
        })
    return rows


def integration_rows() -> List[Dict[str, str]]:
    return [
        {"system": "FastAPI", "purpose": "Document processing and case workflow API", "status": "implemented"},
        {"system": "Streamlit", "purpose": "Internal review dashboard", "status": "implemented"},
        {"system": "Ollama/Qwen", "purpose": "Local report writing and document Q&A", "status": "implemented"},
        {"system": "Telegram", "purpose": "Lightweight notifications and bot access", "status": "implemented"},
        {"system": "n8n", "purpose": "Upload, review, notification, and CRM workflow", "status": "workflow JSON included"},
        {"system": "Supabase", "purpose": "Postgres schema for multi-user persistence", "status": "schema included"},
        {"system": "Docker", "purpose": "Backend, dashboard, n8n, optional Ollama", "status": "compose included"},
    ]


st.title("Local DocumentOps Automation")
st.caption(f"Backend: {API_URL}")

try:
    health = api_get("/health")
except Exception as exc:
    st.error(f"Backend unavailable: {exc}")
    st.stop()

with st.sidebar:
    st.subheader("Connection")
    st.success(f"{health.get('mode')} | cases: {health.get('case_count', 0)}")
    st.caption(f"Ollama model: {health.get('ollama_model')}")

    st.subheader("Context")
    company = st.text_input("Company / owner", value="")
    contact = st.text_input("Contact name", value="")
    email = st.text_input("Email", value="")
    department = st.text_input("Department", value="Operations")
    priority = st.selectbox("Priority", ["normal", "high", "urgent"])

    st.subheader("Review Settings")
    materiality = st.number_input("Materiality amount", min_value=0.0, value=10000.0, step=1000.0)
    confidence_threshold = st.slider("Confidence threshold", 0.1, 1.0, 0.75, step=0.05)
    review_sla = st.number_input("Review SLA hours", min_value=1, value=24, step=1)
    require_visual_marker = st.checkbox("Require stamp/signature/logo marker", value=False)

try:
    cases = load_cases()
except Exception as exc:
    st.error(f"Could not load cases: {exc}")
    cases = []

pipeline_df = pd.DataFrame(pipeline_rows(cases))
counts = {status: len([item for item in cases if item.get("status") == status]) for status in STATUS_FLOW}
review_backlog = counts.get("Needs Review", 0)
avg_completeness = pipeline_df["completeness"].mean() if not pipeline_df.empty else 0
high_risk = len(pipeline_df[pipeline_df["risk"] == "high"]) if not pipeline_df.empty else 0
material_total = pipeline_df["total_amount"].sum() if not pipeline_df.empty else 0

summary_cols = st.columns(5)
summary_cols[0].metric("Cases", len(cases))
summary_cols[1].metric("Needs Review", review_backlog)
summary_cols[2].metric("High Risk", high_risk)
summary_cols[3].metric("Avg Complete", f"{avg_completeness:.0%}")
summary_cols[4].metric("Total Amount", fmt_number(material_total, 0))

intake_tab, ops_tab, board_tab, review_tab, settings_tab, report_tab, integrations_tab, audit_tab = st.tabs([
    "Intake",
    "Operations",
    "Status Board",
    "Review Queue",
    "Settings & Diff",
    "Report",
    "Integrations",
    "Audit",
])

with intake_tab:
    left, right = st.columns([1.4, 1])
    with left:
        st.subheader("Upload Documents")
        uploads = st.file_uploader("PDF documents", type=["pdf"], accept_multiple_files=True)
        if st.button("Process uploads and create cases", type="primary", disabled=not uploads):
            files = [("files", (upload.name, upload.getvalue(), "application/pdf")) for upload in uploads]
            try:
                processed = api_post("/process", files=files, timeout=300)
                client_info = {"company": company, "name": contact, "email": email}
                metadata = {"owner": company or department, "department": department, "priority": priority}
                review_settings = {"materiality_amount": materiality, "confidence_threshold": confidence_threshold, "review_sla_hours": review_sla, "require_visual_marker": require_visual_marker}
                created = []
                for doc in processed.get("documents", []):
                    created_case = api_post(
                        f"/cases/from-document/{doc['document_id']}",
                        json={"client_info": client_info, "metadata": metadata, "review_settings": review_settings, "actor": "streamlit"},
                        timeout=120,
                    )
                    created.append(created_case)
                if created:
                    st.session_state["selected_case_id"] = created[-1].get("case_id")
                st.success(f"Created {len(created)} case(s)")
                st.rerun()
            except Exception as exc:
                st.error(f"Processing failed: {exc}")
    with right:
        st.subheader("Demo")
        demo_case = st.selectbox("Demo case", DEMO_CASES)
        if st.button("Create demo case"):
            try:
                result = api_post(f"/demo/seed?case={demo_case}", timeout=120)
                st.session_state["selected_case_id"] = result.get("document_case", {}).get("case_id")
                st.success("Demo case created")
                st.rerun()
            except Exception as exc:
                st.error(f"Demo seed failed: {exc}")
        signal_rows = [
            {"signal": "PDF text extraction", "status": "active"},
            {"signal": "Table extraction", "status": "active" if health.get("tables_enabled") else "off"},
            {"signal": "Vector search", "status": "active" if health.get("embeddings_enabled") else "off"},
            {"signal": "QR/stamp/signature/logo detection", "status": "local heuristic"},
        ]
        st.dataframe(pd.DataFrame(signal_rows), width='stretch', hide_index=True)

with ops_tab:
    st.subheader("Operations Dashboard")
    if not pipeline_df.empty:
        chart_left, chart_right = st.columns(2)
        chart_left.bar_chart(pipeline_df.groupby("status").size().reindex(STATUS_FLOW, fill_value=0))
        chart_right.bar_chart(pipeline_df.groupby("risk").size())
        st.markdown("#### Case Pipeline")
        st.dataframe(pipeline_df.sort_values(["status", "risk", "low_confidence"], ascending=[True, True, False]), width='stretch', hide_index=True)
    else:
        st.info("No document cases yet.")

with board_tab:
    st.subheader("Case Status Board")
    board_cols = st.columns(len(STATUS_FLOW))
    for column, status in zip(board_cols, STATUS_FLOW):
        with column:
            st.markdown(f"**{status}**")
            status_items = [item for item in cases if item.get("status") == status]
            if not status_items:
                st.caption("No cases")
            for item in status_items:
                summary = item.get("case_summary", {})
                risk = item.get("review_checklist", {}).get("risk_level", "unknown")
                st.markdown(
                    f"""
                    <div class="workflow-card">
                    <strong>{item.get('client_info', {}).get('company') or item.get('source_filename')}</strong><br>
                    <span class="muted">{str(item.get('case_id'))[:8]}</span><br>
                    {badge(str(risk).upper(), risk_tone(risk))}<br><br>
                    <span class="muted">{summary.get('document_type', 'unknown')}</span><br>
                    <span class="muted">Complete {float(summary.get('data_completeness') or 0):.0%}</span><br>
                    <span class="muted">Markers {summary.get('visual_markers_found', 0)}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

with review_tab:
    st.subheader("Review Queue")
    selected = select_case(cases, "review_case")
    if not selected:
        st.info("Create a document case from Intake first.")
    else:
        summary = selected.get("case_summary", {})
        risk = selected.get("review_checklist", {}).get("risk_level", "unknown")
        cols = st.columns(6)
        cols[0].metric("Type", summary.get("document_type", "unknown"))
        cols[1].metric("Completeness", f"{float(summary.get('data_completeness') or 0):.0%}")
        cols[2].metric("Low Conf", summary.get("low_confidence_count", 0))
        cols[3].metric("Markers", summary.get("visual_markers_found", 0))
        cols[4].metric("Amount", fmt_number(summary.get("total_amount"), 0))
        cols[5].markdown(f"Risk<br>{badge(str(risk).upper(), risk_tone(risk))}", unsafe_allow_html=True)

        low_conf = selected.get("review", {}).get("low_confidence_fields", [])
        if low_conf:
            st.warning(f"{len(low_conf)} field(s) need review.")
            st.dataframe(pd.DataFrame(low_conf), width='stretch', hide_index=True)
        else:
            st.success("No low-confidence fields detected.")

        marker_types = selected.get("extraction", {}).get("visual_marker_types", {}) or {}
        if marker_types:
            st.dataframe(pd.DataFrame([{"marker": key, "count": value} for key, value in marker_types.items()]), width='stretch', hide_index=True)

        edit_left, edit_right = st.columns([1.1, 1])
        with edit_left:
            st.markdown("#### Extracted Fields")
            edited_fields = st.data_editor(make_field_rows(selected.get("extraction", {}).get("fields", {})), width='stretch', hide_index=True, num_rows="dynamic", key=f"fields_{selected['case_id']}")
        with edit_right:
            st.markdown("#### Structured Metrics")
            edited_metrics = st.data_editor(make_metric_rows(selected.get("extraction", {}).get("period_metrics", [])), width='stretch', hide_index=True, num_rows="dynamic", key=f"metrics_{selected['case_id']}")

        action_cols = st.columns([1.2, 1, 2])
        if action_cols[0].button("Save corrections", type="primary"):
            fields_payload = {}
            for _, row in edited_fields.iterrows():
                name = str(clean_cell(row.get("field")) or "").strip()
                if name:
                    fields_payload[name] = {"value": clean_cell(row.get("value")), "confidence": float(row.get("confidence") or 1.0)}
            metrics_payload = []
            for _, row in edited_metrics.iterrows():
                period = str(clean_cell(row.get("period")) or "").strip()
                if period:
                    metrics_payload.append({"period": period, "value": float(row.get("value") or 0), "unit": clean_cell(row.get("unit")) or "value", "confidence": float(row.get("confidence") or 1.0), "source": clean_cell(row.get("source")) or "manual"})
            api_patch(f"/cases/{selected['case_id']}/extraction", {"fields": fields_payload, "period_metrics": metrics_payload, "actor": "streamlit"})
            st.rerun()

        status_index = STATUS_FLOW.index(selected.get("status", "New")) if selected.get("status") in STATUS_FLOW else 0
        new_status = action_cols[1].selectbox("Move status", STATUS_FLOW, index=status_index)
        note = action_cols[2].text_input("Status note", value="")
        if st.button("Update case status"):
            api_patch(f"/cases/{selected['case_id']}/status", {"status": new_status, "actor": "streamlit", "note": note})
            st.rerun()

        st.markdown("#### Review Checklist")
        st.dataframe(pd.DataFrame(selected.get("review_checklist", {}).get("checks", [])), width='stretch', hide_index=True)

with settings_tab:
    st.subheader("Settings & Diff")
    selected = select_case(cases, "settings_case")
    if selected:
        current = selected.get("review_settings", {})
        c1, c2, c3, c4, c5 = st.columns(5)
        new_materiality = c1.number_input("Materiality amount", value=float(current.get("materiality_amount", 10000)), step=1000.0, key="set_materiality")
        new_conf = c2.slider("Confidence threshold", 0.1, 1.0, float(current.get("confidence_threshold", 0.75)), step=0.05, key="set_conf")
        new_sla = c3.number_input("SLA hours", value=int(current.get("review_sla_hours", 24)), step=1, key="set_sla")
        currency = c4.text_input("Currency", value=str(current.get("currency", "USD")), key="set_currency")
        require_marker = c5.checkbox("Require marker", value=bool(current.get("require_visual_marker", False)), key="set_marker")
        if st.button("Save settings version", type="primary"):
            api_patch(f"/cases/{selected['case_id']}/settings", {"actor": "streamlit", "review_settings": {"materiality_amount": new_materiality, "confidence_threshold": new_conf, "review_sla_hours": new_sla, "currency": currency, "require_visual_marker": require_marker}})
            st.rerun()
        versions = selected.get("versions", [])
        if len(versions) >= 2:
            version_ids = [version["version_id"] for version in versions]
            left_version = st.selectbox("Left version", version_ids, index=0)
            right_version = st.selectbox("Right version", version_ids, index=len(version_ids) - 1)
            diff = api_get(f"/cases/{selected['case_id']}/diff", left=left_version, right=right_version)
            rows = [{"metric": key, "left": payload.get("left"), "right": payload.get("right"), "delta": payload.get("delta")} for key, payload in diff.get("summary_delta", {}).items()]
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
        else:
            st.info("Create a settings or correction version to compare.")

with report_tab:
    st.subheader("Generated Report")
    selected = select_case(cases, "report_case")
    if selected:
        st.text_area("Deterministic report", selected.get("generated_report", ""), height=340)
        export_cols = st.columns([1, 1, 3])
        if export_cols[0].button("Prepare PDF report"):
            try:
                st.session_state["case_pdf_bytes"] = api_download(f"/cases/{selected['case_id']}/export-pdf")
                st.session_state["case_pdf_name"] = f"document_case_{selected['case_id']}.pdf"
                st.success("PDF report is ready")
            except Exception as exc:
                st.error(f"PDF export failed: {exc}")
        if st.session_state.get("case_pdf_bytes"):
            export_cols[1].download_button("Download PDF", data=st.session_state["case_pdf_bytes"], file_name=st.session_state.get("case_pdf_name", "document_case.pdf"), mime="application/pdf")
        if st.button("Generate polished report with Ollama/Qwen"):
            try:
                result = api_post(f"/cases/{selected['case_id']}/report-text", timeout=180)
                st.text_area("Polished report", result.get("report_text", ""), height=420)
            except Exception as exc:
                st.error(f"Qwen report failed: {exc}")

with integrations_tab:
    st.subheader("Integrations")
    st.dataframe(pd.DataFrame(integration_rows()), width='stretch', hide_index=True)
    st.json({"event": "case_needs_review", "case_id": "{case_id}", "status": "Needs Review", "next_action": "Review low-confidence fields"})

with audit_tab:
    st.subheader("Audit")
    selected = select_case(cases, "audit_case")
    if selected:
        audit = api_get(f"/cases/{selected['case_id']}/audit").get("events", [])
        if audit:
            st.dataframe(pd.DataFrame(audit), width='stretch', hide_index=True)
        else:
            st.info("No audit events yet.")