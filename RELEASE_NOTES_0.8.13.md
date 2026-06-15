# Release Notes 0.8.13

- Fixed duplicate Alexa-Web-Login route registration during the patched Home Assistant app startup.
- Prevented `RuntimeError: Added route will never be executed, method * is already registered` when both `server.py` and `server_patched.py` register the Alexa web login proxy.
- Kept the `/auth/alexa-openhab/...` login proxy available for Home Assistant Ingress while making route setup safe across direct and patched server entrypoints.
- Includes the previous startup-path fixes from 0.8.11 and 0.8.12 so the HA OS update process can pick up a single current add-on version.

Home Assistant should offer this update automatically through the add-on update process because `alexa_device_management/config.yaml` now declares version `0.8.13`.
