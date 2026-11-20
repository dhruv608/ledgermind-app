"""Firm-editable rule sets in the database: the seed file until a firm saves a version; saving keeps
the older versions; law figures are never served from the database."""
from backend.app.core.database import SessionLocal
from backend.app.services.shared import rules_store


def test_seed_then_saved_version_then_history():
    db = SessionLocal()
    try:
        db.query(rules_store.RuleSet).filter(rules_store.RuleSet.name == "checklists").delete()
        db.commit()
        rules_store._cache.clear()
        seed = rules_store.load("checklists", db)
        assert "accounts_ct" in seed                                  # the file, nothing saved yet
        changed = {**seed, "accounts_ct": {"title": "Our own checklist"}}
        rules_store.save(db, "checklists", changed, note="test edit")
        assert rules_store.load("checklists", db)["accounts_ct"]["title"] == "Our own checklist"
        rules_store.save(db, "checklists", seed, note="back to the seed")
        history = rules_store.versions(db, "checklists")
        assert [h["version"] for h in history] == [2, 1] and [h["active"] for h in history] == [True, False]
        assert rules_store.load("checklists", db) == seed
    finally:
        db.query(rules_store.RuleSet).filter(rules_store.RuleSet.name == "checklists").delete()
        db.commit()
        rules_store._cache.clear()
        db.close()


def test_law_figures_are_not_editable():
    import pytest
    assert "parameters" not in rules_store.EDITABLE
    with pytest.raises(ValueError):
        rules_store.save(None, "parameters", {})
