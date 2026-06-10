# Local Model Guide

## Recommended Default

Use **Qwen3 8B, 4-bit quantized, through Ollama** for the local demo.

Why:

- Fits an 8 GB VRAM Linux machine better than 14B+ models.
- Strong instruction following for report drafting and document Q&A.
- Good multilingual ability for messy business documents.
- Works as an optional assistant while deterministic extraction and review logic stay in Python.

Start with:

```bash
ollama pull qwen3:8b
export OLLAMA_MODEL=qwen3:8b
```

Fallback:

```bash
ollama pull qwen2.5:7b-instruct
export OLLAMA_MODEL=qwen2.5:7b-instruct
```

## Practical Model Choices

| Machine | Model | Use |
| --- | --- | --- |
| 8 GB VRAM | `qwen3:8b` or `qwen2.5:7b-instruct` | Best local quality/speed balance |
| 8 GB VRAM, low memory pressure | `mistral:7b-instruct` | Backup if Qwen is slow or unavailable |
| CPU-only | `qwen2.5:3b-instruct` or `phi3:mini` | Basic demos only |
| 12-16 GB VRAM | `qwen3:14b` | Better writing/reasoning, slower |
| 24 GB+ VRAM | vLLM + Qwen3 14B/32B | Higher throughput/API-style serving |

## How This Project Uses the Model

Python handles:

- PDF extraction
- table parsing
- QR detection
- stamp/signature/logo candidate detection
- structured field extraction
- confidence scoring
- review checklist logic
- versioning and audit logging
- deterministic PDF/Markdown report generation

The LLM handles:

- document Q&A over retrieved excerpts
- concise summaries
- polished report wording from structured case data

That keeps the demo reliable even if the local model occasionally writes imperfect prose.

## Suggested Ollama Settings

- temperature: `0.1` to `0.3`
- context: `8192` or higher if your machine can handle it
- use short, structured prompts
- keep extracted values and review decisions outside the LLM