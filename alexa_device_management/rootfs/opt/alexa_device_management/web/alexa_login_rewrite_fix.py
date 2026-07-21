"""Fix absolute Amazon URL rewriting in the proxied login HTML."""

from __future__ import annotations

import re

import oh_style_login


def rewrite_html(request, text: str, current_host: str = "www.amazon.com") -> str:
    """Rewrite Amazon links through the local ingress proxy.

    The original implementation expected four regex groups although its pattern
    only produced three. Capturing the URL scheme explicitly keeps the existing
    reconstruction logic intact and prevents every proxied HTML response from
    failing with ``ValueError``.
    """
    result = text

    def repl_absolute(match: re.Match[str]) -> str:
        quote, scheme, host, path = match.groups()
        target = f"{scheme}://{host}{path}"
        return f"={quote}{oh_style_login.proxied_url(request, target)}"

    result = re.sub(
        r"=([\"'])(https?)://([a-z0-9.-]+)((?:/|&#x2F;)[^\"']*)",
        repl_absolute,
        result,
        flags=re.I,
    )

    local_root = oh_style_login.external_url(
        request, f"/auth/alexa-app/proxy/{current_host}/"
    )
    result = re.sub(
        r"=([\"'])/(?!/)",
        lambda match: f"={match.group(1)}{local_root}",
        result,
    )
    result = re.sub(
        r"=([\"'])&#x2F;",
        lambda match: f"={match.group(1)}{local_root}",
        result,
    )

    for host in oh_style_login.AMAZON_PROXY_HOSTS:
        root = oh_style_login.external_url(
            request, f"/auth/alexa-app/proxy/{host}/"
        )
        result = result.replace(f"https://{host}/", root)
        result = result.replace(f"http://{host}/", root)

    return result


def install() -> None:
    """Replace the faulty runtime rewriter used by the login proxy."""
    oh_style_login.rewrite_html = rewrite_html
