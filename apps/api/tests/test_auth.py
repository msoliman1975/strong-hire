"""Sign-in tests (P3). Requirement IDs: AC-2 (training-data consent off by default)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select

from strong_api.auth import CurrentUser
from strong_api.auth.google import GoogleIdentity, GoogleSignInError
from strong_api.auth.settings import DEV_SESSION_SECRET, AppEnv, AuthSettings
from strong_core.db.models import AuditLog, Org, User
from strong_core.schemas import AuthProvider, OrgType

from .conftest import AuthHarness, build_harness

ADULT = {"age_confirmed": True, "terms_accepted": True}


def _users(auth: AuthHarness) -> list[User]:
    async def q(db: Any) -> list[User]:
        return list((await db.execute(select(User))).scalars())

    return auth.query(q)  # type: ignore[no-any-return]


def _sign_up(auth: AuthHarness, email: str = "ana@example.com", **extra: Any) -> dict[str, Any]:
    assert auth.client.post("/auth/dev-login", json={"email": email}).status_code == 200
    resp = auth.client.post("/auth/signup", json={**ADULT, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------- sign-up


def test_new_email_needs_signup_before_a_user_exists(auth: AuthHarness) -> None:
    resp = auth.client.post("/auth/dev-login", json={"email": "Ana@Example.com"})
    assert resp.json() == {"status": "needs_signup", "email": "ana@example.com", "user": None}
    assert auth.client.get("/auth/me").json()["status"] == "needs_signup"
    assert _users(auth) == []


def test_ac2_signup_creates_personal_org_and_consent_defaults_off(auth: AuthHarness) -> None:
    """AC-2: training-data consent is off unless the user opts in."""
    state = _sign_up(auth)
    assert state["status"] == "signed_in"
    assert state["user"]["training_consent"] is False
    assert state["user"]["auth_provider"] == "dev"

    async def q(db: Any) -> tuple[User, Org, AuditLog]:
        user = (await db.execute(select(User))).scalar_one()
        org = await db.get(Org, user.org_id)
        log = (await db.execute(select(AuditLog))).scalar_one()
        return user, org, log

    user, org, log = auth.query(q)
    assert user.training_consent is False
    assert org.type == OrgType.PERSONAL
    assert log.action == "user.signup"
    assert log.org_id == org.id
    assert log.details_json["age_confirmed_18_plus"] is True
    assert log.details_json["training_consent"] is False


def test_ac2_signup_stores_opt_in_consent(auth: AuthHarness) -> None:
    state = _sign_up(auth, training_consent=True)
    assert state["user"]["training_consent"] is True
    assert _users(auth)[0].training_consent is True


@pytest.mark.parametrize("missing", ["age_confirmed", "terms_accepted"])
def test_signup_requires_18_plus_and_terms(auth: AuthHarness, missing: str) -> None:
    auth.client.post("/auth/dev-login", json={"email": "kid@example.com"})
    resp = auth.client.post("/auth/signup", json={**ADULT, missing: False})
    assert resp.status_code == 422
    assert _users(auth) == []
    assert auth.client.get("/auth/me").json()["status"] == "needs_signup"


def test_signup_without_a_sign_in_is_rejected(auth: AuthHarness) -> None:
    assert auth.client.post("/auth/signup", json=ADULT).status_code == 401


def test_signup_rejects_unknown_fields(auth: AuthHarness) -> None:
    auth.client.post("/auth/dev-login", json={"email": "ana@example.com"})
    resp = auth.client.post("/auth/signup", json={**ADULT, "org_id": "x"})
    assert resp.status_code == 422


def test_known_email_signs_in_without_signup(auth: AuthHarness) -> None:
    _sign_up(auth)
    auth.client.post("/auth/logout")
    assert auth.client.get("/auth/me").json()["status"] == "signed_out"
    state = auth.client.post("/auth/dev-login", json={"email": "ANA@example.com"}).json()
    assert state["status"] == "signed_in"
    assert len(_users(auth)) == 1


def test_require_user_dependency(auth: AuthHarness) -> None:
    @auth.app.get("/whoami")
    async def whoami(user: CurrentUser) -> dict[str, str]:
        return {"email": user.email}

    assert auth.client.get("/whoami").status_code == 401
    auth.client.post("/auth/dev-login", json={"email": "ana@example.com"})
    assert auth.client.get("/whoami").status_code == 401  # pending sign-up is not a user
    auth.client.post("/auth/signup", json=ADULT)
    assert auth.client.get("/whoami").json() == {"email": "ana@example.com"}


# ---------------------------------------------------------------- dev login


def test_dev_login_exists_only_in_local() -> None:
    for harness in build_harness(AppEnv.PRODUCTION):
        assert harness.client.post("/auth/dev-login", json={}).status_code == 404
        assert harness.client.get("/auth/providers").json()["dev"] is False


def test_providers_in_local(auth: AuthHarness) -> None:
    assert auth.client.get("/auth/providers").json() == {
        "google": False,
        "email": True,
        "dev": True,
    }


def test_production_refuses_the_dev_session_secret() -> None:
    with pytest.raises(ValidationError):
        AuthSettings(app_env=AppEnv.PRODUCTION, session_secret=DEV_SESSION_SECRET)
    with pytest.raises(ValidationError):
        AuthSettings(app_env=AppEnv.PRODUCTION, session_secret="short")


# ---------------------------------------------------------------- magic links


def _token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def test_magic_link_sign_up_flow(auth: AuthHarness) -> None:
    resp = auth.client.post("/auth/magic-link", json={"email": "Bo@Example.com"})
    assert resp.status_code == 202
    [(to, link)] = auth.email.sent
    assert to == "bo@example.com"
    assert link.startswith("http://web.test/api/auth/magic-link/callback?token=")
    assert resp.json()["dev_link"] == link

    cb = auth.client.get(f"/auth/magic-link/callback?token={_token(link)}", follow_redirects=False)
    assert cb.status_code == 303
    assert cb.headers["location"] == "http://web.test/signup"
    state = auth.client.post("/auth/signup", json=ADULT).json()
    assert state["user"]["auth_provider"] == "email"


def test_magic_link_works_once(auth: AuthHarness) -> None:
    auth.client.post("/auth/magic-link", json={"email": "bo@example.com"})
    token = _token(auth.email.sent[0][1])
    first = auth.client.get(f"/auth/magic-link/callback?token={token}", follow_redirects=False)
    assert first.headers["location"] == "http://web.test/signup"
    again = auth.client.get(f"/auth/magic-link/callback?token={token}", follow_redirects=False)
    assert again.headers["location"] == "http://web.test/signin?error=link_used"


def test_magic_link_rejects_a_forged_token(auth: AuthHarness) -> None:
    cb = auth.client.get("/auth/magic-link/callback?token=abc.def.ghi", follow_redirects=False)
    assert cb.headers["location"] == "http://web.test/signin?error=link_invalid"
    assert auth.client.get("/auth/me").json()["status"] == "signed_out"


def test_magic_link_for_known_user_goes_home(auth: AuthHarness) -> None:
    _sign_up(auth, email="bo@example.com")
    auth.client.post("/auth/logout")
    auth.client.post("/auth/magic-link", json={"email": "bo@example.com"})
    token = _token(auth.email.sent[-1][1])
    cb = auth.client.get(f"/auth/magic-link/callback?token={token}", follow_redirects=False)
    assert cb.headers["location"] == "http://web.test/"
    assert auth.client.get("/auth/me").json()["status"] == "signed_in"


def test_magic_link_rejects_bad_email(auth: AuthHarness) -> None:
    assert auth.client.post("/auth/magic-link", json={"email": "nope"}).status_code == 422
    assert auth.email.sent == []


def test_magic_link_hides_dev_link_outside_local() -> None:
    for harness in build_harness(AppEnv.PRODUCTION):
        resp = harness.client.post("/auth/magic-link", json={"email": "bo@example.com"})
        assert resp.json() == {"sent": True, "dev_link": None}
        assert len(harness.email.sent) == 1


# ---------------------------------------------------------------- Google


class FakeGoogle:
    def __init__(self, email: str | None) -> None:
        self.email = email

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> RedirectResponse:
        return RedirectResponse(f"https://accounts.google.test/auth?redirect_uri={redirect_uri}")

    async def fetch_identity(self, request: Request) -> GoogleIdentity:
        if self.email is None:
            raise GoogleSignInError("denied")
        return GoogleIdentity(email=self.email)


def test_google_login_redirects_to_google() -> None:
    for harness in build_harness(google=FakeGoogle("g@example.com")):
        assert harness.client.get("/auth/providers").json()["google"] is True
        resp = harness.client.get("/auth/google/login", follow_redirects=False)
        assert resp.headers["location"] == (
            "https://accounts.google.test/auth?redirect_uri=http://web.test/api/auth/google/callback"
        )


def test_google_callback_signs_up_with_google_provider() -> None:
    for harness in build_harness(google=FakeGoogle("G@Example.com")):
        cb = harness.client.get("/auth/google/callback", follow_redirects=False)
        assert cb.headers["location"] == "http://web.test/signup"
        state = harness.client.post("/auth/signup", json=ADULT).json()
        assert state["email"] == "g@example.com"
        assert state["user"]["auth_provider"] == AuthProvider.GOOGLE.value


def test_google_callback_error_goes_back_to_sign_in() -> None:
    for harness in build_harness(google=FakeGoogle(None)):
        cb = harness.client.get("/auth/google/callback", follow_redirects=False)
        assert cb.headers["location"] == "http://web.test/signin?error=google"


def test_google_routes_404_when_not_configured(auth: AuthHarness) -> None:
    assert auth.client.get("/auth/google/login", follow_redirects=False).status_code == 404
