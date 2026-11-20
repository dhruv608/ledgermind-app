"""/api/sa: an individual's Self Assessment jobs. Each job is its owner's only, like a company client."""

from fastapi import APIRouter

from backend.app.sa.api import (bank, capital, checklist, documents, filing, foreign, jobs, lines, property,
                                trade)

router = APIRouter()
# The same order the routes were first written in (a fixed path such as /jobs/status comes before /jobs/{job_id})
for _area in (jobs, documents, lines, property, trade, bank, checklist, filing, capital, foreign):
    router.include_router(_area.router)
