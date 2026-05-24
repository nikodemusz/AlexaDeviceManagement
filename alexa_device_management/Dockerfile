# https://developers.home-assistant.io/docs/apps/configuration#app-dockerfile
ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

# Install Python and pip
RUN apk add --no-cache python3 py3-pip

# Install Python dependencies for the web server
COPY rootfs/opt/alexa_device_management/web/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY custom_components /opt/alexa_device_management/custom_components
COPY rootfs /

LABEL \
    io.hass.name="Alexa Device Management" \
    io.hass.description="Manage your Amazon Alexa devices from Home Assistant" \
    io.hass.type="app" \
    org.opencontainers.image.title="Home Assistant App: Alexa Device Management" \
    org.opencontainers.image.description="Manage your Amazon Alexa devices from Home Assistant" \
    org.opencontainers.image.source="https://github.com/nikodemusz/AlexaDeviceManagement"
