"""Load the firm's coding from finished working papers into the database (table firm_examples): every client account
name on each working paper's ETB tab with the firm code it was given. Loading a client again replaces its examples.

    python backend/scripts/load_firm_examples.py <folder of client folders> [--only "A,B"] [--skip "C,D"] [--dry-run]

Each client folder holds its finished working papers (a file with 'WP' or 'working paper' in its name and an ETB /
'Trial Balance' tab). The database is the one in DATABASE_URL (backend/.env), so check it before loading."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.app.core.database import SessionLocal  # noqa: E402
from backend.app.services.mapping import firm_examples  # noqa: E402


def working_papers(folder: str):
    for name in sorted(os.listdir(folder)):
        low = name.lower()
        if low.endswith(".xlsx") and ("wp" in low.split() or "wp" in low or "working paper" in low) and "ledgermind" not in low:
            yield os.path.join(folder, name)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("folder")
    p.add_argument("--only", default="")
    p.add_argument("--skip", default="")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    skip = {s.strip() for s in a.skip.split(",") if s.strip()}
    db = SessionLocal()
    total = clients = 0
    for client in sorted(os.listdir(a.folder)):
        path = os.path.join(a.folder, client)
        if not os.path.isdir(path) or (only and client not in only) or client in skip:
            continue
        examples = []
        for wp in working_papers(path):
            try:
                examples = firm_examples.from_working_papers(wp)
            except Exception as e:
                print(f"  {client}: {os.path.basename(wp)} not read ({e})")
            if examples:
                break
        if not examples:
            continue
        n = len(examples) if a.dry_run else firm_examples.load(db, client, examples)
        print(f"{client[:45]:45} {n:4} examples")
        total += n
        clients += 1
    print(f"{'(dry run) ' if a.dry_run else ''}{total} examples from {clients} clients; "
          f"{len(firm_examples.habits(db))} firm habits in the database")


if __name__ == "__main__":
    main()
