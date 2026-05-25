# Alexa Device Management

Standalone web UI to manage your Amazon Alexa smart home devices directly from
Home Assistant OS. This is **not** a Home Assistant integration – it is a
standalone app that runs its own web server and is accessible via the HA sidebar.

## Why?

Amazon removed the web interface that allowed bulk management of Alexa devices.
The Alexa App only lets you manage one device at a time which is tedious.
This app provides a web-based alternative for viewing, editing, and bulk-managing
your Alexa devices.

## Configuration

Configure your Amazon credentials in the add-on settings:

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
4. Use the Login with Amazon (LWA) OAuth2 flow to obtain a **Refresh Token**.
5. Enter all values in the add-on configuration.

## Web UI

After starting the add-on, open **Alexa Devices** from the Home Assistant sidebar.
The UI displays all your registered Alexa devices and allows you to manage them.
