# n8n Workflow Sketch

Use this workflow for the demo automation layer.

## Trigger

- Manual Trigger or Webhook: new bill/proposal request

## Steps

1. HTTP Request: `POST http://localhost:8000/process`
   - Send uploaded PDF as multipart form field `files`.
2. HTTP Request: `POST http://localhost:8000/solar/proposals/from-document/{document_id}`
   - Include client info, site data, and assumptions as JSON.
3. IF: proposal status is `Needs Review`
   - Send Telegram/Slack/email notification to founder/reviewer.
4. HTTP Request: `GET http://localhost:8000/solar/proposals/{proposal_id}`
   - Fetch proposal detail for CRM/dashboard sync.
5. CRM action
   - Create or update a lead/deal record with proposal ID, status, system size, savings estimate, and risk level.
6. Notification
   - Send summary: client, annual kWh, estimated kWp, annual savings, risk level, review URL.

## Suggested Notification Text

New solar proposal generated.
Client: {{$json.client_info.company}}
System: {{$json.calculation.estimated_system_size_kwp}} kWp
Savings: {{$json.calculation.estimated_annual_savings}}
Risk: {{$json.underwriting_checklist.risk_level}}
Status: {{$json.status}}

Review in the dashboard before sending.