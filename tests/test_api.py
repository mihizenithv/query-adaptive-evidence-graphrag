from fastapi.testclient import TestClient

from app.core import STORE
from app.main import app

client = TestClient(app)

SAMPLE = (
    "Acme Corp acquired Beta Labs in 2023. Beta Labs developed the Orion engine, "
    "which powers Acme's analytics platform. Dr. Rao leads the Orion team at Beta Labs. "
    "Acme Corp reported revenue of 12 million dollars in 2024."
)


def _reset() -> None:
    for document_id in list(STORE.documents):
        STORE.clear_document(document_id)
    STORE.documents.clear()


def test_health() -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_query_requires_document() -> None:
    _reset()
    response = client.post("/api/query", json={"query": "Who leads Orion?"})
    assert response.status_code == 409


def test_upload_then_query_returns_evidence() -> None:
    _reset()
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("notes.txt", SAMPLE.encode(), "text/plain")},
    )
    assert upload.status_code == 200
    body = upload.json()
    assert body["document"]["status"] == "ready"
    assert body["graph"]["nodes"]

    answer = client.post("/api/query", json={"query": "Who leads the Orion team?"})
    assert answer.status_code == 200
    assert answer.json()


def test_unsupported_file_type_is_rejected() -> None:
    response = client.post(
        "/api/documents/upload",
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 400


def test_short_query_is_rejected() -> None:
    assert client.post("/api/query", json={"query": "a"}).status_code == 422
