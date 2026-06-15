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

# Keep the Docker build deterministic. Runtime fixes belong in the checked-in
# Python sources, not in fragile inline source-rewrite scripts inside this file.
RUN python3 - <<'PY'
from pathlib import Path

web_dir = Path('/opt/alexa_device_management/web')
for path in (
    web_dir / 'server.py',
    web_dir / 'server_patched.py',
    web_dir / 'server_patched_entry.py',
    web_dir / 'server_app_entry.py',
    web_dir / 'alexa_openhab_login.py',
):
    compile(path.read_text(), str(path), 'exec')
PY

LABEL \
    io.hass.name="Alexa Device Management" \
    io.hass.description="Standalone web UI for managing Amazon Alexa devices" \
    io.hass.type="app" \
    org.opencontainers.image.title="Home Assistant App: Alexa Device Management" \
    org.opencontainers.image.description="Standalone web UI for managing Amazon Alexa smart home devices – a replacement for Amazon's removed bulk-management interface" \
    org.opencontainers.image.source="https://github.com/nikodemusz/AlexaDeviceManagement"
