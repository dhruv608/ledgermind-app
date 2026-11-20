"""Use of home per director: the directors on the client setup. Made-up names."""
import json
import os
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.review.adjustments import _director_count


def test_director_count():
    assert _director_count(N(profile=N(directors=json.dumps(["A Director", "B Director"])))) == 2
    assert _director_count(N(profile=N(directors=json.dumps([])))) == 1
    assert _director_count(N(profile=None)) == 1
