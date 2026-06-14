# Docker Runbook

## Backend + Dashboard + n8n

```bash
docker compose up --build
```

Open:

- Dashboard: `http://localhost:8501`
- API docs: `http://localhost:8000/docs`
- n8n: `http://localhost:5678`

Import the workflow from:

```text
automation/n8n_documentops_workflow.json
```

Inside n8n, `BACKEND_URL` is already set to `http://backend:8000`.

CLI import:

```bash
docker exec -i documentops-n8n n8n import:workflow --input=/files/automation/n8n_documentops_workflow.json
docker restart documentops-n8n
```

If CLI import fails on a newer n8n image, import the same JSON from the n8n editor UI using **Import from File** or **Import from Clipboard**.

## OCR Settings

The backend image installs Tesseract OCR and uses it as a fallback when a PDF page has weak native text extraction.

Useful environment variables:

```bash
OCR_ENABLED=true
OCR_DPI=220
OCR_LANG=eng
OCR_FORCE=false
```

For difficult scanned documents, try one run with:

```bash
OCR_FORCE=true OCR_DPI=260 docker compose up --build
```

Higher DPI can improve OCR quality but slows processing.

## Optional Ollama Container

```bash
docker compose --profile ollama up --build
```

Then pull a model inside the Ollama container:

```bash
docker exec -it documentops-ollama ollama pull qwen3:8b
```

For an 8 GB VRAM Linux machine, running Ollama directly on the host is usually simpler than Docker GPU passthrough. In that case, run the backend outside Docker or point `OLLAMA_URL` to your host Ollama server.

## Storage

The backend uses a Docker volume named `backend-storage`, so uploaded documents, local JSON state, reports, and vector storage survive container restarts.
