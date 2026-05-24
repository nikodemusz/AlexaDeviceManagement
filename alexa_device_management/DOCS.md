# Alexa Device Management

This add-on lets you manage your Amazon Alexa devices directly from Home Assistant.

## Configuration

Before you can use the add-on, you need to configure your Amazon Alexa API credentials
in the add-on settings:

| Option | Description |
|--------|-------------|
| `amazon_region` | Your Amazon region (`eu`, `na`, `fe`). Default: `eu` |
| `client_id` | OAuth2 Client ID from your Amazon Developer Console |
| `client_secret` | OAuth2 Client Secret from your Amazon Developer Console |
| `refresh_token` | OAuth2 Refresh Token obtained via the Amazon auth flow |

### How to obtain credentials

1. Go to the [Amazon Developer Console](https://developer.amazon.com/).
2. Create a new Security Profile under **Apps & Services → Login with Amazon**.
3. Note the **Client ID** and **Client Secret**.
4. Use the Login with Amazon (LWA) OAuth2 flow to obtain a **Refresh Token** with
   the `alexa::devices:all:geolocation:read` and `alexa::devices:all:address:full:read` scopes.
5. Enter all values in the add-on configuration.

## Web UI

Once the add-on is started, open the **Alexa Devices** panel in the Home Assistant sidebar
to view your registered Alexa devices.

## Custom Integration

The add-on also installs the `alexa_device_management` custom component into:

```
/config/custom_components/alexa_device_management
```

After the first start, restart Home Assistant and add **Alexa Device Management**
from **Settings → Devices & Services**.
