from fastapi import APIRouter, Depends
from backend.app.api.deps import assistant_user, require_user
from backend.app.api.endpoints import (upload, mapping, audit, workpapers, engagements, firm_rules, auth, books,
                                       profile_setup, capital_allowances, reconciliations, cis, supplementary, assistant,
                                       adjustments, firm_settings, queries, scrutiny, reanalysis, checks, opening,
                                       notes, evidence, custom_papers, job_details, stock_lines)

api_router = APIRouter()

# Everything except the sign-in needs a signed-in user, and only reaches that user's own clients and rules
signed_in = [Depends(require_user)]
api_router.include_router(upload.router, prefix="", tags=["Ingestion & Upload"], dependencies=signed_in)
api_router.include_router(engagements.router, prefix="/engagements", tags=["Client Engagements"], dependencies=signed_in)
# The rest of a client's screens, under the same /engagements/{id} address
for module, tag in ((profile_setup, "Profile & setup"), (capital_allowances, "Capital allowances"),
                    (reconciliations, "Control accounts"), (cis, "CIS"), (supplementary, "Supplementary & VAT returns"),
                    (adjustments, "Accruals & prepayments"), (queries, "Queries"), (scrutiny, "GL scrutiny"),
                    (reanalysis, "Reanalysis"), (checks, "Background checks"), (opening, "Opening balances"),
                    (notes, "Area notes"), (evidence, "Area evidence"), (custom_papers, "Added working papers"), (job_details, "Job details"), (stock_lines, "Stock lines")):
    api_router.include_router(module.router, prefix="/engagements", tags=[tag], dependencies=signed_in)
api_router.include_router(mapping.router, prefix="/mapping", tags=["COA Mapping"], dependencies=signed_in)
api_router.include_router(audit.router, prefix="/audit", tags=["Statutory Audit"], dependencies=signed_in)
api_router.include_router(workpapers.router, prefix="/workpapers", tags=["Workpapers Generation"], dependencies=signed_in)
api_router.include_router(firm_rules.router, prefix="/firm-rules", tags=["Account rules"], dependencies=signed_in)
api_router.include_router(firm_settings.router, prefix="/firm-settings", tags=["Firm settings"], dependencies=signed_in)
api_router.include_router(auth.router, prefix="/auth", tags=["Sign-in"])
# Clients with no accounting software (bank statement and Dext): the Books tab
api_router.include_router(books.router, prefix="/books", tags=["Books"], dependencies=signed_in)
# Self Assessment (an individual's return): its own module, each job checked to be the user's own in the endpoints
from backend.app.sa import api as sa_api  # noqa: E402
api_router.include_router(sa_api.router, prefix="/sa", tags=["Self Assessment"], dependencies=signed_in)
# The assistant's chat panel: each chat is checked to be the user's own in the endpoints. The test chat page (/chat)
# reaches it with its code instead of a sign-in (services/assistant/chat_access.py)
api_router.include_router(assistant.router, prefix="/assistant", tags=["Assistant"],
                          dependencies=[Depends(assistant_user)])
from backend.app.api.endpoints import chat_access as chat_access_api  # noqa: E402
api_router.include_router(chat_access_api.router, prefix="/chat-access", tags=["Test chat page"])
