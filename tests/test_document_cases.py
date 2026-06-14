import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from demo_data import demo_client_info, demo_document, demo_metadata, demo_review_settings
from document_cases import DocumentCaseService
from report_pdf import build_case_report_pdf


def make_service(tmp_path):
    return DocumentCaseService(tmp_path / "storage")


def create_case(service, case="utility_bill"):
    return service.create_from_document(
        document=demo_document(case),
        client_info=demo_client_info(case),
        metadata=demo_metadata(case),
        review_settings=demo_review_settings(case),
        actor="test",
    )


def test_demo_utility_bill_case_has_extraction_and_summary(tmp_path):
    service = make_service(tmp_path)
    item = create_case(service, "utility_bill")

    assert item["extraction"]["document_type"] == "utility_bill"
    assert len(item["extraction"]["period_metrics"]) == 12
    assert item["case_summary"]["period_metric_total"] == 561270
    assert item["case_summary"]["total_amount"] == 101028.60
    assert item["case_summary"]["visual_markers_found"] == 1
    assert item["extraction"]["visual_marker_types"] == {"logo_candidate": 1}
    assert item["versions"][0]["version_id"] == "v1"


def test_demo_variants_cover_contract_invoice_and_incomplete(tmp_path):
    service = make_service(tmp_path)
    contract = create_case(service, "contract")
    invoice = create_case(service, "invoice")
    incomplete = create_case(service, "incomplete")

    assert contract["extraction"]["document_type"] == "contract"
    assert contract["case_summary"]["visual_markers_found"] == 2
    assert invoice["extraction"]["document_type"] == "invoice"
    assert incomplete["review_checklist"]["risk_level"] == "high"
    assert "visual_marker_requirement" in incomplete["review_checklist"]["failed_checks"]


def test_settings_update_creates_version_and_diff(tmp_path):
    service = make_service(tmp_path)
    item = create_case(service, "invoice")

    updated = service.update_settings(item["case_id"], {"materiality_amount": 1000}, actor="test")
    diff = service.diff_versions(item["case_id"], "v1", "v2")

    assert len(updated["versions"]) == 2
    assert updated["versions"][-1]["label"] == "Review setting update"
    assert "materiality_flag" in diff["summary_delta"]


def test_title_update_is_saved_and_audited(tmp_path):
    service = make_service(tmp_path)
    item = create_case(service, "contract")

    updated = service.update_title(item["case_id"], "Maintenance Contract Review", actor="test")
    audit = service.audit_log(item["case_id"])

    assert updated["metadata"]["display_title"] == "Maintenance Contract Review"
    assert service.get_case(item["case_id"])["metadata"]["display_title"] == "Maintenance Contract Review"
    assert any(event["action"] == "title_updated" for event in audit)


def test_manual_correction_recalculates_and_audits(tmp_path):
    service = make_service(tmp_path)
    item = create_case(service, "incomplete")
    metrics = [{"period": "jan", "value": 100, "unit": "units", "confidence": 1.0, "source": "manual"}]

    updated = service.update_extraction(
        item["case_id"],
        {
            "fields": {"document_id_number": {"value": "DOC-001", "confidence": 0.99}},
            "period_metrics": metrics,
        },
        actor="reviewer",
    )
    audit = service.audit_log(item["case_id"])

    assert updated["extraction"]["fields"]["document_id_number"]["value"] == "DOC-001"
    assert updated["case_summary"]["period_metric_total"] == 100
    assert updated["versions"][-1]["label"] == "Manual correction"
    assert any(event["action"] == "extraction_corrected" for event in audit)


def test_case_pdf_export(tmp_path):
    service = make_service(tmp_path)
    item = create_case(service, "contract")
    pdf_path = build_case_report_pdf(item, tmp_path / "reports")

    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    assert pdf_path.stat().st_size > 1000
