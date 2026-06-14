import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from demo_data import demo_client_info, demo_document, demo_metadata, demo_review_settings
from document_cases import DocumentCaseService
from report_pdf import build_case_report_pdf, build_generated_report_pdf


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


def test_contract_extraction_uses_preamble_and_key_terms(tmp_path):
    service = make_service(tmp_path)
    text = """
MUTUAL NON-DISCLOSURE AGREEMENT
Contract No.: NDA-2026-00391
Effective Date: June 14, 2026
This Mutual Non-Disclosure Agreement is entered into as of June 14, 2026, by and between:
DISCLOSING / RECEIVING PARTY A
DISCLOSING / RECEIVING PARTY B
Nexora Technologies, Inc.
a Delaware corporation
Meridian Consulting Group, LLC
a New York limited liability company
Each of the above is individually referred to herein as a Party.
Business Purpose: Evaluation of a potential technology licensing and co-development partnership between the Parties, including joint feasibility studies, technical due diligence, and commercial term negotiations.
3.1 Term. This Agreement shall commence on the Effective Date and shall remain in full force and effect for a period of three
(3) years, unless earlier terminated by either Party upon thirty (30) days prior written notice.
3.2 Survival. The obligations of confidentiality with respect to Confidential Information disclosed during the Term shall survive and remain in effect for a period of five (5) years following the date of termination or expiration. Obligations relating to trade secrets shall survive indefinitely.
3.3 Return or Destruction. Upon termination of this Agreement or upon written request by the Disclosing Party, the Receiving Party shall within fifteen (15) business days return or destroy all tangible materials.
7.1 Governing Law. This Agreement shall be governed by and construed in accordance with the laws of the State of Delaware. Any dispute shall be subject to the exclusive jurisdiction of the federal and state courts located in Wilmington, Delaware.
IN WITNESS WHEREOF
______________________________________
Authorized Signature
"""
    document = {
        "document_id": "nda-doc",
        "filename": "NDA_Agreement.pdf",
        "pages": 3,
        "qr_codes": [],
        "visual_markers": [],
        "tables": [],
        "chunks": [{"page": 1, "text": text}],
    }

    item = service.create_from_document(document=document, metadata={"owner": "Legal Ops"}, actor="test")
    fields = item["extraction"]["fields"]
    failed = item["review_checklist"]["failed_checks"]

    assert fields["document_id_number"]["value"] == "NDA-2026-00391"
    assert fields["counterparty"]["value"] == "Nexora Technologies, Inc; Meridian Consulting Group, LLC"
    assert fields["document_date"]["value"] == "June 14, 2026"
    assert fields["business_purpose"]["value"].startswith("Evaluation of a potential technology licensing")
    assert fields["term"]["value"] == "three (3) years"
    assert fields["survival_period"]["value"] == "five (5) years; Trade secrets survive indefinitely"
    assert "State of Delaware" in fields["governing_law"]["value"]
    assert fields["signature_status"]["value"] == "Signature blocks present; signatures not detected"
    assert "structured_values_found" not in failed
    assert item["case_summary"]["low_confidence_count"] == 0


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
    assert updated["metadata"]["suggested_filename"] == "maintenance_contract_review.pdf"
    assert service.get_case(item["case_id"])["metadata"]["display_title"] == "Maintenance Contract Review"
    assert any(event["action"] == "title_updated" for event in audit)


def test_ai_report_is_saved_and_audited(tmp_path):
    service = make_service(tmp_path)
    item = create_case(service, "invoice")

    updated = service.update_ai_report(
        item["case_id"],
        "## Executive Summary\nPrepared report.",
        "qwen3:8b",
        facts={"total_amount": 18450.75},
        actor="test",
    )
    audit = service.audit_log(item["case_id"])

    assert updated["ai_report"]["text"].startswith("## Executive Summary")
    assert updated["ai_report"]["model"] == "qwen3:8b"
    assert updated["ai_report"]["facts"]["total_amount"] == 18450.75
    assert any(event["action"] == "ai_report_generated" for event in audit)


def test_manual_correction_clears_stale_ai_report(tmp_path):
    service = make_service(tmp_path)
    item = create_case(service, "invoice")
    service.update_ai_report(item["case_id"], "Old report", "qwen3:8b", actor="test")

    updated = service.update_extraction(
        item["case_id"],
        {"fields": {"total_amount": {"value": 100, "confidence": 1.0}}},
        actor="reviewer",
    )

    assert "ai_report" not in updated


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


def test_utility_bill_extraction_respects_units_and_money_labels(tmp_path):
    service = make_service(tmp_path)
    document = {
        "document_id": "tricky-utility",
        "filename": "tricky_utility_bill.pdf",
        "pages": 2,
        "qr_codes": [],
        "visual_markers": [],
        "tables": [
            {
                "page": 1,
                "rows": [
                    ["ACCOUNT INFORMATION", "", "BILL SUMMARY", ""],
                    ["Customer Name", "James A. Thornton", "Account Number", "7842-1193-005"],
                    ["Service Address", "1847 Maple Grove Drive", "Bill Date", "June 10, 2026"],
                    ["", "Springfield, IL 62704", "Due Date", "June 30, 2026"],
                    ["Rate Class", "Residential R1", "Previous Balance", "$0.00"],
                ],
            },
            {
                "page": 2,
                "rows": [
                    ["Month", "Usage kWh", "Amount USD"],
                    ["Jan", "812", "$130.20"],
                    ["Feb", "744", "$119.40"],
                    ["Mar", "631", "$108.10"],
                ],
            },
            {
                "page": 2,
                "rows": [
                    ["TOTAL CURRENT CHARGES", "", "682 kWh", "$147.83"],
                ],
            },
        ],
        "chunks": [
            {
                "page": 1,
                "text": (
                    "Customer Name James A. Thornton Account Number 7842-1193-005 "
                    "Service Address 1847 Maple Grove Drive Bill Date June 10, 2026 "
                    "Due Date June 30, 2026 Rate Class Residential R1 "
                    "AMOUNT DUE BY JUNE 30, 2026 $147.83 "
                    "6-MONTH USAGE COMPARISON (kWh) Jan '26 812 Feb '26 744 Mar '26 631 "
                    "Apr '26 503 May '26 589 Jun '26 682 PAYMENT OPTIONS Phone 1-800-555-4743"
                ),
            }
        ],
    }

    item = service.create_from_document(document=document, metadata={"owner": "Test"}, actor="test")
    fields = item["extraction"]["fields"]
    metrics = item["extraction"]["period_metrics"]

    assert fields["document_id_number"]["value"] == "7842-1193-005"
    assert fields["counterparty"]["value"] == "James A. Thornton"
    assert fields["document_date"]["value"] == "June 10, 2026"
    assert fields["service_or_site"]["value"] == "1847 Maple Grove Drive Springfield, IL 62704"
    assert fields["category_or_rate"]["value"] == "Residential R1"
    assert fields["total_amount"]["value"] == 147.83
    assert [row["period"] for row in metrics] == ["jan", "feb", "mar", "apr", "may", "jun"]
    assert [row["value"] for row in metrics] == [812, 744, 631, 503, 589, 682]
    assert {row["unit"] for row in metrics} == {"kwh"}
    assert item["case_summary"]["period_metric_total"] == 3961
    assert item["case_summary"]["total_amount"] == 147.83


def test_case_pdf_export(tmp_path):
    service = make_service(tmp_path)
    item = create_case(service, "contract")
    pdf_path = build_case_report_pdf(item, tmp_path / "reports")

    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    assert pdf_path.stat().st_size > 1000


def test_generated_report_pdf_export(tmp_path):
    service = make_service(tmp_path)
    item = create_case(service, "invoice")
    pdf_path = build_generated_report_pdf(item, "## Executive Summary\n- Total amount: 18,450.75", tmp_path / "reports")

    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    assert pdf_path.name.endswith("_report.pdf")
    assert len(pdf_path.name) < 90
    assert pdf_path.stat().st_size > 1000
