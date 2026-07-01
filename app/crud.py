"""Aggregator shim: re-exports every domain service function.

The real database operations now live in ``app/modules/*/service.py`` (one
file per domain). This module keeps the flat ``crud.<fn>()`` call sites in
routers, jobs and connectors working until the final cleanup step.
"""

from __future__ import annotations

from app.modules.contacts.service import (
    add_key_date,
    create_contact,
    delete_contact,
    delete_key_date,
    get_contact,
    get_or_create_tags,
    list_contacts,
    refresh_all_warmth,
    update_contact,
)
from app.modules.insights.service import (
    add_life_event,
    get_life_event,
    update_life_event,
)
from app.modules.integrations.social.service import upsert_snapshot
from app.modules.interactions.service import (
    add_interaction,
    add_synced_interaction,
    delete_interaction,
    interaction_exists,
)

__all__ = [
    "get_or_create_tags",
    "create_contact",
    "get_contact",
    "list_contacts",
    "update_contact",
    "delete_contact",
    "add_key_date",
    "delete_key_date",
    "refresh_all_warmth",
    "add_interaction",
    "interaction_exists",
    "add_synced_interaction",
    "delete_interaction",
    "add_life_event",
    "update_life_event",
    "get_life_event",
    "upsert_snapshot",
]
