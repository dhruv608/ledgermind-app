"""Where a background run of the checks has got: the review calls step() as it starts each area, and the runner that
started it saves the step for the screen. Outside a background run (the review endpoint, test scripts) step() does
nothing."""

from contextvars import ContextVar
from typing import Callable, Optional

_hook: ContextVar[Optional[Callable[[str], None]]] = ContextVar("check_progress", default=None)


def step(key: str) -> None:
    hook = _hook.get()
    if hook is not None:
        hook(key)


def watching(hook: Callable[[str], None]):
    """Set the hook for this thread's run; returns the token to reset it with."""
    return _hook.set(hook)


def done_watching(token) -> None:
    _hook.reset(token)
