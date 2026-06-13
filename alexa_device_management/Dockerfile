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

# Ensure the plain server entrypoint also exposes the Alexa web login proxy.
# Depending on the Home Assistant app runner, /opt/.../server.py may be started
# directly instead of server_patched_entry.py. In that case the route
# /auth/alexa-openhab/start was missing and the Amazon login frontend returned
# only "404: Not Found" through ingress.
RUN python3 - <<'PY'
from pathlib import Path
import re

server = Path('/opt/alexa_device_management/web/server.py')
s = server.read_text()

if 'import alexa_openhab_login' not in s:
    s = s.replace(
        'import aiohttp\nfrom aiohttp import web\n',
        'import aiohttp\nfrom aiohttp import web\nimport alexa_openhab_login\n',
        1,
    )

replacement = '''async def handle_auth_login(request: web.Request) -> web.Response:
    """Start the Alexa web-session login assistant.

    This project does not use the Alexa Smart Home Skill OAuth flow here. It
    needs the Amazon/Alexa web-login frontend that creates a local Alexa web
    session for reading and managing devices.
    """
    options = load_options()
    alexa_host = options.get("alexa_host", "alexa.amazon.de")
    alexa_host = (alexa_host or "alexa.amazon.de").strip().lower()
    alexa_host = alexa_host.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not re.fullmatch(r"[a-z0-9.-]+", alexa_host):
        alexa_host = "alexa.amazon.de"

    ingress_path = request.headers.get("X-Ingress-Path", "")
    if not re.match(r"^[a-zA-Z0-9/_-]*$", ingress_path):
        ingress_path = ""

    scheme = request.headers.get("X-Forwarded-Proto", "https") or "https"
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "")
    if not host:
        return web.json_response(
            {"error": "Externe Ingress-URL konnte nicht ermittelt werden."},
            status=400,
        )

    auth_url = (
        f"{scheme}://{host}{ingress_path.rstrip('/')}/auth/alexa-openhab/start"
        f"?host={urllib.parse.quote(alexa_host)}"
    )

    return web.json_response({
        "auth_url": auth_url,
        "message": "Alexa-Login-Assistent öffnen.",
    })


async def handle_auth_callback'''

pattern = r'async def handle_auth_login\(request: web\.Request\) -> web\.Response:\n.*?\n\nasync def handle_auth_callback'
s, count = re.subn(pattern, replacement, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Could not patch handle_auth_login in server.py')

route_marker = '    app.router.add_post("/auth/logout", handle_auth_logout)\n'
route_replacement = route_marker + '    alexa_openhab_login.setup_routes(app)\n'
if 'alexa_openhab_login.setup_routes(app)' not in s:
    s = s.replace(route_marker, route_replacement, 1)

server.write_text(s)
PY

# In the browser UI the Amazon login must be started directly from the click
# event. A fetch() preflight followed by window.open() is treated as a delayed
# popup by Safari/iOS and some Home Assistant ingress contexts, so the Amazon
# login tab may never open. The server-side /auth/login endpoint now redirects
# into the local Alexa app-login proxy; the UI only opens that URL directly.
RUN python3 - <<'PY'
from pathlib import Path

index = Path('/opt/alexa_device_management/web/static/index.html')
s = index.read_text()

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

new = '''    function startLogin(event) {
      if (event) {
        event.preventDefault();
      }

      hideLoginFallback();

      const loginUrl = `${INGRESS_PATH}/auth/login`;
      const popup = window.open(loginUrl, "_blank", "noopener");

      if (popup) {
        try { popup.focus(); } catch (_) {}
        showAlert("Der Amazon-Login wurde geöffnet.", "success");
        return;
      }

      showLoginFallback(loginUrl);
      showAlert("Der Browser hat den neuen Tab blockiert. Bitte öffne den Amazon-Login über den Link unten.", "warning");
    }
'''

if old not in s:
    raise SystemExit('Could not patch startLogin() in static/index.html')

s = s.replace(old, new, 1)
s = s.replace(
    'Klicke auf den Button, um den Session-Assistenten zu öffnen.',
    'Klicke auf den Button, um den Amazon-Login in einem neuen Tab zu öffnen.',
)
s = s.replace('Session-Assistent öffnen</a>', 'Amazon-Login öffnen</a>')
index.write_text(s)
PY

# Temporary safety fix: make Alexa device API failures visible instead of
# silently falling back to demo devices. The real next step is replacing the
# current LWA endpoint calls with the Alexa web API client.
RUN python3 - <<'PY'
from pathlib import Path

server = Path('/opt/alexa_device_management/web/server.py')
index = Path('/opt/alexa_device_management/web/static/index.html')

s = server.read_text()
s = s.replace(
"""                if resp.status == 404:\n                    break\n                if resp.status != 200:\n                    text = await resp.text()\n                    endpoint_errors.append(\n                        f\"{endpoint_path} failed ({resp.status}): {text[:120]}\"\n                    )\n                    break\n""",
"""                if resp.status == 404:\n                    text = await resp.text()\n                    endpoint_errors.append(\n                        f\"{endpoint_path} failed (404): endpoint does not exist or token is not accepted for this Alexa API ({text[:120]})\"\n                    )\n                    break\n                if resp.status != 200:\n                    text = await resp.text()\n                    endpoint_errors.append(\n                        f\"{endpoint_path} failed ({resp.status}): {text[:120]}\"\n                    )\n                    break\n""",
1,
)
s = s.replace(
"""        return web.json_response(\n            {\"devices\": get_demo_devices(), \"auth_error\": str(exc)},\n        )\n""",
"""        return web.json_response(\n            {\"devices\": [], \"auth_error\": str(exc), \"demo\": False},\n        )\n""",
1,
)
s = s.replace(
"""            return web.json_response(\n                {\"devices\": get_demo_devices(), \"api_error\": str(exc)},\n            )\n""",
"""            return web.json_response(\n                {\"devices\": [], \"api_error\": str(exc), \"demo\": False},\n            )\n""",
1,
)
server.write_text(s)

i = index.read_text()
i = i.replace(
"""        const data = await resp.json();\n        renderDevices(data.devices || []);\n        updateDeviceInfo(data.devices || [], data.demo === true);\n""",
"""        const data = await resp.json();\n        const devices = data.devices || [];\n        const errorMessage = data.api_error || data.auth_error || data.warning || \"\";\n        renderDevices(devices);\n        updateDeviceInfo(devices, data.demo === true, errorMessage);\n        if (errorMessage) {\n          showAlert(errorMessage, \"error\");\n        }\n""",
1,
)
index.write_text(i)
PY

LABEL \
    io.hass.name="Alexa Device Management" \
    io.hass.description="Standalone web UI for managing Amazon Alexa devices" \
    io.hass.type="app" \
    org.opencontainers.image.title="Home Assistant App: Alexa Device Management" \
    org.opencontainers.image.description="Standalone web UI for managing Amazon Alexa smart home devices – a replacement for Amazon's removed bulk-management interface" \
    org.opencontainers.image.source="https://github.com/nikodemusz/AlexaDeviceManagement"
