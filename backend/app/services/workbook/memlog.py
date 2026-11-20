"""
Memory used at each step of a workbook build, written to the server log ('docker compose logs backend'), so a build
that grows too big shows which step did it (the server stops the app when memory runs out).
Nothing is stored; on a computer without /proc (Windows) the lines are not written.
"""

import logging
from typing import Optional

try:
    import resource              # Linux (the server); not on Windows
except ImportError:
    resource = None

# uvicorn's own logger: the app's other loggers print warnings only
log = logging.getLogger("uvicorn.error")


def _status_mb(field: str) -> Optional[int]:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def step(client: str, label: str) -> None:
    """One log line: the app's memory now and its peak so far, and the largest helper program (LibreOffice) so far."""
    now, peak = _status_mb("VmRSS"), _status_mb("VmHWM")
    if now is None or resource is None:
        return
    children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024
    log.info("Workbook %s: %s - memory %d MB (peak %d MB, LibreOffice peak %d MB)", client, label, now, peak or 0,
             children)
