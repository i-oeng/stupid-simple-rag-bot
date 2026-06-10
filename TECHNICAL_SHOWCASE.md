# Technical Showcase

This is a self-directed local DocumentOps automation prototype. It explores how PDF processing, local LLMs, RAG, workflow automation, internal dashboards, Telegram access, and production-oriented data modeling can turn unstructured documents into reviewable operational cases.

## Core Technical Skills Demonstrated

| Area | Implementation |
| --- | --- |
| Internal tools | Streamlit dashboard with intake, operations visibility, status board, review queue, settings diff, generated reports, integrations, and audit log |
| Backend APIs | FastAPI service with upload, document processing, case creation, correction, status, diff, audit, search, summary, Q&A, and PDF export endpoints |
| Document automation | PDF text extraction, table extraction, QR detection, visual marker detection, validation, structured field extraction, confidence scoring |
| Visual AI workflow | Local OpenCV heuristics for stamp, signature, and logo candidates, exposed as review signals instead of final truth |
| AI-assisted workflow | Optional local Ollama/Qwen report writing, summaries, and document Q&A |
| RAG/vector search | Local Chroma/FastEmbed document indexing and retrieval |
| Human review | Manual correction screen for extracted fields and structured metrics before approval |
| Workflow system | Case stages: New, Parsed, Needs Review, Approved, Sent |
| Versioning | Review setting updates and extraction corrections create comparable case versions |
| Operational visibility | Backlog, risk, completeness, confidence, marker counts, amount exposure, and status tracking |
| Integrations | Telegram bot, importable n8n workflow JSON, Supabase schema, FastAPI endpoints for external tools |
| Testing | Pytest coverage for cases, visual marker review checks, diffs, corrections, and PDF export |
| Deployment | Docker Compose setup for backend, dashboard, n8n, and optional Ollama |

## Demo Highlights

- Create demo cases for a utility bill, contract, invoice, or incomplete document.
- Upload PDFs and generate review cases.
- Show QR/stamp/signature/logo signals from the document processor.
- Review extracted fields with confidence scores.
- Correct fields or structured period metrics.
- Require a visual marker for signed/stamped document types and watch the checklist change.
- Compare case versions after changing review settings.
- Export a PDF case report.
- Import `automation/n8n_documentops_workflow.json` to show automation handoff.
- Use `supabase/schema.sql` to show the production data model.

## Honest Limitations

- Visual marker detection is heuristic, not legal-grade verification.
- Extraction quality depends on PDF quality and layout.
- The current storage layer is local JSON, not a multi-user Postgres backend.
- Scanned image-only PDFs need stronger OCR for production use.
- The app should add authentication before shared sensitive-document use.

## Future Improvements

- Replace local JSON storage with Supabase Postgres.
- Add authentication and role-based approval.
- Add OCR for scanned PDFs with weak embedded text.
- Add more real-world document fixtures and regression tests.
- Add CRM/queue integrations through n8n.
- Add field-level provenance links back to document pages.