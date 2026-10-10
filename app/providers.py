"""Optional model providers. Credentials are read only from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratedAnswer:
    text: str
    reasoning: str | None = None


class NvidiaProvider:
    """Small adapter around NVIDIA endpoints with a no-network fallback."""

    def __init__(self) -> None:
        self.api_key = os.getenv("NVIDIA_API_KEY")
        self.model = os.getenv("NVIDIA_LLM_MODEL", "deepseek-ai/deepseek-v4-flash-0731")
        self.temperature = float(os.getenv("NVIDIA_TEMPERATURE", "0.2"))
        self.max_tokens = int(os.getenv("NVIDIA_MAX_TOKENS", "2048"))

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def generate_grounded(self, question: str, context: str) -> GeneratedAnswer | None:
        if not self.enabled:
            return None
        try:
            from langchain_nvidia_ai_endpoints import ChatNVIDIA

            client = ChatNVIDIA(
                model=self.model,
                api_key=self.api_key,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            response = client.invoke([
                {
                    "role": "system",
                    "content": "Answer only from the supplied evidence. If it is insufficient, say so. Do not expose chain-of-thought.",
                },
                {"role": "user", "content": f"Question: {question}\n\nEvidence:\n{context}"},
            ])
            text = str(response.content)
            if text.count("\ufffd") > 2 or sum(ord(char) < 9 for char in text) > 2:
                return None
            return GeneratedAnswer(
                text=text,
                reasoning=(response.additional_kwargs or {}).get("reasoning") or (response.additional_kwargs or {}).get("reasoning_content"),
            )
        except Exception:
            # Keep the retrieval system usable when the optional hosted provider
            # is unavailable; diagnostics remain available in application logs.
            return None


class NvidiaEmbeddingProvider:
    """Optional numeric embedding adapter. Vectors never enter source text/UI state."""

    def __init__(self) -> None:
        self.api_key = os.getenv("NVIDIA_API_KEY")
        self.model = os.getenv("NVIDIA_EMBEDDING_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def embed_documents(self, texts: list[str]) -> list[list[float]] | None:
        if not self.enabled:
            return None
        try:
            from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings

            client = NVIDIAEmbeddings(model=self.model, api_key=self.api_key)
            vectors = client.embed_documents([sanitize_for_embedding(text) for text in texts])
            return [[float(value) for value in vector] for vector in vectors]
        except Exception:
            return None


def sanitize_for_embedding(text: str) -> str:
    return " ".join(sanitize_text(text).split())
