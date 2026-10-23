"""Email and password sign-in tests (P3). Requirement IDs: AC-4 (sign up and sign in with a
password; the email is confirmed by a link), AC-5 (forgot password), AC-6 (lockout after 5
failures)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from strong_api.auth.passwords import (
    LOCKOUT_FAILURES,
    hash_password,
    password_problem,
    verify_password,
)
from strong_api.auth.settings import AppEnv
from strong_core.db.models import AuditLog, User

from .conftest import AuthHarness, build_harness

PW = "correct horse battery"
SIGNUP = {
    "email": "Ana@Example.com",
    "password": PW,
    "full_name": "Ana Lima",
    "age_confirmed": True,
    "terms_accepted": True,
}


def _user(auth: AuthHarness, email: str = "ana@example.com") -> User | None:
    async def q(db: Any) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    return auth.query(q)  # type: ignore[no-any-return]


def _token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def _last(auth: AuthHarness, kind: str) -> tuple[str, str]:
    mails = [(to, link) for k, to, link in auth.email.mail if k == kind]
    assert mails, f"no {kind} email"
    return mails[-1]


def _login(auth: AuthHarness, password: str = PW, email: str = "ana@example.com") -> Any:
    return auth.client.post("/auth/password/login", json={"email": email, "password": password})


def _signed_up_and_confirmed(auth: AuthHarness) -> None:
    assert auth.client.post("/auth/password/signup", json=SIGNUP).status_code == 200
    _, link = _last(auth, "confirm")
    auth.client.get(f"/auth/password/confirm?token={_token(link)}", follow_redirects=False)
    auth.client.post("/auth/logout")


# ---------------------------------------------------------------- password rules


def test_ac4_password_rules() -> None:
    """AC-4: at least 8 characters, and not the email name."""
    assert password_problem("1234567", "ana@example.com") == "Use at least 8 characters."
    assert password_problem("12345678", "ana@example.com") is None
    assert password_problem("ana-is-my-password", "ana@example.com") is not None
    assert password_problem("x" * 129, "ana@example.com") is not None
    assert password_problem(PW, "ana@example.com") is None


def test_ac4_hash_is_argon2_and_verifies() -> None:
    hashed = hash_password(PW)
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, PW)
    assert not verify_password(hashed, PW + "!")
    assert not verify_password(None, PW)
    assert not verify_password("not-a-hash", PW)


# ---------------------------------------------------------------- sign-up and confirmation


def test_ac4_signup_signs_in_and_emails_a_confirmation_link(auth: AuthHarness) -> None:
    resp = auth.client.post("/auth/password/signup", json=SIGNUP)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "signed_in"
    assert auth.client.get("/auth/me").json()["user"]["email"] == "ana@example.com"
    user = _user(auth)
    assert user is not None
    assert user.auth_provider == "password"
    assert user.email_verified_at is None
    assert user.password_hash and user.password_hash != PW
    assert user.full_name == "Ana Lima"
    assert user.training_consent is False  # AC-2
    to, link = _last(auth, "confirm")
    assert to == "ana@example.com"
    assert link.startswith("http://web.test/api/auth/password/confirm?token=")


def test_ac4_signup_records_the_confirmations(auth: AuthHarness) -> None:
    auth.client.post("/auth/password/signup", json=SIGNUP)

    async def q(db: Any) -> AuditLog:
        return (await db.execute(select(AuditLog))).scalar_one()  # type: ignore[no-any-return]

    log = auth.query(q)
    assert log.action == "user.signup"
    assert log.details_json["auth_provider"] == "password"
    assert log.details_json["age_confirmed_18_plus"] is True


@pytest.mark.parametrize("missing", ["age_confirmed", "terms_accepted"])
def test_ac4_signup_requires_18_plus_and_terms(auth: AuthHarness, missing: str) -> None:
    resp = auth.client.post("/auth/password/signup", json={**SIGNUP, missing: False})
    assert resp.status_code == 422
    assert _user(auth) is None


def test_ac4_signup_rejects_a_weak_password(auth: AuthHarness) -> None:
    resp = auth.client.post("/auth/password/signup", json={**SIGNUP, "password": "short"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Use at least 8 characters."
    assert _user(auth) is None


def test_ac4_password_sign_in_works_before_the_confirmation(auth: AuthHarness) -> None:
    auth.client.post("/auth/password/signup", json=SIGNUP)
    auth.client.post("/auth/logout")
    resp = _login(auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "signed_in"
    user = _user(auth)
    assert user is not None and user.email_verified_at is None


def test_ac4_confirmation_link_signs_in(auth: AuthHarness) -> None:
    auth.client.post("/auth/password/signup", json=SIGNUP)
    auth.client.post("/auth/logout")
    _, link = _last(auth, "confirm")
    cb = auth.client.get(f"/auth/password/confirm?token={_token(link)}", follow_redirects=False)
    assert cb.status_code == 303
    assert cb.headers["location"] == "http://web.test/"
    me = auth.client.get("/auth/me").json()
    assert me["status"] == "signed_in"
    assert me["user"]["auth_provider"] == "password"
    user = _user(auth)
    assert user is not None and user.email_verified_at is not None

    again = auth.client.get(f"/auth/password/confirm?token={_token(link)}", follow_redirects=False)
    assert again.headers["location"] == "http://web.test/signin?confirmed=1"


def test_ac4_sign_in_with_password_after_confirmation(auth: AuthHarness) -> None:
    _signed_up_and_confirmed(auth)
    resp = _login(auth, email="ANA@example.com")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "signed_in"
    assert auth.client.get("/auth/me").json()["user"]["email"] == "ana@example.com"


def test_ac4_wrong_password_and_unknown_email_get_the_same_reply(auth: AuthHarness) -> None:
    _signed_up_and_confirmed(auth)
    wrong = _login(auth, password="not the password")
    unknown = _login(auth, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


@pytest.mark.parametrize("confirmed", [True, False])
def test_ac4_signup_for_a_taken_email_is_refused(auth: AuthHarness, confirmed: bool) -> None:
    """A second sign-up never replaces the password, also before the email is confirmed."""
    if confirmed:
        _signed_up_and_confirmed(auth)
    else:
        auth.client.post("/auth/password/signup", json=SIGNUP)
        auth.client.post("/auth/logout")
    before = _user(auth)
    resp = auth.client.post("/auth/password/signup", json={**SIGNUP, "password": "another pw"})
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]
    assert auth.client.get("/auth/me").json()["status"] == "signed_out"
    after = _user(auth)
    assert before is not None and after is not None
    assert after.password_hash == before.password_hash
    assert _login(auth).status_code == 200


def test_ac4_resend_confirmation(auth: AuthHarness) -> None:
    auth.client.post("/auth/password/signup", json=SIGNUP)
    count = len(auth.email.mail)
    assert auth.client.post("/auth/password/resend", json={"email": "ana@example.com"}).json()[
        "sent"
    ]
    assert len(auth.email.mail) == count + 1
    # Unknown emails get the same reply and no email.
    auth.client.post("/auth/password/resend", json={"email": "nobody@example.com"})
    assert len(auth.email.mail) == count + 1


def test_ac4_confirm_rejects_a_forged_token(auth: AuthHarness) -> None:
    cb = auth.client.get("/auth/password/confirm?token=abc.def", follow_redirects=False)
    assert cb.headers["location"] == "http://web.test/signin?error=link_invalid"


def test_ac4_magic_link_on_unconfirmed_account_drops_the_untrusted_password(
    auth: AuthHarness,
) -> None:
    """Someone signed up with an email they do not own. The owner's magic link wins."""
    auth.client.post("/auth/password/signup", json=SIGNUP)
    auth.client.post("/auth/logout")
    auth.client.post("/auth/magic-link", json={"email": "ana@example.com"})
    _, link = auth.email.sent[-1]
    auth.client.get(f"/auth/magic-link/callback?token={_token(link)}", follow_redirects=False)
    assert auth.client.get("/auth/me").json()["status"] == "signed_in"
    user = _user(auth)
    assert user is not None
    assert user.email_verified_at is not None
    assert user.password_hash is None
    auth.client.post("/auth/logout")
    assert _login(auth).status_code == 401


def test_ac4_magic_link_still_works_for_password_users(auth: AuthHarness) -> None:
    _signed_up_and_confirmed(auth)
    auth.client.post("/auth/magic-link", json={"email": "ana@example.com"})
    _, link = auth.email.sent[-1]
    auth.client.get(f"/auth/magic-link/callback?token={_token(link)}", follow_redirects=False)
    assert auth.client.get("/auth/me").json()["status"] == "signed_in"
    auth.client.post("/auth/logout")
    assert _login(auth).status_code == 200  # the confirmed password is kept


def test_ac4_dev_links_are_hidden_outside_local() -> None:
    for harness in build_harness(AppEnv.PRODUCTION):
        harness.client.post("/auth/password/signup", json=SIGNUP)
        assert harness.email.mail[-1][0] == "confirm"
        resp = harness.client.post("/auth/password/forgot", json={"email": "ana@example.com"})
        assert resp.json() == {"sent": True, "dev_link": None}


# ---------------------------------------------------------------- forgot password (AC-5)


def test_ac5_reset_sets_a_new_password_and_signs_in(auth: AuthHarness) -> None:
    _signed_up_and_confirmed(auth)
    resp = auth.client.post("/auth/password/forgot", json={"email": "ana@example.com"})
    assert resp.status_code == 202
    _, link = _last(auth, "reset")
    assert link.startswith("http://web.test/reset-password?token=")
    token = _token(link)
    state = auth.client.post(
        "/auth/password/reset", json={"token": token, "password": "brand new secret"}
    )
    assert state.status_code == 200, state.text
    assert state.json()["status"] == "signed_in"
    auth.client.post("/auth/logout")
    assert _login(auth).status_code == 401
    assert _login(auth, password="brand new secret").status_code == 200

    again = auth.client.post(
        "/auth/password/reset", json={"token": token, "password": "yet another secret"}
    )
    assert again.status_code == 400

    async def q(db: Any) -> list[str]:
        return list((await db.execute(select(AuditLog.action))).scalars())

    assert "user.password_reset" in auth.query(q)


def test_ac5_forgot_reveals_nothing_for_unknown_emails(auth: AuthHarness) -> None:
    resp = auth.client.post("/auth/password/forgot", json={"email": "nobody@example.com"})
    assert resp.status_code == 202
    assert resp.json() == {"sent": True, "dev_link": None}
    assert auth.email.mail == []


def test_ac5_magic_link_user_can_set_a_first_password(auth: AuthHarness) -> None:
    auth.client.post("/auth/dev-login", json={"email": "bo@example.com"})
    auth.client.post("/auth/signup", json={"age_confirmed": True, "terms_accepted": True})
    auth.client.post("/auth/logout")
    auth.client.post("/auth/password/forgot", json={"email": "bo@example.com"})
    _, link = _last(auth, "reset")
    resp = auth.client.post("/auth/password/reset", json={"token": _token(link), "password": PW})
    assert resp.status_code == 200
    auth.client.post("/auth/logout")
    assert _login(auth, email="bo@example.com").status_code == 200


def test_ac5_reset_keeps_the_link_when_the_password_is_weak(auth: AuthHarness) -> None:
    _signed_up_and_confirmed(auth)
    auth.client.post("/auth/password/forgot", json={"email": "ana@example.com"})
    token = _token(_last(auth, "reset")[1])
    weak = auth.client.post("/auth/password/reset", json={"token": token, "password": "short"})
    assert weak.status_code == 422
    ok = auth.client.post(
        "/auth/password/reset", json={"token": token, "password": "long enough now"}
    )
    assert ok.status_code == 200


def test_ac5_reset_rejects_a_forged_token(auth: AuthHarness) -> None:
    resp = auth.client.post("/auth/password/reset", json={"token": "abc.def", "password": PW})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "That reset link is not valid. Ask for a new one."


# ---------------------------------------------------------------- lockout (AC-6)


def test_ac6_lockout_after_repeated_failures(auth: AuthHarness) -> None:
    _signed_up_and_confirmed(auth)
    for _ in range(LOCKOUT_FAILURES):
        assert _login(auth, password="wrong password!").status_code == 401
    locked = _login(auth)
    assert locked.status_code == 429
    assert "15 minutes" in locked.json()["detail"]


def test_ac6_success_clears_the_failure_count(auth: AuthHarness) -> None:
    _signed_up_and_confirmed(auth)
    for _ in range(LOCKOUT_FAILURES - 1):
        _login(auth, password="wrong password!")
    assert _login(auth).status_code == 200
    auth.client.post("/auth/logout")
    for _ in range(LOCKOUT_FAILURES - 1):
        _login(auth, password="wrong password!")
    assert _login(auth).status_code == 200
