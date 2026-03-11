from __future__ import annotations
import httpx

_ollama_client: httpx.AsyncClient | None = None


def init_ollama_client(base_url: str, timeout: float = 120.0) -> httpx.AsyncClient:
    global _ollama_client
    _ollama_client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
    return _ollama_client


async def close_ollama_client() -> None:
    global _ollama_client
    if _ollama_client is not None:
        await _ollama_client.aclose()
    _ollama_client = None


def get_ollama_client() -> httpx.AsyncClient:
    if _ollama_client is None:
        raise RuntimeError("Ollama HTTP client not initialized. Call init_ollama_client() first.")
    return _ollama_client


_slack_client: httpx.AsyncClient | None = None


def init_slack_client(timeout: float = 10.0) -> httpx.AsyncClient:
    global _slack_client
    _slack_client = httpx.AsyncClient(timeout=timeout)
    return _slack_client


async def close_slack_client() -> None:
    global _slack_client
    if _slack_client is not None:
        await _slack_client.aclose()
    _slack_client = None


def get_slack_client() -> httpx.AsyncClient:
    if _slack_client is None:
        raise RuntimeError("Slack HTTP client not initialized. Call init_slack_client() first.")
    return _slack_client
