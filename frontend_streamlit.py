import os
from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
STATUS_FLOW = ["New", "Parsed", "Needs Review", "Approved", "Sent"]

st.set_page_config(page_title="Solar Proposal Automation", layout="wide")
st.title("Solar Proposal Automation")


def api_get(path: str, **params):
    response = requests.get(f"{API_URL}{path}", params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def api_post(path: str, json: Dict[str, Any] | None = None, files=None, timeout=180):
    response = requests.post(f"{API_URL}{path}", json=json, files=files, timeout=timeout)
    response.raise_for_status()
    return response.json()


def api_patch(path: str, json: Dict[str, Any]):
    response = requests.patch(f"{API_URL}{path}", json=json, timeout=60)
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.header("Client")
    company = st.text_input("Company")
    contact = st.text_input("Contact name")
    email = st.text_input("Email")
    st.header("Site")
    address = st.text_input("Site address")
    country = st.text_input("Country / region")
    roof_area = st.number_input("Usable roof area m2", min_value=0.0, value=0.0, step=50.0)
    st.header("Core Assumptions")
    grid_tariff = st.number_input("Grid tariff per kWh", min_value=0.0, value=0.16, step=0.01)
    ppa_rate = st.number_input("PPA rate per kWh", min_value=0.0, value=0.115, step=0.005)
    yield_kwh = st.number_input("Solar yield kWh/kWp/year", min_value=1.0, value=1450.0, step=25.0)
    offset = st.slider("Target offset", min_value=0.1, max_value=1.0, value=0.75, step=0.05)

st.caption(f"Backend: {API_URL}")

try:
    health = api_get("/health")
    st.success(f"Backend healthy | mode={health.get('mode')} | model={health.get('ollama_model')}")
except Exception as exc:
    st.error(f"Backend unavailable: {exc}")
    st.stop()

st.subheader("Upload Bills and Create Proposal")
uploads = st.file_uploader("Upload utility bills, contracts, or financial docs", type=["pdf"], accept_multiple_files=True)
if st.button("Process uploads and create proposal", type="primary", disabled=not uploads):
    files = []
    for upload in uploads:
        files.append(("files", (upload.name, upload.getvalue(), "application/pdf")))
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
        st.success(f"Created {len(created)} proposal(s)")
        st.rerun()
    except Exception as exc:
        st.error(f"Processing failed: {exc}")

st.subheader("Proposal Status Board")
try:
    proposals = api_get("/solar/proposals").get("proposals", [])
except Exception as exc:
    st.error(f"Could not load proposals: {exc}")
    proposals = []

columns = st.columns(len(STATUS_FLOW))
for column, status in zip(columns, STATUS_FLOW):
    with column:
        st.markdown(f"**{status}**")
        for proposal in [p for p in proposals if p.get("status") == status]:
            calc = proposal.get("calculation", {})
            st.container(border=True).markdown(
                f"{proposal.get('client_info', {}).get('company') or proposal.get('source_filename')}\n\n"
                f"`{proposal.get('proposal_id')}`\n\n"
                f"{calc.get('estimated_system_size_kwp', 0):,.0f} kWp | savings {calc.get('estimated_annual_savings', 0):,.0f}"
            )

st.subheader("Proposal Detail")
if not proposals:
    st.info("No proposals yet. Upload a utility bill to create one.")
    st.stop()

proposal_options = {f"{p.get('source_filename')} | {p.get('proposal_id')}": p.get("proposal_id") for p in proposals}
selected_label = st.selectbox("Select proposal", list(proposal_options.keys()))
proposal_id = proposal_options[selected_label]
proposal = api_get(f"/solar/proposals/{proposal_id}")

calc = proposal.get("calculation", {})
metric_cols = st.columns(5)
metric_cols[0].metric("Annual kWh", f"{calc.get('annual_kwh', 0):,.0f}")
metric_cols[1].metric("System kWp", f"{calc.get('estimated_system_size_kwp', 0):,.1f}")
metric_cols[2].metric("Year 1 Production", f"{calc.get('year_one_production_kwh', 0):,.0f}")
metric_cols[3].metric("Annual Savings", f"{calc.get('estimated_annual_savings', 0):,.0f}")
metric_cols[4].metric("Risk", proposal.get("underwriting_checklist", {}).get("risk_level", "unknown"))

left, right = st.columns([2, 1])
with left:
    st.markdown("### Extracted Fields")
    fields = proposal.get("extraction", {}).get("fields", {})
    field_rows = [{"field": key, "value": value.get("value"), "confidence": value.get("confidence")} for key, value in fields.items()]
    st.dataframe(pd.DataFrame(field_rows), use_container_width=True)

    st.markdown("### Monthly Consumption")
    monthly = proposal.get("extraction", {}).get("monthly_consumption", [])
    st.dataframe(pd.DataFrame(monthly), use_container_width=True)

    st.markdown("### Proposal Draft")
    st.text_area("Draft", proposal.get("proposal_draft", ""), height=320)

with right:
    st.markdown("### Review")
    new_status = st.selectbox("Status", STATUS_FLOW, index=STATUS_FLOW.index(proposal.get("status", "New")) if proposal.get("status") in STATUS_FLOW else 0)
    note = st.text_input("Status note")
    if st.button("Update status"):
        api_patch(f"/solar/proposals/{proposal_id}/status", {"status": new_status, "actor": "streamlit", "note": note})
        st.rerun()

    st.markdown("### Assumptions")
    current = proposal.get("assumptions", {})
    new_grid = st.number_input("Grid tariff", value=float(current.get("grid_tariff_per_kwh", 0.16)), step=0.01, key="detail_grid")
    new_ppa = st.number_input("PPA rate", value=float(current.get("ppa_rate_per_kwh", 0.115)), step=0.005, key="detail_ppa")
    new_yield = st.number_input("Solar yield", value=float(current.get("solar_yield_kwh_per_kwp_year", 1450)), step=25.0, key="detail_yield")
    new_offset = st.slider("Target offset", 0.1, 1.0, float(current.get("target_offset_pct", 0.75)), step=0.05, key="detail_offset")
    if st.button("Recalculate version"):
        api_patch(
            f"/solar/proposals/{proposal_id}/assumptions",
            {
                "actor": "streamlit",
                "assumptions": {
                    "grid_tariff_per_kwh": new_grid,
                    "ppa_rate_per_kwh": new_ppa,
                    "solar_yield_kwh_per_kwp_year": new_yield,
                    "target_offset_pct": new_offset,
                },
            },
        )
        st.rerun()

    versions = proposal.get("versions", [])
    if len(versions) >= 2:
        st.markdown("### Version Diff")
        left_version = st.selectbox("Left", [v["version_id"] for v in versions], index=0)
        right_version = st.selectbox("Right", [v["version_id"] for v in versions], index=len(versions) - 1)
        if st.button("Compare"):
            diff = api_get(f"/solar/proposals/{proposal_id}/diff", left=left_version, right=right_version)
            st.json(diff.get("calculation_delta", {}))

st.markdown("### Underwriting Checklist")
checklist = proposal.get("underwriting_checklist", {}).get("checks", [])
st.dataframe(pd.DataFrame(checklist), use_container_width=True)

with st.expander("Audit log"):
    audit = api_get(f"/solar/proposals/{proposal_id}/audit").get("events", [])
    st.dataframe(pd.DataFrame(audit), use_container_width=True)