"""Every test runs on a local sqlite file, never on a hosted database: set here, before any test imports the app (the
settings file of a developer's PC points at the hosted one)."""
import os
import tempfile

if not os.environ.get("DATABASE_URL", "").startswith("sqlite"):
    here = "D:/Work500/scratch/uidb" if os.path.isdir("D:/Work500/scratch/uidb") else tempfile.gettempdir()
    os.environ["DATABASE_URL"] = f"sqlite:///{here}/pytest.db"
os.environ["DATABASE_SECRET_ARN"] = ""
os.environ.pop("ALLOW_LIVE_DB", None)
