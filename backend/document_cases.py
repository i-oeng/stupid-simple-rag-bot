import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MONTHS = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]
MONTH_RE = re.compile(
    r"(?i)\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r")\b"
)
MONTH_LOOKAHEAD_RE = (
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
)
EXPLICIT_USAGE_RE = re.compile(
    r"(?i)(?<![\w/$])([0-9][0-9,]*(?:\.[0-9]+)?)\s*(kwh|kw\s*h|kwhr|mwh|wh|units?|unit)\b"
)
USAGE_CONTEXT_RE = re.compile(r"(?i)\b(kwh|kw\s*h|kwhr|mwh|wh|usage|consumption|energy|billed usage|metered usage|units?)\b")
MONEY_CONTEXT_RE = re.compile(
    r"(?i)([$\u20ac\u00a3\u20a6]|\b(?:amount|total|due|balance|charge|cost|tax|vat|subtotal|invoice|contract|payment|paid|fee|surcharge|usd|ngn|ghs|kes|zar|eur|gbp)\b)"
)
MONEY_AMOUNT_RE = re.compile(
    r"(?i)(?:[$\u20ac\u00a3\u20a6]\s*[-\u2013]?\s*[0-9][0-9,]*(?:\.[0-9]{1,4})?|"
    r"\b(?:usd|ngn|ghs|kes|zar|eur|gbp)\s*[-\u2013]?\s*[0-9][0-9,]*(?:\.[0-9]{1,4})?|"
    r"[-\u2013]?\s*[0-9][0-9,]*(?:\.[0-9]{1,4})?\s*(?:usd|ngn|ghs|kes|zar|eur|gbp)\b)"
)
DATE_RE = re.compile(r"(?i)\b(?:date|due date|effective date|expiry date|contract date)\s*[:#-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4}|[a-z]{3,9}\s+[0-9]{1,2},?\s+[0-9]{4})")
NUMBER_RE = re.compile(r"[0-9][0-9, .]*")
STRICT_NUMBER_RE = re.compile(r"(?<![\w])[-+]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?")
LABEL_STOP_TERMS = [
    "account information", "bill summary", "customer name", "customer", "client", "vendor", "supplier",
    "counterparty", "party", "name", "account number", "account no", "invoice number", "invoice no",
    "contract number", "document id", "reference", "ref", "service address", "supply address",
    "site address", "delivery address", "project site", "bill date", "invoice date", "due date",
    "effective date", "expiry date", "contract date", "date", "rate class", "tariff", "plan",
    "category", "department", "cost center", "previous balance", "current charges", "amount due",
    "invoice total", "contract value", "billing period", "meter number", "payment options",
]
MONEY_LABELS = [
    "amount due", "total amount due", "amount due by", "balance due", "total due", "invoice total",
    "grand total", "total current charges", "current charges", "contract value", "amount payable",
    "total payable", "subtotal",
]
LABEL_PRIORITY = {label: index for index, label in enumerate(MONEY_LABELS)}

DEFAULT_REVIEW_SETTINGS: Dict[str, Any] = {
    "materiality_amount": 10000,
    "confidence_threshold": 0.75,
    "review_sla_hours": 24,
    "currency": "USD",
    "require_identifier": True,
    "require_counterparty": True,
    "require_date_or_term": True,
    "require_visual_marker": False,
}

STATUS_FLOW = ["New", "Parsed", "Needs Review", "Approved", "Sent"]
LOW_CONFIDENCE_THRESHOLD = 0.75


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocumentCaseService:
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.cases_path = storage_dir / "document_cases.json"
        self.audit_path = storage_dir / "case_audit_log.json"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def default_settings(self) -> Dict[str, Any]:
        return deepcopy(DEFAULT_REVIEW_SETTINGS)

    def create_from_document(
        self,
        document: Dict[str, Any],
        client_info: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        review_settings: Optional[Dict[str, Any]] = None,
        actor: str = "system",
    ) -> Dict[str, Any]:
        if not document:
            raise ValueError("Document not found")

        case_id = uuid.uuid4().hex
        settings = self.default_settings()
        if review_settings:
            settings.update({k: v for k, v in review_settings.items() if v is not None})

        extraction = self.extract_fields(document)
        summary = self.build_case_summary(extraction, settings)
        checklist = self.build_review_checklist(extraction, summary, client_info or {}, metadata or {}, settings)
        report = self.generate_report(case_id, document, client_info or {}, metadata or {}, extraction, summary, checklist)
        low_confidence = self.low_confidence_fields(extraction, settings)
        status = "Needs Review" if low_confidence or checklist["risk_level"] != "low" else "Parsed"

        case = {
            "case_id": case_id,
            "status": status,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "document_id": document.get("document_id"),
            "source_filename": document.get("filename"),
            "client_info": client_info or {},
            "metadata": metadata or {},
            "review_settings": settings,
            "extraction": extraction,
            "case_summary": summary,
            "review_checklist": checklist,
            "generated_report": report,
            "versions": [
                {
                    "version_id": "v1",
                    "created_at": utc_now(),
                    "label": "Initial case",
                    "review_settings": deepcopy(settings),
                    "case_summary": deepcopy(summary),
                }
            ],
            "review": {
                "low_confidence_fields": low_confidence,
                "next_action": "Review low-confidence fields and missing checklist items" if status == "Needs Review" else "Ready for approval",
            },
        }
        self._save_case(case)
        self._audit(case_id, actor, "created", {"status": status, "document_id": document.get("document_id")})
        return case

    def extract_fields(self, document: Dict[str, Any]) -> Dict[str, Any]:
        text = "\n".join(chunk.get("text", "") for chunk in document.get("chunks", []))
        tables = document.get("tables", [])
        lower_text = text.lower()
        document_type = self._detect_document_type(lower_text)
        metrics = self._extract_period_metrics(text, tables)
        total_amount = self._extract_money(text, tables)
        line_items: List[Dict[str, Any]] = []
        if document_type == "contract":
            fields = self._extract_contract_fields(text, tables)
        elif document_type == "invoice":
            fields, line_items = self._extract_invoice_fields(text, tables, total_amount)
        else:
            fields = self._extract_operational_fields(text, tables, total_amount)
        return {
            "document_type": document_type,
            "fields": fields,
            "period_metrics": metrics,
            "line_items": line_items,
            "tables_found": len(tables),
            "qr_codes_found": len(document.get("qr_codes", [])),
            "visual_markers_found": len(document.get("visual_markers", [])),
            "visual_marker_types": self._marker_counts(document.get("visual_markers", [])),
            "confidence_summary": {
                "overall": self._overall_confidence(fields, metrics),
                "low_confidence_count": len([item for item in fields.values() if item.get("confidence", 0) < LOW_CONFIDENCE_THRESHOLD]),
            },
        }

    def _extract_operational_fields(self, text: str, tables: List[Dict[str, Any]], total_amount: Optional[float]) -> Dict[str, Dict[str, Any]]:
        date_value = self._find_value(text, tables, ["invoice date", "bill date", "effective date", "contract date", "due date", "expiry date", "date"])
        if not date_value:
            match = DATE_RE.search(text)
            date_value = match.group(1).strip() if match else None
        return {
            "document_id_number": self._field(self._find_value(text, tables, ["document id", "reference", "ref", "invoice number", "invoice no", "contract number", "account number", "account no"]), 0.76),
            "counterparty": self._field(self._find_value(text, tables, ["customer name", "customer", "client", "vendor", "supplier", "counterparty", "party", "name"]), 0.64),
            "document_date": self._field(date_value, 0.68),
            "service_or_site": self._field(self._find_value(text, tables, ["service address", "supply address", "site address", "delivery address", "project site"], allow_continuation=True), 0.58),
            "category_or_rate": self._field(self._find_value(text, tables, ["tariff", "rate class", "plan", "category", "department", "cost center"]), 0.60),
            "total_amount": self._field(total_amount, 0.88 if total_amount else 0.25),
        }

    def _extract_invoice_fields(self, text: str, tables: List[Dict[str, Any]], total_amount: Optional[float]) -> tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        line_items = self._extract_invoice_line_items(text, tables)
        subtotal = self._invoice_money_value(text, "subtotal")
        tax_amount = self._invoice_money_value(text, "tax")
        fields = {
            "document_id_number": self._field(self._invoice_identifier(text), 0.94),
            "vendor": self._field(self._invoice_vendor(text), 0.88),
            "counterparty": self._field(self._invoice_bill_to(text), 0.90),
            "document_date": self._field(self._invoice_date(text, "issue date") or self._invoice_date(text, "invoice date"), 0.92),
            "due_date": self._field(self._invoice_date(text, "due date"), 0.92),
            "service_or_site": self._field(self._invoice_billing_address(text), 0.76),
            "category_or_rate": self._field(self._invoice_category(line_items), 0.82),
            "subtotal": self._field(subtotal, 0.88 if subtotal is not None else 0.25),
            "tax_amount": self._field(tax_amount, 0.86 if tax_amount is not None else 0.25),
            "total_amount": self._field(total_amount, 0.92 if total_amount else 0.25),
            "payment_reference": self._field(self._invoice_payment_reference(text), 0.88),
            "payment_account": self._field(self._invoice_payment_account(text), 0.82),
        }
        return fields, line_items

    def _invoice_identifier(self, text: str) -> Optional[str]:
        return self._first_match(text, [
            r"(?im)^\s*invoice\s*(?:no\.?|number|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})\s*$",
            r"(?im)^\s*reference\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})\s*$",
        ])

    def _invoice_vendor(self, text: str) -> Optional[str]:
        for raw_line in text.splitlines()[:12]:
            line = self._clean_value(raw_line)
            if line and not re.search(r"(?i)^(invoice|bill to|issue date|due date|invoice no|description|qty|unit price|amount)$", line):
                return line.strip(" .")
        return None

    def _invoice_bill_to(self, text: str) -> Optional[str]:
        block = self._block_after_heading(text, "bill to", stop_headings=["description", "payment details", "notes"])
        if not block:
            return None
        for raw_line in block.splitlines():
            line = self._clean_value(raw_line)
            if line and not line.lower().startswith("attn:"):
                return line.strip(" .")
        return None

    def _invoice_billing_address(self, text: str) -> Optional[str]:
        block = self._block_after_heading(text, "bill to", stop_headings=["description", "payment details", "notes"])
        if not block:
            return None
        parts = []
        for raw_line in block.splitlines()[1:]:
            line = self._clean_value(raw_line)
            if line and not line.lower().startswith("attn:"):
                parts.append(line)
        return " ".join(parts[:3]) or None

    def _invoice_date(self, text: str, label: str) -> Optional[str]:
        return self._first_match(text, [rf"(?im)^\s*{re.escape(label)}\s*[:#-]?\s*([A-Z][a-z]+\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}})\s*$"])

    def _invoice_money_value(self, text: str, label: str) -> Optional[float]:
        pattern = re.compile(rf"(?im)^\s*{re.escape(label)}(?:\s*\([^)]*\))?\s*[:#-]?\s*([$???]?\s*[0-9][0-9,]*(?:\.[0-9]{{2}})?)\s*$")
        match = pattern.search(text)
        return self._parse_number(match.group(1)) if match else None

    def _invoice_payment_reference(self, text: str) -> Optional[str]:
        block = self._block_after_heading(text, "payment details", stop_headings=["notes", "description", "bill to"])
        search_text = block or text
        return self._first_match(search_text, [r"(?im)^\s*reference\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})\s*$"])

    def _invoice_payment_account(self, text: str) -> Optional[str]:
        block = self._block_after_heading(text, "payment details", stop_headings=["notes", "description", "bill to"])
        search_text = block or text
        return self._first_match(search_text, [r"(?im)^\s*account\s+no\.?\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})\s*$"])

    def _invoice_category(self, line_items: List[Dict[str, Any]]) -> Optional[str]:
        if not line_items:
            return None
        descriptions = " ".join(str(item.get("description", "")) for item in line_items).lower()
        if any(term in descriptions for term in ["design", "logo", "ui", "ux", "illustration", "animation", "brand"]):
            return "Design services"
        if any(term in descriptions for term in ["consulting", "retainer", "support"]):
            return "Professional services"
        return "Invoice services"

    def _extract_invoice_line_items(self, text: str, tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        lines = [self._clean_value(line) for line in text.splitlines()]
        lines = [line for line in lines if line]
        try:
            start = next(index for index, line in enumerate(lines) if self._label_key(line) == "description")
        except StopIteration:
            return self._line_items_from_tables(tables)
        while start < len(lines) and self._label_key(lines[start]) != "amount":
            start += 1
        start += 1
        end = next((index for index in range(start, len(lines)) if self._label_key(lines[index]).startswith("subtotal")), len(lines))
        items: List[Dict[str, Any]] = []
        description_parts: List[str] = []
        index = start
        while index < end:
            line = lines[index]
            if re.fullmatch(r"\d+(?:\.\d+)?", line) and index + 2 < end and self._money_from_snippet(lines[index + 1]) is not None and self._money_from_snippet(lines[index + 2]) is not None:
                description = self._clean_value(" ".join(description_parts))
                quantity = self._parse_number(line) or 0
                unit_price = self._money_from_snippet(lines[index + 1]) or 0
                amount = self._money_from_snippet(lines[index + 2]) or 0
                if description:
                    items.append({
                        "description": description,
                        "quantity": int(quantity) if float(quantity).is_integer() else quantity,
                        "unit_price": round(unit_price, 2),
                        "amount": round(amount, 2),
                        "confidence": 0.90,
                        "source": "invoice_text",
                    })
                description_parts = []
                index += 3
                continue
            description_parts.append(line)
            index += 1
        return items or self._line_items_from_tables(tables)

    def _line_items_from_tables(self, tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for table in tables:
            for row in table.get("rows", []):
                text = self._clean_value(" ".join(self._clean_cell(cell) for cell in row))
                amounts = [self._parse_number(match.group(0)) for match in MONEY_AMOUNT_RE.finditer(text)]
                amounts = [amount for amount in amounts if amount is not None]
                quantity = next((self._parse_number(match.group(0)) for match in STRICT_NUMBER_RE.finditer(text) if "$" not in match.group(0)), None)
                if len(amounts) >= 2 and quantity:
                    description = re.split(r"\d+(?:\.\d+)?\s*[$???]", text, maxsplit=1)[0]
                    items.append({
                        "description": self._clean_value(description),
                        "quantity": int(quantity) if float(quantity).is_integer() else quantity,
                        "unit_price": round(amounts[-2], 2),
                        "amount": round(amounts[-1], 2),
                        "confidence": 0.76,
                        "source": "invoice_table",
                    })
        return [item for item in items if item.get("description")]

    def _block_after_heading(self, text: str, heading: str, stop_headings: List[str]) -> Optional[str]:
        lines = text.splitlines()
        start = None
        heading_key = self._label_key(heading)
        stop_keys = {self._label_key(item) for item in stop_headings}
        for index, line in enumerate(lines):
            if self._label_key(line) == heading_key:
                start = index + 1
                break
        if start is None:
            return None
        collected = []
        for line in lines[start:]:
            key = self._label_key(line)
            if key in stop_keys:
                break
            collected.append(line)
        return "\n".join(collected).strip() or None

    def _extract_contract_fields(self, text: str, tables: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        fields: Dict[str, Dict[str, Any]] = {
            "document_id_number": self._field(self._contract_identifier(text) or self._find_value(text, tables, ["contract number", "contract no", "contract reference", "contract ref", "reference"]), 0.92),
            "counterparty": self._field(self._contract_parties(text) or self._find_value(text, tables, ["counterparty", "party"]), 0.90),
            "document_date": self._field(self._contract_effective_date(text) or self._find_value(text, tables, ["effective date", "contract date", "date"]), 0.90),
            "business_purpose": self._field(self._business_purpose(text), 0.86),
            "term": self._field(self._contract_term(text), 0.84),
            "survival_period": self._field(self._survival_period(text), 0.82),
            "return_or_destruction": self._field(self._return_or_destruction(text), 0.82),
            "governing_law": self._field(self._governing_law(text), 0.84),
            "signature_status": self._field(self._signature_status(text), 0.76),
        }
        total_amount = self._extract_money(text, tables)
        if total_amount is not None:
            fields["total_amount"] = self._field(total_amount, 0.88)
        return fields

    def _contract_identifier(self, text: str) -> Optional[str]:
        patterns = [
            r"(?i)contract\s+(?:reference\s+)?(?:no\.?|number|ref\.?)\s*[:#.-]?\s*([A-Z0-9][A-Z0-9-]{3,})",
            r"(?i)contract\s+reference\s+no\.?\s*[:#.-]?\s*([A-Z0-9][A-Z0-9-]{3,})",
        ]
        return self._first_match(text, patterns)

    def _contract_effective_date(self, text: str) -> Optional[str]:
        return self._first_match(text, [
            r"(?i)effective\s+date\s*[:#.-]?\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"(?i)effective\s*[:#.-]?\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        ])

    def _contract_parties(self, text: str) -> Optional[str]:
        block_match = re.search(r"(?is)by\s+and\s+between:\s*(.*?)(?:\bEach\s+of\s+the\s+above\b|\bRECITALS\b)", text)
        block = block_match.group(1) if block_match else text[:1800]
        parties: List[str] = []
        company_re = re.compile(r"(?i)\b(?:inc\.?|llc|ltd\.?|limited|corp\.?|corporation|company|group|partners|technologies|consulting)\b")
        skip_re = re.compile(r"(?i)^(disclosing|receiving|party\s+[ab]|a\s+(?:delaware|new\s+york)\b|page\s+|contract\s+|effective|confidential|mutual|and\s+confidentiality)")
        for raw_line in block.splitlines():
            line = self._clean_value(raw_line)
            if not line or skip_re.search(line):
                continue
            if company_re.search(line) and not re.search(r"\d", line):
                cleaned = line.strip(" .")
                if cleaned not in parties:
                    parties.append(cleaned)
            if len(parties) >= 4:
                break
        return "; ".join(parties[:4]) if parties else None

    def _business_purpose(self, text: str) -> Optional[str]:
        matches = list(re.finditer(r"(?is)Business\s+Purpose\s*:\s*(.*?)(?:\n[A-Z][A-Z /&-]{3,}\n|\nIN\s+WITNESS|$)", text))
        if matches:
            return self._clean_clause(matches[-1].group(1), 360)
        match = re.search(r'(?is)collaboration\s+involving\s+(.*?)(?:\(the\s+"Business Purpose"\)|\.)', text)
        return self._clean_clause(match.group(0), 260) if match else None

    def _contract_term(self, text: str) -> Optional[str]:
        return self._clean_clause(self._first_match(text, [
            r"(?is)remain\s+in\s+full\s+force\s+and\s+effect\s+for\s+a\s+period\s+of\s+(.{1,100}?years?)(?:,|\.)",
            r"(?is)Term\.\s*(.*?)(?:\n3\.2|\n\d+\.\d+|$)",
        ]), 260)

    def _survival_period(self, text: str) -> Optional[str]:
        clause = self._first_match(text, [r"(?is)obligations\s+of\s+confidentiality\s+with\s+respect\s+to\s+Confidential\s+Information\s+disclosed\s+during\s+the\s+Term\s+shall\s+survive\s+and\s+remain\s+in\s+effect\s+for\s+a\s+period\s+of\s+(.{1,120}?years?)(?:\s+following|,|\.)"])
        trade_secret = "Trade secrets survive indefinitely" if re.search(r"(?i)trade\s+secrets\s+shall\s+survive\s+indefinitely", text) else None
        parts = [part for part in [self._clean_clause(clause, 180), trade_secret] if part]
        return "; ".join(parts) if parts else None

    def _return_or_destruction(self, text: str) -> Optional[str]:
        clause = self._first_match(text, [r"(?is)Return\s+or\s+Destruction\.\s*(.*?)(?:\n4\.|\n\d+\.\d+|$)"])
        return self._clean_clause(clause, 420)

    def _governing_law(self, text: str) -> Optional[str]:
        clause = self._first_match(text, [r"(?is)Governing\s+Law\.\s*(.*?)(?:\n7\.2|\n\d+\.\d+|$)"])
        return self._clean_clause(clause, 420)

    def _signature_status(self, text: str) -> Optional[str]:
        if re.search(r"(?i)authorized\s+signature", text):
            has_blank_lines = "________________________________" in text
            return "Signature blocks present; signatures not detected" if has_blank_lines else "Signature blocks present"
        return None

    def _first_match(self, text: str, patterns: List[str]) -> Optional[str]:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return self._clean_value(match.group(1))
        return None

    def _clean_clause(self, value: Optional[str], limit: int) -> Optional[str]:
        cleaned = self._clean_value(value)
        if not cleaned:
            return None
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
        return cleaned[:limit].rstrip(" ,;")

    def build_case_summary(self, extraction: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
        metrics = extraction.get("period_metrics", [])
        metric_total = sum(float(row.get("value", 0)) for row in metrics)
        total_amount = extraction.get("fields", {}).get("total_amount", {}).get("value") or 0
        low_confidence = self.low_confidence_fields(extraction, settings)
        data_completeness = self._data_completeness(extraction)
        return {
            "document_type": extraction.get("document_type", "unknown"),
            "period_metric_count": len(metrics),
            "period_metric_total": round(metric_total, 2),
            "line_item_count": len(extraction.get("line_items", [])),
            "total_amount": round(float(total_amount or 0), 2),
            "data_completeness": data_completeness,
            "low_confidence_count": len(low_confidence),
            "materiality_flag": bool(total_amount and float(total_amount) >= float(settings.get("materiality_amount", 0))),
            "qr_codes_found": extraction.get("qr_codes_found", 0),
            "visual_markers_found": extraction.get("visual_markers_found", 0),
            "visual_marker_types": extraction.get("visual_marker_types", {}),
            "tables_found": extraction.get("tables_found", 0),
        }

    def build_review_checklist(self, extraction: Dict[str, Any], summary: Dict[str, Any], client_info: Dict[str, Any], metadata: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
        fields = extraction.get("fields", {})
        document_type = extraction.get("document_type")
        checks = [
            self._check("document_type_detected", extraction.get("document_type") != "unknown", "Document type could be classified"),
            self._check("identifier_present", bool(fields.get("document_id_number", {}).get("value")) or not settings.get("require_identifier"), "Document/reference/account identifier present"),
            self._check("counterparty_present", bool(fields.get("counterparty", {}).get("value") or client_info.get("company")) or not settings.get("require_counterparty"), "Counterparty/client/vendor name present"),
            self._check("date_or_term_present", bool(fields.get("document_date", {}).get("value")) or not settings.get("require_date_or_term"), "Date, due date, or term present"),
        ]
        if document_type == "contract":
            key_terms = [
                fields.get("business_purpose", {}).get("value"),
                fields.get("term", {}).get("value"),
                fields.get("return_or_destruction", {}).get("value"),
                fields.get("governing_law", {}).get("value"),
            ]
            checks.append(self._check("contract_terms_found", len([value for value in key_terms if value]) >= 2, "Business purpose, term, return/destruction, or governing-law terms found"))
            checks.append(self._check("signature_blocks_found", bool(fields.get("signature_status", {}).get("value")), "Signature block or signature status identified"))
        else:
            checks.append(self._check("structured_values_found", summary.get("period_metric_count", 0) > 0 or summary.get("total_amount", 0) > 0, "At least one useful metric or amount found"))
        checks.extend([
            self._check("visual_marker_requirement", not settings.get("require_visual_marker") or summary.get("visual_markers_found", 0) > 0, "Stamp, signature, or logo marker detected when required"),
            self._check("review_context_present", bool(metadata.get("owner") or metadata.get("department") or client_info.get("company")), "Owner, department, or client context present"),
        ])
        failed = [check["name"] for check in checks if check["status"] != "pass"]
        risk_level = "low" if not failed else "medium" if len(failed) <= 2 else "high"
        return {"risk_level": risk_level, "checks": checks, "failed_checks": failed}

    def generate_report(self, case_id: str, document: Dict[str, Any], client_info: Dict[str, Any], metadata: Dict[str, Any], extraction: Dict[str, Any], summary: Dict[str, Any], checklist: Dict[str, Any]) -> str:
        owner = metadata.get("owner") or client_info.get("company") or extraction.get("fields", {}).get("counterparty", {}).get("value") or "Review team"
        return "\n".join([
            f"# Document Review Report - {owner}",
            "",
            f"Case ID: {case_id}",
            f"Source document: {document.get('filename')}",
            f"Detected type: {extraction.get('document_type')}",
            "",
            "## Extracted Summary",
            f"Data completeness: {summary['data_completeness']:.0%}",
            f"Structured period values found: {summary['period_metric_count']}",
            f"Period value total: {summary['period_metric_total']:,.2f}",
            f"Total amount: {summary['total_amount']:,.2f}",
            f"QR codes found: {summary['qr_codes_found']}",
            f"Visual markers found: {summary.get('visual_markers_found', 0)}",
            "",
            "## Review Status",
            f"Risk level: {checklist['risk_level']}",
            f"Low-confidence fields: {summary['low_confidence_count']}",
            "This report is generated from extracted document data and should be reviewed before operational use.",
        ])

    def update_status(self, case_id: str, status: str, actor: str = "user", note: str = "") -> Dict[str, Any]:
        if status not in STATUS_FLOW:
            raise ValueError(f"Invalid status. Use one of: {', '.join(STATUS_FLOW)}")
        case = self.get_case(case_id)
        if not case:
            raise ValueError("Case not found")
        previous = case.get("status")
        case["status"] = status
        case["updated_at"] = utc_now()
        self._save_case(case)
        self._audit(case_id, actor, "status_changed", {"from": previous, "to": status, "note": note})
        return case

    def update_title(self, case_id: str, title: str, actor: str = "user") -> Dict[str, Any]:
        cleaned = " ".join(str(title or "").split()).strip(" .")
        if not cleaned:
            raise ValueError("Title cannot be empty")
        if len(cleaned) > 90:
            cleaned = cleaned[:90].rstrip()
        case = self.get_case(case_id)
        if not case:
            raise ValueError("Case not found")
        previous = case.setdefault("metadata", {}).get("display_title")
        case["metadata"]["display_title"] = cleaned
        case["metadata"]["suggested_filename"] = f"{self._slug(cleaned)}.pdf"
        case["updated_at"] = utc_now()
        self._save_case(case)
        self._audit(case_id, actor, "title_updated", {"from": previous, "to": cleaned, "suggested_filename": case["metadata"]["suggested_filename"]})
        return case

    def update_ai_report(self, case_id: str, report_text: str, model: str, facts: Optional[Dict[str, Any]] = None, actor: str = "system") -> Dict[str, Any]:
        cleaned = str(report_text or "").strip()
        if not cleaned:
            raise ValueError("Report text cannot be empty")
        case = self.get_case(case_id)
        if not case:
            raise ValueError("Case not found")
        case["ai_report"] = {
            "text": cleaned,
            "model": model,
            "facts": facts or {},
            "generated_at": utc_now(),
        }
        case["updated_at"] = utc_now()
        self._save_case(case)
        self._audit(case_id, actor, "ai_report_generated", {"model": model, "characters": len(cleaned)})
        return case

    def record_automation_error(self, case_id: str, step: str, error: str, actor: str = "system") -> Dict[str, Any]:
        case = self.get_case(case_id)
        if not case:
            raise ValueError("Case not found")
        case.setdefault("metadata", {}).setdefault("automation_errors", []).append({
            "timestamp": utc_now(),
            "step": step,
            "error": str(error)[:500],
        })
        case["updated_at"] = utc_now()
        self._save_case(case)
        self._audit(case_id, actor, "automation_error", {"step": step, "error": str(error)[:500]})
        return case

    def update_settings(self, case_id: str, settings: Dict[str, Any], actor: str = "user") -> Dict[str, Any]:
        case = self.get_case(case_id)
        if not case:
            raise ValueError("Case not found")
        old = deepcopy(case.get("review_settings", {}))
        case["review_settings"].update({k: v for k, v in settings.items() if v is not None})
        self._refresh_case(case, label="Review setting update")
        self._save_case(case)
        self._audit(case_id, actor, "settings_updated", {"old": old, "new": case["review_settings"], "version_id": case.get("versions", [])[-1]["version_id"]})
        return case

    def update_extraction(self, case_id: str, extraction_patch: Dict[str, Any], actor: str = "user") -> Dict[str, Any]:
        case = self.get_case(case_id)
        if not case:
            raise ValueError("Case not found")
        extraction = case.setdefault("extraction", {})
        fields = extraction.setdefault("fields", {})
        changed_fields = []
        for name, payload in (extraction_patch.get("fields", {}) or {}).items():
            if not isinstance(payload, dict):
                payload = {"value": payload}
            previous = deepcopy(fields.get(name, {}))
            fields[name] = {"value": payload.get("value"), "confidence": round(float(payload.get("confidence", 1.0)), 2)}
            if previous != fields[name]:
                changed_fields.append(name)
        if "period_metrics" in extraction_patch:
            extraction["period_metrics"] = self._clean_metric_rows(extraction_patch.get("period_metrics") or [])
            changed_fields.append("period_metrics")
        extraction["confidence_summary"] = {
            "overall": self._overall_confidence(fields, extraction.get("period_metrics", [])),
            "low_confidence_count": len(self.low_confidence_fields(extraction, case.get("review_settings", {}))),
        }
        self._refresh_case(case, label="Manual correction")
        self._save_case(case)
        self._audit(case_id, actor, "extraction_corrected", {"changed_fields": sorted(set(changed_fields)), "version_id": case.get("versions", [])[-1]["version_id"]})
        return case

    def diff_versions(self, case_id: str, left: str, right: str) -> Dict[str, Any]:
        case = self.get_case(case_id)
        if not case:
            raise ValueError("Case not found")
        versions = {version["version_id"]: version for version in case.get("versions", [])}
        if left not in versions or right not in versions:
            raise ValueError("Version not found")
        left_summary = versions[left].get("case_summary", {})
        right_summary = versions[right].get("case_summary", {})
        keys = sorted(set(left_summary) | set(right_summary))
        return {
            "case_id": case_id,
            "left": left,
            "right": right,
            "summary_delta": {key: {"left": left_summary.get(key), "right": right_summary.get(key), "delta": self._delta(left_summary.get(key), right_summary.get(key))} for key in keys},
        }

    def list_cases(self) -> List[Dict[str, Any]]:
        return list(self._load_cases().values())

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        return self._load_cases().get(case_id)

    def audit_log(self, case_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        items = json.loads(self.audit_path.read_text(encoding="utf-8"))
        if case_id:
            return [item for item in items if item.get("case_id") == case_id]
        return items

    def low_confidence_fields(self, extraction: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        threshold = float((settings or {}).get("confidence_threshold", LOW_CONFIDENCE_THRESHOLD))
        lows = []
        for name, payload in extraction.get("fields", {}).items():
            if payload.get("confidence", 0) < threshold:
                lows.append({"field": name, "value": payload.get("value"), "confidence": payload.get("confidence")})
        for row in extraction.get("period_metrics", []):
            if row.get("confidence", 0) < threshold:
                lows.append({"field": f"period_metrics.{row.get('period')}", "value": row.get("value"), "confidence": row.get("confidence")})
        return lows

    def _refresh_case(self, case: Dict[str, Any], label: str) -> None:
        extraction = case.get("extraction", {})
        settings = case.get("review_settings", {})
        case.pop("ai_report", None)
        case["case_summary"] = self.build_case_summary(extraction, settings)
        case["review_checklist"] = self.build_review_checklist(extraction, case["case_summary"], case.get("client_info", {}), case.get("metadata", {}), settings)
        case["generated_report"] = self.generate_report(case["case_id"], {"filename": case.get("source_filename")}, case.get("client_info", {}), case.get("metadata", {}), extraction, case["case_summary"], case["review_checklist"])
        low_confidence = self.low_confidence_fields(extraction, settings)
        case["review"] = {
            "low_confidence_fields": low_confidence,
            "next_action": "Review low-confidence fields and missing checklist items" if low_confidence or case["review_checklist"]["risk_level"] != "low" else "Ready for approval",
        }
        case["updated_at"] = utc_now()
        version_id = f"v{len(case.get('versions', [])) + 1}"
        case.setdefault("versions", []).append({
            "version_id": version_id,
            "created_at": utc_now(),
            "label": label,
            "review_settings": deepcopy(settings),
            "case_summary": deepcopy(case["case_summary"]),
        })

    def _detect_document_type(self, lower_text: str) -> str:
        if any(term in lower_text for term in ["kwh", "meter", "tariff", "utility", "electricity"]):
            return "utility_bill"
        if any(term in lower_text for term in ["agreement", "contract", "effective date", "party", "termination"]):
            return "contract"
        if any(term in lower_text for term in ["invoice", "amount due", "balance due", "payment due"]):
            return "invoice"
        if any(term in lower_text for term in ["balance sheet", "income statement", "cash flow", "financial statement"]):
            return "financial_statement"
        return "operational_document" if lower_text.strip() else "unknown"

    def _extract_period_metrics(self, text: str, tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        seen = set()
        for metric in self._usage_comparison_metrics(text):
            self._add_metric_row(rows, seen, metric)
        for line in text.splitlines():
            metric = self._metric_from_segment(line, source="text", confidence=0.86)
            if metric:
                self._add_metric_row(rows, seen, metric)
        for metric in self._table_period_metrics(tables, text):
            self._add_metric_row(rows, seen, metric)
        rows.sort(key=lambda item: MONTHS.index(item["period"]) if item["period"] in MONTHS else 99)
        return rows

    def _add_metric_row(self, rows: List[Dict[str, Any]], seen: set, metric: Optional[Dict[str, Any]]) -> None:
        if not metric:
            return
        period = metric.get("period")
        value = metric.get("value")
        if not period or period in seen or not value or value <= 0:
            return
        rows.append(metric)
        seen.add(period)

    def _usage_comparison_metrics(self, text: str) -> List[Dict[str, Any]]:
        metrics: List[Dict[str, Any]] = []
        header_re = re.compile(r"(?i)(?:\d+\s*-\s*month\s+)?(?:usage|consumption|energy)\s+(?:comparison|history|summary)?\s*\((kwh|kw\s*h|kwhr|mwh|wh|units?)\)")
        for header in header_re.finditer(text):
            unit = self._normalize_unit(header.group(1))
            block = text[header.end(): header.end() + 2200]
            block = re.split(
                r"(?i)\b(payment options|current charges breakdown|account information|bill summary|please return|review checklist)\b",
                block,
                maxsplit=1,
            )[0]
            month_re = re.compile(
                rf"(?is)({MONTH_LOOKAHEAD_RE})(?:\s+['\u2019]?\d{{2,4}})?(?P<body>.*?)(?={MONTH_LOOKAHEAD_RE}(?:\s+['\u2019]?\d{{2,4}})?|$)"
            )
            for match in month_re.finditer(block):
                period = self._normalize_month(match.group(1))
                body = match.group("body")
                numbers = [self._parse_number(item.group(0)) for item in STRICT_NUMBER_RE.finditer(body)]
                numbers = [number for number in numbers if number and number > 0]
                if not period or not numbers:
                    continue
                value = numbers[-1]
                metrics.append({"period": period, "value": round(value, 2), "unit": unit, "confidence": 0.90, "source": "usage_comparison"})
        return metrics

    def _metric_from_segment(
        self,
        segment: str,
        source: str,
        confidence: float,
        default_unit: Optional[str] = None,
        require_usage_context: bool = True,
    ) -> Optional[Dict[str, Any]]:
        period = self._find_month(segment)
        if not period:
            return None
        explicit_matches = list(EXPLICIT_USAGE_RE.finditer(segment))
        if explicit_matches:
            match = explicit_matches[-1]
            value = self._parse_number(match.group(1))
            unit = self._normalize_unit(match.group(2))
            if value and unit:
                return {"period": period, "value": round(value, 2), "unit": unit, "confidence": confidence, "source": source}
        if not default_unit:
            return None
        if require_usage_context and not USAGE_CONTEXT_RE.search(segment):
            return None
        if MONEY_CONTEXT_RE.search(segment):
            return None
        numbers = [self._parse_number(item.group(0)) for item in STRICT_NUMBER_RE.finditer(segment)]
        numbers = [number for number in numbers if number and number > 0]
        if not numbers:
            return None
        value = numbers[-1]
        return {"period": period, "value": round(value, 2), "unit": default_unit, "confidence": confidence, "source": source}

    def _table_period_metrics(self, tables: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
        metrics: List[Dict[str, Any]] = []
        implicit_unit = self._implicit_usage_unit(text)
        for table in tables:
            usage_columns: List[int] = []
            usage_column_units: Dict[int, str] = {}
            for raw_row in table.get("rows", []):
                cells = [self._clean_cell(cell) for cell in raw_row]
                joined = " ".join(cells)
                if not joined.strip():
                    continue
                if not self._find_month(joined):
                    detected_units = self._usage_column_units(cells)
                    if detected_units:
                        usage_column_units = detected_units
                        usage_columns = list(detected_units.keys())
                    continue

                metric = self._metric_from_segment(joined, source="table", confidence=0.88)
                if metric:
                    metrics.append(metric)
                    continue

                period = self._find_month(joined)
                if not period:
                    continue
                for column_index in usage_columns:
                    if column_index < len(cells):
                        value = self._parse_number(cells[column_index])
                        if value and value > 0:
                            unit = usage_column_units.get(column_index) or self._unit_from_text(cells[column_index]) or "units"
                            metrics.append({"period": period, "value": round(value, 2), "unit": unit, "confidence": 0.90, "source": "table"})
                            break
                else:
                    if implicit_unit and self._row_looks_like_usage_history(joined):
                        metric = self._metric_from_segment(
                            joined,
                            source="table_usage_history",
                            confidence=0.88,
                            default_unit=implicit_unit,
                            require_usage_context=False,
                        )
                        if metric:
                            metrics.append(metric)
        return metrics

    def _clean_metric_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned = []
        for row in rows:
            period = str(row.get("period", "")).strip().lower()[:12]
            if not period:
                continue
            try:
                value = float(row.get("value") or 0)
            except (TypeError, ValueError):
                value = 0
            if value <= 0:
                continue
            try:
                confidence = float(row.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0
            cleaned.append({
                "period": period,
                "value": round(value, 2),
                "unit": row.get("unit") or "value",
                "confidence": round(max(0.0, min(confidence, 1.0)), 2),
                "source": row.get("source") or "manual",
            })
        return cleaned

    def _extract_money(self, text: str, tables: List[Dict[str, Any]]) -> Optional[float]:
        candidates: List[tuple] = []
        for label in MONEY_LABELS:
            for snippet in self._snippets_after_label(text, label):
                amount = self._money_from_snippet(snippet)
                if amount is not None:
                    candidates.append((LABEL_PRIORITY[label], "text", amount))
        for table in tables:
            for row in table.get("rows", []):
                cells = [self._clean_cell(cell) for cell in row]
                joined = " ".join(cells)
                key = self._label_key(joined)
                for label in MONEY_LABELS:
                    if self._label_key(label) in key:
                        amount = self._money_from_cells(cells)
                        if amount is not None:
                            candidates.append((LABEL_PRIORITY[label], "table", amount))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return round(float(candidates[0][2]), 2)

    def _find_value(self, text: str, tables: List[Dict[str, Any]], labels: List[str], allow_continuation: bool = False) -> Optional[str]:
        table_value = self._find_value_in_tables(tables, labels, allow_continuation=allow_continuation)
        if table_value:
            return table_value
        return self._find_value_in_text(text, labels)

    def _find_value_in_tables(self, tables: List[Dict[str, Any]], labels: List[str], allow_continuation: bool = False) -> Optional[str]:
        for table in tables:
            rows = table.get("rows", [])
            for row_index, row in enumerate(rows):
                cells = [self._clean_cell(cell) for cell in row]
                for cell_index, cell in enumerate(cells):
                    if not cell:
                        continue
                    if not any(self._cell_matches_label(cell, label) for label in labels):
                        continue
                    value_index = cell_index + 1
                    if value_index >= len(cells):
                        continue
                    value_parts = [cells[value_index]]
                    if allow_continuation:
                        next_index = row_index + 1
                        while next_index < len(rows):
                            next_cells = [self._clean_cell(cell) for cell in rows[next_index]]
                            left_cell = next_cells[cell_index] if cell_index < len(next_cells) else ""
                            continuation = next_cells[value_index] if value_index < len(next_cells) else ""
                            if left_cell or not continuation:
                                break
                            value_parts.append(continuation)
                            next_index += 1
                    value = self._clean_value(" ".join(part for part in value_parts if part))
                    if value and not self._looks_like_label(value):
                        return value
        return None

    def _find_value_in_text(self, text: str, labels: List[str]) -> Optional[str]:
        for label in sorted(labels, key=len, reverse=True):
            pattern = re.compile(rf"(?i)\b{re.escape(label)}\b\s*[:#-]?\s*([\s\S]{{0,180}})")
            for match in pattern.finditer(text):
                value = self._truncate_at_stop_label(match.group(1), current_label=label)
                value = self._clean_value(value)
                if value and not self._looks_like_label(value):
                    return value[:100]
        return None

    def _snippets_after_label(self, text: str, label: str) -> List[str]:
        snippets = []
        pattern = re.compile(rf"(?i)\b{re.escape(label)}\b\s*[:#-]?\s*([\s\S]{{0,220}})")
        for match in pattern.finditer(text):
            snippets.append(self._truncate_at_stop_label(match.group(1), current_label=label, keep_money_context=True))
        return snippets

    def _truncate_at_stop_label(self, value: str, current_label: str, keep_money_context: bool = False) -> str:
        earliest: Optional[int] = None
        current = self._label_key(current_label)
        for label in LABEL_STOP_TERMS:
            if self._label_key(label) == current:
                continue
            if keep_money_context and label in {"due date", "date"} and self._label_key(current_label) in {"amount due", "amount due by", "total amount due", "balance due"}:
                continue
            match = re.search(rf"(?i)\b{re.escape(label)}\b", value)
            if match and match.start() > 0:
                earliest = match.start() if earliest is None else min(earliest, match.start())
        if earliest is not None:
            value = value[:earliest]
        return value

    def _money_from_cells(self, cells: List[str]) -> Optional[float]:
        for cell in reversed(cells):
            amount = self._money_from_snippet(cell)
            if amount is not None:
                return amount
        return None

    def _money_from_snippet(self, snippet: str) -> Optional[float]:
        snippet = str(snippet or "")
        for match in MONEY_AMOUNT_RE.finditer(snippet):
            amount = self._parse_number(match.group(0))
            if amount is not None:
                return amount
        numeric_matches = list(STRICT_NUMBER_RE.finditer(snippet))
        if not numeric_matches:
            return None
        if self._looks_like_date_without_amount(snippet, numeric_matches):
            return None
        decimal_values = []
        all_values = []
        for match in numeric_matches:
            token = match.group(0)
            amount = self._parse_number(token)
            if amount is None:
                continue
            if 1900 <= amount <= 2100 and "." not in token:
                continue
            all_values.append(amount)
            if "." in token:
                decimal_values.append(amount)
        values = decimal_values or all_values
        return values[-1] if values else None

    def _looks_like_date_without_amount(self, snippet: str, numeric_matches: List[re.Match]) -> bool:
        if any("." in match.group(0) for match in numeric_matches):
            return False
        if re.search(rf"(?i){MONTH_LOOKAHEAD_RE}\s+\d{{1,2}},?\s+\d{{4}}", snippet):
            return True
        return bool(re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", snippet))

    def _usage_column_units(self, cells: List[str]) -> Dict[int, str]:
        columns = {}
        for index, cell in enumerate(cells):
            if USAGE_CONTEXT_RE.search(cell) and not MONEY_CONTEXT_RE.search(cell):
                columns[index] = self._unit_from_text(cell) or "units"
        return columns

    def _row_looks_like_usage_history(self, text: str) -> bool:
        stripped = text.strip()
        if not MONTH_RE.match(stripped):
            return False
        if MONEY_CONTEXT_RE.search(stripped):
            return False
        if re.search(r"(?i)\b(date|billing period|due|charge|tax|balance|payment|invoice|contract|rate)\b", stripped):
            return False
        return True

    def _implicit_usage_unit(self, text: str) -> Optional[str]:
        usage_header = re.search(r"(?i)(?:usage|consumption|energy)\s+(?:comparison|history|summary)?\s*\((kwh|kw\s*h|kwhr|mwh|wh|units?)\)", text)
        if usage_header:
            return self._normalize_unit(usage_header.group(1))
        return None

    def _unit_from_text(self, text: str) -> Optional[str]:
        match = re.search(r"(?i)\b(kwh|kw\s*h|kwhr|mwh|wh|units?|unit)\b", text)
        return self._normalize_unit(match.group(1)) if match else None

    def _normalize_unit(self, value: Any) -> str:
        unit = re.sub(r"\s+", "", str(value or "").lower())
        mapping = {
            "kwh": "kwh",
            "kwhour": "kwh",
            "kwhr": "kwh",
            "mwh": "mwh",
            "wh": "wh",
            "unit": "units",
            "units": "units",
        }
        return mapping.get(unit, unit or "units")

    def _find_month(self, text: str) -> Optional[str]:
        match = MONTH_RE.search(str(text or ""))
        return self._normalize_month(match.group(1)) if match else None

    def _normalize_month(self, value: str) -> str:
        return str(value or "").lower()[:3]

    def _cell_matches_label(self, cell: str, label: str) -> bool:
        cell_key = self._label_key(cell)
        label_key = self._label_key(label)
        return cell_key == label_key or cell_key.startswith(f"{label_key} ")

    def _label_key(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()

    def _clean_cell(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _clean_value(self, value: Any) -> str:
        cleaned = self._clean_cell(value).strip(" :#-")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def _looks_like_label(self, value: str) -> bool:
        key = self._label_key(value)
        return key in {self._label_key(label) for label in LABEL_STOP_TERMS}

    def _slug(self, value: Any) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "")).strip("_").lower()
        return (slug[:36].strip("_") or "document_case")

    def _field(self, value: Any, confidence: float) -> Dict[str, Any]:
        return {"value": value, "confidence": round(confidence if value not in [None, ""] else min(confidence, 0.25), 2)}

    def _overall_confidence(self, fields: Dict[str, Dict[str, Any]], metrics: List[Dict[str, Any]]) -> float:
        scores = [field.get("confidence", 0) for field in fields.values()]
        scores.extend(row.get("confidence", 0) for row in metrics)
        return round(sum(scores) / len(scores), 2) if scores else 0.0

    def _data_completeness(self, extraction: Dict[str, Any]) -> float:
        fields = extraction.get("fields", {})
        present = len([field for field in fields.values() if field.get("value") not in [None, ""]])
        requires_structured_values = extraction.get("document_type") not in {"contract", "operational_document"}
        structured_score = 1 if requires_structured_values and (extraction.get("period_metrics") or extraction.get("line_items")) else 0
        denominator = len(fields) + (1 if requires_structured_values else 0)
        return round((present + structured_score) / max(denominator, 1), 2)

    def _check(self, name: str, passed: bool, evidence: str) -> Dict[str, str]:
        return {"name": name, "status": "pass" if passed else "needs_review", "evidence": evidence}

    def _marker_counts(self, markers: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for marker in markers or []:
            kind = marker.get("kind") or marker.get("type") or "unknown"
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def _parse_number(self, value: str) -> Optional[float]:
        cleaned = re.sub(r"[^0-9,.]", "", str(value)).strip()
        if not cleaned:
            return None
        if cleaned.count(",") > 0 and cleaned.count(".") > 0:
            cleaned = cleaned.replace(",", "")
        elif cleaned.count(",") == 1 and len(cleaned.rsplit(",", 1)[-1]) <= 2:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "").replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _delta(self, left: Any, right: Any) -> Optional[float]:
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return round(right - left, 4)
        return None

    def _load_cases(self) -> Dict[str, Dict[str, Any]]:
        if not self.cases_path.exists():
            return {}
        try:
            return json.loads(self.cases_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_case(self, case: Dict[str, Any]) -> None:
        cases = self._load_cases()
        cases[case["case_id"]] = case
        self.cases_path.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")

    def _audit(self, case_id: str, actor: str, action: str, details: Dict[str, Any]) -> None:
        items = self.audit_log()
        items.append({"timestamp": utc_now(), "case_id": case_id, "actor": actor, "action": action, "details": details})
        self.audit_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
