# Local DocumentOps Automation

A local-first prototype for turning messy operational PDFs into reviewable workflow cases. It processes utility bills, contracts, invoices, financial statements, and general operational documents without relying on paid AI APIs.

The app combines document extraction, QR/stamp/signature/logo detection, confidence scoring, human review, RAG search, Telegram access, n8n automation, Supabase-ready persistence, and Docker deployment.

## What It Does

- Upload one or more PDF documents
- Extract text chunks, tables, QR codes, dates, amounts, and useful identifiers
- Detect stamp, signature, and logo candidates with local OpenCV heuristics
- Classify documents as utility bills, contracts, invoices, financial statements, or operational documents
- Create review cases with status: `New -> Parsed -> Needs Review -> Approved -> Sent`
- Automatically name new cases and prepare source-grounded Qwen report drafts after upload
- Score extracted fields with confidence values and flag low-confidence fields
- Let reviewers correct fields and structured period metrics
- Version settings and corrections so changes can be compared
- Generate Markdown and short-name PDF case reports
- Use Ollama + Qwen optionally for Q&A, summaries, and polished report text
- Include Streamlit, FastAPI, Telegram, n8n, Supabase schema, and Docker Compose

## Demo Flow

1. Start the backend and dashboard.
2. Open `http://localhost:8501`.
3. In `Intake`, upload PDFs or create a demo case.
4. In `Operations`, show backlog, risk, completeness, status, and amount visibility.
5. In `Review Queue`, inspect confidence scores, marker candidates, extracted fields, and checklist failures.
6. Correct a field or structured metric.
7. In `Review Settings`, change review thresholds or require a visual marker and review the settings history.
8. In `Report`, review the automatically prepared Qwen draft and export Markdown/PDF.
9. Move the case through `Needs Review -> Approved -> Sent`.
10. In `Audit`, show traceability.

## Local Windows Run

```powershell
cd C:\Users\user\Desktop\ragbot
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cd backend
python app.py
```

In another terminal:

```powershell
cd C:\Users\user\Desktop\ragbot
.\.venv\Scripts\activate
python -m streamlit run frontend_streamlit.py --server.port 8501
```

## Ubuntu Setup

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip curl git tesseract-ocr tesseract-ocr-eng
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b

cd ~/ragbot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the backend:

```bash
cd ~/ragbot/backend
source ../.venv/bin/activate
export OLLAMA_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen3:8b
export OCR_ENABLED=true
export OCR_DPI=220
python app.py
```

Start the dashboard:

```bash
cd ~/ragbot
source .venv/bin/activate
export API_URL=http://127.0.0.1:8000
python -m streamlit run frontend_streamlit.py --server.port 8501
```

Open `http://localhost:8501` and `http://localhost:8000/docs`.

## Docker

```bash
docker compose up --build
```

This starts the backend, dashboard, and n8n. The backend image includes Tesseract OCR for scanned PDFs. See `DOCKER.md` for the optional Ollama profile.

## Main API Endpoints

- `POST /process` - upload PDFs and extract text, QR data, visual markers, tables, validation, and reports
- `GET /documents/{document_id}/report` - download the Markdown processing report
- `GET /search?q=...` - search local document vectors
- `POST /ask` - ask Qwen/Ollama over retrieved chunks
- `POST /demo/seed?case=utility_bill|contract|invoice|incomplete` - generate a fresh Qwen demo case
- `POST /cases/from-document/{document_id}` - create a review case
- `GET /cases/board` - status board grouped by workflow stage
- `PATCH /cases/{case_id}/extraction` - correct extracted fields and metrics
- `PATCH /cases/{case_id}/settings` - edit review settings and create a new version
- `GET /cases/{case_id}/diff?left=v1&right=v2` - compare versions
- `PATCH /cases/{case_id}/status` - move a case through the workflow
- `GET /cases/{case_id}/audit` - case audit log
- `POST /cases/{case_id}/report-text` - generate polished report text
- `GET /cases/{case_id}/export-pdf` - export a PDF case report

## Telegram Bot

```bash
cd ~/ragbot/backend
source ../.venv/bin/activate
export TELEGRAM_BOT_TOKEN=your_bot_token
export BACKEND_URL=http://127.0.0.1:8000
python telegram_bot.py
```

Telegram supports PDF upload, validation, local search, Qwen Q&A, summaries, processing reports, and `/case` to create a review case. Sensitive documents should use the local dashboard/API because Telegram transport is external.

## n8n and Supabase

Import `automation/n8n_documentops_workflow.json` in n8n. It receives a PDF, calls `/process`, creates a case, branches on `Needs Review`, and prepares notification/CRM payloads.

Use `supabase/schema.sql` when moving from local JSON storage to Postgres. It covers clients, documents, chunks, vector embeddings, document cases, versions, audit events, workflow events, QR payloads, and visual marker candidates.

## Tests

```bash
python -m pytest -p no:cacheprovider tests
```

## Notes

The app currently uses local JSON under `backend/storage/` plus Chroma vector storage. Visual marker detection is useful for workflow triage, but it is not legal-grade signature verification.
