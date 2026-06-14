import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from demo_data import demo_client_info, demo_metadata, demo_review_settings
from document_cases import STATUS_FLOW, DocumentCaseService
from document_processor import LocalDocumentProcessor
from report_pdf import build_case_report_pdf, build_generated_report_pdf
from utils import cleanup_old_files, ensure_directories

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

app = FastAPI(title="Local DocumentOps Automation API", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
REPORT_DIR = STORAGE_DIR / "reports"
ensure_directories(STORAGE_DIR)
processor = LocalDocumentProcessor(STORAGE_DIR)
case_service = DocumentCaseService(STORAGE_DIR)


class AskRequest(BaseModel):
    question: str
    limit: int = 5


class SummarizeRequest(BaseModel):
    max_chunks: int = 8


class CaseCreateRequest(BaseModel):
    client_info: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    review_settings: Dict[str, Any] = Field(default_factory=dict)
    auto_prepare: bool = False
    actor: str = "user"


class CaseStatusRequest(BaseModel):
    status: str
    actor: str = "user"
    note: str = ""


class SettingsUpdateRequest(BaseModel):
    review_settings: Dict[str, Any]
    actor: str = "user"


class ExtractionCorrectionRequest(BaseModel):
    fields: Dict[str, Any] = Field(default_factory=dict)
    period_metrics: Optional[List[Dict[str, Any]]] = None
    actor: str = "user"


class ReportPdfRequest(BaseModel):
    report_text: str


@app.on_event("startup")
async def startup_event():
    cleanup_old_files(UPLOAD_DIR)
    print("Local DocumentOps automation API started")
    print(f"Embeddings enabled: {processor.embeddings_enabled}")
    print(f"Tables enabled: {processor.tables_enabled}")
    print(f"OCR available: {processor.ocr_available}")


@app.post("/process")
async def process_pdfs(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    results = []
    saved_paths = []
    try:
        for file in files:
            if not file.filename or not file.filename.lower().endswith(".pdf"):
                continue
            safe_name = Path(file.filename).name
            file_path = UPLOAD_DIR / safe_name
            with file_path.open("wb") as output:
                shutil.copyfileobj(file.file, output)
            saved_paths.append(file_path)
        if not saved_paths:
            raise HTTPException(status_code=400, detail="No PDF files found")
        for path in saved_paths:
            processed = processor.process_pdf(path)
            result = processed.to_dict()
            result["validation"] = processor.validate_document(processed.document_id)
            results.append(result)
    finally:
        for path in saved_paths:
            path.unlink(missing_ok=True)
    return JSONResponse({
        "message": f"Processed {len(results)} PDF(s)",
        "visual_marker_detection": "local_cv_heuristic",
        "embeddings_enabled": processor.embeddings_enabled,
        "tables_enabled": processor.tables_enabled,
        "ocr_available": processor.ocr_available,
        "documents": results,
    })


@app.get("/documents")
async def list_documents():
    return {"documents": processor.list_documents()}


@app.get("/documents/{document_id}")
async def get_document(document_id: str):
    document = processor.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@app.get("/documents/{document_id}/report")
async def download_document_report(document_id: str):
    document = processor.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    report_path = Path(document.get("report_path", ""))
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report file not found")
    return FileResponse(report_path, media_type="text/markdown", filename=f"report_{document_id}.md")


@app.get("/search")
async def search_documents(q: str = Query(..., min_length=1), limit: int = Query(5, ge=1, le=20)):
    return processor.search(q, limit)


@app.get("/validate/{document_id}")
async def validate_document(document_id: str):
    result = processor.validate_document(document_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/ask")
async def ask_documents(request: AskRequest):
    search_result = processor.search(request.question, request.limit)
    if search_result.get("error"):
        raise HTTPException(status_code=503, detail=search_result["error"])
    context = _format_search_context(search_result["results"])
    prompt = f"""You are a local document review assistant.
Use only the provided document excerpts. If the answer is not in the excerpts, say so.
Return a concise answer with cited page references.

Question: {request.question}

Document excerpts:
{context}
"""
    answer = await _ask_ollama(prompt)
    return {"question": request.question, "answer": answer, "sources": search_result["results"], "model": OLLAMA_MODEL}


@app.post("/summarize/{document_id}")
async def summarize_document(document_id: str, request: SummarizeRequest = SummarizeRequest()):
    document = processor.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    chunks = document.get("chunks", [])[: request.max_chunks]
    validation = processor.validate_document(document_id)
    context = "\n\n".join(f"[Page {chunk.get('page')}] {chunk.get('text')}" for chunk in chunks)
    prompt = f"""You are a local document review assistant.
Use only the provided document excerpts and validation signals.
Return JSON with these keys: summary, document_type, key_fields, risks, missing_items, source_pages.
Do not invent facts.

Validation signals:
{validation}

Document excerpts:
{context}
"""
    answer = await _ask_ollama(prompt)
    return {"document_id": document_id, "summary": answer, "validation": validation, "model": OLLAMA_MODEL}


@app.get("/cases/settings/default")
async def default_case_settings():
    return case_service.default_settings()


@app.post("/demo/seed")
async def seed_demo_case(case: str = Query("utility_bill", pattern="^(utility_bill|contract|invoice|incomplete)$")):
    payload = await _generate_qwen_demo_payload(case)
    document = _demo_document_from_payload(case, payload)
    client_info = _clean_mapping(payload.get("client_info")) or demo_client_info(case)
    metadata = _clean_mapping(payload.get("metadata")) or demo_metadata(case)
    review_settings = demo_review_settings(case)
    review_settings.update({key: value for key, value in _clean_mapping(payload.get("review_settings")).items() if value is not None})
    if payload.get("title"):
        metadata["display_title"] = str(payload["title"]).strip()[:90]

    document_case = case_service.create_from_document(
        document=document,
        client_info=client_info,
        metadata=metadata,
        review_settings=review_settings,
        actor="qwen_demo_seed",
    )
    return {"message": "Qwen demo case generated", "case": case, "model": OLLAMA_MODEL, "document_case": document_case}


@app.post("/cases/from-document/{document_id}")
async def create_document_case(document_id: str, request: CaseCreateRequest = CaseCreateRequest()):
    document = processor.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        item = case_service.create_from_document(
            document=document,
            client_info=request.client_info,
            metadata=request.metadata,
            review_settings=request.review_settings,
            actor=request.actor,
        )
        if request.auto_prepare:
            item = await _prepare_case_with_qwen(item["case_id"], actor=request.actor)
        return item
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/cases")
async def list_document_cases():
    return {"cases": case_service.list_cases(), "status_flow": STATUS_FLOW}


@app.get("/cases/board")
async def case_status_board():
    cases = case_service.list_cases()
    board = {status: [] for status in STATUS_FLOW}
    for item in cases:
        board.setdefault(item.get("status", "New"), []).append(item)
    return {"board": board, "status_flow": STATUS_FLOW}


@app.get("/cases/{case_id}")
async def get_document_case(case_id: str):
    item = case_service.get_case(case_id)
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")
    return item


@app.patch("/cases/{case_id}/status")
async def update_case_status(case_id: str, request: CaseStatusRequest):
    try:
        return case_service.update_status(case_id, request.status, actor=request.actor, note=request.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/cases/{case_id}/settings")
async def update_case_settings(case_id: str, request: SettingsUpdateRequest):
    try:
        return case_service.update_settings(case_id, request.review_settings, actor=request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/cases/{case_id}/extraction")
async def update_case_extraction(case_id: str, request: ExtractionCorrectionRequest):
    patch = {"fields": request.fields}
    if request.period_metrics is not None:
        patch["period_metrics"] = request.period_metrics
    try:
        return case_service.update_extraction(case_id, patch, actor=request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/cases/{case_id}/diff")
async def diff_case_versions(case_id: str, left: str = "v1", right: str = "v2"):
    try:
        return case_service.diff_versions(case_id, left, right)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/cases/{case_id}/audit")
async def case_audit(case_id: str):
    return {"events": case_service.audit_log(case_id)}


@app.post("/cases/{case_id}/title")
async def generate_case_title(case_id: str, actor: str = "streamlit"):
    item = case_service.get_case(case_id)
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")
    title = await _generate_case_title_text(item)
    try:
        return case_service.update_title(case_id, title, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/cases/{case_id}/report-text")
async def generate_polished_case_report(case_id: str):
    item = case_service.get_case(case_id)
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")
    payload = await _generate_case_report_text(item)
    try:
        updated = case_service.update_ai_report(case_id, payload["report_text"], OLLAMA_MODEL, facts=payload["facts"], actor="streamlit")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"case_id": case_id, "model": OLLAMA_MODEL, "facts": payload["facts"], "report_text": payload["report_text"], "case": updated}


@app.post("/cases/{case_id}/report-pdf")
async def export_generated_report_pdf(case_id: str, request: ReportPdfRequest):
    item = case_service.get_case(case_id)
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")
    if not request.report_text.strip():
        raise HTTPException(status_code=400, detail="Report text is empty")
    try:
        pdf_path = build_generated_report_pdf(item, request.report_text, REPORT_DIR)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF export failed: {exc}") from exc
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/cases/{case_id}/export-pdf")
async def export_case_pdf(case_id: str):
    item = case_service.get_case(case_id)
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        pdf_path = build_case_report_pdf(item, REPORT_DIR)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF export failed: {exc}") from exc
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "mode": "local-documentops-automation",
        "model_required": False,
        "embeddings_enabled": processor.embeddings_enabled,
        "tables_enabled": processor.tables_enabled,
        "ocr_available": processor.ocr_available,
        "ollama_url": OLLAMA_URL,
        "ollama_model": OLLAMA_MODEL,
        "case_count": len(case_service.list_cases()),
    }


@app.get("/stats")
async def get_stats():
    reports = list(REPORT_DIR.glob("*.pdf")) + list(REPORT_DIR.glob("*.md"))
    uploads = list(UPLOAD_DIR.glob("*.pdf"))
    return {"documents": len(processor.list_documents()), "cases": len(case_service.list_cases()), "reports": len(reports), "pending_uploads": len(uploads)}


@app.delete("/cleanup")
async def cleanup_storage():
    cleanup_old_files(UPLOAD_DIR, hours=0)
    return {"message": "Upload storage cleaned up successfully"}


@app.get("/")
async def root():
    return {
        "name": "Local DocumentOps Automation API",
        "version": "5.0.0",
        "description": "Local document automation: PDF extraction, QR/stamp/signature/logo detection, confidence scoring, review queue, RAG search, workflow handoff, audit logs, and generated reports.",
        "endpoints": {
            "POST /process": "Upload PDFs and receive extracted chunks, QR data, visual-marker candidates, tables, validation, and report IDs",
            "POST /demo/seed": "Generate a fresh Qwen demo document case",
            "POST /cases/from-document/{document_id}": "Create a document case from a processed PDF; set auto_prepare=true to generate title and report text",
            "GET /cases/board": "Status board grouped by workflow stage",
            "PATCH /cases/{case_id}/extraction": "Correct extracted fields and structured metrics",
            "PATCH /cases/{case_id}/settings": "Edit review thresholds and create a new version",
            "GET /cases/{case_id}/diff": "Compare case versions",
            "PATCH /cases/{case_id}/status": "Move case through New, Parsed, Needs Review, Approved, Sent",
            "POST /cases/{case_id}/title": "Generate and save a short Qwen case title",
            "POST /cases/{case_id}/report-text": "Generate polished local LLM report text",
            "POST /cases/{case_id}/report-pdf": "Export the generated report text as a PDF",
            "GET /cases/{case_id}/export-pdf": "Export a PDF case report",
            "GET /documents/{document_id}/report": "Download the Markdown processing report",
        },
    }


def _format_search_context(results: List[dict]) -> str:
    lines = []
    for index, item in enumerate(results, start=1):
        metadata = item.get("metadata") or {}
        page = metadata.get("page", "unknown")
        filename = metadata.get("filename", "unknown")
        lines.append(f"[{index}] File: {filename}, Page: {page}\n{item.get('text', '')}")
    return "\n\n".join(lines)


async def _prepare_case_with_qwen(case_id: str, actor: str = "system") -> Dict[str, Any]:
    item = case_service.get_case(case_id)
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")

    if not (item.get("metadata") or {}).get("display_title"):
        try:
            title = await _generate_case_title_text(item)
            item = case_service.update_title(case_id, title, actor=actor)
        except Exception as exc:
            item = case_service.record_automation_error(case_id, "title", _error_text(exc), actor=actor)

    try:
        latest = case_service.get_case(case_id) or item
        payload = await _generate_case_report_text(latest)
        item = case_service.update_ai_report(case_id, payload["report_text"], OLLAMA_MODEL, facts=payload["facts"], actor=actor)
    except Exception as exc:
        item = case_service.record_automation_error(case_id, "report", _error_text(exc), actor=actor)

    return item


async def _generate_case_title_text(item: Dict[str, Any]) -> str:
    facts = _case_report_facts(item)
    fallback = _fallback_case_title(item)
    prompt = f"""Create a short, professional title for this document review case.
Use only the supplied facts. Do not include the case ID. Do not use quotes.
Prefer the real document type, parties/counterparty, and document reference.
Return only the title, maximum 7 words.

Facts:
{facts}
"""
    title = (await _ask_ollama(prompt)).strip().strip('"').strip("'")
    title = title.splitlines()[0] if title else ""
    return _clean_case_title(title, fallback)


async def _generate_case_report_text(item: Dict[str, Any]) -> Dict[str, Any]:
    facts = _case_report_facts(item)
    prompt = f"""You are drafting an evidence-bound operational document review report.
Use only the supplied extracted fields and document excerpts. Do not invent facts, do not change numbers, and do not add unsupported legal conclusions.
Do not use markdown tables because this report is exported to PDF. Use short paragraphs and bullets.
If a value is missing, write "Not extracted".

For contracts, the useful report is not a numbers report. Summarize the document substance: parties, purpose, effective date, term/survival, confidentiality duties, return/destruction, governing law or dispute venue, signature status, and review flags.
For bills or invoices, emphasize account/vendor, dates, totals, usage/line metrics, low-confidence values, and review flags.

Return Markdown with these exact sections:
## Executive Summary
## Important Details
## Extracted Fields
## Risks And Review Flags
## Recommended Next Actions

Facts and source excerpts:
{facts}
"""
    answer = await _ask_ollama(prompt)
    return {"facts": facts, "report_text": answer}


def _error_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc)


def _case_report_facts(item: Dict[str, Any]) -> Dict[str, Any]:
    extraction = item.get("extraction", {})
    fields = extraction.get("fields", {})
    summary = item.get("case_summary", {})
    checklist = item.get("review_checklist", {})
    return {
        "source_filename": item.get("source_filename"),
        "document_type": summary.get("document_type") or extraction.get("document_type"),
        "extracted_fields": {
            name: {"value": payload.get("value"), "confidence": payload.get("confidence")}
            for name, payload in fields.items()
            if isinstance(payload, dict)
        },
        "period_metrics": extraction.get("period_metrics", [])[:18],
        "summary": {
            "total_amount": summary.get("total_amount"),
            "period_metric_count": summary.get("period_metric_count"),
            "period_metric_total": summary.get("period_metric_total"),
            "data_completeness": summary.get("data_completeness"),
            "low_confidence_count": summary.get("low_confidence_count"),
            "qr_codes_found": summary.get("qr_codes_found"),
            "visual_markers_found": summary.get("visual_markers_found"),
            "visual_marker_types": summary.get("visual_marker_types", {}),
            "risk_level": checklist.get("risk_level"),
            "failed_checks": checklist.get("failed_checks", []),
        },
        "review_checks": checklist.get("checks", []),
        "document_excerpts": _case_document_excerpts(item),
    }


def _case_document_excerpts(item: Dict[str, Any], max_chars: int = 5200) -> List[Dict[str, Any]]:
    document = processor.get_document(str(item.get("document_id") or ""))
    if not document:
        return []
    excerpts = []
    used = 0
    for chunk in document.get("chunks", [])[:12]:
        text = re.sub(r"\s+", " ", str(chunk.get("text") or "")).strip()
        if not text:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        snippet = text[:remaining].rstrip()
        used += len(snippet)
        excerpts.append({"page": chunk.get("page"), "text": snippet})
    return excerpts


def _fallback_case_title(item: Dict[str, Any]) -> str:
    extraction = item.get("extraction", {})
    fields = extraction.get("fields", {})
    document_type = str((item.get("case_summary", {}) or {}).get("document_type") or extraction.get("document_type") or "document").replace("_", " ").title()
    source = Path(str(item.get("source_filename") or "")).stem.replace("_", " ").strip()
    document_id = fields.get("document_id_number", {}).get("value")
    counterparty = fields.get("counterparty", {}).get("value")
    if source and source.lower() not in {"document", "document case"}:
        return source
    if counterparty and document_id:
        first_party = str(counterparty).split(";")[0].split(",")[0].strip()
        return f"{document_type} - {first_party}"
    if document_id:
        return f"{document_type} - {document_id}"
    if counterparty:
        return f"{document_type} - {counterparty}"
    return "Document Review"


def _clean_case_title(title: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", str(title or "")).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or len(cleaned.split()) > 9 or len(cleaned) > 64:
        cleaned = fallback
    cleaned = re.sub(r"\s+", " ", str(cleaned or "Document Review")).strip(" .")
    return cleaned[:64].rstrip(" -_") or "Document Review"


async def _generate_qwen_demo_payload(case: str) -> Dict[str, Any]:
    prompt = f"""Generate a fresh synthetic demo document for a local document review dashboard.
Document category: {case}

Return ONLY valid JSON. No markdown. No code fences.

Required JSON shape:
{{
  "title": "short human title",
  "filename": "demo filename ending in .pdf",
  "document_text": "realistic document text with extractable labels and line breaks",
  "client_info": {{"company": "company name", "name": "contact name", "email": "contact email"}},
  "metadata": {{"owner": "short review owner", "department": "department", "priority": "normal|high|urgent"}},
  "review_settings": {{"materiality_amount": 10000, "confidence_threshold": 0.75, "review_sla_hours": 24, "currency": "USD", "require_visual_marker": true}},
  "tables": [[["Header 1", "Header 2"], ["Row", "Value"]]],
  "qr_text": "short QR payload",
  "visual_markers": [{{"page": 1, "kind": "logo_candidate|signature_candidate|stamp_candidate", "confidence": 0.55, "bbox": {{"x": 40, "y": 40, "width": 100, "height": 40}}, "method": "qwen_demo"}}]
}}

Rules:
- Make each generation different: company, location, amounts, IDs, and dates must vary.
- Use realistic but fictional data only.
- Keep document_text between 18 and 45 lines.
- Use labels that a parser can extract, such as Account Number, Invoice Number, Contract Number, Customer, Vendor, Client, Counterparty, Due date, Effective Date, Service Address, Project Site, Tariff, Category, Cost Center, Amount due, Invoice total, or Contract Value.
- For utility_bill include at least 6 monthly lines like "Jan 42100 kWh".
- For invoice include at least 3 line/month metric rows and an Invoice total.
- For contract include Contract Number, Counterparty or Party, Effective Date, Contract Value, Category, and Project Site.
- For incomplete intentionally omit at least two important fields and set require_visual_marker to true with an empty visual_markers list.
- For contract include at least one signature_candidate or stamp_candidate.
- The tables value must be a list of tables; each table must be a list of rows; each row must be a list of strings.
"""
    answer = await _ask_ollama(
        prompt,
        system_content="You generate realistic synthetic business documents for software demos. Return strict JSON only.",
        temperature=0.75,
    )
    try:
        return _parse_json_object(answer)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Qwen returned invalid demo JSON: {exc}") from exc


def _parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise ValueError("No JSON object found")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise ValueError("Top-level JSON must be an object")
    return payload


def _demo_document_from_payload(case: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    document_id = f"qwen-demo-{uuid.uuid4().hex}"
    filename = str(payload.get("filename") or f"qwen_demo_{case}.pdf").strip() or f"qwen_demo_{case}.pdf"
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    text = str(payload.get("document_text") or "").strip()
    if len(text) < 40:
        raise HTTPException(status_code=502, detail="Qwen demo document text was too short")

    return {
        "document_id": document_id,
        "filename": Path(filename).name,
        "pages": 2,
        "metadata": {"source": "qwen_demo", "case": case},
        "qr_codes": [{"page": 1, "text": str(payload.get("qr_text") or f"QWEN-DEMO-{case.upper()}"), "type": "qrcode"}],
        "visual_markers": _clean_visual_markers(payload.get("visual_markers")),
        "tables": _clean_demo_tables(document_id, payload.get("tables")),
        "chunks": [
            {"id": f"{document_id}-p1-c0", "chunk_id": f"{document_id}-p1", "document_id": document_id, "filename": Path(filename).name, "page": 1, "text": text},
        ],
    }


def _clean_mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_demo_tables(document_id: str, tables: Any) -> List[Dict[str, Any]]:
    if not isinstance(tables, list):
        return []
    if tables and isinstance(tables[0], list) and (not tables[0] or not isinstance(tables[0][0], list)):
        tables = [tables]
    cleaned_tables = []
    for index, table in enumerate(tables[:3]):
        if not isinstance(table, list):
            continue
        rows = []
        for row in table[:24]:
            if isinstance(row, list):
                rows.append([str(cell) for cell in row[:8]])
        if rows:
            cleaned_tables.append({"document_id": document_id, "page": 1, "table_index": index, "rows": rows})
    return cleaned_tables


def _clean_visual_markers(markers: Any) -> List[Dict[str, Any]]:
    if not isinstance(markers, list):
        return []
    allowed = {"logo_candidate", "signature_candidate", "stamp_candidate"}
    cleaned = []
    for marker in markers[:5]:
        if not isinstance(marker, dict):
            continue
        kind = str(marker.get("kind") or "").strip()
        if kind not in allowed:
            continue
        bbox = marker.get("bbox") if isinstance(marker.get("bbox"), dict) else {}
        try:
            page = int(marker.get("page") or 1)
            confidence = round(float(marker.get("confidence") or 0.55), 2)
            x = float(bbox.get("x", 40))
            y = float(bbox.get("y", 40))
            width = float(bbox.get("width", 80))
            height = float(bbox.get("height", 30))
        except (TypeError, ValueError):
            continue
        cleaned.append({
            "page": page,
            "kind": kind,
            "confidence": confidence,
            "bbox": {
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            },
            "method": "qwen_demo",
        })
    return cleaned


async def _ask_ollama(prompt: str, system_content: str = "You are careful, concise, and evidence-bound. Never invent document facts or alter extracted values.", temperature: float = 0.1) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Ollama request failed: {exc}") from exc


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
