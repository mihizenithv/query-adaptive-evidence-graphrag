from app.core import GraphEdge, GraphNode, Store, chunk_document, route, sanitize_text, stable_id


def test_ids_are_stable():
    assert stable_id("entity", "Microsoft") == stable_id("entity", "microsoft")


def test_chunk_hierarchy_preserves_parent():
    chunks = chunk_document("doc:1", "Heading\n\n" + "important evidence " * 200)
    assert chunks
    assert any(c.parent_id for c in chunks)
    assert all(c.parent_id is None or any(p.id == c.parent_id for p in chunks) for c in chunks)


def test_route_avoids_graph_for_simple_question():
    decision = route("What is the definition?", [])
    assert decision["mode"] == "hybrid_text"


def test_graph_edges_reference_nodes():
    nodes = {"a": GraphNode("a", "Entity", "A"), "b": GraphNode("b", "Entity", "B")}
    edges = [GraphEdge("e", "a", "b", "RELATED_TO", .8)]
    assert all(edge.source in nodes and edge.target in nodes for edge in edges)


def test_source_sanitization_removes_binary_control_output():
    cleaned = sanitize_text("normal\x00text\ufffd\x1f\nnext")
    assert cleaned == "normaltext\nnext"
    assert "\ufffd" not in cleaned
