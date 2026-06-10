import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from demo_data import demo_assumptions, demo_client_info, demo_document, demo_site_data
from solar_proposal import SolarProposalService


def make_service(tmp_path):
    return SolarProposalService(tmp_path / "storage")


def test_demo_proposal_has_consumption_and_savings(tmp_path):
    service = make_service(tmp_path)

    proposal = service.create_from_document(
        document=demo_document(),
        client_info=demo_client_info(),
        site_data=demo_site_data(),
        assumptions=demo_assumptions(),
        actor="test",
    )

    assert proposal["extraction"]["document_type"] == "utility_bill"
    assert len(proposal["extraction"]["monthly_consumption"]) == 12
    assert proposal["calculation"]["annual_kwh"] == 561270
    assert proposal["calculation"]["estimated_system_size_kwp"] > 300
    assert proposal["calculation"]["estimated_annual_savings"] > 0
    assert proposal["versions"][0]["version_id"] == "v1"


def test_assumption_update_creates_version_and_diff(tmp_path):
    service = make_service(tmp_path)
    proposal = service.create_from_document(demo_document(), demo_client_info(), demo_site_data(), demo_assumptions())

    updated = service.update_assumptions(proposal["proposal_id"], {"ppa_rate_per_kwh": 0.10}, actor="test")
    diff = service.diff_versions(proposal["proposal_id"], "v1", "v2")

    assert len(updated["versions"]) == 2
    assert updated["versions"][-1]["label"] == "Assumption update"
    assert diff["calculation_delta"]["estimated_annual_savings"]["delta"] > 0


def test_manual_correction_recalculates_and_audits(tmp_path):
    service = make_service(tmp_path)
    proposal = service.create_from_document(demo_document(), demo_client_info(), demo_site_data(), demo_assumptions())
    monthly = [{"month": month, "kwh": 10000, "confidence": 1.0, "source": "manual"} for month in [
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"
    ]]

    updated = service.update_extraction(
        proposal["proposal_id"],
        {
            "fields": {"tariff": {"value": "Corrected Commercial TOU", "confidence": 0.98}},
            "monthly_consumption": monthly,
        },
        actor="reviewer",
    )
    audit = service.audit_log(proposal["proposal_id"])

    assert updated["calculation"]["annual_kwh"] == 120000
    assert updated["extraction"]["fields"]["tariff"]["value"] == "Corrected Commercial TOU"
    assert updated["versions"][-1]["label"] == "Manual correction"
    assert any(event["action"] == "extraction_corrected" for event in audit)