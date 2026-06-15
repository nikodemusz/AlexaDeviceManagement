# https://developers.home-assistant.io/docs/apps/configuration#app-dockerfile
ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

# Install Python and pip
RUN apk add --no-cache python3 py3-pip

# Install Python dependencies for the web server
COPY rootfs/opt/alexa_device_management/web/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY rootfs /

# Release safety fixes for 0.8.15:
# - keep the Alexa web/app login flow independent from the removed legacy LWA
#   client_id/client_secret/refresh_token flow
# - make the Alexa web-login helper syntactically valid if the source file is
#   missing the opening module docstring marker
# - install the Alexa app-login routes without relying on brittle exact HTML/JS
#   string patches that can break the Home Assistant add-on build
# - keep the old /auth/alexa-openhab path as a compatibility alias
RUN python3 - <<'PY'
from pathlib import Path
import re

web_dir = Path('/opt/alexa_device_management/web')
server = web_dir / 'server.py'
patched_server = web_dir / 'server_patched.py'
login_helper = web_dir / 'alexa_openhab_login.py'
index = web_dir / 'static' / 'index.html'

# Fix accidentally broken module docstring in alexa_openhab_login.py.
helper_text = login_helper.read_text()
if helper_text.startswith('Local-only login proxy:'):
    login_helper.write_text('"""' + helper_text)
    helper_text = login_helper.read_text()

# Prefer the neutral /auth/alexa-app route name, but keep the older
# /auth/alexa-openhab route working so already-open login redirects do not die.
helper_text = helper_text.replace('/auth/alexa-openhab', '/auth/alexa-app')
helper_text = helper_text.replace(
    'def setup_routes(app: web.Application) -> None:\n'
    '    app.router.add_route("*", "/auth/alexa-app/{tail:.*}", proxy)\n'
    '    app.on_cleanup.append(cleanup)\n',
    'def setup_routes(app: web.Application) -> None:\n'
    '    app.router.add_route("*", "/auth/alexa-app/{tail:.*}", proxy)\n'
    '    app.router.add_route("*", "/auth/alexa-openhab/{tail:.*}", proxy)\n'
    '    app.on_cleanup.append(cleanup)\n',
)
login_helper.write_text(helper_text)

# Patch server.py idempotently. The shipped source still contains the old LWA
# OAuth handler; for this add-on we need the local Alexa web-session helper.
s = server.read_text()
if 'import alexa_openhab_login' not in s:
    s = s.replace(
        'import aiohttp\nfrom aiohttp import web\n',
        'import aiohttp\nfrom aiohttp import web\nimport alexa_openhab_login\n',
        1,
    )

replacement = '''async def handle_auth_login(request: web.Request) -> web.StreamResponse:
    """Start the local Alexa app-login proxy."""
    options = load_options()
    alexa_host = options.get("alexa_host", "alexa.amazon.de")
    alexa_host = (alexa_host or "alexa.amazon.de").strip().lower()
    alexa_host = alexa_host.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not re.fullmatch(r"[a-z0-9.-]+", alexa_host):
        alexa_host = "alexa.amazon.de"

    ingress_path = request.headers.get("X-Ingress-Path", "")
    if not re.match(r"^[a-zA-Z0-9/_-]*$", ingress_path):
        ingress_path = ""

    return web.HTTPFound(
        f"{ingress_path.rstrip('/')}/auth/alexa-app/start"
        f"?host={urllib.parse.quote(alexa_host)}"
    )


async def handle_auth_callback'''

pattern = r'async def handle_auth_login\(request: web\.Request\) -> web\.(?:Response|StreamResponse):\n.*?\n\nasync def handle_auth_callback'
s, count = re.subn(pattern, replacement, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Could not patch handle_auth_login in server.py')

route_marker = '    app.router.add_post("/auth/logout", handle_auth_logout)\n'
if 'alexa_openhab_login.setup_routes(app)' not in s:
    s = s.replace(route_marker, route_marker + '    alexa_openhab_login.setup_routes(app)\n', 1)
server.write_text(s)

# Make the patched Alexa-web path the single source of truth for connection
# status and device discovery. Otherwise a leftover legacy LWA/API-key setup
# can make the UI think it is already connected and hide the Alexa web login.
ps = patched_server.read_text()
ps = ps.replace(
    '    return await _original_handle_api_devices(request)\n',
    '    return web.json_response({\n'
    '        "devices": [],\n'
    '        "demo": False,\n'
    '        "source": "not_connected",\n'
    '        "warning": "Alexa-Web-Session fehlt. Bitte Alexa-Web-Login verbinden.",\n'
    '    })\n',
    1,
)
ps = ps.replace(
    '    data["configured"] = bool(data.get("configured") or data["alexa_web_configured"])\n',
    '    data["legacy_lwa_configured"] = bool(data.get("configured"))\n'
    '    data["configured"] = data["alexa_web_configured"]\n',
    1,
)
ps = ps.replace(
    '    else:\n'
    '        data["token_source"] = data.get("token_source") or "not_connected"\n'
    '    return web.json_response(data)\n',
    '    else:\n'
    '        legacy_configured = bool(data.get("configured"))\n'
    '        data["configured"] = False\n'
    '        data["authenticated"] = False\n'
    '        data["legacy_lwa_configured"] = legacy_configured\n'
    '        data["token_source"] = "not_connected"\n'
    '        data["amazon_user"] = {}\n'
    '        if legacy_configured:\n'
    '            data["auth_message"] = "Alte LWA/API-Key-Konfiguration ignoriert. Bitte Alexa-Web-Login neu verbinden."\n'
    '    return web.json_response(data)\n',
    1,
)
patched_server.write_text(ps)

# Make UI login direct and idempotent. If the repository source already has the
# fixed function, leave it alone instead of aborting the Docker build.
i = index.read_text()
old = '''    async function startLogin() {
      try {
        hideLoginFallback();
        const resp = await fetch(`${INGRESS_PATH}/auth/login`);
        if (!resp.ok) {
          const data = await resp.json();
          showAlert(data.error || "Login-Fehler", "error");
          return;
        }
        const data = await resp.json();
        const popup = window.open(data.auth_url, "_blank");
        const popupBlocked = !popup;
        if (!popupBlocked) {
          try { popup.focus(); } catch (_) {}
          showAlert("Der Alexa-Web-Session-Assistent wurde geöffnet.", "success");
          return;
        }
        showLoginFallback(data.auth_url);
        showAlert("Der Browser hat den neuen Tab blockiert. Bitte öffne den Assistenten über den Link unten.", "warning");
      } catch (err) {
        showAlert("Fehler beim Starten des Assistenten: " + err.message, "error");
      }
    }
'''
new = '''    function startLogin() {
      const loginUrl = `${INGRESS_PATH}/auth/login`;
      window.location.assign(loginUrl);
    }
'''
if old in i:
    i = i.replace(old, new, 1)

i = i.replace(
    'Klicke auf den Button, um den Session-Assistenten zu öffnen.',
    'Klicke auf den Button, um den Amazon-Login direkt zu starten.',
)
i = i.replace('Session-Assistent öffnen</a>', 'Amazon-Login öffnen</a>')
index.write_text(i)

# Keep API errors visible instead of silently falling back to demo data. All
# replacements are optional so this block remains safe across repeated builds.
s = server.read_text()
s = s.replace(
'''                if resp.status == 404:\n                    break\n                if resp.status != 200:\n                    text = await resp.text()\n                    endpoint_errors.append(\n                        f"{endpoint_path} failed ({resp.status}): {text[:120]}"\n                    )\n                    break\n''',
'''                if resp.status == 404:\n                    text = await resp.text()\n                    endpoint_errors.append(\n                        f"{endpoint_path} failed (404): endpoint does not exist or token is not accepted for this Alexa API ({text[:120]})"\n                    )\n                    break\n                if resp.status != 200:\n                    text = await resp.text()\n                    endpoint_errors.append(\n                        f"{endpoint_path} failed ({resp.status}): {text[:120]}"\n                    )\n                    break\n''',
1,
)
s = s.replace(
'''        return web.json_response(\n            {"devices": get_demo_devices(), "auth_error": str(exc)},\n        )\n''',
'''        return web.json_response(\n            {"devices": [], "auth_error": str(exc), "demo": False},\n        )\n''',
1,
)
s = s.replace(
'''            return web.json_response(\n                {"devices": get_demo_devices(), "api_error": str(exc)},\n            )\n''',
'''            return web.json_response(\n                {"devices": [], "api_error": str(exc), "demo": False},\n            )\n''',
1,
)
server.write_text(s)

# Fail early during image build if the helper is still syntactically broken.
compile(login_helper.read_text(), str(login_helper), 'exec')
compile(patched_server.read_text(), str(patched_server), 'exec')
PY

LABEL \
    io.hass.name="Alexa Device Management" \
    io.hass.description="Standalone web UI for managing Amazon Alexa devices" \
    io.hass.type="app" \
    org.opencontainers.image.title="Home Assistant App: Alexa Device Management" \
    org.opencontainers.image.description="Standalone web UI for managing Amazon Alexa smart home devices – a replacement for Amazon's removed bulk-management interface" \
    org.opencontainers.image.source="https://github.com/nikodemusz/AlexaDeviceManagement"
