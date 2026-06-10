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
KWH_RE = re.compile(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+([0-9][0-9, .]{2,})\s*(?:kwh)?")
NUMBER_RE = re.compile(r"[0-9][0-9, .]*")

DEFAULT_ASSUMPTIONS: Dict[str, Any] = {
    "grid_tariff_per_kwh": 0.16,
    "ppa_rate_per_kwh": 0.115,
    "solar_yield_kwh_per_kwp_year": 1450,
    "target_offset_pct": 0.75,
    "system_derate_pct": 0.86,
    "annual_degradation_pct": 0.005,
    "payment_term_years": 15,
    "capex_per_kwp": 780,
    "opex_pct_of_capex": 0.015,
    "fx_rate": 1.0,
    "diesel_price_per_liter": 1.1,
}

STATUS_FLOW = ["New", "Parsed", "Needs Review", "Approved", "Sent"]
LOW_CONFIDENCE_THRESHOLD = 0.75


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SolarProposalService:
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.proposals_path = storage_dir / "solar_proposals.json"
        self.audit_path = storage_dir / "audit_log.json"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def default_assumptions(self) -> Dict[str, Any]:
        return deepcopy(DEFAULT_ASSUMPTIONS)

    def create_from_document(
        self,
        document: Dict[str, Any],
        client_info: Optional[Dict[str, Any]] = None,
        site_data: Optional[Dict[str, Any]] = None,
        assumptions: Optional[Dict[str, Any]] = None,
        actor: str = "system",
    ) -> Dict[str, Any]:
        if not document:
            raise ValueError("Document not found")

        proposal_id = uuid.uuid4().hex
        merged_assumptions = self.default_assumptions()
        if assumptions:
            merged_assumptions.update({k: v for k, v in assumptions.items() if v is not None})

        extraction = self.extract_bill_fields(document)
        calculation = self.calculate(extraction["monthly_consumption"], merged_assumptions)
        checklist = self.build_underwriting_checklist(extraction, calculation, client_info or {}, site_data or {})
        draft = self.generate_proposal_draft(proposal_id, document, client_info or {}, site_data or {}, extraction, calculation, checklist)
        low_confidence = self.low_confidence_fields(extraction)
        status = "Needs Review" if low_confidence or checklist["risk_level"] != "low" else "Parsed"

        proposal = {
            "proposal_id": proposal_id,
            "status": status,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "document_id": document.get("document_id"),
            "source_filename": document.get("filename"),
            "client_info": client_info or {},
            "site_data": site_data or {},
            "assumptions": merged_assumptions,
            "extraction": extraction,
            "calculation": calculation,
            "underwriting_checklist": checklist,
            "proposal_draft": draft,
            "versions": [
                {
                    "version_id": "v1",
                    "created_at": utc_now(),
                    "label": "Initial draft",
                    "assumptions": deepcopy(merged_assumptions),
                    "calculation": deepcopy(calculation),
                }
            ],
            "review": {
                "low_confidence_fields": low_confidence,
                "next_action": "Review low-confidence fields and assumptions" if status == "Needs Review" else "Ready for commercial review",
            },
        }
        self._save_proposal(proposal)
        self._audit(proposal_id, actor, "created", {"status": status, "document_id": document.get("document_id")})
        return proposal

    def extract_bill_fields(self, document: Dict[str, Any]) -> Dict[str, Any]:
        text = "\n".join(chunk.get("text", "") for chunk in document.get("chunks", []))
        tables = document.get("tables", [])
        lower_text = text.lower()
        monthly = self._extract_monthly_consumption(text, tables)
        annual_kwh = sum(row["kwh"] for row in monthly)

        fields = {
            "account_number": self._field(self._find_after_label(text, ["account number", "account no", "account"]), 0.72),
            "meter_number": self._field(self._find_after_label(text, ["meter number", "meter no", "meter"]), 0.76),
            "tariff": self._field(self._find_after_label(text, ["tariff", "rate class", "plan"]), 0.62),
            "customer_name": self._field(self._find_after_label(text, ["customer", "client", "name"]), 0.55),
            "service_address": self._field(self._find_after_label(text, ["service address", "supply address", "site address"]), 0.58),
            "annual_kwh": self._field(annual_kwh if annual_kwh else None, 0.9 if annual_kwh else 0.2),
        }
        document_type = "utility_bill" if any(term in lower_text for term in ["kwh", "meter", "tariff", "billing", "invoice"]) else "unknown"
        return {
            "document_type": document_type,
            "fields": fields,
            "monthly_consumption": monthly,
            "confidence_summary": {
                "overall": self._overall_confidence(fields, monthly),
                "low_confidence_count": len([item for item in fields.values() if item["confidence"] < LOW_CONFIDENCE_THRESHOLD]),
            },
        }

    def calculate(self, monthly_consumption: List[Dict[str, Any]], assumptions: Dict[str, Any]) -> Dict[str, Any]:
        annual_kwh = sum(float(row.get("kwh", 0)) for row in monthly_consumption)
        if annual_kwh <= 0:
            annual_kwh = float(assumptions.get("fallback_annual_kwh", 0) or 0)

        target_offset = float(assumptions.get("target_offset_pct", 0.75))
        solar_yield = max(float(assumptions.get("solar_yield_kwh_per_kwp_year", 1450)), 1.0)
        derate = float(assumptions.get("system_derate_pct", 0.86))
        grid_tariff = float(assumptions.get("grid_tariff_per_kwh", 0.16))
        ppa_rate = float(assumptions.get("ppa_rate_per_kwh", 0.115))
        capex_per_kwp = float(assumptions.get("capex_per_kwp", 780))
        opex_pct = float(assumptions.get("opex_pct_of_capex", 0.015))

        target_solar_kwh = annual_kwh * target_offset
        system_size_kwp = target_solar_kwh / max(solar_yield * derate, 1.0)
        year_one_production_kwh = system_size_kwp * solar_yield * derate
        current_annual_cost = annual_kwh * grid_tariff
        ppa_annual_cost = year_one_production_kwh * ppa_rate + max(annual_kwh - year_one_production_kwh, 0) * grid_tariff
        estimated_annual_savings = current_annual_cost - ppa_annual_cost
        capex = system_size_kwp * capex_per_kwp
        annual_opex = capex * opex_pct
        simple_payback_years = capex / max(estimated_annual_savings - annual_opex, 1) if estimated_annual_savings > annual_opex else None

        return {
            "annual_kwh": round(annual_kwh, 2),
            "target_solar_kwh": round(target_solar_kwh, 2),
            "estimated_system_size_kwp": round(system_size_kwp, 2),
            "year_one_production_kwh": round(year_one_production_kwh, 2),
            "current_annual_cost": round(current_annual_cost, 2),
            "ppa_blended_annual_cost": round(ppa_annual_cost, 2),
            "estimated_annual_savings": round(estimated_annual_savings, 2),
            "estimated_capex": round(capex, 2),
            "estimated_annual_opex": round(annual_opex, 2),
            "simple_payback_years": round(simple_payback_years, 2) if simple_payback_years else None,
        }

    def build_underwriting_checklist(self, extraction: Dict[str, Any], calculation: Dict[str, Any], client_info: Dict[str, Any], site_data: Dict[str, Any]) -> Dict[str, Any]:
        fields = extraction.get("fields", {})
        checks = [
            self._check("12_month_consumption", bool(extraction.get("monthly_consumption")) and len(extraction.get("monthly_consumption", [])) >= 10, "At least 10 monthly kWh values found"),
            self._check("account_or_meter", bool(fields.get("account_number", {}).get("value") or fields.get("meter_number", {}).get("value")), "Account or meter number present"),
            self._check("tariff_identified", bool(fields.get("tariff", {}).get("value")), "Tariff or rate class extracted"),
            self._check("site_location", bool(site_data.get("address") or fields.get("service_address", {}).get("value")), "Site address present"),
            self._check("positive_savings", calculation.get("estimated_annual_savings", 0) > 0, "Estimated savings are positive"),
            self._check("client_contact", bool(client_info.get("name") or client_info.get("company")), "Client/company name present"),
        ]
        failed = [check["name"] for check in checks if check["status"] != "pass"]
        risk_level = "low" if not failed else "medium" if len(failed) <= 2 else "high"
        return {"risk_level": risk_level, "checks": checks, "failed_checks": failed}

    def generate_proposal_draft(self, proposal_id: str, document: Dict[str, Any], client_info: Dict[str, Any], site_data: Dict[str, Any], extraction: Dict[str, Any], calculation: Dict[str, Any], checklist: Dict[str, Any]) -> str:
        client = client_info.get("company") or client_info.get("name") or extraction.get("fields", {}).get("customer_name", {}).get("value") or "Client"
        site = site_data.get("address") or extraction.get("fields", {}).get("service_address", {}).get("value") or "the site"
        return "\n".join([
            f"# Solar PPA Proposal Draft - {client}",
            "",
            f"Proposal ID: {proposal_id}",
            f"Source document: {document.get('filename')}",
            f"Site: {site}",
            "",
            "## Consumption and System Estimate",
            f"Annual consumption reviewed: {calculation['annual_kwh']:,.0f} kWh",
            f"Recommended solar system size: {calculation['estimated_system_size_kwp']:,.1f} kWp",
            f"Estimated year-one production: {calculation['year_one_production_kwh']:,.0f} kWh",
            "",
            "## Commercial Estimate",
            f"Current estimated annual energy cost: {calculation['current_annual_cost']:,.2f}",
            f"Estimated blended annual cost under PPA: {calculation['ppa_blended_annual_cost']:,.2f}",
            f"Estimated annual savings: {calculation['estimated_annual_savings']:,.2f}",
            "",
            "## Review Notes",
            f"Underwriting risk level: {checklist['risk_level']}",
            "This draft is generated from extracted bill data and editable assumptions. It requires commercial/underwriting review before sending.",
        ])

    def update_status(self, proposal_id: str, status: str, actor: str = "user", note: str = "") -> Dict[str, Any]:
        if status not in STATUS_FLOW:
            raise ValueError(f"Invalid status. Use one of: {', '.join(STATUS_FLOW)}")
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found")
        previous = proposal.get("status")
        proposal["status"] = status
        proposal["updated_at"] = utc_now()
        self._save_proposal(proposal)
        self._audit(proposal_id, actor, "status_changed", {"from": previous, "to": status, "note": note})
        return proposal

    def update_assumptions(self, proposal_id: str, assumptions: Dict[str, Any], actor: str = "user") -> Dict[str, Any]:
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found")
        old = deepcopy(proposal.get("assumptions", {}))
        proposal["assumptions"].update({k: v for k, v in assumptions.items() if v is not None})
        self._refresh_proposal(proposal, label="Assumption update")
        self._save_proposal(proposal)
        self._audit(proposal_id, actor, "assumptions_updated", {"old": old, "new": proposal["assumptions"], "version_id": proposal.get("versions", [])[-1]["version_id"]})
        return proposal

    def update_extraction(self, proposal_id: str, extraction_patch: Dict[str, Any], actor: str = "user") -> Dict[str, Any]:
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found")

        extraction = proposal.setdefault("extraction", {})
        fields = extraction.setdefault("fields", {})
        incoming_fields = extraction_patch.get("fields", {}) or {}
        changed_fields = []
        for name, payload in incoming_fields.items():
            if not isinstance(payload, dict):
                payload = {"value": payload}
            previous = deepcopy(fields.get(name, {}))
            fields[name] = {
                "value": payload.get("value"),
                "confidence": round(float(payload.get("confidence", 1.0)), 2),
            }
            if previous != fields[name]:
                changed_fields.append(name)

        if "monthly_consumption" in extraction_patch:
            extraction["monthly_consumption"] = self._clean_monthly_rows(extraction_patch.get("monthly_consumption") or [])
            changed_fields.append("monthly_consumption")

        extraction["confidence_summary"] = {
            "overall": self._overall_confidence(fields, extraction.get("monthly_consumption", [])),
            "low_confidence_count": len(self.low_confidence_fields(extraction)),
        }
        self._refresh_proposal(proposal, label="Manual correction")
        proposal["review"]["next_action"] = "Review updated extraction and approve" if proposal.get("status") == "Needs Review" else proposal["review"].get("next_action", "Ready for review")
        self._save_proposal(proposal)
        self._audit(proposal_id, actor, "extraction_corrected", {"changed_fields": sorted(set(changed_fields)), "version_id": proposal.get("versions", [])[-1]["version_id"]})
        return proposal

    def diff_versions(self, proposal_id: str, left: str, right: str) -> Dict[str, Any]:
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found")
        versions = {version["version_id"]: version for version in proposal.get("versions", [])}
        if left not in versions or right not in versions:
            raise ValueError("Version not found")
        left_calc = versions[left].get("calculation", {})
        right_calc = versions[right].get("calculation", {})
        keys = sorted(set(left_calc) | set(right_calc))
        return {
            "proposal_id": proposal_id,
            "left": left,
            "right": right,
            "calculation_delta": {key: {"left": left_calc.get(key), "right": right_calc.get(key), "delta": self._delta(left_calc.get(key), right_calc.get(key))} for key in keys},
        }

    def list_proposals(self) -> List[Dict[str, Any]]:
        return list(self._load_proposals().values())

    def get_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        return self._load_proposals().get(proposal_id)

    def audit_log(self, proposal_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        items = json.loads(self.audit_path.read_text(encoding="utf-8"))
        if proposal_id:
            return [item for item in items if item.get("proposal_id") == proposal_id]
        return items

    def low_confidence_fields(self, extraction: Dict[str, Any]) -> List[Dict[str, Any]]:
        fields = extraction.get("fields", {})
        lows = []
        for name, payload in fields.items():
            if payload.get("confidence", 0) < LOW_CONFIDENCE_THRESHOLD:
                lows.append({"field": name, "value": payload.get("value"), "confidence": payload.get("confidence")})
        for row in extraction.get("monthly_consumption", []):
            if row.get("confidence", 0) < LOW_CONFIDENCE_THRESHOLD:
                lows.append({"field": f"monthly_consumption.{row.get('month')}", "value": row.get("kwh"), "confidence": row.get("confidence")})
        return lows

    def _refresh_proposal(self, proposal: Dict[str, Any], label: str) -> None:
        extraction = proposal.get("extraction", {})
        proposal["calculation"] = self.calculate(extraction.get("monthly_consumption", []), proposal.get("assumptions", {}))
        proposal["underwriting_checklist"] = self.build_underwriting_checklist(extraction, proposal["calculation"], proposal.get("client_info", {}), proposal.get("site_data", {}))
        proposal["proposal_draft"] = self.generate_proposal_draft(proposal["proposal_id"], {"filename": proposal.get("source_filename")}, proposal.get("client_info", {}), proposal.get("site_data", {}), extraction, proposal["calculation"], proposal["underwriting_checklist"])
        low_confidence = self.low_confidence_fields(extraction)
        proposal["review"] = {
            "low_confidence_fields": low_confidence,
            "next_action": "Review low-confidence fields and assumptions" if low_confidence or proposal["underwriting_checklist"]["risk_level"] != "low" else "Ready for commercial review",
        }
        proposal["updated_at"] = utc_now()
        version_id = f"v{len(proposal.get('versions', [])) + 1}"
        proposal.setdefault("versions", []).append({
            "version_id": version_id,
            "created_at": utc_now(),
            "label": label,
            "assumptions": deepcopy(proposal.get("assumptions", {})),
            "calculation": deepcopy(proposal["calculation"]),
        })

    def _clean_monthly_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned = []
        for row in rows:
            month = str(row.get("month", "")).strip().lower()[:3]
            if month not in MONTHS:
                continue
            try:
                kwh = float(row.get("kwh") or 0)
            except (TypeError, ValueError):
                kwh = 0
            if kwh <= 0:
                continue
            try:
                confidence = float(row.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0
            cleaned.append({
                "month": month,
                "kwh": round(kwh, 2),
                "confidence": round(max(0.0, min(confidence, 1.0)), 2),
                "source": row.get("source") or "manual",
            })
        cleaned.sort(key=lambda item: MONTHS.index(item["month"]))
        return cleaned

    def _extract_monthly_consumption(self, text: str, tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        seen = set()
        for match in KWH_RE.finditer(text):
            month = match.group(1).lower()[:3]
            value = self._parse_number(match.group(2))
            if value and month not in seen:
                rows.append({"month": month, "kwh": value, "confidence": 0.82, "source": "text"})
                seen.add(month)

        for table in tables:
            for row in table.get("rows", []):
                joined = " ".join(str(cell or "") for cell in row)
                month = next((m for m in MONTHS if re.search(rf"\b{m}", joined, re.I)), None)
                if not month or month in seen:
                    continue
                numbers = [self._parse_number(item) for item in NUMBER_RE.findall(joined)]
                numbers = [number for number in numbers if number and number > 10]
                if numbers:
                    rows.append({"month": month, "kwh": max(numbers), "confidence": 0.88, "source": "table"})
                    seen.add(month)

        rows.sort(key=lambda item: MONTHS.index(item["month"]) if item["month"] in MONTHS else 99)
        return rows

    def _find_after_label(self, text: str, labels: List[str]) -> Optional[str]:
        for label in labels:
            pattern = re.compile(rf"(?i){re.escape(label)}\s*[:#-]?\s*([^\n\r]{{2,80}})")
            match = pattern.search(text)
            if match:
                return match.group(1).strip()[:80]
        return None

    def _field(self, value: Any, confidence: float) -> Dict[str, Any]:
        return {"value": value, "confidence": round(confidence if value not in [None, ""] else min(confidence, 0.25), 2)}

    def _overall_confidence(self, fields: Dict[str, Dict[str, Any]], monthly: List[Dict[str, Any]]) -> float:
        scores = [field.get("confidence", 0) for field in fields.values()]
        scores.extend(row.get("confidence", 0) for row in monthly)
        return round(sum(scores) / len(scores), 2) if scores else 0.0

    def _check(self, name: str, passed: bool, evidence: str) -> Dict[str, str]:
        return {"name": name, "status": "pass" if passed else "needs_review", "evidence": evidence}

    def _parse_number(self, value: str) -> Optional[float]:
        cleaned = re.sub(r"[^0-9,.]", "", value).strip()
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

    def _load_proposals(self) -> Dict[str, Dict[str, Any]]:
        if not self.proposals_path.exists():
            return {}
        try:
            return json.loads(self.proposals_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_proposal(self, proposal: Dict[str, Any]) -> None:
        proposals = self._load_proposals()
        proposals[proposal["proposal_id"]] = proposal
        self.proposals_path.write_text(json.dumps(proposals, indent=2, ensure_ascii=False), encoding="utf-8")

    def _audit(self, proposal_id: str, actor: str, action: str, details: Dict[str, Any]) -> None:
        items = self.audit_log()
        items.append({"timestamp": utc_now(), "proposal_id": proposal_id, "actor": actor, "action": action, "details": details})
        self.audit_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")