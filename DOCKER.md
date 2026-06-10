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