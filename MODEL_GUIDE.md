# Local Model Guide

## Recommended Default

Use **Qwen3 8B, 4-bit quantized, through Ollama** for the local demo.

Why:

- Fits an 8 GB VRAM Linux machine better than 14B+ models.
- Strong instruction following for proposal drafting and document Q&A.
- Good multilingual ability for messy business documents.
- Works well as an optional assistant while deterministic extraction/calculation remains in Python.

Start with:

```bash
ollama pull qwen3:8b
export OLLAMA_MODEL=qwen3:8b
```

If `qwen3:8b` is not available in your Ollama install, use:

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

The model is intentionally not responsible for finance math or final truth. Python handles:

- PDF extraction
- table parsing
- monthly kWh cleanup
- confidence scoring
- system size calculation
- savings calculation
- proposal versioning
- audit logging

The LLM handles:

- document Q&A over retrieved excerpts
- concise summaries
- polished proposal wording from structured data

That keeps the demo reliable even if the local model occasionally writes imperfect prose.

## Suggested Ollama Settings

For proposal text:

- temperature: `0.1` to `0.3`
- context: `8192` or higher if your machine can handle it
- use short, structured prompts
- keep numeric calculations outside the LLM

For Qwen3 thinking mode, use it only when asking for analysis. For proposal drafting, prefer non-thinking or concise output so responses are faster and cleaner.