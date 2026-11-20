"""Embeddings for the knowledge base, from the provider in the settings:

  bedrock  (default) on AWS Bedrock, the same AWS account and role as the chat model (no other key in production):
           Amazon Titan Text Embeddings V2 (amazon.titan-embed-text-v2:0, London), or Cohere Embed v4
           (cohere.embed-v4:0) once the account's AWS Marketplace payment is set up.
  gemini   Google's gemini-embedding-001 (needs GOOGLE_API_KEY).

Pieces are embedded as documents, questions as queries (Cohere and Gemini treat the two differently; Titan does not).
Vectors are unit length for cosine search. Changing the provider, model or size means embedding every piece again
(backend/scripts/kb_reembed.py): vectors from two models cannot be compared."""

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List

import requests

from backend.app.core.config import settings

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
RETRIES = 9                     # a long load (an Act, a manual) rides out Bedrock throttling: waits up to a minute
PARALLEL = 12                   # requests at once
TITAN_MAX_CHARS = 30000         # Titan V2 takes up to 8,192 tokens; our pieces are far below


def _normalise(v: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _retry(call):
    for attempt in range(RETRIES):
        try:
            return call()
        except Exception as e:                     # throttling or a busy moment: wait and try again
            text = str(e)
            if attempt < RETRIES - 1 and any(w in text for w in ("Throttl", "TooManyRequests", "429", "503", "500",
                                                                  "timeout", "Timeout", "ServiceUnavailable")):
                time.sleep(min(2 ** attempt * 2, 60))
                continue
            raise


# ---- AWS Bedrock -------------------------------------------------------------------------------------------------
_client = None


def _bedrock():
    global _client
    if _client is None:
        from backend.app.core.s3 import aws_client
        _client = aws_client("bedrock-runtime", settings.KB_EMBED_REGION or settings.BEDROCK_REGION or settings.AWS_REGION)
    return _client


def _titan(text: str) -> List[float]:
    body = {"inputText": text[:TITAN_MAX_CHARS], "dimensions": settings.KB_EMBED_DIMS, "normalize": True}
    r = _retry(lambda: _bedrock().invoke_model(modelId=settings.KB_EMBED_MODEL, body=json.dumps(body)))
    return _normalise(json.loads(r["body"].read())["embedding"])


def _cohere(texts: List[str], kind: str) -> List[List[float]]:
    body = {"texts": texts, "input_type": kind, "embedding_types": ["float"], "output_dimension": settings.KB_EMBED_DIMS}
    r = _retry(lambda: _bedrock().invoke_model(modelId=settings.KB_EMBED_MODEL, body=json.dumps(body)))
    out = json.loads(r["body"].read())["embeddings"]
    return [_normalise(v) for v in (out["float"] if isinstance(out, dict) else out)]


def _bedrock_embed(texts: List[str], kind: str) -> List[List[float]]:
    if "cohere" in settings.KB_EMBED_MODEL:
        batches = [texts[i:i + 96] for i in range(0, len(texts), 96)]       # Cohere takes 96 to a request
        with ThreadPoolExecutor(PARALLEL) as pool:
            return [v for vs in pool.map(lambda b: _cohere(b, kind), batches) for v in vs]
    if len(texts) == 1:
        return [_titan(texts[0])]
    with ThreadPoolExecutor(PARALLEL) as pool:                                # Titan: one text to a request
        return list(pool.map(_titan, texts))


# ---- Google Gemini -----------------------------------------------------------------------------------------------
def _gemini_batch(texts: List[str], task: str) -> List[List[float]]:
    model = settings.KB_EMBED_MODEL
    body = {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]}, "taskType": task,
                          "outputDimensionality": settings.KB_EMBED_DIMS} for t in texts]}
    for attempt in range(RETRIES):
        r = requests.post(GEMINI_API.format(model=model), json=body, timeout=120,
                          headers={"x-goog-api-key": settings.GOOGLE_API_KEY})
        if r.status_code == 200:
            return [_normalise(e["values"]) for e in r.json()["embeddings"]]
        if r.status_code in (429, 500, 503) and attempt < RETRIES - 1:
            time.sleep(2 ** attempt * 2)
            continue
        raise RuntimeError(f"Gemini embedding failed ({r.status_code}): {r.text[:200]}")
    return []


def _gemini_embed(texts: List[str], task: str) -> List[List[float]]:
    if not settings.GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set: the knowledge base cannot embed text with Gemini")
    batches = [texts[i:i + 100] for i in range(0, len(texts), 100)]
    with ThreadPoolExecutor(PARALLEL) as pool:
        return [v for vs in pool.map(lambda b: _gemini_batch(b, task), batches) for v in vs]


# ---- The two calls the knowledge base uses -----------------------------------------------------------------------
def embed_documents(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    if settings.KB_EMBED_PROVIDER == "gemini":
        return _gemini_embed(texts, "RETRIEVAL_DOCUMENT")
    return _bedrock_embed(texts, "search_document")


def embed_query(text: str) -> List[float]:
    if settings.KB_EMBED_PROVIDER == "gemini":
        return _gemini_embed([text], "RETRIEVAL_QUERY")[0]
    return _bedrock_embed([text], "search_query")[0]
