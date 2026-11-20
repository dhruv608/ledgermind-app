# LedgerMind

Year-end working papers for UK accounting firms.

LedgerMind reads a company's bookkeeping exports (trial balance, general ledger, aged debtors and creditors, VAT
returns, payroll reports, fixed asset register, last year's figures), maps every account to the firm's chart,
checks the books against UK accounting and tax rules, proposes the correcting journals and questions, and builds
the Excel working paper with the corporation tax computation. The accountant reviews and decides on screen; every
figure, page and workbook updates from those decisions.

A second module prepares Self Assessment (SA100) working papers for individuals.

## How a job flows

```
 Upload files ──► Read and identify ──► Map accounts ──► Run checks ──► Review on screen ──► Build the Excel
 (TB, GL, VAT,    (which file is        (firm chart:      (14 steps in    (points, journals,    (ETB, one T account
  payroll, FAR)    which, periods,       rules, memory,    the background:  queries; approve,     per area, journals,
                   balances check)       last year, AI)    bank, VAT, CT)   decline, explain)     CT computation)
                                             ▲                                    │
                                             └──────── decisions are remembered ──┘
```

Rules and law decide; AI only suggests. Every option offered to the accountant comes from a rule file or the law
knowledge base, and nothing is posted without the accountant's confirmation.

## Tech stack

| Layer | Technology |
|---|---|
| API | Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic 2 |
| Data | PostgreSQL (AWS RDS) with pgvector for the law knowledge base; SQLite for local runs and tests |
| Workbook | openpyxl, recalculated by Excel (local) or LibreOffice (server) |
| AI | AWS Bedrock (language models for suggestions and the assistant; Cohere / Titan embeddings for search) |
| Files | Amazon S3 (local disk in development) |
| Web app | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, TanStack Query |
| Hosting | Docker on one EC2 server behind nginx; GitHub Actions builds images to ECR and deploys over SSM |

## Repository layout

```
backend/
  app/
    api/endpoints/     HTTP routes, one file per area (upload, mapping, audit, workpapers, queries ...)
    core/              settings, database session, errors, AWS clients (Bedrock, S3), AI usage
    models/            SQLAlchemy tables
    services/          business logic, one folder per domain
      ingestion/         reading TB, GL, AP/AR, VAT, payroll and asset files
      mapping/           mapping client accounts to the firm chart
      checks/            the background check runner
      review/            review points and proposed journals
      queries/           questions for the client and the accountant
      reanalysis/        costs posted to the wrong account
      tax/ cis/ loans/   corporation tax, CIS, loan schedules
      reconciliation/    control accounts: each balance against what it is checked against
      papers/            figures behind the on-screen working papers (roll-forwards, T accounts, ETB)
      shared/            sign-in, change tracking, file cache, the firm's rule store
      workbook/          the Excel working paper builder
      kb/                law knowledge base (embeddings and search)
      assistant/         the in-app assistant ("Ledge")
    sa/                Self Assessment module
    rules/             rule files (JSON): industry checks, queries, merchants, firm policies
  scripts/             one-off maintenance scripts
  tests/               pytest suite, one folder per domain (ingestion, payroll, vat, workbook, sa ...)
frontend/
  src/
    app/               pages (App Router)
    components/        UI by area (review, mapping, setup, clients, sa, workbook ...)
    lib/api/           typed API client, one file per backend area
    lib/               shared state: job store, change signal, status rules, notifications
    types/             shared TypeScript types
docs/                  architecture, deployment and contributing guides
nginx/                 reverse proxy templates
deploy/                server setup script
.github/workflows/     deploy and weekly knowledge-base refresh
```

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Running locally

Requirements: Python 3.12+, Node 22+, and (optional) Microsoft Excel or LibreOffice to recalculate workbooks.

**Backend** (run from the repository root):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS / Linux: source .venv/bin/activate
pip install -r backend/requirements.txt
copy backend\.env.example backend\.env    # set DATABASE_URL=sqlite:///./local.db for a local database
python -m uvicorn backend.app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs (not served in production).

**Frontend**:

```bash
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

Open http://localhost:3000.

For safety, the backend refuses to start against a hosted database from a developer machine unless
`ALLOW_LIVE_DB=1` is set.

## Tests

```bash
python -m pytest backend/tests        # backend unit and integration tests
cd frontend && npx tsc --noEmit       # frontend type check
```

## Deployment

Pushing to `main` does not deploy. A deploy is started by hand from GitHub Actions (`deploy.yml`): it builds the
backend and frontend images, pushes them to ECR, and tells the server to pull and restart. See
[docs/deployment.md](docs/deployment.md).

## Contributing

Code conventions, comments and commit style: [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## License

Private and proprietary. All rights reserved.
