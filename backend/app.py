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

from demo_data import demo_assumptions, demo_client_info, demo_document, demo_site_data
from document_processor import LocalDocumentProcessor
from proposal_pdf import build_proposal_pdf
from solar_proposal import STATUS_FLOW, SolarProposalService
from utils import cleanup_old_files, ensure_directories

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

app = FastAPI(title="Solar Proposal Automation API", version="4.0.0")

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
solar_service = SolarProposalService(STORAGE_DIR)


class AskRequest(BaseModel):
    question: str
    limit: int = 5


class SummarizeRequest(BaseModel):
    max_chunks: int = 8


class SolarProposalCreateRequest(BaseModel):
    client_info: Dict[str, Any] = Field(default_factory=dict)
    site_data: Dict[str, Any] = Field(default_factory=dict)
    assumptions: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "user"


class ProposalStatusRequest(BaseModel):
    status: str
    actor: str = "user"
    note: str = ""


class AssumptionsUpdateRequest(BaseModel):
    assumptions: Dict[str, Any]
    actor: str = "user"


class ExtractionCorrectionRequest(BaseModel):
    fields: Dict[str, Any] = Field(default_factory=dict)
    monthly_consumption: Optional[List[Dict[str, Any]]] = None
    actor: str = "user"


@app.on_event("startup")
async def startup_event():
    cleanup_old_files(UPLOAD_DIR)
    print("Solar proposal automation API started")
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


@app.get("/solar/assumptions/default")
async def default_solar_assumptions():
    return solar_service.default_assumptions()


@app.post("/demo/seed")
async def seed_demo_proposal():
    proposal = solar_service.create_from_document(
        document=demo_document(case),
        client_info=demo_client_info(case),
        site_data=demo_site_data(case),
        assumptions=demo_assumptions(case),
        actor="demo_seed",
    )
    return {"message": "Demo proposal created", "case": case, "proposal": proposal}


@app.post("/solar/proposals/from-document/{document_id}")
async def create_solar_proposal(document_id: str, request: SolarProposalCreateRequest = SolarProposalCreateRequest()):
    document = processor.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        proposal = solar_service.create_from_document(
            document=document,
            client_info=request.client_info,
            site_data=request.site_data,
            assumptions=request.assumptions,
            actor=request.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return proposal


@app.get("/solar/proposals")
async def list_solar_proposals():
    return {"proposals": solar_service.list_proposals(), "status_flow": STATUS_FLOW}


@app.get("/solar/proposals/board")
async def solar_status_board():
    proposals = solar_service.list_proposals()
    board = {status: [] for status in STATUS_FLOW}
    for proposal in proposals:
        board.setdefault(proposal.get("status", "New"), []).append(proposal)
    return {"board": board, "status_flow": STATUS_FLOW}


@app.get("/solar/proposals/{proposal_id}")
async def get_solar_proposal(proposal_id: str):
    proposal = solar_service.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@app.patch("/solar/proposals/{proposal_id}/status")
async def update_solar_proposal_status(proposal_id: str, request: ProposalStatusRequest):
    try:
        return solar_service.update_status(proposal_id, request.status, actor=request.actor, note=request.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/solar/proposals/{proposal_id}/assumptions")
async def update_solar_proposal_assumptions(proposal_id: str, request: AssumptionsUpdateRequest):
    try:
        return solar_service.update_assumptions(proposal_id, request.assumptions, actor=request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/solar/proposals/{proposal_id}/extraction")
async def update_solar_proposal_extraction(proposal_id: str, request: ExtractionCorrectionRequest):
    patch = {"fields": request.fields}
    if request.monthly_consumption is not None:
        patch["monthly_consumption"] = request.monthly_consumption
    try:
        return solar_service.update_extraction(proposal_id, patch, actor=request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/solar/proposals/{proposal_id}/diff")
async def diff_solar_proposal_versions(proposal_id: str, left: str = "v1", right: str = "v2"):
    try:
        return solar_service.diff_versions(proposal_id, left, right)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/solar/proposals/{proposal_id}/audit")
async def solar_proposal_audit(proposal_id: str):
    return {"events": solar_service.audit_log(proposal_id)}


@app.post("/solar/proposals/{proposal_id}/proposal-text")
async def generate_polished_solar_proposal_text(proposal_id: str):
    proposal = solar_service.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    prompt = f"""You are drafting a concise commercial solar PPA proposal for commercial review.
Use only the supplied structured data. Do not change the numeric estimates.
Return a clean proposal draft with sections: Executive Summary, Consumption Review, Proposed System, Savings Estimate, Risks/Assumptions, Next Steps.

Structured proposal data:
{proposal}
"""
    answer = await _ask_ollama(prompt)
    return {"proposal_id": proposal_id, "model": OLLAMA_MODEL, "proposal_text": answer}



@app.get("/solar/proposals/{proposal_id}/export-pdf")
async def export_solar_proposal_pdf(proposal_id: str):
    proposal = solar_service.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    try:
        pdf_path = build_proposal_pdf(proposal, REPORT_DIR)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF export failed: {exc}") from exc
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)

@app.get("/download/report/{document_id}")
async def download_report(document_id: str):
    report_path = REPORT_DIR / f"{document_id}.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(report_path, media_type="text/markdown", filename=f"report_{document_id}.md")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "mode": "solar-proposal-automation",
        "model_required": False,
        "embeddings_enabled": processor.embeddings_enabled,
        "tables_enabled": processor.tables_enabled,
        "ollama_url": OLLAMA_URL,
        "ollama_model": OLLAMA_MODEL,
        "proposal_count": len(solar_service.list_proposals()),
    }


@app.get("/stats")
async def get_stats():
    reports = list(REPORT_DIR.glob("*.md"))
    uploads = list(UPLOAD_DIR.glob("*.pdf"))
    return {
        "documents": len(processor.list_documents()),
        "proposals": len(solar_service.list_proposals()),
        "reports": len(reports),
        "pending_uploads": len(uploads),
        "storage": {
            "reports_mb": sum(path.stat().st_size for path in reports) / (1024 * 1024),
            "uploads_mb": sum(path.stat().st_size for path in uploads) / (1024 * 1024),
        },
    }


@app.delete("/cleanup")
async def cleanup_storage():
    cleanup_old_files(UPLOAD_DIR, hours=0)
    return {"message": "Upload storage cleaned up successfully"}


@app.get("/")
async def root():
    return {
        "name": "Solar Proposal Automation API",
        "version": "4.0.0",
        "description": "Bill-to-proposal workflow: PDF extraction, confidence scoring, assumptions, solar sizing, savings, underwriting review, approvals, and Qwen/Ollama proposal text.",
        "endpoints": {
            "POST /process": "Upload PDFs and receive extracted chunks, QR data, tables, validation, and report IDs",
            "POST /solar/proposals/from-document/{document_id}": "Create a solar proposal from a processed utility bill",
            "GET /solar/proposals/board": "CRM-style status board",
            "POST /demo/seed": "Create a realistic demo proposal without uploading a PDF",
            "PATCH /solar/proposals/{proposal_id}/assumptions": "Edit assumptions and create a new proposal version",
            "PATCH /solar/proposals/{proposal_id}/extraction": "Correct extracted fields and monthly kWh, then recalculate",
            "GET /solar/proposals/{proposal_id}/diff": "Compare proposal versions",
            "PATCH /solar/proposals/{proposal_id}/status": "Move proposal through New, Parsed, Needs Review, Approved, Sent",
            "POST /solar/proposals/{proposal_id}/proposal-text": "Generate polished Qwen proposal text",
            "GET /solar/proposals/{proposal_id}/export-pdf": "Export a branded PDF proposal",
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


async def _ask_ollama(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You are careful, concise, and evidence-bound. Never invent document facts or change deterministic financial calculations."},
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