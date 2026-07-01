"""Structural guard rails for the modular refactor.

These lock the public API surface, the DB tables, and SQLAlchemy mapper
resolution, so any restructuring step that accidentally drops a route/table or
breaks a relationship fails in CI before it can deploy.
"""

from sqlalchemy.orm import configure_mappers

EXPECTED_TABLES = {
    "contact_tags",
    "contacts",
    "integration_tokens",
    "interactions",
    "key_dates",
    "life_events",
    "social_snapshots",
    "tags",
}

EXPECTED_ROUTES = {
    ("DELETE", "/api/contacts/{contact_id}"),
    ("DELETE", "/api/contacts/{contact_id}/interactions/{interaction_id}"),
    ("DELETE", "/api/contacts/{contact_id}/key-dates/{key_date_id}"),
    ("GET", "/api/admin/diagnostics"),
    ("GET", "/api/admin/logs"),
    ("GET", "/api/ai/status"),
    ("GET", "/api/contacts"),
    ("GET", "/api/contacts/{contact_id}"),
    ("GET", "/api/contacts/{contact_id}/recommendation"),
    ("GET", "/api/dashboard"),
    ("GET", "/api/digest/text"),
    ("GET", "/api/health"),
    ("GET", "/api/integrations/chater/inspect"),
    ("GET", "/api/integrations/chater/status"),
    ("GET", "/api/integrations/google/authorize"),
    ("GET", "/api/integrations/google/callback"),
    ("GET", "/api/integrations/google/status"),
    ("GET", "/api/integrations/telegram/status"),
    ("GET", "/api/tags"),
    ("PATCH", "/api/contacts/{contact_id}"),
    ("PATCH", "/api/life-events/{event_id}"),
    ("POST", "/api/contacts"),
    ("POST", "/api/contacts/{contact_id}/dossier"),
    ("POST", "/api/contacts/{contact_id}/import"),
    ("POST", "/api/contacts/{contact_id}/interactions"),
    ("POST", "/api/contacts/{contact_id}/key-dates"),
    ("POST", "/api/contacts/{contact_id}/life-events"),
    ("POST", "/api/integrations/chater/dedupe"),
    ("POST", "/api/integrations/chater/import"),
    ("POST", "/api/integrations/google/disconnect"),
    ("POST", "/api/integrations/google/sync"),
    ("POST", "/api/integrations/telegram/test"),
    ("POST", "/api/life-events/{event_id}/message"),
    ("POST", "/api/maintenance/refresh-warmth"),
    ("POST", "/api/maintenance/run-daily"),
}


def test_api_surface_unchanged(client):
    spec = client.get("/openapi.json").json()["paths"]
    routes = {
        (method.upper(), path)
        for path, item in spec.items()
        for method in item
    }
    assert routes == EXPECTED_ROUTES


def test_all_tables_registered():
    from app.database import Base

    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_mappers_resolve():
    # Forces every string relationship to resolve; raises if a model is missing.
    import app.models  # noqa: F401

    configure_mappers()
