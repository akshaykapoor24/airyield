"""IMAP connection test: can we log in, and which folders are there?

Used when a user connects Zoho, GoDaddy, Titan, Rediff, Hostinger, Yahoo or any other
IMAP mailbox (architecture/03 §3.5). Reading mail comes later; this only proves the
credentials work and proposes folders. It never selects a folder for writing and never
fetches a message, so nothing in the mailbox can change.

TLS ONLY. Port 993 (implicit TLS) or 143 with STARTTLS, certificates verified. Plaintext
IMAP would put the user's password on the wire, so it is not offered.

THE HOST IS USER INPUT, WHICH MAKES THIS AN SSRF SURFACE. Without a guard, "test my
mailbox" is a way to make the server open TCP connections to anything it can reach — the
database on the private network included. So every address the host resolves to must be
public, and only the IMAP ports are allowed. The resolved address is what we connect to,
which closes the gap between checking a name and using it (DNS rebinding).

imaplib is blocking; the async wrapper runs it in a thread.
"""
from __future__ import annotations

import asyncio
import imaplib
import ipaddress
import logging
import re
import socket
import ssl
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

ALLOWED_PORTS = {993: "ssl", 143: "starttls"}
_TIMEOUT_S = 20


class ImapError(Exception):
    """A failure the user can act on. `code` lets the UI pick an icon; the message is the sentence."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Folder:
    name: str             # exactly as the server spells it — what SELECT needs
    display: str          # decoded for people (IMAP folder names are modified UTF-7)
    flags: tuple[str, ...]

    @property
    def special_use(self) -> str | None:
        for f in self.flags:
            if f.lower() in ("\\junk", "\\spam", "\\sent", "\\trash", "\\drafts", "\\archive", "\\all"):
                return f.lower().lstrip("\\")
        return None


@dataclass
class ImapTestResult:
    folders: list[Folder] = field(default_factory=list)
    suggested_folders: list[str] = field(default_factory=list)
    junk_folder: str | None = None


# ── host safety ─────────────────────────────────────────────────────────────

_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _effective(addr: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """The address that really gets reached. Many Indian ISPs and mobile networks run
    IPv6-only with NAT64, so a perfectly public server like imappro.zoho.in resolves to
    64:ff9b::<its IPv4>. Python calls that range reserved; judging the wrapper instead of
    the IPv4 inside would block every mail host on those networks."""
    if isinstance(addr, ipaddress.IPv6Address):
        if addr in _NAT64:
            return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
        if addr.ipv4_mapped is not None:
            return addr.ipv4_mapped
    return addr


def is_public_ip(ip: str) -> bool:
    addr = _effective(ipaddress.ip_address(ip))
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified)


def resolve_public(host: str, port: int) -> str:
    """The first public address for `host`, or ImapError. Refuses if ANY address is private:
    a name that resolves to both is exactly what a rebinding attack looks like."""
    host = (host or "").strip().rstrip(".").lower()
    if not host or not re.fullmatch(r"[a-z0-9.-]+", host):
        raise ImapError("bad_host", "Enter the mail server's host name, for example imap.zoho.in.")
    if port not in ALLOWED_PORTS:
        raise ImapError("bad_port", "Use port 993 (SSL) or 143 (STARTTLS). Plain IMAP is not allowed.")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ImapError("unknown_host", f"The mail server {host} could not be found. Check the spelling.") from exc
    # IPv4 first: it is reachable from every server this runs on; IPv6 only when there is no v4.
    ips = sorted({info[4][0] for info in infos}, key=lambda ip: (":" in ip, ip))
    if not ips or not all(is_public_ip(ip) for ip in ips):
        raise ImapError("blocked_host", f"{host} is not a public mail server, so FareQube will not connect to it.")
    return ips[0]


# ── folder parsing ──────────────────────────────────────────────────────────

_LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$')


def decode_modified_utf7(name: str) -> str:
    """RFC 3501 §5.1.3 folder-name encoding: '&' starts base64 UTF-16BE, '&-' is a literal '&'."""
    out, i = [], 0
    while i < len(name):
        ch = name[i]
        if ch != "&":
            out.append(ch)
            i += 1
            continue
        end = name.find("-", i)
        if end == -1:
            out.append(name[i:])
            break
        chunk = name[i + 1:end]
        if not chunk:
            out.append("&")
        else:
            import base64
            b64 = chunk.replace(",", "/")
            b64 += "=" * (-len(b64) % 4)
            try:
                out.append(base64.b64decode(b64).decode("utf-16-be"))
            except Exception:  # noqa: BLE001 — show the raw name rather than fail the test
                out.append(name[i:end + 1])
        i = end + 1
    return "".join(out)


def parse_list_line(line: bytes) -> Folder | None:
    m = _LIST_RE.match(line.strip())
    if not m:
        return None
    raw = m.group("name").strip()
    if raw.startswith(b'"') and raw.endswith(b'"'):
        raw = raw[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
    name = raw.decode("ascii", errors="replace")
    flags = tuple(f.decode("ascii", errors="replace") for f in m.group("flags").split())
    if any(f.lower() == "\\noselect" for f in flags):
        return None
    return Folder(name=name, display=decode_modified_utf7(name), flags=flags)


def suggest_folders(folders: list[Folder]) -> tuple[list[str], str | None]:
    """INBOX by default; the Junk folder is reported separately so the UI can offer it."""
    inbox = next((f.name for f in folders if f.name.upper() == "INBOX"), "INBOX")
    junk = next((f.name for f in folders if f.special_use in ("junk", "spam")), None)
    if junk is None:
        junk = next((f.name for f in folders if f.display.lower() in ("junk", "spam", "junk e-mail", "bulk mail")), None)
    return [inbox], junk


# ── the test ────────────────────────────────────────────────────────────────

def tls_context() -> ssl.SSLContext:
    """Full certificate verification against the system store PLUS Mozilla's bundle (certifi).

    Why both: Windows installs many root certificates only on demand, and Python reads the
    store without triggering that download. GoDaddy's IMAP server (imap.secureserver.net)
    chains to Starfield Root G2, which a fresh Windows box often has not fetched yet — the
    connection then failed as "self-signed certificate in chain" although the chain is valid.
    The system store stays loaded so a company's own root (a TLS-inspecting proxy) still works.
    Verification is never switched off."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — certifi missing: the system store alone still verifies
        logger.warning("[mail.imap] certifi unavailable; using the system certificate store only")
    return ctx


def open_session(host: str, port: int, username: str, password: str) -> imaplib.IMAP4:
    """A logged-in IMAP session over verified TLS to a vetted public address. Blocking.
    Raises ImapError with a user-facing sentence; the caller must logout()."""
    ip = resolve_public(host, port)
    ctx = tls_context()
    conn: imaplib.IMAP4 | None = None
    try:
        # Connect to the vetted IP but present the host name, so the certificate is checked
        # against the name the user typed.
        sock = socket.create_connection((ip, port), timeout=_TIMEOUT_S)
        if ALLOWED_PORTS[port] == "ssl":
            sock = ctx.wrap_socket(sock, server_hostname=host)
        conn = _ImapOverSocket(host, port, sock)
        if ALLOWED_PORTS[port] == "starttls":
            conn.starttls(ssl_context=ctx)
        conn.login(username, password)
        return conn
    except Exception as exc:
        if conn is not None:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        raise _as_imap_error(exc, host, port) from exc


def _as_imap_error(exc: Exception, host: str, port: int) -> ImapError:
    if isinstance(exc, ImapError):
        return exc
    if isinstance(exc, imaplib.IMAP4.error):
        text = str(exc).lower()
        if "auth" in text or "login" in text or "credential" in text or "password" in text:
            return ImapError("auth_failed", "The mail server rejected the username or password. "
                             "Most providers need an app password here, not your normal password.")
        return ImapError("imap_error", f"The mail server refused the request: {exc}")
    if isinstance(exc, ssl.SSLError):
        return ImapError("tls_failed", "A secure (TLS) connection could not be made. Check the port and host.")
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return ImapError("timeout", f"{host}:{port} did not answer in {_TIMEOUT_S} seconds.")
    if isinstance(exc, OSError):
        return ImapError("unreachable", f"Could not connect to {host}:{port}.")
    return ImapError("imap_error", f"The mail server connection failed: {exc}")


def _test_sync(host: str, port: int, username: str, password: str) -> ImapTestResult:
    conn: imaplib.IMAP4 | None = None
    try:
        conn = open_session(host, port, username, password)
        typ, data = conn.list()
        if typ != "OK":
            raise ImapError("list_failed", "Logged in, but the server would not list its folders.")
        folders = [f for f in (parse_list_line(d) for d in data if isinstance(d, bytes)) if f]
        suggested, junk = suggest_folders(folders)
        return ImapTestResult(folders=folders, suggested_folders=suggested, junk_folder=junk)
    except ImapError:
        raise
    except Exception as exc:
        raise _as_imap_error(exc, host, port) from exc
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass


class _ImapOverSocket(imaplib.IMAP4):
    """imaplib.IMAP4 on a socket we opened ourselves (to the vetted IP, already TLS-wrapped)."""

    def __init__(self, host: str, port: int, sock: socket.socket):
        self._prepared_sock = sock
        super().__init__(host, port)

    # `_create_socket` is imaplib's own hook (3.9+). Overriding `open` instead would break on
    # 3.14, where the reader moved from `self.file` to `self._file`.
    def _create_socket(self, timeout=None):
        return self._prepared_sock


async def test_login(host: str, port: int, username: str, password: str) -> ImapTestResult:
    return await asyncio.to_thread(_test_sync, host, port, username, password)


# ── reading new mail (the sync) ─────────────────────────────────────────────
#
# Strict mode (architecture/04 §4.10): the SERVER is asked for messages FROM the registry's
# addresses and "@domain" terms, so mail from anyone else is never listed, fetched or stored.
# IMAP's FROM is a substring match, which is why the sync re-checks the sender after download.
#
# Everything is read-only: folders are opened with EXAMINE and bodies fetched with
# BODY.PEEK[], so nothing is ever marked read, moved or flagged in the user's mailbox.

import time
from datetime import date, datetime

_SEARCH_CHUNK = 20
# How many "fetched but not ours" UIDs a folder cursor remembers — enough to cover the
# lookback window on a busy mailbox, small enough to keep the cursor a few KB.
_IGNORED_KEEP = 500
_STATUS_RE = re.compile(rb"(UIDNEXT|UIDVALIDITY)\s+(\d+)")
_FETCH_META_RE = re.compile(rb"UID\s+(\d+)")
_SIZE_RE = re.compile(rb"RFC822\.SIZE\s+(\d+)")
_DATE_RE = re.compile(rb'INTERNALDATE\s+"[^"]+"')


@dataclass
class FetchedMessage:
    folder: str
    uidvalidity: int
    uid: int
    internaldate: datetime | None      # naive UTC
    size: int | None
    raw: bytes | None                  # full RFC 5322, or only the header when too large
    too_large: bool = False
    first_sync: bool = False           # part of a folder's first import (no notification storm)

    @property
    def provider_id(self) -> str:
        return provider_message_id(self.folder, self.uidvalidity, self.uid)


@dataclass
class ReadResult:
    messages: list[FetchedMessage] = field(default_factory=list)
    cursors: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    more_waiting: bool = False


def provider_message_id(folder: str, uidvalidity: int, uid: int) -> str:
    return f"{folder}:{uidvalidity}:{uid}"


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def from_criteria(addresses: list[str]) -> list[str]:
    """IMAP prefix-OR over FROM terms: OR FROM "a" OR FROM "b" FROM "c"."""
    tokens: list[str] = []
    for addr in addresses[:-1]:
        tokens += ["OR", "FROM", quote(addr)]
    tokens += ["FROM", quote(addresses[-1])]
    return tokens


def imap_date(d: date) -> str:
    return d.strftime("%d-%b-%Y")


def _internaldate(blob: bytes) -> datetime | None:
    m = _DATE_RE.search(blob)
    if not m:
        return None
    tt = imaplib.Internaldate2tuple(m.group(0))
    return datetime.utcfromtimestamp(time.mktime(tt)) if tt else None


def _folder_state(conn: imaplib.IMAP4, folder: str) -> tuple[int, int]:
    typ, data = conn.status(quote(folder), "(UIDNEXT UIDVALIDITY)")
    if typ != "OK" or not data or not data[0]:
        raise ImapError("folder_missing", f"The folder {folder} could not be opened.")
    values = {k.decode(): int(v) for k, v in _STATUS_RE.findall(data[0])}
    return values.get("UIDNEXT", 1), values.get("UIDVALIDITY", 0)


def _search(conn: imaplib.IMAP4, uid_range: str, since: date | None, addresses: list[str]) -> set[int]:
    found: set[int] = set()
    for i in range(0, len(addresses), _SEARCH_CHUNK):
        criteria = ["UID", uid_range] + (["SINCE", imap_date(since)] if since else [])
        criteria += from_criteria(addresses[i:i + _SEARCH_CHUNK])
        typ, data = conn.uid("SEARCH", *criteria)
        if typ != "OK":
            raise ImapError("search_failed", "The mail server rejected the search for new mail.")
        if data and data[0]:
            found |= {int(x) for x in data[0].split()}
    return found


def _sizes(conn: imaplib.IMAP4, uids: list[int]) -> dict[int, tuple[int | None, datetime | None]]:
    out: dict[int, tuple[int | None, datetime | None]] = {}
    if not uids:
        return out
    typ, data = conn.uid("FETCH", ",".join(map(str, uids)), "(RFC822.SIZE INTERNALDATE)")
    for item in data or []:
        blob = item[0] if isinstance(item, tuple) else item
        if not isinstance(blob, bytes):
            continue
        m = _FETCH_META_RE.search(blob)
        if m:
            size = _SIZE_RE.search(blob)
            out[int(m.group(1))] = (int(size.group(1)) if size else None, _internaldate(blob))
    return out


def _fetch_body(conn: imaplib.IMAP4, uid: int, header_only: bool) -> bytes | None:
    part = "BODY.PEEK[HEADER]" if header_only else "BODY.PEEK[]"
    typ, data = conn.uid("FETCH", str(uid), f"({part})")
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _read_sync(host: str, port: int, username: str, password: str, *, folders: list[str],
               cursors: dict, senders: list[str], since: date, existing: set[str],
               limit: int, max_bytes: int, lookback: date | None = None) -> ReadResult:
    result = ReadResult(cursors=dict(cursors))
    conn = open_session(host, port, username, password)
    try:
        remaining = limit
        for folder in folders:
            try:
                uidnext, uidvalidity = _folder_state(conn, folder)
                typ, _ = conn.select(quote(folder), readonly=True)      # EXAMINE
                if typ != "OK":
                    raise ImapError("folder_missing", f"The folder {folder} could not be opened.")
                cur = cursors.get(folder)
                first = not cur or cur.get("uidvalidity") != uidvalidity
                earlier: set[int] = set()
                if first:
                    uids = _search(conn, "1:*", since, senders)
                else:
                    last = int(cur.get("last_uid", 0))
                    # "n:*" returns the newest message even when nothing is newer than n.
                    uids = {u for u in _search(conn, f"{last + 1}:*", None, senders) if u > last}
                    # LOOKBACK. A server gives a new message its UID at once but indexes its From
                    # header for SEARCH a little later (seen on Zoho: a mail delivered a minute
                    # before a check was not found by FROM, while UIDNEXT had already moved past
                    # it — so the cursor skipped it for good). Re-searching the last few days
                    # catches those; `existing` and `ignored` keep it from fetching anything twice.
                    if lookback:
                        uids |= _search(conn, "1:*", lookback, senders)
                    known = set(cur.get("senders", []))
                    added = [s for s in senders if s not in known]
                    if added:
                        # A sender added since the last check (a party onboarded, a company domain
                        # now read): fetch their earlier mail too, imported like a first check —
                        # one summary, not a bell entry per old message.
                        earlier = _search(conn, "1:*", since, added) - uids
                        uids |= earlier

                ignored = set(int(u) for u in (cur or {}).get("ignored", [])) if not first else set()
                todo = sorted(u for u in uids
                              if provider_message_id(folder, uidvalidity, u) not in existing and u not in ignored)
                take = todo[:max(remaining, 0)]
                meta = _sizes(conn, take)
                for uid in take:
                    size, when = meta.get(uid, (None, None))
                    too_large = bool(size and size > max_bytes)
                    raw = _fetch_body(conn, uid, header_only=too_large)
                    result.messages.append(FetchedMessage(
                        folder=folder, uidvalidity=uidvalidity, uid=uid, internaldate=when,
                        size=size, raw=raw, too_large=too_large, first_sync=first or uid in earlier,
                    ))
                remaining -= len(take)
                complete = len(take) == len(todo)
                result.more_waiting |= not complete
                # Complete: skip straight to the end of the folder. Not complete: everything
                # left is above the last uid taken (todo is ascending), so resume from there.
                last_uid = (uidnext - 1) if complete else take[-1] if take else int((cur or {}).get("last_uid", 0))
                # `ignored` (UIDs fetched but deliberately not stored) is carried over and
                # topped up by the sync layer, which is the one that knows what it skipped.
                result.cursors[folder] = {"uidvalidity": uidvalidity, "last_uid": last_uid, "senders": senders,
                                          "ignored": sorted(ignored)[-_IGNORED_KEEP:]}
            except ImapError as exc:
                result.errors.append(f"{folder}: {exc}")
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return result


async def read_new(host: str, port: int, username: str, password: str, **kwargs) -> ReadResult:
    return await asyncio.to_thread(_read_sync, host, port, username, password, **kwargs)
