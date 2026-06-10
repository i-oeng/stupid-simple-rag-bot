# Demo Script: Local DocumentOps Automation

## Goal

Show that the tool turns messy PDFs into reviewable operational cases with local extraction, confidence scoring, visual marker detection, human correction, workflow automation, and audit logs.

`PDF upload -> extraction -> confidence review -> correction/settings version -> approval workflow -> report/export -> automation handoff`

## Seven-Minute Walkthrough

1. Open the dashboard at `http://localhost:8501`.
2. Start on `Operations` and show total cases, review backlog, high-risk count, average completeness, and total amount.
3. Go to `Intake` and create a demo case. Use `contract` to show signature/stamp candidates or `incomplete` to show failed checklist items.
4. Go to `Status Board` and show where the case sits in the workflow.
5. Go to `Review Queue` and point out confidence scores, extracted fields, marker counts, and checklist failures.
6. Correct one field, such as a document ID or counterparty, and save corrections.
7. Go to `Settings & Diff`.
8. Change confidence threshold or require-marker and save a settings version.
9. Show the diff table between `v1` and `v2`.
10. Go to `Report` and export the PDF report.
11. Move status from `Needs Review` to `Approved`.
12. Go to `Audit` and show the creation, correction, settings, and status trail.
13. Go to `Integrations` and explain n8n, Telegram, Ollama/Qwen, Supabase, and CRM handoff.

## What To Say

I built a local-first DocumentOps prototype for processing messy operational PDFs. It extracts text, tables, QR codes, amounts, dates, document identifiers, and visual marker candidates. It creates a review case, scores confidence, flags missing or low-confidence fields, lets a reviewer correct data, versions changes, exports a report, and exposes automation handoffs for n8n, Telegram, Supabase, and CRM-style systems.

The important part is that it is not just a PDF parser. It wraps AI and extraction inside an operational workflow: intake, review, correction, approval, reporting, automation, and auditability.

## Strong Talking Points

- Local-first processing keeps sensitive documents off paid external AI APIs.
- Confidence scoring avoids pretending uncertain extraction is perfect.
- Visual marker detection finds likely stamps, signatures, and logos as review signals.
- Manual correction keeps the workflow usable when OCR or layouts are messy.
- Versioning makes review setting changes and corrections visible.
- n8n shows how the tool can fit into real business automation.
- Supabase schema shows a path from prototype storage to multi-user persistence.
- Ollama/Qwen is optional: the core workflow works without the LLM.

## Honest Limitations

- Visual marker detection is heuristic, not legal verification.
- It still needs more real-world PDFs to improve extraction rules.
- The current storage layer is local JSON, not multi-user Postgres.
- Scanned image-only PDFs need stronger OCR for production use.