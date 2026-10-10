# Architecture decision log

| Decision | Why | Alternative rejected | Cost / quality effect |
|---|---|---|---|
| FastAPI + Next.js | Supports typed APIs and a serious interactive graph workstation | Streamlit-only UI | More setup, substantially better graph interaction and separation |
| SQLite + NetworkX first | Local, inspectable, zero-service MVP | Mandatory PostgreSQL/Neo4j | Lower operational cost; adapter boundary preserves migration path |
| Deterministic router first | Makes retrieval decisions explainable and benchmarkable | Neural router from day one | Lower cost and easier diagnosis; learned policy can replace it later |
| Heuristic extraction fallback | Keeps the product runnable without paid APIs or Ollama | LLM for every relation | Lower quality on ambiguous text, but safer and reproducible |
| Evidence attached to every semantic object | Prevents graph claims from becoming unverifiable | Entity-relation-only graph | Slightly larger data model, materially better faithfulness and UI provenance |
