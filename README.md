# Solar Proposal Automation Assistant

A local-first prototype for reducing solar proposal generation from days to hours. It turns uploaded utility bills and client/site assumptions into a structured proposal workflow: bill parsing, confidence review, solar sizing, savings estimates, PPA-style proposal draft, underwriting checklist, approval board, and audit log.

## What It Does

- Upload utility bills and optional contracts/financial documents
- Extract text, QR codes, and tables from PDFs
- Build a cleaned monthly consumption table when month/kWh data is present
- Score extracted fields with confidence values
- Estimate solar system size from editable assumptions
- Estimate current energy cost, PPA blended cost, savings, capex, opex, and simple payback
- Generate a PPA-style proposal draft
- Produce an underwriting/risk checklist
- Track proposal status: `New -> Parsed -> Needs Review -> Approved -> Sent`
- Store proposal versions when assumptions change
- Show proposal diffs between versions
- Keep an audit log of status and assumption changes
- Optionally use Ollama + Qwen for polished proposal text and document Q&A
- Includes a Streamlit dashboard and a Telegram bot interface

## Core URLs

- FastAPI backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Streamlit dashboard: `http://localhost:8501`
- Ollama API: `http://localhost:11434`

## Local Windows Run

```powershell
cd C:\Users\user\Desktop\ragbot
.\.venv\Scripts\activate
pip install -r requirements.txt
cd backend
python app.py
```

In another terminal:

```powershell
cd C:\Users\user\Desktop\ragbot
.\.venv\Scripts\activate
streamlit run frontend_streamlit.py
```

## Ubuntu Setup

Install system basics:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip curl git
```

If you have an NVIDIA GPU, verify it:

```bash
nvidia-smi
```

Install Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:9b
```

Set up the app:

```bash
cd ~/ragbot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the backend:

```bash
cd ~/ragbot/backend
export OLLAMA_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen3.5:9b
python app.py
```

Start the dashboard in another terminal:

```bash
cd ~/ragbot
source .venv/bin/activate
export API_URL=http://127.0.0.1:8000
streamlit run frontend_streamlit.py --server.port 8501
```

Open:

```text
http://localhost:8501
http://localhost:8000/docs
```

## Main API Endpoints

- `POST /process` - upload PDFs and extract text, tables, QR codes, validation data
- `POST /solar/proposals/from-document/{document_id}` - create a solar proposal from a processed bill
- `GET /solar/proposals/board` - status board grouped by workflow stage
- `GET /solar/proposals/{proposal_id}` - proposal detail
- `PATCH /solar/proposals/{proposal_id}/status` - approve/reject/move status
- `PATCH /solar/proposals/{proposal_id}/assumptions` - edit assumptions and recalculate a new version
- `GET /solar/proposals/{proposal_id}/diff?left=v1&right=v2` - proposal diff mode
- `GET /solar/proposals/{proposal_id}/audit` - audit log
- `POST /solar/proposals/{proposal_id}/proposal-text` - generate polished proposal copy with Qwen/Ollama

## Telegram Bot

Create a bot with BotFather, then run:

```bash
cd ~/ragbot
source .venv/bin/activate
cd backend
export TELEGRAM_BOT_TOKEN=your_bot_token
export BACKEND_URL=http://127.0.0.1:8000
python telegram_bot.py
```

Telegram is convenient for demos, but uploaded files pass through Telegram transport. Sensitive review should use the local dashboard/API.

## n8n Automation

See `automation/n8n_solar_workflow.md` for a workflow sketch:

- Trigger on new bill upload
- Call `/process`
- Call `/solar/proposals/from-document/{document_id}`
- Notify reviewer if status is `Needs Review`
- Create/update CRM record
- Send proposal summary to Telegram/Slack/email

## Notes

The app currently uses local JSON files under `backend/storage/` plus Chroma vector storage. That keeps the prototype fast and fully local. For a more production-like deployment, the next step is replacing JSON storage with Supabase Postgres tables while keeping the same API behavior.