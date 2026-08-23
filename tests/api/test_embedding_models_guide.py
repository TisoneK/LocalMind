"""B-2026-08-23-14 guide: GET /api/models/embeddings reports whether the
configured embed model is actually pulled, and which alternative to suggest.

Without these fields the UI can't tell the user their memory stores will
fail (the endpoint force-includes the configured model in the dropdown list,
hiding the mismatch).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import api.routes.models as models_routes
from api.routes.models import list_embedding_models


def _run(coro):
    return asyncio.run(coro)


class FakeOllama:
    """Patches httpx.AsyncClient.get to answer /api/tags with pulled models."""

    def __init__(self, pulled: list[str]):
        self._pulled = pulled

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, timeout=5):
        class _Resp:
            def __init__(self, models):
                self.status_code = 200
                self._models = models

            def json(self):
                return {"models": [{"name": m} for m in self._models]}

        return _Resp(self._pulled)


def _patch_ollama(pulled, configured):
    patchers = [
        patch.object(models_routes.settings, "ollama_embed_model", configured),
        patch("httpx.AsyncClient", lambda **kw: FakeOllama(pulled)),
    ]
    for p in patchers:
        p.start()
    return patchers


class TestEmbeddingModelGuide:
    def test_configured_model_available(self):
        patchers = _patch_ollama(pulled=["mxbai-embed-large:latest"], configured="mxbai-embed-large")
        try:
            data = _run(list_embedding_models())
        finally:
            for p in patchers:
                p.stop()
        assert data["configured_available"] is True
        assert data["suggested"] is None

    def test_configured_model_missing_suggests_pulled_alternative(self):
        # nomic-embed-text configured but only mxbai pulled → guide fires.
        patchers = _patch_ollama(pulled=["mxbai-embed-large:latest"], configured="nomic-embed-text")
        try:
            data = _run(list_embedding_models())
        finally:
            for p in patchers:
                p.stop()
        assert data["configured_available"] is False
        assert data["suggested"] == "mxbai-embed-large:latest"

    def test_configured_model_missing_no_alternative(self):
        # Only the (missing) configured model would be listed — nothing to suggest.
        patchers = _patch_ollama(pulled=[], configured="nomic-embed-text")
        try:
            data = _run(list_embedding_models())
        finally:
            for p in patchers:
                p.stop()
        assert data["configured_available"] is False
        assert data["suggested"] is None
