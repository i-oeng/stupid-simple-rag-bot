# Local Document Processing System

A local-first backend for processing operational PDFs such as utility bills, contracts, invoices, and internal documents. It extracts PDF text, detects QR codes, extracts tables, creates local embeddings, stores searchable evidence, runs rule-based validation, and can call a local Qwen model through Ollama for summaries and document QA.

## Current Features

- PDF upload and processing through FastAPI
- SHA-256 file hashing to avoid duplicate reprocessing
- Page-level text extraction with PyMuPDF
- QR detection and decoding with zxing-cpp
- Table extraction with pdfplumber
- Local embeddings with FastEmbed
- Local vector storage with ChromaDB
- Rule-based validation for text, QR, dates, amounts, and tables
- Ollama/Qwen endpoints for RAG-based QA and summaries
- Markdown processing reports
- No custom trained model, dataset, or paid API required

## Local API Setup

```powershell
cd C:\Users\user\Desktop\ragbot
.\.venv\Scripts\activate
pip install -r requirements.txt
cd backend
python app.py
```

Open:

```text
http://localhost:8000
http://localhost:8000/docs
```

## Ubuntu + Ollama + Qwen Setup

Install NVIDIA drivers and verify the GPU:

```bash
nvidia-smi
```

Install Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Pull Qwen3.5 9B:

```bash
ollama pull qwen3.5:9b
ollama run qwen3.5:9b
```

Run the backend on Ubuntu:

```bash
cd ~/ragbot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cd backend
export OLLAMA_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen3.5:9b
python app.py
```

## API

- `POST /process` - upload PDFs and receive chunks, QR codes, tables, validation, and report IDs
- `GET /documents` - list processed documents
- `GET /documents/{document_id}` - inspect one processed document
- `GET /search?q=...` - search indexed document chunks locally
- `GET /validate/{document_id}` - run rule-based validation
- `POST /ask` - ask Qwen over retrieved document chunks
- `POST /summarize/{document_id}` - generate a Qwen summary using extracted evidence
- `GET /download/report/{document_id}` - download a Markdown report
- `GET /health` - check service status
- `GET /stats` - view basic storage stats

## Recommended Telegram Layer

Keep FastAPI as the local processing engine. Add Telegram as the user interface:

- `/process` - upload a PDF
- `/search <query>` - search indexed documents
- `/summary <document_id>` - summarize with Qwen
- `/validate <document_id>` - show validation result
- `/report <document_id>` - download the Markdown report

Telegram is convenient for demos, but uploaded files pass through Telegram transport. For sensitive documents, use the local API or a local web UI.