"""Structural guard rails for the modular refactor.

These lock the public API surface, the DB tables, and SQLAlchemy mapper
resolution, so any restructuring step that accidentally drops a route/table or
breaks a relationship fails in CI before it can deploy.
"""

from sqlalchemy.orm import configure_mappers

EXPECTED_TABLES = {
    "business_connections",
    "contact_embeddings",
    "contact_facts",
    "contact_tags",
    "contacts",
    "goal_contacts",
    "goals",
    "integration_tokens",
    "interactions",
    "key_dates",
    "life_events",
    "reminders",
    "social_snapshots",
    "style_profile",
    "tags",
    "telegram_drafts",
    "time_report_requests",
    "ideas",
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
    ("DELETE", "/api/goals/{goal_id}"),
    ("DELETE", "/api/goals/{goal_id}/contacts/{contact_id}"),
    ("GET", "/api/dashboard"),
    ("GET", "/api/goals"),
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
    ("PATCH", "/api/goals/{goal_id}"),
    ("PATCH", "/api/life-events/{event_id}"),
    ("GET", "/api/contacts/{contact_id}/facts"),
    ("POST", "/api/contacts"),
    ("POST", "/api/goals"),
    ("POST", "/api/goals/{goal_id}/contacts/{contact_id}"),
    ("POST", "/api/contacts/{contact_id}/dossier"),
    ("POST", "/api/contacts/{contact_id}/facts"),
    ("POST", "/api/contacts/{contact_id}/facts/extract"),
    ("POST", "/api/contacts/{contact_id}/import"),
    ("POST", "/api/contacts/{contact_id}/interactions"),
    ("POST", "/api/contacts/{contact_id}/key-dates"),
    ("POST", "/api/contacts/{contact_id}/life-events"),
    ("PATCH", "/api/facts/{fact_id}"),
    ("POST", "/api/facts/{fact_id}/invalidate"),
    ("POST", "/api/integrations/chater/dedupe"),
    ("POST", "/api/integrations/chater/import"),
    ("POST", "/api/integrations/google/disconnect"),
    ("POST", "/api/integrations/google/sync"),
    ("POST", "/api/integrations/telegram/test"),
    ("POST", "/api/life-events/{event_id}/message"),
    ("POST", "/api/maintenance/refresh-warmth"),
    ("POST", "/api/maintenance/run-daily"),
    ("GET", "/api/timereport/poll"),
    ("POST", "/api/timereport/deliver"),
    ("GET", "/api/tasks"),
    ("POST", "/api/tasks"),
    ("GET", "/api/tasks/next"),
    ("PATCH", "/api/tasks/{task_id}"),
    ("DELETE", "/api/tasks/{task_id}"),
    ("POST", "/api/tasks/sync"),
    ("POST", "/api/tasks/nudge"),
    ("GET", "/api/projects"),
    ("POST", "/api/projects"),
    ("PATCH", "/api/projects/{project_id}"),
    ("DELETE", "/api/projects/{project_id}"),
    ("GET", "/api/ideas"),
    ("POST", "/api/ideas"),
    ("GET", "/api/ideas/{idea_id}"),
    ("POST", "/api/ideas/{idea_id}/append"),
    ("PATCH", "/api/ideas/{idea_id}"),
    ("DELETE", "/api/ideas/{idea_id}"),
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
