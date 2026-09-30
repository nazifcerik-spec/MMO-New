"""Import all model modules so Base.metadata is complete (used by Alembic and tests)."""

from app.models import auth, character, content, localization, progression  # noqa: F401
