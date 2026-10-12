"""Email intake — connecting a mailbox (architecture/03-mailbox-connectors.md, 09 §9.2).

    GET    /mail/config                         what this server can offer, and what this user may do
    GET    /mail/detect?email=…                 which connector fits the address (MX lookup)
    GET    /mail/connections                    my mailboxes (Super Admin: every mailbox in the workspace)
    POST   /mail/connections/{google|microsoft}/start   → consent URL
    GET    /mail/oauth/{google|microsoft}/callback      ← provider redirect; ends on the Mailboxes page
    POST   /mail/connections/imap               test the login, then save
    POST   /mail/connections/relay              provision a forwarding address
    POST   /mail/connections/{id}/test          re-check that the mailbox is still reachable
    PATCH  /mail/connections/{id}               folders, include spam, backfill window
    POST   /mail/connections/{id}/pause|resume
    DELETE /mail/connections/{id}               revoke, wipe credentials, keep the row as history

NOTHING HERE READS MAIL YET. Connecting proves access and stores it encrypted; the sync
worker that reads allowlisted senders is the next stage. The page says so.

THE CALLBACK IS THE ONE ROUTE WITHOUT A BEARER TOKEN — it is a browser redirect from Google
or Microsoft. It is authenticated by the single-use `state` saved at /start, which names the
user, and it re-checks that user (active, plan) itself because get_current_user never runs.
Every outcome, failure included, ends as a redirect to the Mailboxes page with a message,
never as a JSON error page the user is stranded on.
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core import rate_limit
from app.database import get_db
from app.dependencies import get_current_user
from app.models.mail import MailConnection
from app.models.user import User, UserRole, role_matches
from app.schemas.mail import (
    ConnectionOut, ConnectionSettingsIn, ConnectResultOut, DetectOut, FolderOut, ImapConnectIn,
    MailConfigOut, OwnerOut, ProviderAvailability, ProviderOut, RelayConnectIn, StartOAuthIn, StartOAuthOut,
    TestOut,
)
from app.services.mail import crypto, detect, imap_client, oauth, providers

logger = logging.getLogger(__name__)
router = APIRouter()

# Who may connect a mailbox. Approvers and viewers review nothing from mail, so they connect
# nothing; the platform admin belongs to no workspace (architecture/09 §9.8).
_CONNECT_ROLES = (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN, UserRole.OPERATIONS_USER, UserRole.FINANCE_USER)
_OAUTH_PROVIDERS = {"google": "gmail", "microsoft": "microsoft"}
_DEFAULT_SETTINGS = {"folders": ["INBOX"], "include_spam": True, "backfill_days": 30}


# ── guards ──────────────────────────────────────────────────────────────────

def _require_enabled() -> None:
    if not settings.MAIL_INTAKE_ENABLED:
        raise HTTPException(status_code=404, detail="Email intake is not enabled on this server.")


def _can_connect(user: User) -> bool:
    return user.tenant_id is not None and role_matches(user.role, *_CONNECT_ROLES)


def _is_super_admin(user: User) -> bool:
    return role_matches(user.role, UserRole.SUPER_ADMIN)


def _require_connect(user: User, visibility: str = "personal") -> None:
    if not _can_connect(user):
        raise HTTPException(status_code=403, detail="Your role cannot connect a mailbox. Ask your Super Admin.")
    if visibility == "workspace" and not _is_super_admin(user):
        raise HTTPException(status_code=403, detail="Only the Super Admin can connect a shared workspace mailbox.")


def _require_crypto() -> None:
    if not crypto.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Mailbox connections are not set up on this server yet (MAIL_ENCRYPTION_KEY is missing).",
        )


async def _limit(scope: str, user: User, limit: int, window_s: int) -> None:
    allowed, retry_after = await rate_limit.hit(scope, str(user.id), limit, window_s)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {retry_after} seconds.",
                            headers={"Retry-After": str(retry_after)})


async def _load_owned(db: AsyncSession, user: User, connection_id: int) -> MailConnection:
    """A connection this user may manage: their own, or any in the workspace for the Super Admin."""
    conn = await db.get(MailConnection, connection_id)
    if conn is None or conn.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Mailbox not found.")
    if conn.owner_user_id != user.id and not _is_super_admin(user):
        raise HTTPException(status_code=404, detail="Mailbox not found.")
    return conn


# ── serialising ─────────────────────────────────────────────────────────────

def _forwarding_address(conn: MailConnection) -> str | None:
    if conn.provider != "relay" or not conn.relay_token or not settings.MAIL_INBOUND_DOMAIN:
        return None
    return f"{conn.relay_token}@{settings.MAIL_INBOUND_DOMAIN}"


def _out(conn: MailConnection, owner: User | None, me: User) -> ConnectionOut:
    return ConnectionOut(
        id=conn.id, provider=conn.provider, email_address=conn.email_address,
        visibility=conn.visibility, status=conn.status, status_reason=conn.status_reason,
        screening_mode=conn.screening_mode,
        # Mailboxes connected before the provider tile was recorded get it inferred from the host.
        settings={**(conn.settings or {}),
                  "provider_key": (conn.settings or {}).get("provider_key") or providers.key_for_host(conn.imap_host)},
        owner=OwnerOut(id=conn.owner_user_id, name=owner.full_name if owner else "—"),
        is_mine=conn.owner_user_id == me.id,
        imap_host=conn.imap_host, imap_port=conn.imap_port, imap_username=conn.imap_username,
        forwarding_address=_forwarding_address(conn), granted_scopes=conn.granted_scopes,
        last_tested_at=conn.last_tested_at, last_synced_at=conn.last_synced_at, created_at=conn.created_at,
    )


async def _owner(db: AsyncSession, conn: MailConnection) -> User | None:
    return await db.get(User, conn.owner_user_id)


# ── credentials ─────────────────────────────────────────────────────────────

def _store_credentials(conn: MailConnection, payload: dict) -> None:
    enc, dek, ref = crypto.encrypt(payload, crypto.row_aad(conn.tenant_id, conn.id))
    conn.credentials_enc, conn.credentials_dek_enc, conn.credentials_key_ref = enc, dek, ref


def _read_credentials(conn: MailConnection) -> dict:
    if not conn.credentials_enc or not conn.credentials_dek_enc:
        raise crypto.CredentialsUnreadable("No credentials are stored for this mailbox.")
    return crypto.decrypt(conn.credentials_enc, conn.credentials_dek_enc, crypto.row_aad(conn.tenant_id, conn.id))


def _wipe_credentials(conn: MailConnection) -> None:
    conn.credentials_enc = conn.credentials_dek_enc = conn.credentials_key_ref = None


async def _claim_row(db: AsyncSession, user: User, provider: str, email: str, visibility: str) -> MailConnection:
    """The row this mailbox lives in: new, or the existing one when it is this user's (a
    reconnect keeps the sync cursor) or disconnected. Refuses a box a colleague connected."""
    existing = (await db.execute(
        select(MailConnection).where(
            MailConnection.tenant_id == user.tenant_id,
            MailConnection.provider == provider,
            MailConnection.email_address == email,
        )
    )).scalar_one_or_none()
    if existing is not None:
        if existing.status != "disconnected" and existing.owner_user_id != user.id:
            owner = await _owner(db, existing)
            raise HTTPException(
                status_code=409,
                detail=f"{email} is already connected by {owner.full_name if owner else 'a colleague'}. "
                       f"Ask them, or the Super Admin, to share or disconnect it.",
            )
        existing.owner_user_id = user.id
        existing.visibility = visibility
        if not existing.settings:
            existing.settings = dict(_DEFAULT_SETTINGS)
        return existing
    conn = MailConnection(
        tenant_id=user.tenant_id, owner_user_id=user.id, provider=provider, email_address=email,
        visibility=visibility, status="pending_auth", settings=dict(_DEFAULT_SETTINGS),
    )
    db.add(conn)
    await db.flush()          # the id is part of the encryption AAD
    return conn


def _mark_ok(conn: MailConnection) -> None:
    conn.status = "active"
    conn.status_reason = None
    conn.consecutive_failures = 0
    conn.last_tested_at = datetime.utcnow()


# ── read-only endpoints ─────────────────────────────────────────────────────

@router.get("/config", response_model=MailConfigOut)
async def mail_config(current_user: User = Depends(get_current_user)):
    """Always answers (even when disabled) so the UI can explain instead of 404-ing."""
    enabled = settings.MAIL_INTAKE_ENABLED
    ready = crypto.is_configured()

    def avail(ok: bool, why: str) -> ProviderAvailability:
        if not enabled:
            return ProviderAvailability(available=False, reason="Email intake is not enabled on this server.")
        if not ready:
            return ProviderAvailability(available=False, reason="MAIL_ENCRYPTION_KEY is not set on this server.")
        return ProviderAvailability(available=ok, reason=None if ok else why)

    return MailConfigOut(
        enabled=enabled, encryption_ready=ready,
        can_connect=_can_connect(current_user), can_connect_workspace=_is_super_admin(current_user),
        providers={
            "gmail": avail(oauth.google_configured(), "Google sign-in is not configured on this server yet."),
            "microsoft": avail(oauth.microsoft_configured(), "Microsoft sign-in is not configured on this server yet."),
            "imap": avail(True, ""),
            "relay": avail(bool(settings.MAIL_INBOUND_DOMAIN), "Forwarding addresses are not set up on this server yet."),
        },
        inbound_domain=settings.MAIL_INBOUND_DOMAIN or None,
    )


@router.get("/detect", response_model=DetectOut)
async def detect_provider(email: str = Query(..., max_length=320), current_user: User = Depends(get_current_user)):
    _require_enabled()
    try:
        address = detect.normalise_address(email)
    except detect.InvalidAddress as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    s = await detect.suggest(address)
    return DetectOut(email_address=address, provider=s.provider, imap_host=s.imap_host,
                     imap_port=s.imap_port, label=s.label, note=s.note, provider_key=s.provider_key)


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(current_user: User = Depends(get_current_user)):
    """The connect screen's tiles: every provider, with the right server and app-password steps,
    and whether this server can offer it (Google / Microsoft need their sign-in apps configured)."""
    _require_enabled()
    out = []
    for p in providers.PROVIDERS:
        oauth_ok = False
        if p.connector == "gmail":
            oauth_ok = oauth.google_configured()
            why = "Google sign-in is not configured on this server yet."
        elif p.connector == "microsoft":
            oauth_ok = oauth.microsoft_configured()
            why = ("Microsoft sign-in is not configured on this server yet — Microsoft mailboxes "
                   "cannot connect with a password, so an admin must set it up.")
        else:
            why = None
        # Without its sign-in app, a provider is still usable if it has a password route (Google).
        ok = oauth_ok or p.connector == "imap" or bool(p.imap_alternative)
        d = p.as_dict()
        out.append(ProviderOut(
            key=p.key, name=p.name, connector=p.connector, blurb=p.blurb, imap_host=p.imap_host,
            imap_port=p.imap_port, password_label=p.password_label, steps=d["steps"], help_url=p.help_url,
            popular=p.popular, regions=d["regions"], available=ok and crypto.is_configured(),
            reason=None if ok and crypto.is_configured() else (why or "MAIL_ENCRYPTION_KEY is not set on this server."),
            oauth_available=oauth_ok, imap_alternative=p.imap_alternative,
        ))
    return out


@router.get("/connections", response_model=list[ConnectionOut])
async def list_connections(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_enabled()
    q = select(MailConnection).where(MailConnection.tenant_id == current_user.tenant_id)
    if not _is_super_admin(current_user):
        q = q.where(MailConnection.owner_user_id == current_user.id)
    rows = (await db.execute(q.order_by(MailConnection.created_at.desc()))).scalars().all()
    owners = {u.id: u for u in (await db.execute(
        select(User).where(User.id.in_({r.owner_user_id for r in rows} or {0}))
    )).scalars().all()}
    return [_out(r, owners.get(r.owner_user_id), current_user) for r in rows]


# ── OAuth: Gmail and Microsoft 365 ──────────────────────────────────────────

@router.post("/connections/{provider}/start", response_model=StartOAuthOut)
async def start_oauth(provider: str, body: StartOAuthIn, current_user: User = Depends(get_current_user)):
    _require_enabled()
    if provider not in _OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider.")
    _require_connect(current_user, body.visibility)
    _require_crypto()
    configured = oauth.google_configured() if provider == "google" else oauth.microsoft_configured()
    if not configured:
        raise HTTPException(status_code=503, detail=f"{provider.title()} sign-in is not configured on this server yet.")
    await _limit("mail-oauth-start", current_user, 20, 600)

    hint = None
    if body.login_hint:
        try:
            hint = detect.normalise_address(body.login_hint)
        except detect.InvalidAddress as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    verifier, challenge = oauth.pkce_pair()
    try:
        state = await oauth.save_state(oauth.PendingAuth(
            provider=provider, user_id=current_user.id, tenant_id=current_user.tenant_id,
            verifier=verifier, login_hint=hint, visibility=body.visibility,
        ))
    except oauth.OAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    build = oauth.google_consent_url if provider == "google" else oauth.microsoft_consent_url
    return StartOAuthOut(url=build(state, challenge, hint))


def _back_to_ui(**params: str) -> RedirectResponse:
    url = f"{settings.FRONTEND_URL.rstrip('/')}/email-intake/mailboxes"
    clean = {k: v for k, v in params.items() if v}
    return RedirectResponse(f"{url}?{urlencode(clean)}" if clean else url, status_code=status.HTTP_302_FOUND)


@router.get("/oauth/{provider}/callback", include_in_schema=False)
async def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if not settings.MAIL_INTAKE_ENABLED or provider not in _OAUTH_PROVIDERS:
        return _back_to_ui(error="Email intake is not enabled on this server.")
    try:
        pending = await oauth.consume_state(state or "")
    except oauth.OAuthError as exc:
        return _back_to_ui(error=str(exc))
    if error:
        return _back_to_ui(error=oauth.provider_error_message(provider, error, error_description))
    if pending.provider != provider or not code:
        return _back_to_ui(error="The sign-in response did not match the request. Start again.")

    # get_current_user never ran for this request, so check the user the state names.
    user = (await db.execute(
        select(User).options(selectinload(User.tenant)).where(User.id == pending.user_id)
    )).scalar_one_or_none()
    if (user is None or not user.is_active or user.tenant_id != pending.tenant_id
            or user.tenant is None or not user.tenant.has_active_plan or not _can_connect(user)):
        return _back_to_ui(error="Your account can no longer connect a mailbox.")

    try:
        complete = oauth.complete_google if provider == "google" else oauth.complete_microsoft
        account = await complete(code, pending.verifier)
        if not account.email_address:
            raise oauth.OAuthError("The provider did not tell us which mailbox this is.")
        conn = await _claim_row(db, user, account.provider, account.email_address, pending.visibility)
        conn.provider_account_id = account.provider_account_id
        conn.granted_scopes = account.scopes
        conn.settings = {**(conn.settings or {}), "provider_key": provider}     # google | microsoft
        _store_credentials(conn, account.tokens)
        _mark_ok(conn)
        await db.commit()
    except oauth.OAuthError as exc:
        await db.rollback()
        return _back_to_ui(error=str(exc))
    except HTTPException as exc:          # 409 from _claim_row
        await db.rollback()
        return _back_to_ui(error=str(exc.detail))
    except Exception:                     # noqa: BLE001 — never strand the user on a stack trace
        await db.rollback()
        logger.exception("[mail] %s callback failed", provider)
        return _back_to_ui(error="Something went wrong while connecting. Please try again.")

    logger.info("[mail] connected %s mailbox id=%s tenant=%s", account.provider, conn.id, conn.tenant_id)
    mismatch = "1" if pending.login_hint and pending.login_hint != account.email_address else ""
    return _back_to_ui(connected=account.provider, account=account.email_address, hint_mismatch=mismatch)


# ── IMAP ────────────────────────────────────────────────────────────────────

def _folders_out(result: imap_client.ImapTestResult) -> list[FolderOut]:
    return [FolderOut(name=f.name, display=f.display, special_use=f.special_use) for f in result.folders]


@router.post("/connections/imap", response_model=ConnectResultOut, status_code=201)
async def connect_imap(body: ImapConnectIn, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    _require_enabled()
    _require_connect(current_user, body.visibility)
    _require_crypto()
    await _limit("mail-imap", current_user, 10, 600)
    try:
        email = detect.normalise_address(body.email_address)
    except detect.InvalidAddress as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    username = (body.username or email).strip()
    host = body.host.strip().lower()
    password = body.password
    gmail = host == "imap.gmail.com"
    if gmail:
        password = "".join(password.split())   # Google shows app passwords as "abcd efgh ijkl mnop"

    # Test BEFORE anything is written: a wrong password must not leave a half-made row.
    # Zoho runs separate hosts for paid (imappro.) and free (imap.) accounts and most people do
    # not know which they have, so a refusal from one is retried once on its sibling.
    try:
        result = await imap_client.test_login(host, body.port, username, password)
    except imap_client.ImapError as exc:
        result = None
        if exc.code == "auth_failed":
            for alt in providers.fallbacks_for(host):
                try:
                    result = await imap_client.test_login(alt, body.port, username, password)
                    host = alt
                    break
                except imap_client.ImapError:
                    continue
        if result is None:
            if gmail and exc.code == "auth_failed":
                raise HTTPException(status_code=400, detail=(
                    "Google refused the sign-in. Gmail needs an app password, not your normal password: "
                    "turn on 2-Step Verification, then create one at myaccount.google.com/apppasswords. "
                    "On Google Workspace your admin must also allow IMAP."))
            raise HTTPException(status_code=400, detail=str(exc))

    conn = await _claim_row(db, current_user, "imap", email, body.visibility)
    conn.imap_host, conn.imap_port, conn.imap_username = host, body.port, username
    conn.imap_security = imap_client.ALLOWED_PORTS[body.port]
    folders = list(result.suggested_folders)
    if body.include_spam and result.junk_folder and result.junk_folder not in folders:
        folders.append(result.junk_folder)
    conn.settings = {**(conn.settings or {}), "folders": folders, "include_spam": body.include_spam,
                     "provider_key": body.provider_key if body.provider_key in providers.BY_KEY else "other"}
    _store_credentials(conn, {"password": password})
    _mark_ok(conn)
    await db.commit()
    await db.refresh(conn)
    return ConnectResultOut(
        connection=_out(conn, current_user, current_user),
        test=TestOut(ok=True, message=f"Signed in. Found {len(result.folders)} folders.", status=conn.status,
                     folders=_folders_out(result)),
    )


# ── Forwarding address ──────────────────────────────────────────────────────

def _new_relay_token() -> str:
    return base64.b32encode(os.urandom(15)).decode().lower().rstrip("=")[:20]


@router.post("/connections/relay", response_model=ConnectResultOut, status_code=201)
async def connect_relay(body: RelayConnectIn, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    _require_enabled()
    _require_connect(current_user, body.visibility)
    if not settings.MAIL_INBOUND_DOMAIN:
        raise HTTPException(status_code=503, detail="Forwarding addresses are not set up on this server yet.")
    try:
        email = detect.normalise_address(body.email_address)
    except detect.InvalidAddress as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    conn = await _claim_row(db, current_user, "relay", email, body.visibility)
    if not conn.relay_token:
        conn.relay_token = _new_relay_token()
    _mark_ok(conn)
    await db.commit()
    await db.refresh(conn)
    return ConnectResultOut(
        connection=_out(conn, current_user, current_user),
        test=TestOut(ok=True, status=conn.status,
                     message=f"Forward mail from {email} to {_forwarding_address(conn)}."),
    )


# ── manage an existing connection ───────────────────────────────────────────

@router.post("/connections/{connection_id}/test", response_model=TestOut)
async def test_connection(connection_id: int, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    _require_enabled()
    conn = await _load_owned(db, current_user, connection_id)
    if conn.status == "disconnected":
        raise HTTPException(status_code=400, detail="This mailbox is disconnected. Connect it again.")
    await _limit("mail-test", current_user, 30, 600)

    folders = None
    try:
        if conn.provider == "relay":
            message = f"Waiting for mail forwarded to {_forwarding_address(conn)}."
        elif conn.provider == "imap":
            creds = _read_credentials(conn)
            result = await imap_client.test_login(conn.imap_host or "", conn.imap_port or 993,
                                                  conn.imap_username or conn.email_address, creds["password"])
            folders = _folders_out(result)
            message = f"Signed in. Found {len(result.folders)} folders."
        else:
            tokens = await oauth.refresh(conn.provider, _read_credentials(conn))
            await oauth.probe(conn.provider, tokens["access_token"])
            _store_credentials(conn, tokens)          # Microsoft may have rotated the refresh token
            message = "Connected. FareQube can read this mailbox."
        if conn.status != "paused":
            _mark_ok(conn)
        else:
            conn.last_tested_at = datetime.utcnow()
        ok = True
    except oauth.OAuthError as exc:
        ok, message = False, str(exc)
        conn.consecutive_failures += 1
        conn.status, conn.status_reason = ("needs_reauth" if exc.reauth else conn.status), message
    except imap_client.ImapError as exc:
        ok, message = False, str(exc)
        conn.consecutive_failures += 1
        conn.status = "needs_reauth" if exc.code == "auth_failed" else conn.status
        conn.status_reason = message
    except crypto.CredentialsUnreadable:
        ok, message = False, "The stored credentials could not be read. Reconnect this mailbox."
        conn.status, conn.status_reason = "needs_reauth", message
    await db.commit()
    return TestOut(ok=ok, message=message, status=conn.status, folders=folders)


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
async def update_connection(connection_id: int, body: ConnectionSettingsIn, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    _require_enabled()
    conn = await _load_owned(db, current_user, connection_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    conn.settings = {**(conn.settings or {}), **patch}
    await db.commit()
    await db.refresh(conn)
    return _out(conn, await _owner(db, conn), current_user)


@router.post("/connections/{connection_id}/pause", response_model=ConnectionOut)
async def pause_connection(connection_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    _require_enabled()
    conn = await _load_owned(db, current_user, connection_id)
    if conn.status not in ("active", "error"):
        raise HTTPException(status_code=400, detail=f"A mailbox that is {conn.status.replace('_', ' ')} cannot be paused.")
    conn.status, conn.status_reason = "paused", "Paused by user."
    await db.commit()
    await db.refresh(conn)
    return _out(conn, await _owner(db, conn), current_user)


@router.post("/connections/{connection_id}/resume", response_model=ConnectionOut)
async def resume_connection(connection_id: int, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    _require_enabled()
    conn = await _load_owned(db, current_user, connection_id)
    if conn.status != "paused":
        raise HTTPException(status_code=400, detail="Only a paused mailbox can be resumed.")
    conn.status, conn.status_reason = "active", None
    await db.commit()
    await db.refresh(conn)
    return _out(conn, await _owner(db, conn), current_user)


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect(connection_id: int, db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    """Revoke where the provider allows it, then destroy the stored credentials. The row stays
    (status `disconnected`) so later imports can still say which mailbox they came from."""
    _require_enabled()
    conn = await _load_owned(db, current_user, connection_id)
    if conn.provider in ("gmail", "microsoft") and conn.credentials_enc:
        try:
            await oauth.revoke(conn.provider, _read_credentials(conn))
        except crypto.CredentialsUnreadable:
            pass
    _wipe_credentials(conn)
    conn.status, conn.status_reason = "disconnected", "Disconnected by user."
    conn.relay_token = None                  # the forwarding address stops working
    conn.watch_ref = conn.watch_secret_hash = None
    conn.watch_expires_at = None
    await db.commit()
    logger.info("[mail] disconnected mailbox id=%s tenant=%s", conn.id, conn.tenant_id)
    return Response(status_code=204)
