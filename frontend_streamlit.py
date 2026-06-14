import os
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
STATUS_FLOW = ["New", "Parsed", "Needs Review", "Approved", "Sent"]
DEMO_CASES = ["utility_bill", "contract", "invoice", "incomplete"]
LABEL_OVERRIDES = {
    "case_needs_review": "Case Needs Review",
    "category_or_rate": "Category / Rate",
    "counterparty": "Counterparty",
    "data_completeness": "Data Completeness",
    "date_or_term_present": "Date Or Term Present",
    "document_date": "Document Date",
    "document_id_number": "Document ID Number",
    "document_type": "Document Type",
    "document_type_detected": "Document Type Detected",
    "financial_statement": "Financial Statement",
    "identifier_present": "Identifier Present",
    "low_confidence_count": "Low Confidence Count",
    "logo_candidate": "Logo Candidate",
    "materiality_flag": "Materiality Flag",
    "operational_document": "Operational Document",
    "period_metric_count": "Period Metric Count",
    "period_metric_total": "Period Metric Total",
    "qr_codes_found": "QR Codes Found",
    "review_context_present": "Review Context Present",
    "service_or_site": "Service / Site",
    "signature_candidate": "Signature Candidate",
    "stamp_candidate": "Stamp Candidate",
    "structured_values_found": "Structured Values Found",
    "tables_found": "Tables Found",
    "total_amount": "Total Amount",
    "utility_bill": "Utility Bill",
    "visual_marker_requirement": "Visual Marker Requirement",
    "visual_marker_types": "Visual Marker Types",
    "visual_markers_found": "Visual Markers Found",
}
ACRONYMS = {"api", "crm", "id", "json", "pdf", "qr", "rag", "sla", "url"}

st.set_page_config(page_title="Local DocumentOps Automation", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.25rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        padding: 0.85rem;
        border-radius: 8px;
    }
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: #334155 !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"],
    div[data-testid="stMetric"] [data-testid="stMetricValue"] div {
        color: #0f172a !important;
        font-weight: 750;
    }
    div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
        color: #334155 !important;
    }
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


def fmt_number(value: Any, decimals: int = 0) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "0"


def badge(label: str, tone: str = "blue") -> str:
    return f'<span class="badge badge-{tone}">{label}</span>'


def risk_tone(risk: str) -> str:
    return {"low": "green", "medium": "amber", "high": "red"}.get(str(risk).lower(), "blue")


def humanize(value: Any) -> str:
    if value is None or value == "":
        return "Unknown"
    text = str(value)
    if text in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[text]
    words = text.replace("_", " ").replace("-", " ").split()
    return " ".join(word.upper() if word.lower() in ACRONYMS else word.capitalize() for word in words)


def field_key(label: Any) -> str:
    text = str(label or "").strip()
    reverse = {display: key for key, display in LABEL_OVERRIDES.items()}
    if text in reverse:
        return reverse[text]
    return text.lower().replace("/", " ").replace("-", " ").replace("_", " ").strip().replace(" ", "_")


def display_rows(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    value_humanize_keys = {"action", "document_type", "event", "field", "marker", "metric", "name", "risk", "source", "status", "type", "unit"}
    cleaned = []
    for row in rows:
        cleaned.append({humanize(key): humanize(value) if key in value_humanize_keys else value for key, value in row.items()})
    return pd.DataFrame(cleaned)


def format_details(details: Any) -> str:
    if not isinstance(details, dict):
        return str(details or "")
    parts = []
    for key, value in details.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            parts.append(f"{humanize(key)}: {humanize(value) if isinstance(value, str) else value}")
        elif isinstance(value, list):
            parts.append(f"{humanize(key)}: {len(value)} item(s)")
        else:
            parts.append(f"{humanize(key)}: updated")
    return ", ".join(parts)


def audit_rows(events: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for event in events:
        rows.append({
            "Timestamp": event.get("timestamp", ""),
            "Actor": humanize(event.get("actor", "")),
            "Action": humanize(event.get("action", "")),
            "Details": format_details(event.get("details", {})),
        })
    return pd.DataFrame(rows)


def load_cases() -> List[Dict[str, Any]]:
    return api_get("/cases").get("cases", [])


def case_title(case: Dict[str, Any]) -> str:
    metadata = case.get("metadata", {}) or {}
    fields = case.get("extraction", {}).get("fields", {}) or {}
    counterparty = fields.get("counterparty", {}).get("value")
    document_id = fields.get("document_id_number", {}).get("value")
    source = case.get("source_filename")
    candidate = metadata.get("display_title") or counterparty or case.get("client_info", {}).get("company") or source or "Document Case"
    if candidate in {"Operations", "Review Queue", "Unknown"} and source:
        candidate = source
    if document_id and document_id not in str(candidate):
        return f"{candidate} - {document_id}"
    return str(candidate)


def case_label(case: Dict[str, Any]) -> str:
    return f"{case_title(case)} | {str(case.get('case_id', ''))[:8]}"


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
        rows.append({"field_key": name, "field": humanize(name), "value": payload.get("value"), "confidence": float(payload.get("confidence", 0))})
    return pd.DataFrame(rows, columns=["field_key", "field", "value", "confidence"])


def make_metric_rows(metrics: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = metrics or [{"period": "", "value": 0.0, "unit": "value", "confidence": 1.0, "source": "manual"}]
    display = []
    for row in rows:
        display.append({
            "period": humanize(row.get("period", "")),
            "value": row.get("value", 0.0),
            "unit": humanize(row.get("unit", "value")),
            "confidence": row.get("confidence", 1.0),
            "source": humanize(row.get("source", "manual")),
        })
    return pd.DataFrame(display, columns=["period", "value", "unit", "confidence", "source"])


def clean_cell(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value


def pipeline_rows(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for item in cases:
        summary = item.get("case_summary", {})
        rows.append({
            "case": case_title(item),
            "status": humanize(item.get("status")),
            "type": humanize(summary.get("document_type", "unknown")),
            "risk": humanize(item.get("review_checklist", {}).get("risk_level", "unknown")),
            "completeness": summary.get("data_completeness", 0),
            "low_confidence": summary.get("low_confidence_count", 0),
            "total_amount": summary.get("total_amount", 0),
            "period_values": summary.get("period_metric_count", 0),
            "visual_markers": summary.get("visual_markers_found", 0),
            "next_action": item.get("review", {}).get("next_action", ""),
        })
    return rows


def report_facts(case: Dict[str, Any]) -> Dict[str, Any]:
    summary = case.get("case_summary", {}) or {}
    fields = case.get("extraction", {}).get("fields", {}) or {}
    checklist = case.get("review_checklist", {}) or {}
    return {
        "Document Type": humanize(summary.get("document_type")),
        "Counterparty": fields.get("counterparty", {}).get("value"),
        "Document ID": fields.get("document_id_number", {}).get("value"),
        "Document Date": fields.get("document_date", {}).get("value"),
        "Service / Site": fields.get("service_or_site", {}).get("value"),
        "Category / Rate": fields.get("category_or_rate", {}).get("value"),
        "Total Amount": summary.get("total_amount"),
        "Period Values": summary.get("period_metric_count"),
        "Period Total": summary.get("period_metric_total"),
        "Completeness": f"{float(summary.get('data_completeness') or 0):.0%}",
        "Low Confidence Fields": summary.get("low_confidence_count"),
        "Visual Markers": summary.get("visual_markers_found"),
        "Risk": humanize(checklist.get("risk_level")),
    }


st.title("Local DocumentOps Automation")

try:
    health = api_get("/health")
except Exception as exc:
    st.error(f"Backend unavailable: {exc}")
    st.stop()

with st.sidebar:
    st.subheader("Context")
    company = st.text_input("Company / owner", value="")
    contact = st.text_input("Contact name", value="")
    email = st.text_input("Email", value="")
    department = st.text_input("Department", value="Operations")
    priority = st.selectbox("Priority", ["normal", "high", "urgent"], format_func=humanize)

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
high_risk = len(pipeline_df[pipeline_df["risk"] == "High"]) if not pipeline_df.empty else 0
material_total = pipeline_df["total_amount"].sum() if not pipeline_df.empty else 0

summary_cols = st.columns(5)
summary_cols[0].metric("Cases", len(cases))
summary_cols[1].metric("Needs Review", review_backlog)
summary_cols[2].metric("High Risk", high_risk)
summary_cols[3].metric("Avg Complete", f"{avg_completeness:.0%}")
summary_cols[4].metric("Total Amount", fmt_number(material_total, 0))

intake_tab, ops_tab, board_tab, review_tab, settings_tab, report_tab, audit_tab = st.tabs([
    "Intake",
    "Operations",
    "Status Board",
    "Review Queue",
    "Settings & Diff",
    "Report",
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
        demo_case = st.selectbox("Demo case", DEMO_CASES, format_func=humanize)
        if st.button("Generate demo with Qwen"):
            try:
                result = api_post(f"/demo/seed?case={demo_case}", timeout=240)
                st.session_state["selected_case_id"] = result.get("document_case", {}).get("case_id")
                st.success("Qwen demo case generated")
                st.rerun()
            except Exception as exc:
                st.error(f"Qwen demo generation failed: {exc}")
        signal_rows = [
            {"signal": "PDF text extraction", "status": "active"},
            {"signal": "Table extraction", "status": "active" if health.get("tables_enabled") else "off"},
            {"signal": "Vector search", "status": "active" if health.get("embeddings_enabled") else "off"},
            {"signal": "QR/stamp/signature/logo detection", "status": "local heuristic"},
        ]
        st.dataframe(display_rows(signal_rows), width='stretch', hide_index=True)

with ops_tab:
    st.subheader("Operations Dashboard")
    if not pipeline_df.empty:
        chart_left, chart_right = st.columns(2)
        chart_left.bar_chart(pipeline_df.groupby("status").size().reindex(STATUS_FLOW, fill_value=0))
        chart_right.bar_chart(pipeline_df.groupby("risk").size())
        st.markdown("#### Case Pipeline")
        pipeline_view = pipeline_df.sort_values(["status", "risk", "low_confidence"], ascending=[True, True, False])
        pipeline_view = pipeline_view.rename(columns={column: humanize(column) for column in pipeline_view.columns})
        st.dataframe(pipeline_view, width='stretch', hide_index=True)
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
                    <strong>{case_title(item)}</strong><br>
                    <span class="muted">{str(item.get('case_id'))[:8]}</span><br>
                    {badge(humanize(risk).upper(), risk_tone(risk))}<br><br>
                    <span class="muted">{humanize(summary.get('document_type', 'unknown'))}</span><br>
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
        title_cols = st.columns([3, 1])
        title_cols[0].markdown(f"#### {case_title(selected)}")
        if title_cols[1].button("Name with Qwen", key=f"title_{selected['case_id']}"):
            try:
                updated = api_post(f"/cases/{selected['case_id']}/title?actor=streamlit", timeout=180)
                st.session_state["selected_case_id"] = updated.get("case_id")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not generate case name: {exc}")

        summary = selected.get("case_summary", {})
        risk = selected.get("review_checklist", {}).get("risk_level", "unknown")
        cols = st.columns(6)
        cols[0].metric("Type", humanize(summary.get("document_type", "unknown")))
        cols[1].metric("Completeness", f"{float(summary.get('data_completeness') or 0):.0%}")
        cols[2].metric("Low Conf", summary.get("low_confidence_count", 0))
        cols[3].metric("Markers", summary.get("visual_markers_found", 0))
        cols[4].metric("Amount", fmt_number(summary.get("total_amount"), 0))
        cols[5].markdown(f"Risk<br>{badge(humanize(risk).upper(), risk_tone(risk))}", unsafe_allow_html=True)

        low_conf = selected.get("review", {}).get("low_confidence_fields", [])
        if low_conf:
            st.warning(f"{len(low_conf)} field(s) need review.")
            st.dataframe(display_rows(low_conf), width='stretch', hide_index=True)
        else:
            st.success("No low-confidence fields detected.")

        marker_types = selected.get("extraction", {}).get("visual_marker_types", {}) or {}
        if marker_types:
            st.dataframe(display_rows([{"marker": key, "count": value} for key, value in marker_types.items()]), width='stretch', hide_index=True)

        edit_left, edit_right = st.columns([1.1, 1])
        with edit_left:
            st.markdown("#### Extracted Fields")
            edited_fields = st.data_editor(
                make_field_rows(selected.get("extraction", {}).get("fields", {})),
                width='stretch',
                hide_index=True,
                num_rows="dynamic",
                column_config={"field_key": None, "field": st.column_config.TextColumn("Field")},
                key=f"fields_{selected['case_id']}",
            )
        with edit_right:
            st.markdown("#### Structured Metrics")
            edited_metrics = st.data_editor(make_metric_rows(selected.get("extraction", {}).get("period_metrics", [])), width='stretch', hide_index=True, num_rows="dynamic", key=f"metrics_{selected['case_id']}")

        action_cols = st.columns([1.2, 1, 2])
        if action_cols[0].button("Save corrections", type="primary"):
            fields_payload = {}
            for _, row in edited_fields.iterrows():
                name = str(clean_cell(row.get("field_key")) or field_key(clean_cell(row.get("field"))) or "").strip()
                if name:
                    fields_payload[name] = {"value": clean_cell(row.get("value")), "confidence": float(row.get("confidence") or 1.0)}
            metrics_payload = []
            for _, row in edited_metrics.iterrows():
                period = str(clean_cell(row.get("period")) or "").strip().lower()
                if period:
                    metrics_payload.append({"period": period, "value": float(row.get("value") or 0), "unit": str(clean_cell(row.get("unit")) or "value").lower(), "confidence": float(row.get("confidence") or 1.0), "source": str(clean_cell(row.get("source")) or "manual").lower()})
            api_patch(f"/cases/{selected['case_id']}/extraction", {"fields": fields_payload, "period_metrics": metrics_payload, "actor": "streamlit"})
            st.rerun()

        status_index = STATUS_FLOW.index(selected.get("status", "New")) if selected.get("status") in STATUS_FLOW else 0
        new_status = action_cols[1].selectbox("Move status", STATUS_FLOW, index=status_index)
        note = action_cols[2].text_input("Status note", value="")
        if st.button("Update case status"):
            api_patch(f"/cases/{selected['case_id']}/status", {"status": new_status, "actor": "streamlit", "note": note})
            st.rerun()

        st.markdown("#### Review Checklist")
        st.dataframe(display_rows(selected.get("review_checklist", {}).get("checks", [])), width='stretch', hide_index=True)

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
            st.dataframe(display_rows(rows), width='stretch', hide_index=True)
        else:
            st.info("Create a settings or correction version to compare.")

with report_tab:
    st.subheader("Report")
    selected = select_case(cases, "report_case")
    if selected:
        facts = report_facts(selected)
        st.markdown("#### Verified Values Used")
        st.dataframe(pd.DataFrame([facts]), width='stretch', hide_index=True)

        report_key = f"ai_report_{selected['case_id']}"
        if st.button("Generate report with Qwen", type="primary"):
            try:
                result = api_post(f"/cases/{selected['case_id']}/report-text", timeout=180)
                st.session_state[report_key] = result.get("report_text", "")
                st.session_state[f"{report_key}_model"] = result.get("model", "")
            except Exception as exc:
                st.error(f"Qwen report failed: {exc}")

        report_text = st.session_state.get(report_key, "")
        if not report_text:
            st.info("Generate a report to review and download the Qwen-written version.")
        st.text_area("Report text", report_text, height=440)
        if report_text:
            filename = f"{case_title(selected).lower().replace(' ', '_').replace('/', '-')}_report.md"
            st.download_button(
                "Download report",
                data=report_text.encode("utf-8"),
                file_name=filename,
                mime="text/markdown",
            )

with audit_tab:
    st.subheader("Audit")
    selected = select_case(cases, "audit_case")
    if selected:
        audit = api_get(f"/cases/{selected['case_id']}/audit").get("events", [])
        if audit:
            st.dataframe(audit_rows(audit), width='stretch', hide_index=True)
        else:
            st.info("No audit events yet.")
