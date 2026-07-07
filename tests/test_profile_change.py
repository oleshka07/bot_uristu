"""B4 profile-change detection predicate (Mesh 'career moves surface')."""

from app.modules.automation.daily import _headline_changed


def test_detects_real_change():
    assert _headline_changed("CEO at Acme", "CTO at Acme") is True


def test_ignores_case_and_whitespace():
    assert _headline_changed("CEO at Acme", "  ceo   at acme ") is False


def test_ignores_empty_or_first_snapshot():
    assert _headline_changed(None, "CEO at Acme") is False
    assert _headline_changed("CEO", "") is False
    assert _headline_changed("CEO", "  ") is False


def test_ignores_trivially_short_new_title():
    assert _headline_changed("Founder", "X") is False
