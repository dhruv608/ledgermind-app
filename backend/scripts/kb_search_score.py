"""Score the law search on questions whose right page we know (backend/tests/law_search_cases.json): is a right
page in the top 1 / 3 / 8? Run on the server next to the database:

    python backend/scripts/kb_search_score.py [--show-misses] [--rerank]

A right page is one whose reference starts with any of the case's refs (CTM61505, Notice 706 s11, ...)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.core.database import engine  # noqa: E402
from backend.app.services.kb.store import search  # noqa: E402

CASES = ROOT / "backend" / "tests" / "law_search_cases.json"


def rank(hits, refs):
    for i, h in enumerate(hits, 1):
        if any((h.get("ref") or "").startswith(r) for r in refs):
            return i
    return None


def main() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    ranks, misses = [], []
    for case in cases:
        hits = search(engine, case["q"], k=8, reranked="--rerank" in sys.argv)
        r = rank(hits, case["refs"])
        ranks.append(r)
        if not r or r > 3:
            misses.append((case["q"], r, [h.get("ref") for h in hits[:3]]))
    n = len(cases)
    top = lambda k: sum(1 for r in ranks if r and r <= k)
    mrr = sum(1 / r for r in ranks if r) / n
    print(f"cases {n}  top1 {top(1)} ({top(1) / n:.0%})  top3 {top(3)} ({top(3) / n:.0%})  "
          f"top8 {top(8)} ({top(8) / n:.0%})  MRR {mrr:.3f}")
    if "--show-misses" in sys.argv:
        for q, r, got in misses:
            print(f"  [{r or '-'}] {q}\n        got: {got}")


if __name__ == "__main__":
    main()
