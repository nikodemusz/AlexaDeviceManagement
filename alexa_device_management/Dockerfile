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
