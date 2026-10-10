from __future__ import annotations

import hashlib
import time
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .core import STORE, answer_query, build_graph, chunk_document, extract_text, graph_payload

app = FastAPI(title="Query-Adaptive Evidence GraphRAG", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/documents/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    document_id = "doc:" + hashlib.sha256(data).hexdigest()[:16]
    try:
        text, warnings = extract_text(file.filename or "document.txt", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    chunks = chunk_document(document_id, text)
    STORE.clear_document(document_id)
    STORE.documents[document_id] = {"id": document_id, "name": file.filename, "pages": 1, "status": "ready", "chunk_count": len(chunks), "indexed_at": time.time(), "warnings": warnings}
    build_graph(document_id, chunks)
    return {"document": STORE.documents[document_id], "graph": graph_payload()}


@app.get("/api/graph")
def graph() -> dict[str, Any]:
    return graph_payload()


@app.post("/api/query")
def query(request: QueryRequest) -> dict[str, Any]:
    if not STORE.documents:
        raise HTTPException(status_code=409, detail="Upload a document before querying")
    return answer_query(request.query)


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    return {"documents": list(STORE.documents.values()), "node_count": len(STORE.nodes), "edge_count": len(STORE.edges), "evidence_count": len(STORE.evidence), "query_count": len(STORE.queries)}
