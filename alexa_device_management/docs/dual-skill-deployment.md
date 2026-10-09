# One Alexa Skill, dual v5/v6 backends (prototype)

This design deliberately uses the **existing Alexa Smart Home Skill** and its
existing Home Assistant OAuth account linking. It must **not** be configured
with Login with Amazon or an unrelated LWA client: the access token belongs to
the Home Assistant user and is passed to the appropriate HA API.

## Routing

- Discover: forward the request to Home Assistant's current
  `/api/alexa/smart_home` v5 interface; append eligible v6 endpoints from
  `/config/alexa_device_management/native/config.yaml`.
- Existing endpoint IDs are unchanged, and their directives are forwarded
  unmodified to HA's existing Alexa integration.
- New endpoints have the `native:` prefix and use v6 capability bindings.
- Two separate entity selections: v5 remains in `/data/alexa_device_management/config.json`
  and the generated `/config/packages/alexa.yaml`; v6 is in the separate native
  YAML file. No automatic conversion or disabling of old devices.
- Native v6 is disabled by default. Even with native disabled, the existing
  v5 Discovery and commands continue to function.
- If a physical device is listed in both selections, Alexa will display two
  devices. Remove it from v5 only after testing v6 successfully.

## Installation (do not switch the production Lambda before testing)

1. Review PR #67 and wait for passing CI. After approval/merge, install the
   updated HA app; the live production v5 skill remains unchanged until the
   AWS Lambda entry point is updated.
2. In HA app options, set `native_gateway_token` to a random secret with
   **at least 32 characters**. Do not commit it to Git. Restart the app.
3. Configure the app's optional TCP port 8100 under HA app network settings.
   Publish that port **only through an authenticated-secret TLS 1.2+ reverse
   proxy** at a dedicated HTTPS URL. Do not expose the 8099 admin ingress.
   Restrict IP/host access where possible; the gateway will reject requests
   without the bearer secret. Do not expose HA's Supervisor API publicly.
4. Create `/config/alexa_device_management/native/config.yaml` (use
   `examples/native-config.yaml`), and keep `enabled: false` initially.
   Populate *actual* Home Assistant entity IDs; the example IDs are placeholders.
5. In the existing AWS Lambda, preserve a backup of the current source and
   environment. Replace its handler with `native_skill/lambda_function.py`
   (Python 3.12+; standard library only). Do this on a Lambda **version/alias
   or staging skill** first, not directly on the production alias.
6. Lambda environment:
   - `GATEWAY_URL`: public HTTPS reverse proxy base URL for the dedicated
     gateway (no trailing slash).
   - `GATEWAY_TOKEN`: the same 32+ character app secret.
   Configure Lambda timeout >= 20 seconds to allow HA authentication and
   state retrieval through the gateway.
7. Keep the existing Alexa Developer Smart Home Skill ARN, payload v3,
   HA OAuth account-linking endpoints and HA's `alexa.smart_home` section.
   The Lambda uses the existing linked HA OAuth token for BOTH backends.
8. Run a v5-only Discovery and an existing light on/off test **before** setting
   `enabled: true` in v6 YAML. Then activate the Zisterne v6 YAML and run
   Discovery again: compare exactly one `native:zisterne` with both range
   properties alongside all previous v5 devices.
9. Test: "Alexa, wie voll ist die Zisterne?" and verify liters/percent speech,
   on Echo and Sonos. **Speech interpretation is Amazon-controlled and remains
   unproven until tested on real devices.**

## Security and limitations

- The gateway on TCP/8100 is separate from app ingress. Each request requires
  the app's high-entropy shared bearer secret. The Lambda validates the linked
  HA OAuth token against HA, and native state/commands use that same user token
  for Home Assistant authorization.
- Do not expose admin HTTP port 8099 or use the Supervisor token externally.
- The prototype handles v6 Discovery, ReportState and a few controller actions.
  ChangeReport, AddOrUpdateReport, DeleteReport, token refresh, additional
  capabilities, Alexa publication/certification and robust failure recovery
  remain future work.
- The original HA v5 integration remains necessary **during** dual mode.
  Full independence from HA's Alexa component comes only after retiring v5.
- A failing HA or gateway makes both backends unavailable. Test safely using
  staging before changing an active Alexa Skill.
