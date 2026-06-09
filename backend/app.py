import os
import shutil
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

from document_processor import LocalDocumentProcessor
from utils import cleanup_old_files, ensure_directories

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")

app = FastAPI(title="Local Document Processing API", version="3.1.0")

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


class AskRequest(BaseModel):
    question: str
    limit: int = 5


class SummarizeRequest(BaseModel):
    max_chunks: int = 8


@app.on_event("startup")
async def startup_event():
    cleanup_old_files(UPLOAD_DIR)
    print("Local document processor started")
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
        "mode": "local-document-processing",
        "model_required": False,
        "embeddings_enabled": processor.embeddings_enabled,
        "tables_enabled": processor.tables_enabled,
        "ollama_url": OLLAMA_URL,
        "ollama_model": OLLAMA_MODEL,
    }


@app.get("/stats")
async def get_stats():
    reports = list(REPORT_DIR.glob("*.md"))
    uploads = list(UPLOAD_DIR.glob("*.pdf"))
    return {
        "documents": len(processor.list_documents()),
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
        "name": "Local Document Processing API",
        "version": "3.1.0",
        "description": "Local PDF text extraction, QR detection, table extraction, embeddings, validation, and Qwen/Ollama document QA.",
        "endpoints": {
            "POST /process": "Upload PDFs and receive extracted chunks, QR data, tables, validation, and report IDs",
            "GET /documents": "List processed documents",
            "GET /search?q=...": "Search indexed document chunks locally",
            "GET /validate/{document_id}": "Run rule-based validation",
            "POST /ask": "Ask Qwen over retrieved document chunks",
            "POST /summarize/{document_id}": "Generate a Qwen summary using extracted evidence",
            "GET /download/report/{document_id}": "Download a Markdown processing report",
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
            {"role": "system", "content": "You are careful, concise, and evidence-bound. Never invent document facts."},
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