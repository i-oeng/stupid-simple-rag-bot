# Technical Showcase

This project is a self-directed solar operations automation prototype. It explores how document processing, local LLMs, workflow automation, dashboards, and lightweight CRM logic can shorten the path from utility bill review to proposal approval.

## Core Technical Skills Demonstrated

| Area | Implementation |
| --- | --- |
| Internal tools | Streamlit dashboard with intake, operations visibility, review queue, proposal board, client view, and audit log |
| Backend APIs | FastAPI service with upload, document processing, proposal generation, correction, status, diff, and audit endpoints |
| Document automation | PDF text extraction, table extraction, QR detection, document validation, monthly kWh extraction, confidence scoring |
| AI-assisted workflow | Optional local Ollama/Qwen proposal drafting and document Q&A, with deterministic calculations kept separate from LLM output |
| RAG/vector search | Local Chroma/FastEmbed document indexing and search for uploaded operational documents |
| Human-in-the-loop review | Manual correction screen for extracted fields and monthly consumption before approval |
| CRM-style workflow | Proposal stages: New, Parsed, Needs Review, Approved, Sent |
| Versioning | Assumption updates and extraction corrections create proposal versions that can be compared |
| Operational visibility | Pipeline MW, approved MW, review backlog, risk distribution, confidence, and proposal status tracking |
| Client visibility | Monthly consumption, estimated solar production, grid usage, savings, and portfolio table |
| Integrations | Telegram bot, n8n workflow notes, Supabase-ready persistence plan, FastAPI endpoints for external tools |
| Testing | Pytest coverage for proposal creation, assumption diffing, and manual correction recalculation |

## Why This Project Is Interesting

Utility bills and operational documents are messy, but business teams still need fast, explainable decisions. This prototype treats AI as part of an operations system rather than a standalone chatbot: documents are parsed, uncertain fields are flagged, humans can correct the data, assumptions can be versioned, and the output moves through a review pipeline.

## Demo Highlights

- Create a realistic demo proposal without needing sample documents.
- Upload utility bills and generate proposal records.
- Review extracted fields with confidence scores.
- Correct monthly kWh and recalculate savings.
- Compare proposal versions after changing assumptions.
- Track status and audit events.
- Show management pipeline visibility.
- Show a client-facing energy view.
- Explain where n8n, Telegram, Supabase, and CRM integrations fit.

## Future Improvements

- Export branded PDF proposals.
- Add a real n8n workflow JSON export.
- Replace local JSON storage with Supabase Postgres.
- Add auth and role-based review permissions.
- Add fixtures for multiple real utility bill layouts.
- Add live inverter or meter data to the client view.