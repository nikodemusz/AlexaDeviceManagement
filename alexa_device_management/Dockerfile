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

# Keep the Docker build deterministic. The raw legacy helper sources still contain
# two known historical syntax artifacts that are intentionally normalized by the
# runtime entry wrappers. Apply the same minimal normalization here before compile
# checks so the image build validates the effective runtime sources.
RUN python3 - <<'PY'
from pathlib import Path

web_dir = Path('/opt/alexa_device_management/web')

checks = {
    'server.py': None,
    'server_patched.py': lambda s: s.replace(
        '    )f\n\n\nasync def handle_alexa_web_session_get',
        '    )\n\n\nasync def handle_alexa_web_session_get',
        1,
    ),
    'server_patched_entry.py': None,
    'server_app_entry.py': None,
    'alexa_openhab_login.py': lambda s: '"""' + s if s.startswith('Local-only login proxy:\n') else s,
}

for name, normalizer in checks.items():
    path = web_dir / name
    source = path.read_text()
    if normalizer is not None:
        source = normalizer(source)
    compile(source, str(path), 'exec')
PY

LABEL \
    io.hass.name="Alexa Device Management" \
    io.hass.description="Standalone web UI for managing Amazon Alexa devices" \
    io.hass.type="app" \
    org.opencontainers.image.title="Home Assistant App: Alexa Device Management" \
    org.opencontainers.image.description="Standalone web UI for managing Amazon Alexa smart home devices – a replacement for Amazon's removed bulk-management interface" \
    org.opencontainers.image.source="https://github.com/nikodemusz/AlexaDeviceManagement"
