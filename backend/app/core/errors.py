"""One way for every error to reach the screen.

A few named errors, each with a plain message, what to do next and where to go. The handlers in main.py turn them,
and any error nobody expected, into one shape the app reads:

    {"detail": {"code": "OutOfDate", "message": "...", "next": "...", "go_to": "review", "error_id": "..."}}

HTTPException keeps its own shape (the screens already read it); new code raises these instead.
"""
import logging
import uuid
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("ledgermind.errors")


class AppError(Exception):
    status = 400
    code = "AppError"
    default_next = ""

    def __init__(self, message: str, next: Optional[str] = None, go_to: Optional[str] = None):
        super().__init__(message)
        self.message, self.next, self.go_to = message, next if next is not None else self.default_next, go_to

    def body(self, error_id: Optional[str] = None) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.next:
            out["next"] = self.next
        if self.go_to:
            out["go_to"] = self.go_to
        if error_id:
            out["error_id"] = error_id
        return {"detail": out}


class NotFound(AppError):
    status, code, default_next = 404, "NotFound", "Reload the page: it may have been removed."


class OutOfDate(AppError):
    """The item changed under the screen (LM checked the client again and replaced it)."""
    status, code, default_next = 409, "OutOfDate", "Reload to see the latest."


class NeedsInput(AppError):
    status, code = 422, "NeedsInput"


class NotAllowed(AppError):
    status, code = 403, "NotAllowed"


class FileUnreadable(AppError):
    status, code, default_next = 422, "FileUnreadable", "Check the file opens, then upload it again."


class StillRunning(AppError):
    status, code, default_next = 409, "StillRunning", "Wait for LM to finish, then try again."


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.body())


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything nobody expected: logged with an id the screen shows, so it can be found; never a bare 500."""
    error_id = uuid.uuid4().hex[:8]
    log.exception("Unexpected error %s on %s %s", error_id, request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": {
        "code": "ServerError",
        "message": "Something went wrong on our side.",
        "next": f"Try again. If it keeps happening, quote error {error_id}.",
        "error_id": error_id,
    }})
