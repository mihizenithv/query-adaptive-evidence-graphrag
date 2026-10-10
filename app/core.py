from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .providers import NvidiaProvider

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data" / "runtime"
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "graphrag.sqlite3"


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}:{hashlib.sha256(value.strip().lower().encode()).hexdigest()[:16]}"


@dataclass
class Evidence:
    id: str
    document_id: str
    chunk_id: str
    page: int | None
    section_path: list[str]
    text: str
    character_start: int
    character_end: int


@dataclass
class GraphNode:
    id: str
    type: str
    label: str
    confidence: float = 1.0
    community_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    type: str
    confidence: float
    evidence_ids: list[str] = field(default_factory=list)
    extraction_method: str = "heuristic"


@dataclass
class Chunk:
    id: str
    document_id: str
    text: str
    page: int | None
    section_path: list[str]
    parent_id: str | None
    start: int
    end: int


class Store:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.chunks: dict[str, Chunk] = {}
        self.evidence: dict[str, Evidence] = {}
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}
        self.queries: list[dict[str, Any]] = []
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(DB_PATH) as db:
            db.execute("create table if not exists documents (id text primary key, payload text not null)")
            db.execute("create table if not exists cache (key text primary key, payload text not null)")
            db.commit()

    def clear_document(self, document_id: str) -> None:
        self.documents.pop(document_id, None)
        for mapping, attr in ((self.chunks, "document_id"), (self.evidence, "document_id")):
            for key, value in list(mapping.items()):
                if getattr(value, attr) == document_id:
                    mapping.pop(key, None)
        for key, value in list(self.nodes.items()):
            if any(eid in self.evidence and self.evidence[eid].document_id == document_id for eid in value.evidence_ids):
                self.nodes.pop(key, None)
        for key, value in list(self.edges.items()):
            if any(eid in self.evidence and self.evidence[eid].document_id == document_id for eid in value.evidence_ids):
                self.edges.pop(key, None)


STORE = Store()


def sanitize_text(value: str) -> str:
    """Keep source text human-readable; never expose binary/control bytes."""
    value = value.replace("\ufffd", "")
    value = "".join(char for char in value if char in "\n\r\t" or ord(char) >= 32)
    return value.strip()


def readable_label(value: str, fallback: str) -> str:
    cleaned = sanitize_text(value).replace("\ufffd", "").strip()
    if not cleaned:
        return fallback
    letters = sum(char.isalpha() for char in cleaned)
    suspicious = sum(char in "�□\x00" for char in value)
    if letters < 3 or suspicious > 0 or letters / max(1, len(cleaned)) < 0.35:
        return fallback
    return cleaned


def extract_text(filename: str, data: bytes) -> tuple[str, list[str]]:
    suffix = Path(filename).suffix.lower()
    warnings: list[str] = []
    if suffix == ".txt":
        return sanitize_text(data.decode("utf-8", errors="ignore")), warnings
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(__import__("io").BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
            return sanitize_text("\n\n".join(pages)), warnings
        except Exception as exc:
            warnings.append(f"PDF parser unavailable: {exc}")
            return "", warnings + ["PDF bytes were not decoded as text because the parser was unavailable."]
    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(__import__("io").BytesIO(data))
            return sanitize_text("\n".join(p.text for p in doc.paragraphs)), warnings
        except Exception as exc:
            warnings.append(f"DOCX parser unavailable: {exc}")
            return "", warnings + ["DOCX bytes were not decoded as text because the parser was unavailable."]
    raise ValueError("Supported files are PDF, DOCX, and TXT")


def chunk_document(document_id: str, text: str, size: int = 900, overlap: int = 80) -> list[Chunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[Chunk] = []
    cursor = 0
    parent_id: str | None = None
    parent_buffer = ""
    parent_start = 0
    for paragraph in paragraphs:
        if not parent_buffer:
            parent_start = text.find(paragraph, cursor)
        parent_buffer = f"{parent_buffer}\n{paragraph}".strip()
        cursor = text.find(paragraph, cursor) + len(paragraph)
        if len(parent_buffer) >= 2200 or paragraph == paragraphs[-1]:
            parent_id = stable_id("parent", f"{document_id}:{parent_start}:{parent_buffer}")
            parent = Chunk(parent_id, document_id, parent_buffer, 1, [], None, parent_start, parent_start + len(parent_buffer))
            chunks.append(parent)
            child_text = parent_buffer
            child_cursor = parent_start
            while child_text:
                piece = child_text[:size]
                cid = stable_id("chunk", f"{document_id}:{child_cursor}:{piece}")
                chunks.append(Chunk(cid, document_id, piece, 1, [], parent_id, child_cursor, child_cursor + len(piece)))
                if len(child_text) <= size:
                    break
                child_text = child_text[max(1, size - overlap):]
                child_cursor += max(1, size - overlap)
            parent_buffer = ""
    return chunks


STOPWORDS = {"the", "and", "with", "from", "that", "this", "into", "their", "have", "will", "which", "for", "are", "was", "were", "been", "than", "about", "what", "does", "how", "why"}


def terms(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text) if t.lower() not in STOPWORDS]


def build_graph(document_id: str, chunks: list[Chunk]) -> None:
    child_chunks = [c for c in chunks if c.parent_id]
    for chunk in chunks:
        STORE.chunks[chunk.id] = chunk
        ev = Evidence(stable_id("evidence", chunk.id), document_id, chunk.id, chunk.page, chunk.section_path, chunk.text, chunk.start, chunk.end)
        STORE.evidence[ev.id] = ev
        node_type = "ParentChunk" if not chunk.parent_id else "ChildChunk"
        STORE.nodes[chunk.id] = GraphNode(chunk.id, node_type, readable_label(chunk.text[:72].replace("\n", " "), f"Source chunk {chunk.id[-6:]}"), evidence_ids=[ev.id])
        if chunk.parent_id:
            eid = stable_id("edge", f"{chunk.parent_id}:HAS_CHILD:{chunk.id}")
            STORE.edges[eid] = GraphEdge(eid, chunk.parent_id, chunk.id, "HAS_CHILD", 1.0, [ev.id])
    counts = Counter(term for c in child_chunks for term in terms(c.text))
    entity_terms = [term for term, count in counts.most_common(40) if count >= 1 and len(term) > 3]
    for term in entity_terms:
        nid = stable_id("entity", f"{document_id}:{term}")
        related = [c for c in child_chunks if term in terms(c.text)]
        evs = [stable_id("evidence", c.id) for c in related[:5]]
        STORE.nodes[nid] = GraphNode(nid, "Entity", term, min(0.99, 0.55 + len(related) * .08), evidence_ids=evs)
        for c in related[:5]:
            eid = stable_id("edge", f"{nid}:MENTIONS:{c.id}")
            STORE.edges[eid] = GraphEdge(eid, nid, c.id, "MENTIONS", .75, evs[:1])
    nodes = [n for n in STORE.nodes.values() if n.type == "Entity"]
    for left in nodes:
        for right in nodes:
            if left.id >= right.id:
                continue
            common = set(left.evidence_ids) & set(right.evidence_ids)
            if common:
                eid = stable_id("edge", f"{left.id}:RELATED_TO:{right.id}")
                STORE.edges[eid] = GraphEdge(eid, left.id, right.id, "RELATED_TO", min(.95, .55 + .1 * len(common)), list(common), "co-occurrence")
    layout_nodes()


def layout_nodes() -> None:
    ordered = sorted(STORE.nodes.values(), key=lambda n: n.id)
    width = max(1, math.ceil(math.sqrt(len(ordered))))
    for index, node in enumerate(ordered):
        node.x = 90 + (index % width) * 185
        node.y = 80 + (index // width) * 105


def search(query: str, limit: int = 8) -> list[tuple[Chunk, float]]:
    q = set(terms(query))
    scored = []
    for chunk in STORE.chunks.values():
        if not chunk.parent_id:
            continue
        ct = terms(chunk.text)
        overlap = len(q & set(ct))
        phrase = 0.25 if query.lower() in chunk.text.lower() else 0
        score = overlap / max(1, len(q)) + phrase
        if score > 0:
            scored.append((chunk, score))
    return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]


def route(query: str, preview: list[tuple[Chunk, float]]) -> dict[str, Any]:
    q = query.lower()
    multi = any(x in q for x in ("relationship", "related", "depends", "between", "how does", "path", "connect"))
    global_q = any(x in q for x in ("themes", "overall", "major", "across", "summarize", "landscape"))
    aggregate = any(x in q for x in ("how many", "count", "list all", "compare"))
    graph_conf = sum(n.confidence for n in STORE.nodes.values() if n.type == "Entity") / max(1, len([n for n in STORE.nodes.values() if n.type == "Entity"]))
    utility = min(1.0, .12 + .28 * multi + .18 * aggregate + .2 * global_q + .12 * min(1, len(set(terms(query))) / 6) + .1 * graph_conf)
    if global_q and utility >= .55:
        mode = "global_graph"
    elif multi or utility >= .52:
        mode = "local_graph"
    elif aggregate and len(STORE.edges) > 0:
        mode = "structured"
    else:
        mode = "hybrid_text"
    reasons = []
    if multi: reasons.append("relationship or multi-hop wording detected")
    if aggregate: reasons.append("comparison or aggregation signal detected")
    if global_q: reasons.append("corpus-level or thematic scope detected")
    if not reasons: reasons.append("graph structure adds limited expected value")
    return {"mode": mode, "graph_utility": round(utility, 3), "reasons": reasons, "signals": {"multi_hop": multi, "global": global_q, "aggregation": aggregate}, "preview_count": len(preview)}


def answer_query(query: str) -> dict[str, Any]:
    preview = search(query)
    decision = route(query, preview)
    seeds = [stable_id("entity", f"{next(iter(STORE.documents), '')}:{term}") for term in terms(query) if stable_id("entity", f"{next(iter(STORE.documents), '')}:{term}") in STORE.nodes]
    selected_chunks = [c for c, _ in preview]
    selected_edges: list[GraphEdge] = []
    selected_nodes = set(seeds)
    if decision["mode"] in {"local_graph", "global_graph", "structured"}:
        for edge in STORE.edges.values():
            if edge.source in selected_nodes or edge.target in selected_nodes:
                selected_edges.append(edge)
                selected_nodes.update((edge.source, edge.target))
    evidence = [{"claim": c.text[:180], "page": c.page, "chunk_id": c.id, "text": c.text} for c in selected_chunks[:5]]
    fallback_answer = selected_chunks[0].text[:420] if selected_chunks else "I don't have enough evidence in the indexed document to answer this question."
    generated = NvidiaProvider().generate_grounded(query, "\n\n".join(chunk.text for chunk in selected_chunks[:5]))
    text_answer = generated.text if generated else fallback_answer
    confidence = round(sum(score for _, score in preview[:3]) / max(1, min(3, len(preview))), 3)
    trace = [{"step": "Query", "status": "complete", "detail": query}, {"step": "Query analysis", "status": "complete", "detail": ", ".join(decision["reasons"])}, {"step": "Graph utility", "status": "complete", "detail": str(decision["graph_utility"])}, {"step": "Selected strategy", "status": "complete", "detail": decision["mode"]}, {"step": "Seeds", "status": "complete", "detail": f"{len(seeds)} entity seeds", "node_ids": seeds}, {"step": "Final evidence", "status": "complete", "detail": f"{len(selected_nodes)} nodes, {len(selected_edges)} edges", "node_ids": list(selected_nodes), "edge_ids": [e.id for e in selected_edges]}, {"step": "Answer", "status": "complete", "detail": "grounded response prepared"}]
    result = {"answer": text_answer, "retrieval_mode": decision["mode"], "confidence": confidence, "evidence": evidence, "decision": decision, "trace": trace, "node_ids": list(selected_nodes), "edge_ids": [e.id for e in selected_edges], "generation_provider": "nvidia" if generated else "local_fallback"}
    STORE.queries.append({"query": query, **result, "created_at": time.time()})
    return result


def graph_payload() -> dict[str, Any]:
    # Keep the rendered view responsive while preserving the complete graph in
    # the backend. Every returned object is still a real stored graph object.
    entities = sorted((n for n in STORE.nodes.values() if n.type == "Entity"), key=lambda n: (-n.confidence, n.id))[:140]
    chunks = sorted((n for n in STORE.nodes.values() if n.type == "ChildChunk"), key=lambda n: n.id)[:80]
    parents = sorted((n for n in STORE.nodes.values() if n.type == "ParentChunk"), key=lambda n: n.id)[:20]
    visible_nodes = entities + chunks + parents
    visible_ids = {node.id for node in visible_nodes}
    visible_edges = [edge for edge in STORE.edges.values() if edge.source in visible_ids and edge.target in visible_ids][:360]
    evidence_ids = {evidence_id for node in visible_nodes for evidence_id in node.evidence_ids}
    visible_evidence = [evidence for evidence in STORE.evidence.values() if evidence.id in evidence_ids]
    return {"nodes": [asdict(n) for n in visible_nodes], "edges": [asdict(e) for e in visible_edges], "evidence": [asdict(e) for e in visible_evidence], "documents": list(STORE.documents.values()), "total_nodes": len(STORE.nodes), "total_edges": len(STORE.edges), "rendered_nodes": len(visible_nodes), "rendered_edges": len(visible_edges)}
