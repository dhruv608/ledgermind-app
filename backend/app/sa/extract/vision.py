"""Scans and photos read by an AI model that sees pictures (R-IN-01: every image and scanned PDF is read). Two
different models read each money document; a figure the two do not agree on goes to a person. Every figure is checked again by code (p60.py)."""

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

from backend.app.core import ai_usage

logger = logging.getLogger(__name__)

READER = "moonshotai.kimi-k2.5"          # reads the document
CHECKER = "qwen.qwen3-vl-235b-a22b"      # reads it again, independently


_CLIENT = {}


def _client():
    """One Bedrock client for the readers, with a firm limit: a reply within 2 minutes, at most 6 tries (backing off
    when the service is busy), so one stuck call fails (the document is then a point to check) instead of holding a
    client's whole upload. Fewer tries are not enough when several uploads read at once: clear documents are then
    turned away as busy by both models."""
    if "c" not in _CLIENT:
        import boto3
        from botocore.config import Config
        from backend.app.core.config import settings
        region = settings.BEDROCK_REGION or settings.AWS_REGION
        kw = {"region_name": region, "config": Config(connect_timeout=10, read_timeout=120,
                                                       retries={"max_attempts": 6, "mode": "adaptive"})}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            kw.update(aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
        _CLIENT["c"] = boto3.client("bedrock-runtime", **kw)
    return _CLIENT["c"]


def _format(image: bytes) -> str:
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if image[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "webp"
    if image[:3] == b"GIF":
        return "gif"
    return "png"


# The service turns a larger picture away ('length limit exceeded': a 3 MB scan is refused, 2.1 MB goes through)
MAX_IMAGE = 2_000_000


def fit(image: bytes) -> bytes:
    """A picture over the size the service takes, made smaller: saved as a JPEG, then scaled down until it fits."""
    if len(image) <= MAX_IMAGE:
        return image
    import io
    from PIL import Image
    try:
        pic = Image.open(io.BytesIO(image)).convert("RGB")
    except Exception:
        # A picture the image library cannot open (HEIC, a damaged file): sent as it is, the service may still read it
        return image
    while True:
        buf = io.BytesIO()
        pic.save(buf, "JPEG", quality=90)
        if buf.tell() <= MAX_IMAGE or min(pic.size) < 600:
            return buf.getvalue()
        pic = pic.resize((int(pic.width * 0.8), int(pic.height * 0.8)))


SMALL_SIDE = 1400        # a picture whose longer side is under this is enlarged before it is sent


def enlarge(image: bytes) -> bytes:
    """A small picture made bigger (a small P60 picture the checking model misreads is read right at twice the
    size); a picture the image library cannot open is sent as it is."""
    import io
    from PIL import Image
    try:
        pic = Image.open(io.BytesIO(image))
        side = max(pic.size)
        if side >= SMALL_SIDE or side < 50:
            return image
        times = min(3.0, SMALL_SIDE / side * 1.2)
        big = pic.convert("RGB").resize((int(pic.width * times), int(pic.height * times)), Image.LANCZOS)
        buf = io.BytesIO()
        big.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return image


def plain(image: bytes) -> bytes:
    """The picture saved again as a plain RGB JPEG (a colour mode or format the service cannot sanitize: CMYK, a
    palette, an odd JPEG)."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.open(io.BytesIO(image)).convert("RGB").save(buf, "JPEG", quality=90)
    return fit(buf.getvalue())


def ask(model: str, image: bytes, prompt: str, max_tokens: int = 1200, grow: bool = True) -> Optional[Dict[str, Any]]:
    """The model's JSON answer about the picture, or None. grow=False: a small picture is sent as it is (a question
    about what a page is, made small on purpose, needs no enlarging)."""
    image = fit(enlarge(image) if grow else image)
    send = lambda img: _client().converse(
        modelId=model,
        messages=[{"role": "user", "content": [{"image": {"format": _format(img), "source": {"bytes": img}}},
                                               {"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0})
    try:
        r = send(image)
    except Exception as e:
        # The service could not sanitize the picture: once more as a plain RGB JPEG
        if "sanitiz" not in str(e).lower() and "image" not in str(e).lower():
            raise
        try:
            again = plain(image)
        except Exception:
            raise e                    # not a picture the image library knows either: the service's own reason
        r = send(again)
    ai_usage.record(model, "image", prompt, r)
    text = next((b["text"] for b in r["output"]["message"]["content"] if "text" in b), "")
    found = re.search(r"\{.*\}", text, re.S)
    if not found:
        return None
    try:
        return json.loads(found.group(0))
    except ValueError:
        return None


def ask_text(model: str, text: str, prompt: str, max_tokens: int = 1200) -> Optional[Dict[str, Any]]:
    """The model's JSON answer about a page's own text (a PDF with a text layer: exact digits, no picture)."""
    r = _client().converse(
        modelId=model,
        messages=[{"role": "user", "content": [{"text": f"{prompt}\n\nThe page's text, as printed:\n{text}"}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0})
    ai_usage.record(model, "text", prompt, r)
    out = next((b["text"] for b in r["output"]["message"]["content"] if "text" in b), "")
    found = re.search(r"\{.*\}", out, re.S)
    if not found:
        return None
    try:
        return json.loads(found.group(0))
    except ValueError:
        return None


def read_twice(image: bytes, prompt: str, max_tokens: int = 1200) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(the reader's answer, the checker's answer); either may be None when that model fails."""
    out = []
    for model in (READER, CHECKER):
        try:
            out.append(ask(model, image, prompt, max_tokens))
        except Exception as e:
            logger.warning("SA reader %s failed: %s: %s", model, type(e).__name__, str(e)[:200])
            out.append(None)
    return out[0], out[1]
