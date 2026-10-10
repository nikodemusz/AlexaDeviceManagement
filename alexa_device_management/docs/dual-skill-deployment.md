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

## Home Assistant OAuth routing

The native gateway sends linked Home Assistant user OAuth tokens to Core's
`http://homeassistant:8123/api`, not the Supervisor proxy. Optionally override
this internal target through `HA_USER_HTTP_URL` (full API base URL, ending in
`/api`) if the container environment uses a different Core hostname.
The externally visible Lambda gateway URL and token remain unchanged.

## Protocol corrections in 2.20.1

Update the HA app **and separately deploy** the bundled
`native_skill/lambda_function.py` to the existing AWS Lambda to apply all fixes.
No account relinking, endpoint deletion or native draft activation is part of
this update. An app update alone cannot replace deployed Lambda code.

- AcceptGrant reads the linked HA user token from `payload.grantee.token` and
  delegates the original authorization grant to Home Assistant. This allows
  future valid grants to be processed; it does not repair an existing revoked
  or expired LWA event-gateway authorization by itself.
- Legacy Discovery and synchronous responses retain all Home Assistant
  capabilities. Home Assistant sends proactive events directly, so filtering
  ContactSensor on switches or PowerController on legacy covers only in Lambda
  would create an inconsistent contract. Native covers still expose position
  and Stop without PowerController.
- Native endpoints advertise retrievable EndpointHealth with proactive
  reporting disabled. StateReport and successful control responses return all
  retrievable properties and connectivity. Unknown, unavailable or missing HA
  state returns ENDPOINT_UNREACHABLE rather than a fabricated OFF state; no
  unavailable-value cache is implied. HA property timestamps are preserved in
  UTC, while connectivity records the current successful gateway observation.
- The overview reads active bindings from the separate native YAML, including
  several sensor values belonging to one endpoint. Its association counts are
  not an end-to-end connectivity test; v5 export checkboxes still edit v5 only.

Protocol references: [AcceptGrant](https://developer.amazon.com/docs/alexaplus/device-apis/alexa-authorization.html),
[StateReport](https://developer.amazon.com/docs/alexaplus/device-apis/alexa-statereport.html),
[EndpointHealth](https://developer.amazon.com/docs/alexaplus/device-apis/alexa-endpointhealth.html).

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

## Staged v5 → v6 migration (2.18.0)

The migration **never disables or changes** the legacy `config.json` or
`/config/packages/alexa.yaml`. It proposes disabled native device drafts for
enabled `light`, `switch` and `fan` entities only. Unsupported devices such as
`climate`, sensors and complex device capabilities are reported and
must be migrated manually after native protocol support exists.

Inside the running add-on container (or with paths pointing at equivalent
files on a development machine):

```bash
cd /opt/alexa_device_management/web
python3 native_migration.py
python3 native_migration.py --apply
```

`--apply` **only adds disabled drafts** to
`/config/alexa_device_management/native/config.yaml`. Existing native
devices (including `zisterne`) remain untouched; repeated execution is safe.
Back up that YAML before manual edits.

To migrate **one device at a time**, inspect its capability, enable
`enabled: true` on that device in the native YAML, and make sure global
`enabled: true` is set. Its optional `replaces_legacy_endpoint`
points at the corresponding HA-v5 endpoint ID, e.g. `light#desk`.
The Lambda then hides only that v5 endpoint from subsequent Discovery;
its v5 export and old endpoint control remain available for rollback.
Alexa sees the new `native:ha:light.desk` ID as a **new device** and may
retain a stale v5 copy until a device sync/delete. Check rooms and routines
manually, and do not remove legacy YAML until the entire migration is proven.

To roll back, set the individual native device's `enabled: false`, run
Discovery again and reassign Alexa routines if needed. The original v5
endpoint reappears. **Re-deploy the AWS Lambda** from
`native_skill/lambda_function.py` to activate discovery cutover logic;
an HA add-on update alone is insufficient.

For a local preview against files outside the add-on container:
`python3 native_migration.py --legacy /path/to/config.json --native /path/to/config.yaml`.

## Native covers (2.19.0)

Migration drafts now include `cover` entities as disabled v6 endpoints with
`Alexa.RangeController` position (0–100 %, 0=closed, 100=open) and
`Alexa.PlaybackController` Stop. The gateway calls Home Assistant
`cover.set_cover_position` / `cover.stop_cover` and reads
`current_position`. Covers without an available numeric
`current_position`, `SET_POSITION` or `STOP` support must stay on v5.
Inspect and explicitly enable each migrated cover individually; do not enable
migration drafts in bulk. Alexa retains the old endpoint until a device refresh
or deletion. This feature requires updating both HA app and AWS Lambda.
