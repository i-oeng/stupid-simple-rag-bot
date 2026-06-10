# Automation Artifacts

## n8n Workflow

`n8n_solar_workflow.json` is an importable workflow that demonstrates the operational handoff:

1. Receive a PDF through a webhook.
2. Call the local FastAPI `/process` endpoint.
3. Create a proposal from the processed document.
4. Branch if the proposal needs review.
5. Build a review notification payload for Telegram, Slack, email, or a queue.
6. Build a CRM-style row payload for Airtable, Supabase, Retool, or another operations system.
7. Respond to the webhook with the proposal ID and status.

## Suggested n8n Usage

- Import `n8n_solar_workflow.json` in n8n.
- Set `BACKEND_URL` to `http://backend:8000` in Docker, or to your host backend URL.
- Add real notification nodes after `Review Notification Payload`.
- Add a Supabase/Airtable/CRM node after `CRM Row Payload`.

The workflow intentionally leaves notification and CRM systems as payload nodes so the demo can run without external credentials.