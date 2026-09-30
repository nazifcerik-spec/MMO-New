from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.i18n import LocaleCode


class RegisterIn(ApiModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    locale: LocaleCode = "en"


class LoginIn(ApiModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class MeOut(ApiModel):
    id: int
    email: str
    roles: list[str]
    permissions: list[str]
    is_staff: bool
    locale: LocaleCode


class SettingsIn(ApiModel):
    locale: LocaleCode | None = None
    timezone: str | None = Field(default=None, max_length=64)
    reduced_motion: bool | None = None
    compact_log: bool | None = None


class SettingsOut(ApiModel):
    locale: LocaleCode
    timezone: str
    reduced_motion: bool
    compact_log: bool


class CharacterCreateIn(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    race_id: int = Field(gt=0)
    base_class_id: int = Field(gt=0)


class CharacterOut(ApiModel):
    id: int
    name: str
    race_id: int
    base_class_id: int
    level: int
    xp: int
    unspent_stat_points: int
    created_at: datetime
    last_level_up_at: datetime | None


class NameCheckOut(ApiModel):
    name: str
    available: bool
    valid: bool
    error_code: str | None = None
