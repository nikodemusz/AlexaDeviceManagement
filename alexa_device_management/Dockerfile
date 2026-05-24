# https://developers.home-assistant.io/docs/apps/configuration#app-dockerfile
ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

COPY custom_components /opt/alexa_device_management/custom_components
COPY rootfs /

LABEL \
    io.hass.name="Alexa Device Management Installer" \
    io.hass.description="Installs the Alexa Device Management custom integration" \
    io.hass.type="app" \
    org.opencontainers.image.title="Home Assistant App: Alexa Device Management Installer" \
    org.opencontainers.image.description="Installer app for Alexa Device Management custom integration" \
    org.opencontainers.image.source="https://github.com/nikodemusz/AlexaDeviceManagement"
