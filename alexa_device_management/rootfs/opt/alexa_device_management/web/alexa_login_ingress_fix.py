"""Keep the proven Alexa login proxy flow inside the active HA ingress path."""

from __future__ import annotations

import re

from aiohttp import web

import oh_style_login


def _relative_external_url(request: web.Request, path: str) -> str:
    """Return an ingress-relative URL instead of trusting internal proxy hosts."""
    ingress_path = request.headers.get("X-Ingress-Path", "")
    if not re.fullmatch(r"[a-zA-Z0-9/_-]*", ingress_path):
        ingress_path = ""
    normalized_path = path if path.startswith("/") else "/" + path
    return ingress_path.rstrip("/") + normalized_path


def install() -> None:
    """Patch only URL generation; retain the historically working proxy implementation."""
    oh_style_login.external_url = _relative_external_url
