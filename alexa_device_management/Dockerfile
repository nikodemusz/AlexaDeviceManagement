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

# Validate the runtime sources at build time.
RUN python3 -m py_compile \
    /opt/alexa_device_management/web/server_clean.py \
    /opt/alexa_device_management/web/server_extended.py \
    /opt/alexa_device_management/web/config_store.py \
    /opt/alexa_device_management/web/alexa_cache_service.py \
    /opt/alexa_device_management/web/yaml_generator.py \
    /opt/alexa_device_management/web/ha_export.py \
    /opt/alexa_device_management/web/ha_export_overrides.py \
    /opt/alexa_device_management/web/ha_control.py \
    /opt/alexa_device_management/web/oh_style_login.py

LABEL \
    io.hass.name="Alexa Device Management" \
    io.hass.description="Standalone web UI for managing Amazon Alexa devices and configuring Home Assistant exports" \
    io.hass.type="app" \
    org.opencontainers.image.title="Home Assistant App: Alexa Device Management" \
    org.opencontainers.image.description="Web UI for Alexa device management and Home Assistant to Alexa configuration" \
    org.opencontainers.image.source="https://github.com/nikodemusz/AlexaDeviceManagement"
