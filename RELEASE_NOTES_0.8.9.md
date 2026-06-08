# Release Notes 0.8.9

- Renamed the active Alexa login route from the misleading OpenHAB-based path to `/auth/alexa-app/...`.
- Added a dedicated Alexa App entrypoint used by the add-on start script.
- Added host-aware forwarding for Amazon login requests so forwarded paths can include the target host, for example `/FORWARD/www.amazon.de/...`.
- Kept compatibility with the existing login source while removing the OpenHAB wording from the active runtime route.

Manual add-on version update still required in `alexa_device_management/config.yaml` because the GitHub connector blocked writing that file payload.
