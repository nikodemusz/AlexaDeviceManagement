"""Runtime patch for a clean Alexa login result page.

The login flow itself remains in oh_style_login.py. This module only replaces the
final result page and maplanding redirect handler so successful logins return to
the Home Assistant Ingress URL instead of the domain root.
"""

from __future__ import annotations

import html
import json

from aiohttp import web


def install(login_module) -> None:
    def result_page(request: web.Request, success: bool, message: str) -> web.Response:
        app_url = login_module.external_url(request, "/")
        title = "Alexa verbunden" if success else "Alexa-Login fehlgeschlagen"
        icon = "✅" if success else "❌"
        detail = html.escape(message)

        redirect_meta = ""
        redirect_script = ""
        redirect_note = ""
        if success:
            redirect_meta = f'<meta http-equiv="refresh" content="2;url={html.escape(app_url)}">'
            redirect_script = (
                "<script>setTimeout(function(){ window.location.href = "
                + json.dumps(app_url)
                + "; }, 1200);</script>"
            )
            redirect_note = "<p class='muted'>Du wirst automatisch zur App zurückgeleitet.</p>"

        body = f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {redirect_meta}
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #f5f6fa; color: #1f2933; }}
    main {{ max-width: 720px; margin: 9vh auto; background: white; border-radius: 16px; padding: 32px; box-shadow: 0 10px 35px rgba(0,0,0,.12); }}
    h1 {{ margin-top: 0; font-size: 1.7rem; }}
    .icon {{ font-size: 2.4rem; margin-bottom: 12px; }}
    .muted {{ color: #607080; }}
    .actions {{ margin-top: 24px; display: flex; gap: 12px; flex-wrap: wrap; }}
    a.button {{ display: inline-block; background: #00a8e8; color: white; text-decoration: none; padding: 11px 16px; border-radius: 8px; font-weight: 700; }}
  </style>
</head>
<body>
  <main>
    <div class="icon">{icon}</div>
    <h1>{html.escape(title)}</h1>
    <p>{detail}</p>
    {redirect_note}
    <div class="actions">
      <a class="button" href="{html.escape(app_url)}">Zur Alexa Device Management App</a>
    </div>
  </main>
  {redirect_script}
</body>
</html>"""
        return web.Response(text=body, content_type="text/html")

    async def handle_redirect(request: web.Request, session, location: str, state: dict) -> web.StreamResponse:
        if "/ap/maplanding" in location:
            token = login_module.extract_access_token(location)
            if not token:
                return result_page(request, False, "Access token not found in maplanding redirect")
            try:
                data = await login_module.register_app(session, state, token)
                return result_page(request, True, f"Alexa-Session gespeichert für {data.get('host', 'Alexa')}.")
            except Exception as exc:
                return result_page(request, False, str(exc))
        raise web.HTTPFound(login_module.proxied_url(request, location))

    login_module.handle_redirect = handle_redirect
