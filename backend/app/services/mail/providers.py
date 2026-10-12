"""Every mail provider a FareQube user is likely to have, and how to connect it.

One catalogue drives three things: the brand tiles on the connect screen, MX-based detection
(services/mail/detect.py) and the help text next to the password box. Settings were checked
against each provider's own documentation in October 2026:

  * Google Workspace / Gmail ......... Gmail API with Google sign-in (OAuth); or, when this server
                                       has no Google sign-in app, imap.gmail.com:993 with a Google
                                       app password (needs 2-Step Verification on the account).
  * Microsoft 365 / Outlook.com ...... Microsoft Graph with Microsoft sign-in (OAuth). Exchange
                                       Online turned basic-auth IMAP off, and "Microsoft 365 from
                                       GoDaddy" IS Exchange Online — so it signs in here too.
  * GoDaddy Professional Email ....... imap.secureserver.net:993 (Titan-powered)
  * Zoho Mail ........................ imap(pro).zoho.<dc>: `imappro` for paid/organisation plans,
                                       `imap` for free/personal, one host per data centre. The
                                       connector tries the sibling host if the first refuses.
  * Titan, Yahoo, iCloud, AOL, Rediffmail Pro, Hostinger, Namecheap Private Email, Yandex,
    Fastmail, cPanel/Plesk hosts ..... IMAP with an app password where the provider has them.

A provider not listed still connects through "Other (IMAP)": any server reachable on 993/143.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    connector: str                       # gmail | microsoft | imap
    blurb: str
    imap_host: str | None = None
    imap_port: int = 993
    # Hosts tried, in order, when the first refuses the login (Zoho paid vs free).
    fallback_hosts: tuple[str, ...] = ()
    password_label: str = "App password"
    # Steps shown beside the password box; each is one short instruction.
    steps: tuple[str, ...] = ()
    help_url: str | None = None
    # Address domains that identify this provider without DNS.
    domains: tuple[str, ...] = ()
    # Substrings of MX hosts that identify it.
    mx: tuple[str, ...] = ()
    popular: bool = False                # shown as a big tile; the rest under "More providers"
    regions: tuple[dict, ...] = field(default=())   # Zoho: choose a data centre
    # A sign-in provider's IMAP route, used when this server has no sign-in app for it:
    # {host, port, password_label, steps, help_url}. Google has one (app passwords); Microsoft
    # does not — Exchange Online and Outlook.com turned password IMAP off.
    imap_alternative: dict | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["fallback_hosts"] = list(self.fallback_hosts)
        d["steps"] = list(self.steps)
        d["domains"] = list(self.domains)
        d["mx"] = list(self.mx)
        d["regions"] = list(self.regions)
        return d


def _zoho_region(code: str, label: str, domain: str) -> dict:
    return {"code": code, "label": label, "host": f"imappro.{domain}", "free_host": f"imap.{domain}"}


ZOHO_REGIONS = (
    _zoho_region("in", "India (zoho.in)", "zoho.in"),
    _zoho_region("com", "United States (zoho.com)", "zoho.com"),
    _zoho_region("eu", "Europe (zoho.eu)", "zoho.eu"),
    _zoho_region("au", "Australia (zoho.com.au)", "zoho.com.au"),
    _zoho_region("jp", "Japan (zoho.jp)", "zoho.jp"),
    _zoho_region("ca", "Canada (zohocloud.ca)", "zohocloud.ca"),
)

_APP_PASSWORD_GENERIC = ("Use the mailbox password, or an app password if your provider has two-step sign-in on.",)

PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "google", "Google", "gmail", "Gmail and Google Workspace",
        domains=("gmail.com", "googlemail.com"), mx=("google.com", "googlemail.com"), popular=True,
        steps=("Sign in with the Google account that receives your deals and statements.",
               "Allow FareQube to read your email. It cannot send, delete or change anything."),
        help_url="https://myaccount.google.com/permissions",
        imap_alternative={
            "host": "imap.gmail.com", "port": 993, "password_label": "Google app password",
            "steps": [
                "Turn on 2-Step Verification for this Google account (Google Account → Security).",
                "Open App passwords, type FareQube as the name and press Create.",
                "Paste the 16-letter password Google shows into the box below.",
                "Google Workspace: your admin must allow IMAP and app passwords for your account.",
            ],
            "help_url": "https://myaccount.google.com/apppasswords",
        },
    ),
    Provider(
        "microsoft", "Microsoft", "microsoft", "Microsoft 365, Outlook.com, Hotmail — including Microsoft 365 from GoDaddy",
        domains=("outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.in", "hotmail.co.uk"),
        mx=("mail.protection.outlook.com", "outlook.com"), popular=True,
        steps=("Sign in with the Microsoft account that receives your deals and statements.",
               "Allow FareQube to read your email. Some organisations need their IT admin to approve this first."),
        help_url="https://myaccount.microsoft.com/",
    ),
    Provider(
        "godaddy", "GoDaddy", "imap", "Professional Email (Workspace / Titan-powered)",
        imap_host="imap.secureserver.net", mx=("secureserver.net",), popular=True,
        password_label="Email password",
        steps=("Use your GoDaddy email address and its email password.",
               "If your GoDaddy plan is Microsoft 365, choose Microsoft instead."),
        help_url="https://www.godaddy.com/help/use-imap-settings-to-add-my-professional-email-to-a-client-32204",
    ),
    Provider(
        "zoho", "Zoho Mail", "imap", "Zoho Mail — business and personal",
        imap_host="imappro.zoho.in", fallback_hosts=("imap.zoho.in",),
        domains=("zoho.com", "zohomail.com", "zohomail.in", "zoho.in", "zoho.eu"),
        mx=("zoho.in", "zoho.eu", "zoho.com.au", "zoho.jp", "zohocloud.ca", "zoho.com"), popular=True,
        steps=("In Zoho Mail: Settings → Mail Accounts → IMAP → tick IMAP Access.",
               "In Zoho Accounts: Security → App Passwords → generate one for FareQube, and paste it here."),
        help_url="https://accounts.zoho.in/home#security/app_password",
        regions=ZOHO_REGIONS,
    ),
    Provider(
        "titan", "Titan", "imap", "Titan Mail (Hostinger, Neo and other hosts)",
        imap_host="imap.titan.email", mx=("titan.email",), password_label="Email password",
        steps=_APP_PASSWORD_GENERIC,
    ),
    Provider(
        "yahoo", "Yahoo Mail", "imap", "Yahoo and Rocketmail",
        imap_host="imap.mail.yahoo.com", domains=("yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com", "rocketmail.com"),
        mx=("yahoodns.net",),
        steps=("Yahoo account → Account security → Generate app password → name it FareQube.",
               "Paste the 16-letter app password here (not your Yahoo password)."),
        help_url="https://login.yahoo.com/account/security",
    ),
    Provider(
        "icloud", "iCloud Mail", "imap", "iCloud, me.com, mac.com",
        imap_host="imap.mail.me.com", domains=("icloud.com", "me.com", "mac.com"), mx=("icloud.com", "mail.me.com"),
        steps=("appleid.apple.com → Sign-In and Security → App-Specific Passwords → generate one.",
               "Username is the part of your iCloud address before the @."),
        help_url="https://appleid.apple.com/account/manage",
    ),
    Provider(
        "rediff", "Rediffmail Pro", "imap", "Rediffmail Pro business mail",
        imap_host="imap.rediffmailpro.com", domains=("rediffmail.com",), mx=("rediffmailpro.com", "rediffmail.com"),
        password_label="Email password", steps=("Use your full email address and its password.",),
    ),
    Provider(
        "hostinger", "Hostinger", "imap", "Hostinger Email",
        imap_host="imap.hostinger.com", mx=("hostinger",), password_label="Email password",
        steps=_APP_PASSWORD_GENERIC,
    ),
    Provider(
        "namecheap", "Namecheap", "imap", "Namecheap Private Email",
        imap_host="mail.privateemail.com", mx=("privateemail.com",),
        steps=("Use your mailbox password, or an application password created in Private Email settings.",),
    ),
    Provider(
        "aol", "AOL Mail", "imap", "AOL",
        imap_host="imap.aol.com", domains=("aol.com",), mx=("aol.com",),
        steps=("AOL account security → Generate app password, then paste it here.",),
    ),
    Provider(
        "yandex", "Yandex Mail", "imap", "Yandex 360",
        imap_host="imap.yandex.com", domains=("yandex.com", "yandex.ru"), mx=("yandex",),
        steps=("Yandex ID → Security → App passwords → Mail, then paste it here.",),
    ),
    Provider(
        "fastmail", "Fastmail", "imap", "Fastmail",
        imap_host="imap.fastmail.com", domains=("fastmail.com",), mx=("messagingengine.com",),
        steps=("Fastmail Settings → Privacy & Security → App passwords → IMAP.",),
    ),
    Provider(
        "other", "Other (IMAP)", "imap", "Any other mail host — cPanel, Plesk, your web host",
        password_label="Password or app password", popular=True,
        steps=("Ask your mail host for its IMAP server name (often mail.yourdomain.com).",
               "Use port 993 (SSL) unless your host says 143 (STARTTLS)."),
    ),
)

BY_KEY: dict[str, Provider] = {p.key: p for p in PROVIDERS}


def by_domain(domain: str) -> Provider | None:
    domain = domain.lower()
    return next((p for p in PROVIDERS if domain in p.domains), None)


def by_mx(hosts: list[str]) -> Provider | None:
    hosts = [h.lower().rstrip(".") for h in hosts]
    # Most specific needles first, so "zoho.in" beats a bare "zoho.com" match.
    ranked = sorted(((needle, p) for p in PROVIDERS for needle in p.mx), key=lambda t: -len(t[0]))
    for needle, p in ranked:
        if any(needle in h for h in hosts):
            return p
    return None


def zoho_hosts_for_mx(hosts: list[str]) -> tuple[str, tuple[str, ...]]:
    """(paid host, (free host,)) for the Zoho data centre the MX points at."""
    joined = " ".join(h.lower() for h in hosts)
    for domain in ("zoho.in", "zoho.eu", "zoho.com.au", "zoho.jp", "zohocloud.ca", "zoho.com"):
        if domain in joined:
            return f"imappro.{domain}", (f"imap.{domain}",)
    return "imappro.zoho.com", ("imap.zoho.com",)


def fallbacks_for(host: str) -> tuple[str, ...]:
    """Sibling hosts worth one retry when `host` refuses the login. Zoho only, today."""
    host = host.lower()
    if re.match(r"^imappro\.(zoho|zohocloud)\.", host):
        return ("imap." + host[len("imappro."):],)
    if re.match(r"^imap\.(zoho|zohocloud)\.", host):
        return ("imappro." + host[len("imap."):],)
    return ()


def key_for_host(host: str | None) -> str | None:
    """The provider an IMAP host belongs to — for mailboxes connected before the provider
    tile was recorded (settings.provider_key)."""
    if not host:
        return None
    host = host.lower()
    if re.match(r"^imap(pro)?\.(zoho|zohocloud)\.", host):
        return "zoho"
    for p in PROVIDERS:
        if p.imap_host and p.imap_host == host:
            return p.key
        if p.imap_alternative and p.imap_alternative["host"] == host:
            return p.key
    return None
