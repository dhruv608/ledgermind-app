# Contributing

## Workflow

- Branch from `main`, keep changes small and focused, open a pull request.
- Before pushing: `python -m pytest backend/tests` and `cd frontend && npx tsc --noEmit`.
- Deploys are manual (GitHub Actions, `deploy.yml`); merging does not deploy.

## Commits

- One change per commit, one short line in the imperative or descriptive present
  ("Loan T: point at the named lines' cells", "Sidebar shows the GL scrutiny flags").
- No ticket essays in the message; the code and its tests carry the detail.

## Code

- **Backend:** routes stay thin; logic lives in `app/services/<domain>/`. Pass a `Session` in, don't import a global one
  inside services. Raise the named errors from `app/core/errors.py` for anything the user should see.
- **Frontend:** call the server only through `src/lib/api/`. Use `toast` from `@/lib/notify`, not from `sonner`.
  Statuses and counts come from `src/lib/jobState.ts`.
- **Money:** amounts are rounded to 2 decimals at the edges (display, Excel), not in the middle of a calculation.
  Signs follow the ledger: debit positive, credit negative, unless a function says otherwise.
- **Rules as data:** thresholds and keyword lists that a firm could change belong in `app/rules/*.json` or the firm
  settings, not hard-coded.

## Comments

- Say what the code does and why, in one or two short sentences. Skip comments that repeat the code.
- Cite the law or standard when a rule comes from it (for example `CTA 2009 s54`, `FRS 102 1A`).
- Do not put names, dates, client names or the history of a change in comments; that belongs in git.

## Tests

- Every bug fix gets a test that fails before the fix.
- Test data uses anonymous client names and made-up figures.
