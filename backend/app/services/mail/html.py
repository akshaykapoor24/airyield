"""Making a supplier's HTML mail safe to show (architecture/10 §10.5).

Mail is written by outsiders, so the HTML is treated as hostile:
  * nh3 (an allowlist sanitiser) removes scripts, event handlers, forms, iframes, embeds,
    `javascript:` links and everything else that can run;
  * REMOTE IMAGES ARE DROPPED. A tracking pixel would tell the sender which FareQube user
    opened the mail, when, and from which IP. Only images embedded in the mail itself
    (cid:, replaced here by data: URIs) are shown;
  * links open in a new tab with rel="noopener noreferrer";
  * the frontend still renders the result inside a sandboxed iframe with no scripts — the
    sanitiser is one wall, the sandbox is the second.
"""
from __future__ import annotations

import base64
import re

import nh3

_MAX_INLINE_IMAGE = 3 * 1024 * 1024
# Quoted, unquoted (src=cid:x — common in Outlook mail) and CSS url(cid:x) references.
_CID_RE = re.compile(r"""(["'(=]\s*)cid:(?:<([^<>"']+)>|([^"'<>)\s]+))""", re.IGNORECASE)

_ALLOWED_TAGS = set(nh3.ALLOWED_TAGS) | {
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col",
    "font", "center", "span", "div", "img", "hr", "br", "u", "s", "small", "big",
}
_ALLOWED_ATTRS = {k: set(v) for k, v in nh3.ALLOWED_ATTRIBUTES.items()}
for tag in ("table", "td", "th", "tr", "col", "colgroup", "thead", "tbody"):
    _ALLOWED_ATTRS.setdefault(tag, set()).update(
        {"align", "valign", "width", "height", "bgcolor", "colspan", "rowspan", "cellpadding", "cellspacing", "border", "style"})
for tag in ("div", "span", "p", "font", "center", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "b", "i", "strong", "em", "u"):
    _ALLOWED_ATTRS.setdefault(tag, set()).update({"style", "align", "color", "size", "face"})
_ALLOWED_ATTRS.setdefault("img", set()).update({"src", "alt", "width", "height", "style"})
_ALLOWED_ATTRS.setdefault("a", set()).update({"href", "title"})
_ALLOWED_ATTRS["a"].discard("rel")    # nh3 sets rel itself via link_rel


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    if tag == "img" and attr == "src":
        return value if value.lower().startswith("data:image/") else None    # no remote images
    if attr == "href" and value.lower().startswith("data:"):
        return None
    if attr == "style" and ("url(" in value.lower() or "expression" in value.lower()):
        return None        # CSS can load remote images too
    return value


def inline_images(html: str, images: dict[str, tuple[str, bytes]]) -> str:
    """Replace cid:<id> references with data: URIs for the message's own inline images."""
    def repl(m: re.Match) -> str:
        found = images.get(m.group(2) or m.group(3))
        if not found or len(found[1]) > _MAX_INLINE_IMAGE:
            return m.group(0)
        ctype, data = found
        return f"{m.group(1)}data:{ctype};base64,{base64.b64encode(data).decode()}"
    return _CID_RE.sub(repl, html)


def sanitise(html: str, images: dict[str, tuple[str, bytes]] | None = None) -> str:
    if images:
        html = inline_images(html, images)
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        attribute_filter=_attribute_filter,
        url_schemes={"http", "https", "mailto", "tel", "data"},
        link_rel="noopener noreferrer nofollow",
        set_tag_attribute_values={"a": {"target": "_blank"}},
        strip_comments=True,
    )
