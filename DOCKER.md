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

By default Docker Compose expects Ollama to run on the Ubuntu host:

```bash
ollama pull qwen3:8b
curl http://localhost:11434/api/tags
docker compose up -d --force-recreate backend
docker exec documentops-backend python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').read().decode()[:500])"
```

On Linux, `host.docker.internal` is provided through Docker's `host-gateway` mapping in `docker-compose.yml`.

If the container can resolve `host.docker.internal` but gets connection refused, make Ollama listen on the host gateway:

```bash
sudo systemctl edit ollama
```

Add:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
curl http://localhost:11434/api/tags
docker compose up -d --force-recreate backend
```

If you prefer an Ollama container instead, stop host Ollama first or free port `11434`, then run:

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
