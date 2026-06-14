# Automation Artifacts

## n8n Workflow

`n8n_documentops_workflow.json` is an importable workflow that demonstrates the operational handoff:

1. Receive a PDF through a webhook.
2. Call the local FastAPI `/process` endpoint.
3. Create a document review case from the processed document.
4. Branch if the case needs review.
5. Build a review notification payload for Telegram, Slack, email, or a queue.
6. Build a CRM-style row payload for Airtable, Supabase, Retool, or another operations system.
7. Respond to the webhook with the case ID and status.

## Suggested n8n Usage

- Import `n8n_documentops_workflow.json` in n8n.
- Set `BACKEND_URL` to `http://backend:8000` in Docker, or to your host backend URL.
- Add real notification nodes after `Review Notification Payload`.
- Add a Supabase/Airtable/CRM node after `Operations Row Payload`.

The workflow intentionally leaves notification and CRM systems as payload nodes so the demo can run without external credentials.

## CLI Import

From the project root:

```bash
docker exec -i documentops-n8n n8n import:workflow --input=/files/automation/n8n_documentops_workflow.json
docker restart documentops-n8n
```

If your n8n version rejects CLI import, use the editor UI instead:

1. Open n8n.
2. Select **Import from File** or **Import from Clipboard**.
3. Import `automation/n8n_documentops_workflow.json`.
4. Save, then activate the workflow.
