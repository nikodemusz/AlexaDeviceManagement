"""Constants for Alexa Device Management."""

DOMAIN = "alexa_device_management"
TITLE = "Alexa Device Management"
PANEL_NAME = "alexa-device-management"
PANEL_URL_PATH = "alexa-device-management"
PANEL_ICON = "mdi:amazon-alexa"

# Manager / connection states
STATE_DISCONNECTED = "disconnected"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"

# Events
EVENT_CONNECTION_STATE_CHANGED = f"{DOMAIN}_connection_state_changed"
EVENT_DEVICES_UPDATED = f"{DOMAIN}_devices_updated"

# WebSocket command prefix
WS_PREFIX = DOMAIN
