from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel

LocaleCode = Literal["en", "tr", "zh-CN", "es"]


class LocaleInfo(ApiModel):
    code: LocaleCode
    native_name: str


class LocalesResponse(ApiModel):
    default: LocaleCode
    locales: list[LocaleInfo]


class ResolvedTextOut(ApiModel):
    value: str
    locale: str | None
    fallback: bool


class TextsResponse(ApiModel):
    locale: LocaleCode
    texts: dict[str, ResolvedTextOut]


class LocalePreferenceIn(ApiModel):
    locale: LocaleCode


class TranslationUpdateIn(ApiModel):
    value: str = Field(max_length=10_000)
    status: Literal["missing", "draft", "reviewed", "published"]
    expected_version: int | None = Field(default=None, ge=0)
