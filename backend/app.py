import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from demo_data import demo_client_info, demo_document, demo_metadata, demo_review_settings
from document_cases import STATUS_FLOW, DocumentCaseService
from document_processor import LocalDocumentProcessor
from report_pdf import build_case_report_pdf
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


@app.on_event("startup")
async def startup_event():
    cleanup_old_files(UPLOAD_DIR)
    print("Local DocumentOps automation API started")
    print(f"Embeddings enabled: {processor.embeddings_enabled}")
    print(f"Tables enabled: {processor.tables_enabled}")


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
    document_case = case_service.create_from_document(
        document=demo_document(case),
        client_info=demo_client_info(case),
        metadata=demo_metadata(case),
        review_settings=demo_review_settings(case),
        actor="demo_seed",
    )
    return {"message": "Demo case created", "case": case, "document_case": document_case}


@app.post("/cases/from-document/{document_id}")
async def create_document_case(document_id: str, request: CaseCreateRequest = CaseCreateRequest()):
    document = processor.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        return case_service.create_from_document(
            document=document,
            client_info=request.client_info,
            metadata=request.metadata,
            review_settings=request.review_settings,
            actor=request.actor,
        )
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
    facts = _case_report_facts(item)
    prompt = f"""Create a short, professional title for this document review case.
Use only the supplied facts. Do not include the case ID. Do not use quotes.
Return only the title, maximum 8 words.

Facts:
{facts}
"""
    title = (await _ask_ollama(prompt)).strip().strip('"').strip("'")
    title = title.splitlines()[0] if title else ""
    try:
        return case_service.update_title(case_id, title, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/cases/{case_id}/report-text")
async def generate_polished_case_report(case_id: str):
    item = case_service.get_case(case_id)
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")
    facts = _case_report_facts(item)
    prompt = f"""You are drafting a concise operational document review report.
Use only the supplied facts and structured case data. Do not invent facts, do not change numbers, and do not add unsupported conclusions.
Return a clean Markdown report with sections: Executive Summary, Verified Numbers, Extracted Fields, Risks, Missing Items, Recommended Next Actions.

Facts to preserve exactly:
{facts}

Structured case data:
{item}
"""
    answer = await _ask_ollama(prompt)
    return {"case_id": case_id, "model": OLLAMA_MODEL, "facts": facts, "report_text": answer}


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
            "POST /demo/seed": "Create a demo document case",
            "POST /cases/from-document/{document_id}": "Create a document case from a processed PDF",
            "GET /cases/board": "Status board grouped by workflow stage",
            "PATCH /cases/{case_id}/extraction": "Correct extracted fields and structured metrics",
            "PATCH /cases/{case_id}/settings": "Edit review thresholds and create a new version",
            "GET /cases/{case_id}/diff": "Compare case versions",
            "PATCH /cases/{case_id}/status": "Move case through New, Parsed, Needs Review, Approved, Sent",
            "POST /cases/{case_id}/title": "Generate and save a short Qwen case title",
            "POST /cases/{case_id}/report-text": "Generate polished local LLM report text",
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


def _case_report_facts(item: Dict[str, Any]) -> Dict[str, Any]:
    extraction = item.get("extraction", {})
    fields = extraction.get("fields", {})
    summary = item.get("case_summary", {})
    checklist = item.get("review_checklist", {})
    return {
        "case_id": item.get("case_id"),
        "source_filename": item.get("source_filename"),
        "document_type": summary.get("document_type") or extraction.get("document_type"),
        "counterparty": fields.get("counterparty", {}).get("value"),
        "document_id_number": fields.get("document_id_number", {}).get("value"),
        "document_date": fields.get("document_date", {}).get("value"),
        "service_or_site": fields.get("service_or_site", {}).get("value"),
        "category_or_rate": fields.get("category_or_rate", {}).get("value"),
        "total_amount": summary.get("total_amount"),
        "period_metric_count": summary.get("period_metric_count"),
        "period_metric_total": summary.get("period_metric_total"),
        "data_completeness": summary.get("data_completeness"),
        "low_confidence_count": summary.get("low_confidence_count"),
        "qr_codes_found": summary.get("qr_codes_found"),
        "visual_markers_found": summary.get("visual_markers_found"),
        "risk_level": checklist.get("risk_level"),
        "failed_checks": checklist.get("failed_checks", []),
    }


async def _ask_ollama(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You are careful, concise, and evidence-bound. Never invent document facts or alter extracted values."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.1, "num_ctx": 8192},
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
