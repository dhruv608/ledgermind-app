import sys
from pathlib import Path

# Ensure root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.api.api import api_router

app = FastAPI(
    title="LedgerMind API",
    description="UK GAAP & ACCA Compliant Working Papers Generation Platform with AWS Bedrock AI & Neon PostgreSQL",
    version="1.0.0",
    # The API's own help pages only when running locally, never on the live server
    docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.ENVIRONMENT == "production" else "/openapi.json",
)

# Anything unexpected: one plain answer with an error id (logged), never a bare 500. Added before CORS so the
# answer still carries the CORS headers and the screen can read it
@app.middleware("http")
async def _unexpected_errors(request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001
        from backend.app.core.errors import unexpected_error_handler
        return await unexpected_error_handler(request, exc)


# CORS setup
origins = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()]
# Only the app's own pages may call the server with the sign-in cookie (never "*": any site could act as the user)
origins.extend(["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],   # a download's file name
)

app.include_router(api_router, prefix="/api")

# Named errors in one shape the screens read
from backend.app.core.errors import AppError, app_error_handler  # noqa: E402
app.add_exception_handler(AppError, app_error_handler)

# The firm chart's CIS codes: added to the database when missing
from backend.app.services.cis.codes import ensure_cis_codes_at_start
ensure_cis_codes_at_start()

# The firm's coding learnt from its working papers: its table is created here, never in the middle of an upload
import backend.app.models.firm_examples  # noqa: E402,F401
import backend.app.models.vat_payments  # noqa: E402,F401
import backend.app.models.director_pay  # noqa: E402,F401
import backend.app.models.payroll_allowance  # noqa: E402,F401
import backend.app.models.gl_openings  # noqa: E402,F401
import backend.app.models.gl_foreign  # noqa: E402,F401
import backend.app.models.gl_parties  # noqa: E402,F401
import backend.app.models.loan_agreements  # noqa: E402,F401
import backend.app.models.payroll_headcount  # noqa: E402,F401
import backend.app.models.chat  # noqa: E402,F401
import backend.app.models.client_codes  # noqa: E402,F401
import backend.app.models.yearend_adjustments  # noqa: E402,F401
import backend.app.models.post_year_end  # noqa: E402,F401
import backend.app.models.merchant_memory  # noqa: E402,F401

@app.get("/health")
def healthcheck():
    return {
        "status": "HEALTHY",
        "service": "Automated Financial Working Papers Engine",
        "environment": settings.ENVIRONMENT,
        "primary_ai_model": settings.BEDROCK_PRIMARY_MODEL,
        "reasoning_ai_model": settings.BEDROCK_REASONING_MODEL
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=settings.BACKEND_PORT, reload=True)
