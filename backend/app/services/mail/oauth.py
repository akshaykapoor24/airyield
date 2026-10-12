"""OAuth 2.0 for Gmail and Microsoft 365: consent URL, callback, refresh, revoke.

THE FLOW (architecture/03 §3.3–3.4, 10 §10.2)
    1. start     — random `state` + PKCE verifier saved in Redis for 10 minutes, keyed by
                   state, together with who asked. The browser is sent to the provider.
    2. callback  — the provider redirects back with ?code&state. The state is consumed
                   (one use only), the code is exchanged with the verifier, and the account
                   is identified by asking the provider who it is.
    3. stored    — the token set is encrypted (services/mail/crypto.py) onto the row.

WHY REDIS AND NOT A SIGNED STATE. The PKCE verifier must stay on the server; putting it in
a signed-but-readable state would hand it to anyone who sees the redirect URL. Redis is
already required (Celery, rate limits). If it is down, connecting fails loudly rather than
weakening the flow.

SCOPES ARE READ-ONLY. Gmail: `gmail.readonly` (restricted scope — see the verification
note in architecture/03 §3.3). Microsoft: `Mail.Read` + `offline_access`. No send, no
modify, no delete.

Nothing here touches the database; the router owns rows and commits.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

STATE_TTL_S = 600
_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_SCOPES = f"openid email {GMAIL_SCOPE}"

MS_SCOPES = "openid email offline_access User.Read Mail.Read"
GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me?$select=id,mail,userPrincipalName"
GRAPH_INBOX_URL = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox?$select=id,totalItemCount"


class OAuthError(Exception):
    """A failure written for the user. `reauth` = the stored grant is dead, reconnect needed."""

    def __init__(self, message: str, *, reauth: bool = False):
        super().__init__(message)
        self.reauth = reauth


@dataclass(frozen=True)
class PendingAuth:
    provider: str
    user_id: int
    tenant_id: int
    verifier: str
    login_hint: str | None
    visibility: str


@dataclass(frozen=True)
class ConnectedAccount:
    provider: str
    email_address: str
    provider_account_id: str
    scopes: str
    tokens: dict          # {refresh_token, access_token, expires_at}


# ── configuration ───────────────────────────────────────────────────────────

def google_configured() -> bool:
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def microsoft_configured() -> bool:
    return bool(settings.MS_OAUTH_CLIENT_ID and settings.MS_OAUTH_CLIENT_SECRET)


def redirect_uri(provider: str) -> str:
    return f"{settings.API_PUBLIC_URL.rstrip('/')}/api/v1/mail/oauth/{provider}/callback"


def _ms(path: str) -> str:
    return f"{settings.MS_OAUTH_AUTHORITY.rstrip('/')}/oauth2/v2.0/{path}"


# ── PKCE + state ────────────────────────────────────────────────────────────

def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge) per RFC 7636."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2,
                             decode_responses=True)


async def save_state(pending: PendingAuth) -> str:
    state = secrets.token_urlsafe(32)
    try:
        async with _redis() as r:
            await r.set(f"mail:oauth:{state}", json.dumps(pending.__dict__), ex=STATE_TTL_S)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[mail.oauth] cannot save state: %s", exc)
        raise OAuthError("Connecting a mailbox needs Redis, which is not reachable right now. Try again shortly.") from exc
    return state


async def consume_state(state: str) -> PendingAuth:
    """The pending request for this state, deleted on read so a callback cannot be replayed."""
    if not state:
        raise OAuthError("The sign-in response was missing its security check. Start again.")
    key = f"mail:oauth:{state}"
    try:
        async with _redis() as r:
            # GET + DEL in one MULTI: atomic like GETDEL, which needs Redis >= 6.2.
            async with r.pipeline(transaction=True) as pipe:
                raw, _ = await pipe.get(key).delete(key).execute()
    except Exception as exc:  # noqa: BLE001
        raise OAuthError("Could not verify the sign-in (Redis unavailable). Start again.") from exc
    if not raw:
        raise OAuthError("This sign-in link has expired or was already used. Start again from Mailboxes.")
    return PendingAuth(**json.loads(raw))


# ── consent URLs ────────────────────────────────────────────────────────────

def google_consent_url(state: str, challenge: str, login_hint: str | None) -> str:
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri("google"),
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",          # we need a refresh token
        "prompt": "consent",               # …and Google only re-issues one on explicit consent
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def microsoft_consent_url(state: str, challenge: str, login_hint: str | None) -> str:
    params = {
        "client_id": settings.MS_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri("microsoft"),
        "response_type": "code",
        "response_mode": "query",
        "scope": MS_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{_ms('authorize')}?{urlencode(params)}"


def provider_error_message(provider: str, error: str | None, description: str | None) -> str:
    """Turn ?error=… on the callback into something a travel-desk user can act on."""
    desc = description or ""
    if error == "access_denied" and provider == "google":
        return "Google access was not granted. Connect again and allow FareQube to read your mail."
    if "AADSTS65001" in desc or "AADSTS90094" in desc or "admin" in desc.lower():
        return ("Your organisation's Microsoft 365 admin must approve FareQube before you can connect. "
                "Ask your IT admin, or use the forwarding address instead.")
    if error == "access_denied":
        return "Access was not granted. Connect again and accept the permissions."
    return f"The sign-in did not complete ({error or 'unknown error'}). Please try again."


# ── token exchange ──────────────────────────────────────────────────────────

def _expires_at(payload: dict) -> int:
    return int(time.time()) + int(payload.get("expires_in") or 3600) - 60


def _jwt_claims(token: str | None) -> dict:
    """Claims of an ID token received directly from the token endpoint over TLS. Signature
    checking is optional for that channel (OIDC Core §3.1.3.7); only identifiers are read."""
    if not token or token.count(".") != 2:
        return {}
    body = token.split(".")[1]
    try:
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:  # noqa: BLE001
        return {}


async def _post_token(url: str, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(url, data=data, headers={"Accept": "application/json"})
    payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200:
        err = payload.get("error")
        logger.info("[mail.oauth] token endpoint %s → %s %s", url, resp.status_code, err)
        if err in ("invalid_grant", "interaction_required", "consent_required"):
            raise OAuthError("Access to this mailbox has expired or was revoked. Reconnect it.", reauth=True)
        raise OAuthError("The provider refused the sign-in. Please try again.")
    return payload


async def complete_google(code: str, verifier: str) -> ConnectedAccount:
    tok = await _post_token(GOOGLE_TOKEN_URL, {
        "code": code, "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET, "redirect_uri": redirect_uri("google"),
        "grant_type": "authorization_code", "code_verifier": verifier,
    })
    scopes = tok.get("scope", "")
    if GMAIL_SCOPE not in scopes.split():
        # The consent screen lets people untick individual scopes.
        raise OAuthError("FareQube was not allowed to read your Gmail. Connect again and tick the Gmail permission.")
    if not tok.get("refresh_token"):
        raise OAuthError("Google did not issue a long-lived token. Remove FareQube at "
                         "myaccount.google.com/permissions, then connect again.")
    access = tok["access_token"]
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"Authorization": f"Bearer {access}"}) as client:
        profile = await client.get(GMAIL_PROFILE_URL)
        if profile.status_code != 200:
            raise OAuthError("Signed in, but Gmail did not answer for this account. Is Gmail enabled for it?")
        info = await client.get(GOOGLE_USERINFO_URL)
    email = profile.json().get("emailAddress", "").lower()
    sub = (info.json() if info.status_code == 200 else {}).get("sub") or _jwt_claims(tok.get("id_token")).get("sub")
    return ConnectedAccount(
        provider="gmail", email_address=email, provider_account_id=str(sub or email), scopes=scopes,
        tokens={"refresh_token": tok["refresh_token"], "access_token": access, "expires_at": _expires_at(tok)},
    )


async def complete_microsoft(code: str, verifier: str) -> ConnectedAccount:
    tok = await _post_token(_ms("token"), {
        "code": code, "client_id": settings.MS_OAUTH_CLIENT_ID,
        "client_secret": settings.MS_OAUTH_CLIENT_SECRET, "redirect_uri": redirect_uri("microsoft"),
        "grant_type": "authorization_code", "code_verifier": verifier, "scope": MS_SCOPES,
    })
    if not tok.get("refresh_token"):
        raise OAuthError("Microsoft did not issue a long-lived token (offline access). Please connect again.")
    access = tok["access_token"]
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"Authorization": f"Bearer {access}"}) as client:
        me = await client.get(GRAPH_ME_URL)
        inbox = await client.get(GRAPH_INBOX_URL)
    if me.status_code != 200:
        raise OAuthError("Signed in, but Microsoft did not return this account's details.")
    if inbox.status_code != 200:
        code_ = (inbox.json().get("error") or {}).get("code", "") if inbox.content else ""
        if code_ == "MailboxNotEnabledForRESTAPI":
            raise OAuthError("This mailbox is not on Exchange Online (or has no licence). "
                             "Use IMAP or the forwarding address instead.")
        raise OAuthError("Signed in, but the mailbox could not be read. Check that it has a mail licence.")
    who = me.json()
    claims = _jwt_claims(tok.get("id_token"))
    email = (who.get("mail") or who.get("userPrincipalName") or "").lower()
    account_id = f"{claims.get('tid', '')}:{claims.get('oid') or who.get('id')}"
    return ConnectedAccount(
        provider="microsoft", email_address=email, provider_account_id=account_id,
        scopes=tok.get("scope", MS_SCOPES),
        tokens={"refresh_token": tok["refresh_token"], "access_token": access, "expires_at": _expires_at(tok)},
    )


# ── health checks on an existing connection ─────────────────────────────────

async def refresh(provider: str, tokens: dict) -> dict:
    """A fresh access token. Microsoft may rotate the refresh token, so the whole set returns."""
    if provider == "gmail":
        tok = await _post_token(GOOGLE_TOKEN_URL, {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID, "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token",
        })
    else:
        tok = await _post_token(_ms("token"), {
            "client_id": settings.MS_OAUTH_CLIENT_ID, "client_secret": settings.MS_OAUTH_CLIENT_SECRET,
            "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token", "scope": MS_SCOPES,
        })
    return {
        "refresh_token": tok.get("refresh_token") or tokens["refresh_token"],
        "access_token": tok["access_token"],
        "expires_at": _expires_at(tok),
    }


async def probe(provider: str, access_token: str) -> None:
    """One cheap read proving the mailbox is still reachable with this token."""
    url = GMAIL_PROFILE_URL if provider == "gmail" else GRAPH_INBOX_URL
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code in (401, 403):
        raise OAuthError("FareQube can no longer read this mailbox. Reconnect it.", reauth=True)
    if resp.status_code != 200:
        raise OAuthError(f"The mail provider answered {resp.status_code}. It may be a temporary problem.")


async def revoke(provider: str, tokens: dict) -> None:
    """Best effort. Google has a revoke endpoint; Microsoft does not let an app revoke its own
    delegated grant, so there the stored tokens are simply destroyed by the caller."""
    if provider != "gmail" or not tokens.get("refresh_token"):
        return
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            await client.post(GOOGLE_REVOKE_URL, data={"token": tokens["refresh_token"]})
    except Exception as exc:  # noqa: BLE001 — disconnecting must succeed even if Google is unreachable
        logger.info("[mail.oauth] Google revoke failed (ignored): %s", exc)
