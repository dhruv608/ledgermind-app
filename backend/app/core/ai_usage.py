"""Tokens and cost of every AI call, so the cost of reading a client's papers is measured, not guessed
(which documents the Bedrock bill went on). Each call adds one record; AI_USAGE_LOG (a file
path) also writes them as JSON lines for a test run to add up."""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

# US dollars per million tokens (input, output): AWS Bedrock on-demand, standard tier, EU (London), from AWS's public
# price list (pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/eu-west-2/index.json)
PRICES = {
    "moonshotai.kimi-k2.5": (0.93, 4.65),
    "qwen.qwen3-vl-235b-a22b": (0.82, 4.12),
    "qwen.qwen3-235b-a22b-2507-v1:0": (0.34, 1.37),
    "deepseek.v3.2": (0.961, 2.8675),
    "openai.gpt-oss-120b-1:0": (0.23, 0.93),
}
# AWS Transcribe streaming, EU (London): US$ a second of audio, each stream billed for at least 15 seconds
TRANSCRIBE_PER_SECOND = 0.0001667
TRANSCRIBE_MIN_SECONDS = 15

_LOCK = threading.Lock()
RECORDS: List[Dict[str, Any]] = []


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = PRICES.get(model, (0.60, 3.00))
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000


def transcribe_cost(seconds: float, streams: int = 1) -> float:
    return streams * max(float(seconds), TRANSCRIBE_MIN_SECONDS) * TRANSCRIBE_PER_SECOND


_LOCAL = threading.local()


class collect:
    """The calls made in this thread while it is open, e.g. `with collect() as calls: ...` then sum(c["usd"]...):
    for the cost of one answer or one file read, made by code that only calls record()."""

    def __enter__(self) -> List[Dict[str, Any]]:
        self.calls: List[Dict[str, Any]] = []
        stack = getattr(_LOCAL, "stack", None)
        if stack is None:
            stack = _LOCAL.stack = []
        stack.append(self.calls)
        return self.calls

    def __exit__(self, *exc) -> None:
        _LOCAL.stack.remove(self.calls)


def record(model: str, mode: str, prompt: str, response: Optional[Dict[str, Any]]) -> None:
    """One call: the model, 'image' or 'text', the prompt's first words (which reader asked) and the tokens used."""
    usage = (response or {}).get("usage") or {}
    rec = {"t": round(time.time(), 1), "model": model, "mode": mode, "what": " ".join((prompt or "").split())[:70],
           "in": int(usage.get("inputTokens") or 0), "out": int(usage.get("outputTokens") or 0)}
    rec["usd"] = round(cost(model, rec["in"], rec["out"]), 6)
    for calls in getattr(_LOCAL, "stack", None) or []:
        calls.append(rec)
    with _LOCK:
        RECORDS.append(rec)
        path = os.environ.get("AI_USAGE_LOG")
        if path:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                pass
