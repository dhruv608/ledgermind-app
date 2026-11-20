# Architecture

## Overview

```
Browser (Next.js)  ──►  nginx  ──►  FastAPI  ──►  PostgreSQL (+ pgvector)
                                       │
                                       ├──►  S3 (uploaded files, built workbooks)
                                       └──►  AWS Bedrock (suggestions, assistant, embeddings)
```

One job ("engagement") is one client's year end. Everything a job holds hangs off its engagement id: trial balance
rows, ledger lines, supplementary records, review points, proposed journals, queries, sign-offs and built workbooks.

## Backend

### Layers

| Layer | Folder | Rule |
|---|---|---|
| Routes | `app/api/endpoints/` | Parse the request, call a service, return a schema. No business logic. |
| Services | `app/services/<domain>/` | All business logic. Pure functions where possible; a `Session` is passed in. |
| Models | `app/models/` | SQLAlchemy tables only. |
| Rules | `app/rules/*.json` | Data, not code: industry checks, query rules, merchant names, firm policy defaults. |
| Core | `app/core/` | Settings, database session, named errors, AWS clients. |

### The job pipeline

1. **Upload** (`api/endpoints/upload.py`, `services/ingestion/`): each file is identified (TB, GL, AP/AR, VAT,
   payroll, asset register, last year's TB or working paper), read into rows, and checked (does the TB balance, does
   the period match).
2. **Mapping** (`services/mapping/`): every client account gets a firm chart code. Sources, in order of trust: the
   accountant's own choice, last year, the firm's memory, the client's own code and name, rules, then AI. Each row keeps
   its source and a status (`MATCHED`, `NEEDS_REVIEW`).
3. **Checks** (`services/checks/runner.py`): run in a background thread in 14 steps (books, opening balances, general
   checks, CIS, director's loan, industry, fixed assets, stock, accruals, payroll, loans, VAT, corporation tax, save).
   Progress is stored per step so any server worker can report it. A change made while a run is going marks the run
   to repeat once it ends.
4. **Review** (`services/review/`, `services/queries/`, `services/reanalysis/`): the checks write review points
   (`AuditFinding`), proposed journals (`ProposedJournal`) and queries. Nothing is posted until the accountant approves.
5. **Workbook** (`services/workbook/`): builds the Excel file from the database: contents, ETB, journals, one T account
   per balance sheet area, lead schedules and the corporation tax computation. Cells are formulas linked to the ETB, so
   the file recalculates; a guard keeps every formula under Excel's 8,192-character limit.

### Change tracking

`services/shared/activity.mark_changed` records that a job's data changed and starts the checks again in the background.
The screens compare that moment with the last check and the last workbook build to say what is out of date.

### Errors

`app/core/errors.py` defines named errors (`NotFound`, `OutOfDate`, `NeedsInput`, `NotAllowed`, `FileUnreadable`,
`StillRunning`). Each carries a plain message, what to do next and optionally where to go. A middleware turns any
unexpected exception into the same shape with a logged error id, so the browser never sees a bare 500.

### Law knowledge base

`services/kb/` stores UK tax and accounting sources as chunks with embeddings in PostgreSQL (pgvector) and searches
them by meaning and by exact words together. A weekly GitHub Actions job refreshes the sources.

## Frontend

| Folder | Purpose |
|---|---|
| `src/app/` | Pages. `clients/[id]/page.tsx` is the job workspace: a checklist sidebar and one panel per step. |
| `src/components/<area>/` | Panels and widgets by area (review, mapping, setup, workbook, sa ...). |
| `src/lib/api/` | Typed API client, one file per backend area. All calls go through `client.ts`. |
| `src/lib/queries/` | TanStack Query hooks and keys for job data (`["job", id, ...]`). |
| `src/lib/jobEvents.ts` | One "this job changed" signal. Every successful save sends it; the workspace refreshes every count and watches the background checks. |
| `src/lib/jobState.ts` | The single definition of every status (sidebar, area header, "Next" line, progress count). |
| `src/lib/notify.ts` | App-wide notifications: success messages fade, errors stay until closed. |

### State rules

- A count shown in two places must come from the same function in `jobState.ts`.
- After any save, the workspace refreshes from the server; panels do not patch each other's state.
- While the background checks run, screens whose data they replace are covered with a progress bar; other screens stay usable.

## Self Assessment module

`backend/app/sa/` and `frontend/src/components/sa/` hold the individual tax return module. It reuses the same
patterns (documents in, readers per income type, review points, a working paper out) with its own routes under `/api/sa`.
