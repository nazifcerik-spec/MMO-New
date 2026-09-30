"""Import all model modules so Base.metadata is complete (used by Alembic and tests)."""

from app.models import localization  # noqa: F401
