import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationFailedError
from app.db.session import get_sessionmaker
from app.localization import service
from app.localization.locales import normalize_text, parse_accept_language, safe_label


def test_accept_language_parsing() -> None:
    assert parse_accept_language("tr-TR,tr;q=0.9,en;q=0.8") == "tr"
    assert parse_accept_language("fr;q=1, es;q=0.5") == "es"
    assert parse_accept_language("zh-Hans-CN") == "zh-CN"
    assert parse_accept_language("de, fr") is None
    assert parse_accept_language("en;q=0, es;q=0.1") == "es"


def test_safe_label_and_normalization() -> None:
    assert safe_label("race.high_elf.name") == "High Elf"
    assert safe_label("stat.str.description") == "Str"
    # NFD "e + combining acute" becomes NFC "é"; control chars are stripped.
    assert normalize_text("Café\u0007") == "Café"


def test_pick_fallback_rules() -> None:
    rows = {"en": ("Strength", "published"), "tr": ("", "missing")}
    r = service.pick("stat.str.name", "tr", rows)
    assert (r.value, r.locale, r.fallback) == ("Strength", "en", True)
    r2 = service.pick("stat.str.name", "tr", {"tr": ("Güç", "draft"), "en": ("Strength", "published")})
    assert (r2.value, r2.locale, r2.fallback) == ("Güç", "tr", False)
    r3 = service.pick("x.unknown_thing.name", "es", {})
    assert (r3.value, r3.locale) == ("Unknown Thing", None)


async def test_resolve_many_seeded(db: AsyncSession) -> None:
    res = await service.resolve_many(db, ["stat.str.name", "stat.luk.name", "nope.missing_key"], "zh-CN")
    assert res["stat.str.name"].value == "力量"
    assert res["stat.luk.name"].value == "幸运"
    assert res["nope.missing_key"].value == "Missing Key"
    with pytest.raises(ValidationFailedError):
        await service.resolve_many(db, ["stat.str.name"], "fr")


async def test_missing_translation_falls_back_to_english(db: AsyncSession) -> None:
    await service.seed_values(db, "test.only_english.name", {"en": "Only English"})
    await db.flush()
    res = await service.resolve_many(db, ["test.only_english.name"], "es")
    assert res["test.only_english.name"].value == "Only English"
    assert res["test.only_english.name"].fallback is True


async def test_set_value_optimistic_concurrency(db: AsyncSession) -> None:
    await service.seed_values(db, "test.concurrency.name", {"en": "Sword", "tr": "Kılıç"})
    await db.flush()
    cur = (await service.get_all_locales(db, ["test.concurrency.name"]))["test.concurrency.name"]["tr"]
    row = await service.set_value(
        db,
        key="test.concurrency.name",
        locale="tr",
        value="Kılıç",
        status="reviewed",
        expected_version=cur["version"],
        actor_id=None,
    )
    assert row.version == cur["version"] + 1
    with pytest.raises(ConflictError):
        await service.set_value(
            db,
            key="test.concurrency.name",
            locale="tr",
            value="Kılıç2",
            status="reviewed",
            expected_version=cur["version"],
            actor_id=None,
        )


async def test_seed_does_not_overwrite_reviewed(db: AsyncSession) -> None:
    await service.seed_values(db, "test.protected.name", {"en": "Shield", "es": "Escudo"})
    await db.flush()
    await service.set_value(
        db,
        key="test.protected.name",
        locale="es",
        value="Escudo Real",
        status="reviewed",
        expected_version=None,
        actor_id=None,
    )
    await service.seed_values(db, "test.protected.name", {"en": "Shield", "es": "Escudo"})
    res = await service.resolve_many(db, ["test.protected.name"], "es")
    assert res["test.protected.name"].value == "Escudo Real"


async def test_concurrent_edits_one_wins() -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        await service.seed_values(s, "test.race_edit.name", {"en": "Axe", "tr": "Balta"})
        await s.commit()
        v = (await service.get_all_locales(s, ["test.race_edit.name"]))["test.race_edit.name"]["tr"]["version"]

    async def edit(text: str) -> str:
        async with sm() as s:
            try:
                await service.set_value(
                    s,
                    key="test.race_edit.name",
                    locale="tr",
                    value=text,
                    status="draft",
                    expected_version=v,
                    actor_id=None,
                )
                await s.commit()
                return "ok"
            except ConflictError:
                await s.rollback()
                return "conflict"

    results = await asyncio.gather(edit("Balta A"), edit("Balta B"))
    assert sorted(results) == ["conflict", "ok"]


async def test_completeness_counts(db: AsyncSession) -> None:
    stats = await service.completeness(db, namespace="stat")
    for loc in ("en", "tr", "zh-CN", "es"):
        assert stats[loc]["total"] == 21
        assert stats[loc]["missing"] == 0


async def test_api_texts_locale_resolution(client: AsyncClient) -> None:
    r = await client.get("/api/v1/i18n/texts", params={"keys": "stat.str.name", "locale": "tr"})
    assert r.status_code == 200 and r.json()["texts"]["stat.str.name"]["value"] == "Güç"
    r = await client.get("/api/v1/i18n/texts", params={"keys": "stat.str.name"}, headers={"Accept-Language": "es"})
    assert r.json()["locale"] == "es" and r.json()["texts"]["stat.str.name"]["value"] == "Fuerza"
    client.cookies.set("locale", "zh-CN")
    r = await client.get("/api/v1/i18n/texts", params={"keys": "stat.str.name"}, headers={"Accept-Language": "es"})
    assert r.json()["locale"] == "zh-CN"
    client.cookies.set("locale", "klingon")
    r = await client.get("/api/v1/i18n/texts", params={"keys": "stat.str.name"})
    assert r.json()["locale"] == "en"
    client.cookies.clear()


async def test_api_invalid_locale_param(client: AsyncClient) -> None:
    r = await client.get("/api/v1/i18n/texts", params={"keys": "stat.str.name", "locale": "fr"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_locale"


async def test_api_preference_sets_cookie(client: AsyncClient) -> None:
    r = await client.put("/api/v1/i18n/preference", json={"locale": "tr"})
    assert r.status_code == 204
    assert "locale=tr" in r.headers["set-cookie"]
    bad = await client.put("/api/v1/i18n/preference", json={"locale": "de"})
    assert bad.status_code == 422
    r = await client.get("/api/v1/i18n/locales")
    assert [x["code"] for x in r.json()["locales"]] == ["en", "tr", "zh-CN", "es"]
