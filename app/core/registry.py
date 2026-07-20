"""Explicit ORM model registry.

Imports every module's ``models.py`` so all mapped classes are registered on
the single shared ``core.database.Base`` before ``create_all`` runs and before
SQLAlchemy resolves the string-based relationships between them.

Explicit on purpose (no auto-discovery): a model that isn't registered is a
missing, greppable line here — not a silent runtime failure. Add one import
line whenever a new domain gains a ``models.py``.
"""

from __future__ import annotations

from app.modules.automation import models as automation_models  # noqa: F401
from app.modules.contacts import models as contacts_models  # noqa: F401
from app.modules.insights import models as insights_models  # noqa: F401
from app.modules.integrations import models as integrations_models  # noqa: F401
from app.modules.integrations.social import models as social_models  # noqa: F401
from app.modules.interactions import models as interactions_models  # noqa: F401
from app.modules.goals import models as goals_models  # noqa: F401
from app.modules.search import models as search_models  # noqa: F401
from app.modules.telegram_bot import models as telegram_bot_models  # noqa: F401
from app.modules.timereport import models as timereport_models  # noqa: F401

__all__ = [
    "contacts_models",
    "interactions_models",
    "insights_models",
    "integrations_models",
    "social_models",
    "telegram_bot_models",
    "goals_models",
    "search_models",
    "automation_models",
    "timereport_models",
]
