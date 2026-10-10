# Query-Adaptive Evidence GraphRAG

A local-first, provenance-aware GraphRAG prototype that chooses between text, local graph, community, and structured retrieval per query.

## Quick start

From the repository root, run one command:

```powershell
npm run dev
```

The launcher installs missing frontend/backend dependencies, starts both services, and opens the app at `http://127.0.0.1:3000`.

Press `Ctrl+C` to stop services started by the launcher.

### Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

### Frontend

```powershell
cd web
npm install
npm run dev
```

The default local API is `http://127.0.0.1:8001`. Override it with
`NEXT_PUBLIC_API_URL` when needed.

The backend works without Ollama or paid APIs. Ollama can be enabled later through `OLLAMA_MODEL`.
For NVIDIA-hosted models, set `NVIDIA_API_KEY`, `NVIDIA_LLM_MODEL`, and
`NVIDIA_EMBEDDING_MODEL` in a local, gitignored `.env` file. Never commit keys.

## Project shape

The backend deliberately keeps graph, retrieval, routing, and provenance as explicit modules. NetworkX, vector search, BM25, and model providers are replaceable boundaries rather than hidden framework behavior.

## Research evaluation

Benchmark cases belong in `data/benchmark.jsonl`. The API exposes `/api/evaluate` for the initial deterministic comparison scaffold. Results are measurements, not assumed wins.
