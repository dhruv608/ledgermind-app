"""What the app works out from a client's uploaded files, kept in memory while the server runs.

The same bytes always read the same way, so a result is kept under a digest of the bytes it came from: a new upload is
new bytes and is read again. Each server worker keeps its own copy; past the limit for its kind, the entry used
longest ago goes first."""

import copy
import hashlib
import threading
from collections import OrderedDict
from typing import Any, Callable, Dict

# Entries kept per kind: file contents are a few MB at most, parsed sheets more (a job's bank and Dext files)
LIMITS = {"s3": 200, "sheets": 20, "ageing": 100}
DEFAULT_LIMIT = 50
_lock = threading.Lock()
_stores: Dict[str, "OrderedDict[str, Any]"] = {}


def digest(*parts: Any) -> str:
    """A short fingerprint of bytes and plain values (file names, roles)."""
    h = hashlib.sha1()
    for p in parts:
        h.update(p if isinstance(p, bytes) else repr(p).encode())
        h.update(b"\0")
    return h.hexdigest()


def remember(kind: str, key: str, work: Callable[[], Any], copy_out: bool = True) -> Any:
    """work()'s result for this key, worked out once. copy_out: a copy is handed out, so a caller that changes it does
    not change the kept one (False only for results nobody changes, such as file contents and parsed sheets)."""
    with _lock:
        store = _stores.setdefault(kind, OrderedDict())
        if key in store:
            store.move_to_end(key)
            value = store[key]
            return copy.deepcopy(value) if copy_out else value
    value = work()
    with _lock:
        store[key] = value
        while len(store) > LIMITS.get(kind, DEFAULT_LIMIT):
            store.popitem(last=False)
    return copy.deepcopy(value) if copy_out else value
