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
MONTH_METRIC_RE = re.compile(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+([0-9][0-9, .]{2,})\s*([a-zA-Z/$%]+)?")
MONEY_RE = re.compile(r"(?i)(?:total|amount due|balance due|contract value|invoice total)\s*[:#-]?\s*(?:usd|ngn|ghs|kes|zar|\$)?\s*([0-9][0-9, .]{2,})")
DATE_RE = re.compile(r"(?i)\b(?:date|due date|effective date|expiry date|contract date)\s*[:#-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4}|[a-z]{3,9}\s+[0-9]{1,2},?\s+[0-9]{4})")
NUMBER_RE = re.compile(r"[0-9][0-9, .]*")

DEFAULT_REVIEW_SETTINGS: Dict[str, Any] = {
    "materiality_amount": 10000,
    "confidence_threshold": 0.75,
    "review_sla_hours": 24,
    "currency": "USD",
    "require_identifier": True,
    "require_counterparty": True,
    "require_date_or_term": True,
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
        total_amount = self._extract_money(text)
        date_value = self._find_after_label(text, ["invoice date", "due date", "effective date", "expiry date", "contract date", "date"])
        if not date_value:
            match = DATE_RE.search(text)
            date_value = match.group(1).strip() if match else None

        fields = {
            "document_id_number": self._field(self._find_after_label(text, ["document id", "reference", "ref", "invoice number", "invoice no", "contract number", "account number", "account no"]), 0.76),
            "counterparty": self._field(self._find_after_label(text, ["customer", "client", "vendor", "supplier", "counterparty", "party", "name"]), 0.64),
            "document_date": self._field(date_value, 0.68),
            "service_or_site": self._field(self._find_after_label(text, ["service address", "supply address", "site address", "delivery address", "project site"]), 0.58),
            "category_or_rate": self._field(self._find_after_label(text, ["tariff", "rate class", "plan", "category", "department", "cost center"]), 0.60),
            "total_amount": self._field(total_amount, 0.88 if total_amount else 0.25),
        }
        return {
            "document_type": document_type,
            "fields": fields,
            "period_metrics": metrics,
            "tables_found": len(tables),
            "qr_codes_found": len(document.get("qr_codes", [])),
            "confidence_summary": {
                "overall": self._overall_confidence(fields, metrics),
                "low_confidence_count": len([item for item in fields.values() if item.get("confidence", 0) < LOW_CONFIDENCE_THRESHOLD]),
            },
        }

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
            "total_amount": round(float(total_amount or 0), 2),
            "data_completeness": data_completeness,
            "low_confidence_count": len(low_confidence),
            "materiality_flag": bool(total_amount and float(total_amount) >= float(settings.get("materiality_amount", 0))),
            "qr_codes_found": extraction.get("qr_codes_found", 0),
            "tables_found": extraction.get("tables_found", 0),
        }

    def build_review_checklist(self, extraction: Dict[str, Any], summary: Dict[str, Any], client_info: Dict[str, Any], metadata: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
        fields = extraction.get("fields", {})
        checks = [
            self._check("document_type_detected", extraction.get("document_type") != "unknown", "Document type could be classified"),
            self._check("identifier_present", bool(fields.get("document_id_number", {}).get("value")) or not settings.get("require_identifier"), "Document/reference/account identifier present"),
            self._check("counterparty_present", bool(fields.get("counterparty", {}).get("value") or client_info.get("company")) or not settings.get("require_counterparty"), "Counterparty/client/vendor name present"),
            self._check("date_or_term_present", bool(fields.get("document_date", {}).get("value")) or not settings.get("require_date_or_term"), "Date, due date, or term present"),
            self._check("structured_values_found", summary.get("period_metric_count", 0) > 0 or summary.get("total_amount", 0) > 0, "At least one useful metric or amount found"),
            self._check("review_context_present", bool(metadata.get("owner") or metadata.get("department") or client_info.get("company")), "Owner, department, or client context present"),
        ]
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
        for match in MONTH_METRIC_RE.finditer(text):
            period = match.group(1).lower()[:3]
            value = self._parse_number(match.group(2))
            unit = (match.group(3) or "value").lower()
            if value and period not in seen:
                rows.append({"period": period, "value": value, "unit": unit, "confidence": 0.82, "source": "text"})
                seen.add(period)
        for table in tables:
            for row in table.get("rows", []):
                joined = " ".join(str(cell or "") for cell in row)
                period = next((m for m in MONTHS if re.search(rf"\b{m}", joined, re.I)), None)
                if not period or period in seen:
                    continue
                numbers = [self._parse_number(item) for item in NUMBER_RE.findall(joined)]
                numbers = [number for number in numbers if number and number > 0]
                if numbers:
                    rows.append({"period": period, "value": max(numbers), "unit": "value", "confidence": 0.88, "source": "table"})
                    seen.add(period)
        rows.sort(key=lambda item: MONTHS.index(item["period"]) if item["period"] in MONTHS else 99)
        return rows

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

    def _extract_money(self, text: str) -> Optional[float]:
        match = MONEY_RE.search(text)
        if match:
            return self._parse_number(match.group(1))
        return None

    def _find_after_label(self, text: str, labels: List[str]) -> Optional[str]:
        for label in labels:
            pattern = re.compile(rf"(?i){re.escape(label)}\s*[:#-]?\s*([^\n\r]{{2,100}})")
            match = pattern.search(text)
            if match:
                return match.group(1).strip()[:100]
        return None

    def _field(self, value: Any, confidence: float) -> Dict[str, Any]:
        return {"value": value, "confidence": round(confidence if value not in [None, ""] else min(confidence, 0.25), 2)}

    def _overall_confidence(self, fields: Dict[str, Dict[str, Any]], metrics: List[Dict[str, Any]]) -> float:
        scores = [field.get("confidence", 0) for field in fields.values()]
        scores.extend(row.get("confidence", 0) for row in metrics)
        return round(sum(scores) / len(scores), 2) if scores else 0.0

    def _data_completeness(self, extraction: Dict[str, Any]) -> float:
        fields = extraction.get("fields", {})
        present = len([field for field in fields.values() if field.get("value") not in [None, ""]])
        metric_score = 1 if extraction.get("period_metrics") else 0
        denominator = max(len(fields) + 1, 1)
        return round((present + metric_score) / denominator, 2)

    def _check(self, name: str, passed: bool, evidence: str) -> Dict[str, str]:
        return {"name": name, "status": "pass" if passed else "needs_review", "evidence": evidence}

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