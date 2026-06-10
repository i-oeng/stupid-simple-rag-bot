from typing import Any, Dict


def demo_document() -> Dict[str, Any]:
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
    monthly_rows = [
        ["Month", "Consumption kWh"],
        ["Jan", "42800"],
        ["Feb", "39600"],
        ["Mar", "44150"],
        ["Apr", "46220"],
        ["May", "48750"],
        ["Jun", "50300"],
        ["Jul", "52100"],
        ["Aug", "51800"],
        ["Sep", "49250"],
        ["Oct", "47100"],
        ["Nov", "45400"],
        ["Dec", "43800"],
    ]
    return {
        "document_id": "demo-utility-bill-001",
        "filename": "demo_green_valley_utility_bill.pdf",
        "pages": 2,
        "metadata": {"source": "seeded_demo"},
        "qr_codes": [{"page": 1, "text": "DEMO-BILL-GVF-2026-1048", "type": "qrcode"}],
        "tables": [{"page": 1, "rows": monthly_rows}],
        "chunks": [
            {"chunk_id": "demo-001-p1", "document_id": "demo-utility-bill-001", "filename": "demo_green_valley_utility_bill.pdf", "page": 1, "text": text},
        ],
    }


def demo_client_info() -> Dict[str, Any]:
    return {
        "company": "Green Valley Foods Ltd",
        "name": "Amina Bello",
        "email": "amina.bello@example.com",
        "phone": "+234 000 000 0000",
    }


def demo_site_data() -> Dict[str, Any]:
    return {
        "address": "Plot 42, Industrial Zone, Lagos",
        "country": "Nigeria",
        "usable_roof_area_m2": 4200,
    }


def demo_assumptions() -> Dict[str, Any]:
    return {
        "grid_tariff_per_kwh": 0.18,
        "ppa_rate_per_kwh": 0.125,
        "solar_yield_kwh_per_kwp_year": 1500,
        "target_offset_pct": 0.72,
        "system_derate_pct": 0.86,
        "capex_per_kwp": 790,
    }