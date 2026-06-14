# n8n Workflow Sketch

Use this workflow for the demo automation layer.

## Trigger

- Webhook: new document intake request with a PDF binary field named `data`

## Steps

1. HTTP Request: `POST http://localhost:8000/process`
   - Send uploaded PDF as multipart form field `files`.
2. HTTP Request: `POST http://localhost:8000/cases/from-document/{document_id}`
   - Include client info, metadata, review settings, and actor as JSON.
   - Set `auto_prepare: true` so Qwen generates the case title and report text immediately after deterministic extraction.
3. IF: case status is `Needs Review`
   - True branch: build a Telegram/Slack/email notification payload, then continue to operations logging.
   - False branch: skip the notification payload and continue directly to operations logging.
4. Set: review notification payload
   - Include case ID, owner, document type, risk, next action, and review URL.
   - This node only runs for cases that need human review.
5. Set: operations row payload
   - Include case ID, status, risk, completeness, total amount, marker count, and source filename.
   - This node runs for both true and false branches.
6. Respond to webhook
   - Return case ID and status.

## Suggested Notification Text

New document case needs review.
Owner: {{$json.client_info.company || $json.metadata.owner}}
Case: {{$json.case_id}}
Type: {{$json.case_summary.document_type}}
Risk: {{$json.review_checklist.risk_level}}
Status: {{$json.status}}

Review in the dashboard before approval.
