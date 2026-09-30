import pytest
from httpx import ASGITransport, AsyncClient

from app.content.names import name_key, validate_name
from app.core.errors import ValidationFailedError
from app.core.security import hash_password, verify_password
from app.services.auth import validate_credentials


def test_password_hash_roundtrip() -> None:
    h = hash_password("a-very-good-pass")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "a-very-good-pass")
    assert not verify_password(h, "wrong-pass-123")
    assert not verify_password(None, "anything-here")


@pytest.mark.parametrize(
    "email,password,code",
    [
        ("not-an-email", "long-enough-pw", "invalid_email"),
        ("a@b.co", "short", "weak_password"),
        ("hero@example.com", "hero@example.com", "weak_password"),
        ("hero@example.com", "aaaaaaaaaaaa", "weak_password"),
    ],
)
def test_credential_validation(email: str, password: str, code: str) -> None:
    with pytest.raises(ValidationFailedError) as ei:
        validate_credentials(email, password)
    assert ei.value.code == code


@pytest.mark.parametrize("name", ["Arven", "Kılıç", "Mei-Lin", "O'Neil", "李小龙", "José María"])
def test_valid_names(name: str) -> None:
    assert validate_name(name)


@pytest.mark.parametrize(
    "name,code",
    [
        ("ab", "invalid_name_length"),
        ("x" * 17, "invalid_name_length"),
        ("Arv3n", "invalid_name_chars"),
        ("-Arven", "invalid_name_chars"),
        ("Ar--ven", "invalid_name_chars"),
        ("Admin", "reserved_name"),
        ("GameMaster", "reserved_name"),
        ("SuperAdminX", "reserved_name"),
        ("Ar<script>", "invalid_name_chars"),
    ],
)
def test_invalid_names(name: str, code: str) -> None:
    with pytest.raises(ValidationFailedError) as ei:
        validate_name(name)
    assert ei.value.code == code


def test_name_key_case_insensitive_and_nfkc() -> None:
    assert name_key("ARVEN") == name_key("arven")
    assert name_key("Ａｒｖｅｎ") == name_key("arven")  # full-width folds via NFKC


async def test_register_login_me_logout(make_client, app) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    me = await u.http.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["roles"] == ["player"] and me.json()["is_staff"] is False
    assert "session" in u.http.cookies
    out = await u.http.post("/api/v1/auth/logout")
    assert out.status_code == 204
    assert (await u.http.get("/api/v1/auth/me")).status_code == 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c2:
        bad = await c2.post("/api/v1/auth/login", json={"email": u.email, "password": "wrong-password-1"})
        assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
        ok = await c2.post("/api/v1/auth/login", json={"email": u.email.upper(), "password": u.password})
        assert ok.status_code == 200
        assert (await c2.get("/api/v1/auth/me")).status_code == 200


async def test_duplicate_email_rejected_case_insensitive(make_client, client: AsyncClient) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    r = await client.post("/api/v1/auth/register", json={"email": u.email.upper(), "password": "another-pass-12"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


async def test_csrf_required_for_mutations(make_client) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    token = u.http.headers.pop("X-CSRF-Token")
    r = await u.http.post("/api/v1/auth/logout")
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = await u.http.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    r = await u.http.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token, "Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"
    r = await u.http.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})
    assert r.status_code == 204


async def test_account_lock_after_repeated_failures(make_client, app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "login_max_failures_before_lock", 3)
    monkeypatch.setattr(get_settings(), "rl_login_email", "1000/900")
    u = await make_client()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for _ in range(3):
            await c.post("/api/v1/auth/login", json={"email": u.email, "password": "wrong-password-x"})
        r = await c.post("/api/v1/auth/login", json={"email": u.email, "password": u.password})
        assert r.status_code == 401 and r.json()["error"]["code"] == "account_locked"


async def test_login_rate_limited(make_client, app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rl_login_email", "2/900")
    u = await make_client()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        codes = [
            (await c.post("/api/v1/auth/login", json={"email": u.email, "password": "nope-nope-nope"})).status_code
            for _ in range(3)
        ]
    assert codes == [401, 401, 429]


async def test_settings_update_sets_locale_cookie(make_client) -> None:  # type: ignore[no-untyped-def]
    u = await make_client()
    r = await u.http.put("/api/v1/auth/me/settings", json={"locale": "zh-CN", "timezone": "Europe/Istanbul"})
    assert r.status_code == 200 and r.json()["locale"] == "zh-CN"
    assert u.http.cookies["locale"] == "zh-CN"
    bad = await u.http.put("/api/v1/auth/me/settings", json={"timezone": "Mars/Olympus"})
    assert bad.status_code == 422
