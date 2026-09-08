"""Aggregator — ORM models now live in app/modules/<domain>/models.py.

Kept so `from app.models import X` (and `import app.models` for registration)
keeps working. Importing this module registers every table on Base.metadata.
"""

from app.core.database import Base, utcnow  # noqa: F401
from app.modules.automation.models import Reminder  # noqa: F401
from app.modules.contacts.models import (  # noqa: F401
    Contact,
    Frequency,
    KeyDate,
    Relationship,
    Tag,
    contact_tags,
)
from app.modules.insights.models import (  # noqa: F401
    ContactFact,
    FactType,
    LifeEvent,
    LifeEventStatus,
    StyleProfile,
)
from app.modules.coach.models import CoachSettings, Checkin  # noqa: F401
from app.modules.goals.models import (  # noqa: F401
    ACTIVE_STATUSES,
    Area,
    Goal,
    GoalStatus,
    Horizon,
    goal_contacts,
)
from app.modules.integrations.models import IntegrationToken  # noqa: F401
from app.modules.integrations.social.models import SocialSnapshot  # noqa: F401
from app.modules.interactions.models import (  # noqa: F401
    Channel,
    Direction,
    Interaction,
)
from app.modules.search.models import ContactEmbedding  # noqa: F401
from app.modules.resources.models import (  # noqa: F401
    Resource,
    ResourceKind,
    ResourceStatus,
)
from app.modules.timereport.models import (  # noqa: F401
    TimeReportRequest,
    TimeReportStatus,
)
from app.modules.telegram_bot.models import (  # noqa: F401
    BusinessConnection,
    DraftKind,
    DraftStatus,
    TelegramDraft,
)
