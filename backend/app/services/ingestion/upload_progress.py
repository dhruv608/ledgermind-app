"""Upload progress for the upload screen, so a large ledger does not look stuck. The screen sends a random id with the
files and polls for the stage. Stored in a small temp file per upload, not in memory, because the server runs two
workers and the poll may reach the other one. Only the stage number is written, nothing about the client."""

import json
import os
import re
import tempfile
import time
from typing import Optional

STAGES = ["Reading the files", "Saving the ledger lines", "Mapping the accounts", "Reading the client details"]
FOLDER = os.path.join(tempfile.gettempdir(), "lm_upload_progress")
VALID_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
KEEP_SECONDS = 3600


def _path(upload_id: str) -> Optional[str]:
    return os.path.join(FOLDER, upload_id + ".json") if upload_id and VALID_ID.match(upload_id) else None


def mark(upload_id: Optional[str], stage: int) -> None:
    """The upload is at this stage (1-based). Never fails the upload."""
    path = _path(upload_id or "")
    if path is None:
        return
    try:
        os.makedirs(FOLDER, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"stage": stage, "at": time.time()}, f)
        _tidy()
    except OSError:
        pass


def stage_of(upload_id: str) -> dict:
    """{'stage': n (0 when not started or unknown), 'stages': [...]}."""
    path = _path(upload_id)
    stage = 0
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                stage = int(json.load(f).get("stage") or 0)
        except (OSError, ValueError):
            stage = 0
    return {"stage": stage, "stages": STAGES}


def _tidy() -> None:
    """Old uploads' files removed (an hour after their last stage)."""
    now = time.time()
    for name in os.listdir(FOLDER):
        p = os.path.join(FOLDER, name)
        try:
            if now - os.path.getmtime(p) > KEEP_SECONDS:
                os.remove(p)
        except OSError:
            pass
