from typing import Any, Dict


def demo_document(case: str = "clean") -> Dict[str, Any]:
    cases = {
        "clean": _clean_bill,
        "messy": _messy_bill,
        "incomplete": _incomplete_bill,
    }
    return cases.get(case, _clean_bill)()


def demo_client_info(case: str = "clean") -> Dict[str, Any]:
    clients = {
        "clean": {
            "company": "Green Valley Foods Ltd",
            "name": "Amina Bello",
            "email": "amina.bello@example.com",
            "phone": "+234 000 000 0000",
        },
        "messy": {
            "company": "Atlantic Cold Storage",
            "name": "Kojo Mensah",
            "email": "ops@example.com",
            "phone": "+233 000 000 000",
        },
        "incomplete": {
            "company": "Riverbend Manufacturing",
            "name": "",
            "email": "",
            "phone": "",
        },
    }
    return clients.get(case, clients["clean"])


def demo_site_data(case: str = "clean") -> Dict[str, Any]:
    sites = {
        "clean": {
            "address": "Plot 42, Industrial Zone, Lagos",
            "country": "Nigeria",
            "usable_roof_area_m2": 4200,
        },
        "messy": {
            "address": "Tema Free Zone, Warehouse 7",
            "country": "Ghana",
            "usable_roof_area_m2": 5100,
        },
        "incomplete": {
            "address": "",
            "country": "",
            "usable_roof_area_m2": 0,
        },
    }
    return sites.get(case, sites["clean"])


def demo_assumptions(case: str = "clean") -> Dict[str, Any]:
    assumptions = {
        "clean": {
            "grid_tariff_per_kwh": 0.18,
            "ppa_rate_per_kwh": 0.125,
            "solar_yield_kwh_per_kwp_year": 1500,
            "target_offset_pct": 0.72,
            "system_derate_pct": 0.86,
            "capex_per_kwp": 790,
        },
        "messy": {
            "grid_tariff_per_kwh": 0.21,
            "ppa_rate_per_kwh": 0.135,
            "solar_yield_kwh_per_kwp_year": 1480,
            "target_offset_pct": 0.68,
            "system_derate_pct": 0.85,
            "capex_per_kwp": 820,
        },
        "incomplete": {
            "grid_tariff_per_kwh": 0.16,
            "ppa_rate_per_kwh": 0.12,
            "solar_yield_kwh_per_kwp_year": 1425,
            "target_offset_pct": 0.70,
            "system_derate_pct": 0.84,
            "capex_per_kwp": 800,
        },
    }
    return assumptions.get(case, assumptions["clean"])


def _clean_bill() -> Dict[str, Any]:
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
Current grid tariff: 0.18 per kWh
""".strip()
    monthly_rows = [["Month", "Consumption kWh"]] + [
        ["Jan", "42800"], ["Feb", "39600"], ["Mar", "44150"], ["Apr", "46220"],
        ["May", "48750"], ["Jun", "50300"], ["Jul", "52100"], ["Aug", "51800"],
        ["Sep", "49250"], ["Oct", "47100"], ["Nov", "45400"], ["Dec", "43800"],
    ]
    return _document("demo-utility-bill-clean", "demo_clean_utility_bill.pdf", text, monthly_rows, "DEMO-BILL-CLEAN-1048")


def _messy_bill() -> Dict[str, Any]:
    text = """
ATLANTIC COLD STORAGE - ELECTRICITY STATEMENT
Acct # ACS/7792-19      Meter No M-772910-AC
Rate class: MD Commercial
Supply Address - Tema Free Zone, Warehouse 7
Consumption history: Jan 61,400 kWh | Feb 58,900 kWh | Mar 63,150 kWh
Apr 65,800 kWh | May 70,100 kWh | Jun 73,250 kWh
Jul 76,400 kWh | Aug 75,950 kWh | Sep 72,600 kWh
Oct 69,500 kWh | Nov 66,200 kWh | Dec 64,750 kWh
Notes: cold-room load includes night operations and diesel backup events.
""".strip()
    monthly_rows = [["Billing Period", "Energy"], ["Jan", "61400"], ["Mar", "63150"], ["May", "70100"], ["Jul", "76400"], ["Sep", "72600"], ["Nov", "66200"]]
    return _document("demo-utility-bill-messy", "demo_messy_cold_storage_bill.pdf", text, monthly_rows, "DEMO-BILL-MESSY-7792")


def _incomplete_bill() -> Dict[str, Any]:
    text = """
Riverbend Manufacturing
Electricity invoice extract
Customer: Riverbend Manufacturing
Billing period: Q1 summary only
Jan 30200 kWh
Feb 28750 kWh
Mar 31400 kWh
Some pages missing from scanned PDF.
""".strip()
    monthly_rows = [["Month", "kWh"], ["Jan", "30200"], ["Feb", "28750"], ["Mar", "31400"]]
    return _document("demo-utility-bill-incomplete", "demo_incomplete_bill.pdf", text, monthly_rows, "DEMO-BILL-INCOMPLETE")


def _document(document_id: str, filename: str, text: str, monthly_rows: list, qr_text: str) -> Dict[str, Any]:
    return {
        "document_id": document_id,
        "filename": filename,
        "pages": 2,
        "metadata": {"source": "seeded_demo"},
        "qr_codes": [{"page": 1, "text": qr_text, "type": "qrcode"}],
        "tables": [{"page": 1, "rows": monthly_rows}],
        "chunks": [
            {"chunk_id": f"{document_id}-p1", "document_id": document_id, "filename": filename, "page": 1, "text": text},
        ],
    }