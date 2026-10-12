"""Which connector fits a mailbox, guessed from its address and its domain's MX records.

Saves the most common support call — "I chose IMAP but my mail is on Google". The user types
their address; the address domain (gmail.com, yahoo.com …) or the domain's MX records
(google.com → Google Workspace, mail.protection.outlook.com → Microsoft 365 including GoDaddy's,
secureserver.net → GoDaddy Professional Email, zoho.<dc> → Zoho, titan.email → Titan …) pick an
entry from the provider catalogue in services/mail/providers.py. Anything else → IMAP, host
left for the user.

A suggestion, never a decision: the user can pick any connector. `classify` is pure and
unit-tested; `suggest` adds the DNS lookup, which may fail (no network, NXDOMAIN) and then
falls back to "we could not tell".
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from email_validator import EmailNotValidError, validate_email

from app.services.mail import providers

logger = logging.getLogger(__name__)

_DNS_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class Suggestion:
    provider: str | None          # connector: "gmail" | "microsoft" | "imap" | None (cannot tell)
    imap_host: str | None = None
    imap_port: int | None = None
    label: str = ""               # what the UI says: "Google", "Zoho Mail (India)"
    note: str | None = None       # one sentence of advice, when there is something to say
    provider_key: str | None = None   # services/mail/providers.py catalogue key

    def as_dict(self) -> dict:
        return asdict(self)


def _from_provider(p: providers.Provider, *, host: str | None = None, label: str | None = None,
                   note: str | None = None) -> Suggestion:
    return Suggestion(p.connector, host if host is not None else p.imap_host,
                      p.imap_port if p.connector == "imap" else None,
                      label or p.name, note if note is not None else (" ".join(p.steps) or None), p.key)


_ZOHO_PERSONAL = {"zoho.com": "imap.zoho.com", "zohomail.com": "imap.zoho.com",
                  "zohomail.in": "imap.zoho.in", "zoho.in": "imap.zoho.in", "zoho.eu": "imap.zoho.eu"}


class InvalidAddress(ValueError):
    """Not an email address. Message is written for the user."""


def normalise_address(raw: str) -> str:
    """'  Ops@Agency.IN ' → 'ops@agency.in'. Syntax only — no DNS here."""
    try:
        info = validate_email((raw or "").strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise InvalidAddress(f"'{raw}' is not a valid email address.") from exc
    return info.normalized.lower()


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower()


def classify(domain: str, mx_hosts: list[str]) -> Suggestion:
    """The suggestion for a domain whose MX hosts are already known. Pure."""
    domain = domain.lower().strip(".")
    p = providers.by_domain(domain)
    if p is not None:
        if p.key == "zoho":   # a personal @zohomail address: the free host of its data centre
            return _from_provider(p, host=_ZOHO_PERSONAL.get(domain, "imap.zoho.com"), label="Zoho Mail")
        return _from_provider(p)
    hosts = [h.lower().rstrip(".") for h in mx_hosts]
    p = providers.by_mx(hosts)
    if p is not None:
        if p.key == "zoho":
            # A business domain on Zoho is an ORGANISATION account → imappro.<data centre>.
            paid, _free = providers.zoho_hosts_for_mx(hosts)
            region = next((r["label"].split(" (")[0] for r in providers.ZOHO_REGIONS if r["host"] == paid), "")
            return _from_provider(p, host=paid, label=f"Zoho Mail ({region})" if region else "Zoho Mail")
        return _from_provider(p)
    if hosts:
        other = providers.BY_KEY["other"]
        return _from_provider(other, host=None, label="Other mail host",
                              note=f"Your mail is handled by {hosts[0]}. Ask your mail provider for its IMAP server name.")
    return Suggestion(None, label="Unknown",
                      note="We could not look up who handles mail for this domain. Pick your provider below.")


async def mx_hosts(domain: str) -> list[str]:
    """MX hosts, most preferred first; [] when the lookup fails for any reason."""
    try:
        import dns.asyncresolver
        resolver = dns.asyncresolver.Resolver()
        resolver.lifetime = _DNS_TIMEOUT_S
        answer = await resolver.resolve(domain, "MX")
        return [str(r.exchange) for r in sorted(answer, key=lambda r: r.preference)]
    except Exception as exc:  # noqa: BLE001 — a hint is optional; never fail the request over it
        logger.info("[mail.detect] MX lookup failed for %s: %s", domain, exc)
        return []


async def suggest(address: str) -> Suggestion:
    domain = domain_of(normalise_address(address))
    if providers.by_domain(domain) is not None:
        return classify(domain, [])
    return classify(domain, await mx_hosts(domain))
