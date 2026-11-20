"""Load (or refresh) the assistant's law knowledge base from the public sources in backend/app/rules/kb_sources.json.

    python backend/scripts/kb_load.py                 # every source
    python backend/scripts/kb_load.py notice-700 ctm   # only sources whose slug / path contains one of these
    python backend/scripts/kb_load.py --regions eu-west-2,us-east-1 eim   # Bedrock: embed over several regions
    python backend/scripts/kb_load.py --online        # only the gov.uk manuals and pages (the weekly refresh)

Pages already loaded with the same text are skipped, so a re-run only embeds what changed. Prints the counts per
source and every request that failed; the same summary is saved to data/kb/load_<time>.json."""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

from backend.app.core.database import engine  # noqa: E402
from backend.app.services.kb.loader import load_all  # noqa: E402


def main() -> None:
    args = sys.argv[1:]
    online = "--online" in args
    args = [a for a in args if a != "--online"]
    if "--regions" in args:
        # A big load: share the embedding between regions (same model, same vectors), as kb_reembed.py does
        i = args.index("--regions")
        regions, args = args[i + 1].split(","), args[:i] + args[i + 2:]
        from backend.app.services.kb import store
        from backend.scripts.kb_reembed import bulk_embedder
        store.embed_documents = bulk_embedder(regions)
    started = time.time()
    log = load_all(engine, args or None, online)
    summary = {"finished": datetime.now().isoformat(timespec="seconds"), "minutes": round((time.time() - started) / 60, 1),
               "pages": log.pages, "removed": log.removed, "index_only_skipped": log.index_only, "chunks": log.chunks, "words": log.words,
               "by_source": log.by_source, "failed": log.failed}
    print(json.dumps(summary, indent=1))
    out = ROOT / "data" / "kb"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"load_{datetime.now():%Y%m%d_%H%M}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
