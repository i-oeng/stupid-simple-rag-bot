# Demo Script: Solar Proposal Automation Assistant

## Goal

Show that the tool reduces proposal generation from days to hours by connecting the real workflow:

`utility bill -> extracted consumption -> human review -> assumptions -> proposal version -> approval dashboard -> client visibility`

## Seven-Minute Walkthrough

1. Open the dashboard at `http://localhost:8501`.
2. Start on `Operations` and show pipeline MW, approved MW, review backlog, average confidence, risk distribution, and CRM pipeline.
3. Go to `Intake` and click `Create demo proposal`.
4. Go to `Status Board` and show the proposal in `Needs Review`.
5. Go to `Review Queue` and point out annual kWh, estimated system size, estimated savings, low-confidence fields, and underwriting checks.
6. Correct one field, such as `tariff`, and save corrections.
7. Go to `Assumptions & Diff`.
8. Change one assumption, such as PPA rate or target offset.
9. Click `Create recalculated version`.
10. Show the diff table between `v1` and `v2`.
11. Go to `Client View` and show monthly consumption, solar production, grid usage, savings, and portfolio visibility.
12. Go to `Proposal Draft` and show the generated draft.
13. Move status from `Needs Review` to `Approved`.
14. Go to `Audit` and show the correction/version/status trail.
15. Go to `Integrations` and explain n8n, Telegram, Ollama/Qwen, Supabase, and CRM handoff.

## What To Say

I built a local-first prototype for solar proposal automation. The workflow accepts messy utility bills, extracts operational data, calculates a draft system size and savings estimate, flags low-confidence fields for review, lets a reviewer edit assumptions, produces proposal versions, records an audit trail, and exposes management and client-facing dashboards.

The important part is that it is not just a PDF parser. It maps directly to the business process: bill review, underwriting, proposal generation, internal approval, CRM visibility, and client energy reporting.

## Strong Talking Points

- Local-first processing keeps sensitive customer documents off paid external APIs.
- Confidence scoring avoids pretending uncertain extraction is perfect.
- Manual correction keeps the workflow usable when OCR or bill formats are messy.
- Assumption versioning makes commercial/finance review visible.
- Operations view shows CRM discipline and management visibility.
- Client View shows consumption, savings, and system performance.
- Audit logs support operational accountability.
- Ollama/Qwen is optional: deterministic calculations work without the LLM.

## Honest Limitations

- It still needs real utility bill samples to improve extraction heuristics.
- The current storage layer is local JSON, not multi-user Postgres.
- The savings model is a first-pass estimate, not a bankable engineering model.
- Table extraction quality depends on PDF quality and layout.

## Next Production Steps

- Replace JSON storage with Supabase Postgres tables.
- Add authentication and role-based approval.
- Add a real CRM integration through n8n.
- Add more bill-format test fixtures.
- Add export to branded PDF proposal.
- Add live inverter/monitoring data to the Client View.