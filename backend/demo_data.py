from typing import Any, Dict


def demo_document(case: str = "utility_bill") -> Dict[str, Any]:
    cases = {
        "utility_bill": _utility_bill,
        "contract": _contract,
        "invoice": _invoice,
        "incomplete": _incomplete_document,
    }
    return cases.get(case, _utility_bill)()


def demo_client_info(case: str = "utility_bill") -> Dict[str, Any]:
    clients = {
        "utility_bill": {"company": "Green Valley Foods Ltd", "name": "Amina Bello", "email": "amina.bello@example.com"},
        "contract": {"company": "Atlantic Cold Storage", "name": "Kojo Mensah", "email": "ops@example.com"},
        "invoice": {"company": "Riverbend Manufacturing", "name": "Maya Chen", "email": "finance@example.com"},
        "incomplete": {"company": "Unassigned Review", "name": "", "email": ""},
    }
    return clients.get(case, clients["utility_bill"])


def demo_metadata(case: str = "utility_bill") -> Dict[str, Any]:
    metadata = {
        "utility_bill": {"owner": "Operations", "department": "Energy", "priority": "normal"},
        "contract": {"owner": "Legal Ops", "department": "Commercial", "priority": "high"},
        "invoice": {"owner": "Finance Ops", "department": "Accounts Payable", "priority": "normal"},
        "incomplete": {"owner": "Review Queue", "department": "Unknown", "priority": "high"},
    }
    return metadata.get(case, metadata["utility_bill"])


def demo_review_settings(case: str = "utility_bill") -> Dict[str, Any]:
    settings = {
        "utility_bill": {"materiality_amount": 10000, "confidence_threshold": 0.75, "review_sla_hours": 24, "currency": "USD", "require_visual_marker": False},
        "contract": {"materiality_amount": 50000, "confidence_threshold": 0.80, "review_sla_hours": 12, "currency": "USD", "require_visual_marker": True},
        "invoice": {"materiality_amount": 7500, "confidence_threshold": 0.75, "review_sla_hours": 24, "currency": "USD", "require_visual_marker": False},
        "incomplete": {"materiality_amount": 5000, "confidence_threshold": 0.85, "review_sla_hours": 8, "currency": "USD", "require_visual_marker": True},
    }
    return settings.get(case, settings["utility_bill"])


def _utility_bill() -> Dict[str, Any]:
    text = """
Green Valley Foods Ltd
Utility Bill / Electricity Invoice
Customer: Green Valley Foods Ltd
Account Number: GVF-2026-1048
Meter Number: MTR-8842091
Tariff: Commercial Time of Use
Service Address: Plot 42, Industrial Zone, Lagos
Billing Summary
Jan 42800 kWh
Feb 39600 kWh
Mar 44150 kWh
Apr 46220 kWh
May 48750 kWh
Jun 50300 kWh
Jul 52100 kWh
Aug 51800 kWh
Sep 49250 kWh
Oct 47100 kWh
Nov 45400 kWh
Dec 43800 kWh
Amount due: 101028.60
Due date: 06/30/2026
""".strip()
    rows = [["Month", "Value"], ["Jan", "42800"], ["Feb", "39600"], ["Mar", "44150"], ["Apr", "46220"], ["May", "48750"], ["Jun", "50300"], ["Jul", "52100"], ["Aug", "51800"], ["Sep", "49250"], ["Oct", "47100"], ["Nov", "45400"], ["Dec", "43800"]]
    return _document("demo-doc-utility-bill", "demo_utility_bill.pdf", text, rows, "DEMO-DOC-UTILITY", [
        {"page": 1, "kind": "logo_candidate", "confidence": 0.56, "bbox": {"x": 42, "y": 38, "width": 92, "height": 34}, "method": "seeded_demo"}
    ])


def _contract() -> Dict[str, Any]:
    text = """
Services Agreement
Contract Number: ACS-CON-2026-77
Party: Atlantic Cold Storage
Counterparty: Northline Maintenance Ltd
Effective Date: May 1, 2026
Expiry Date: April 30, 2028
Contract Value: 125000.00
Category: Facilities Maintenance
Project Site: Tema Free Zone, Warehouse 7
Payment term: net 30 days after approved invoice.
Termination: 60 days written notice.
""".strip()
    rows = [["Milestone", "Amount"], ["Mobilization", "25000"], ["Quarterly service", "25000"], ["Retention", "10000"]]
    return _document("demo-doc-contract", "demo_service_contract.pdf", text, rows, "DEMO-DOC-CONTRACT", [
        {"page": 2, "kind": "signature_candidate", "confidence": 0.72, "bbox": {"x": 320, "y": 680, "width": 150, "height": 38}, "method": "seeded_demo"},
        {"page": 2, "kind": "stamp_candidate", "confidence": 0.68, "bbox": {"x": 405, "y": 610, "width": 78, "height": 72}, "method": "seeded_demo"}
    ])


def _invoice() -> Dict[str, Any]:
    text = """
Vendor Invoice
Invoice Number: INV-88420
Vendor: Delta Components Ltd
Client: Riverbend Manufacturing
Invoice Date: 05/15/2026
Due Date: 06/15/2026
Cost Center: Operations Spares
Invoice total: 18450.75
Line items
Jan 6200 units
Feb 5800 units
Mar 6450 units
""".strip()
    rows = [["Line", "Amount"], ["Bearings", "7400.25"], ["Motors", "8100.50"], ["Logistics", "2950.00"]]
    return _document("demo-doc-invoice", "demo_vendor_invoice.pdf", text, rows, "DEMO-DOC-INVOICE", [
        {"page": 1, "kind": "logo_candidate", "confidence": 0.59, "bbox": {"x": 50, "y": 42, "width": 116, "height": 40}, "method": "seeded_demo"}
    ])


def _incomplete_document() -> Dict[str, Any]:
    text = """
Scanned operational document
Identifier page missing
Jan 30200
Feb 28750
Some pages missing from scanned PDF.
""".strip()
    rows = [["Month", "Value"], ["Jan", "30200"], ["Feb", "28750"]]
    return _document("demo-doc-incomplete", "demo_incomplete_operational_doc.pdf", text, rows, "DEMO-DOC-INCOMPLETE", [])


def _document(document_id: str, filename: str, text: str, rows: list, qr_text: str, visual_markers: list) -> Dict[str, Any]:
    return {
        "document_id": document_id,
        "filename": filename,
        "pages": 2,
        "metadata": {"source": "seeded_demo"},
        "qr_codes": [{"page": 1, "text": qr_text, "type": "qrcode"}],
        "visual_markers": visual_markers,
        "tables": [{"page": 1, "rows": rows}],
        "chunks": [
            {"chunk_id": f"{document_id}-p1", "document_id": document_id, "filename": filename, "page": 1, "text": text},
        ],
    }