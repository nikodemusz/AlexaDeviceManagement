# Native-only v6 deployment (3.0.0)

One existing Alexa Smart Home Skill uses the linked Home Assistant OAuth account.
Do not disable the shared skill or replace its linking with Login with Amazon.

## Upgrade

1. Install/start app 3.0.0. The main editor now controls the existing native YAML.
   Archived legacy selections are never imported or enabled automatically.
2. Back up the deployed AWS Lambda source/environment and deploy
   `native_skill/lambda_function.py` to the existing skill's actual version/alias.
   Keep the existing HTTPS `GATEWAY_URL` and gateway secret configuration.
   An app update cannot update AWS. New Discovery skips the old HA-v5 discovery
   path entirely; old device directives receive `NO_SUCH_ENDPOINT`.
3. In the app, install the HA sync helper and its deny-all v5 YAML, validate the
   HA configuration and restart HA when requested. The native helper schema must
   be loaded before raw native endpoint reports can be sent.
4. Keep the existing event gateway settings/region and OAuth authorization. The
   native AddOrUpdateReport uses the same HA-managed LWA event token. Missing or
   rejected authorization remains an explicit error; no automatic relinking.
5. Connect the app's Alexa web session. It is used to enumerate all old HA-v5
   endpoints, including never-selected ones, and delete them individually. A
   refresh verifies removal. Failed/partial inventory or deletion is not success.
6. Trigger the app's Alexa sync or let its background reconciliation run. Native
   AddOrUpdateReport includes the exact same endpoint metadata as Lambda Discovery,
   split into batches of at most 50 and 256 KiB. Failed reports are retried.
7. Compare the expected native endpoint count with fresh Alexa inventory and test
   representative real device control. A report HTTP 202 is acceptance, not proof
   of discovery, state correctness or voice support.

## Automatic legacy retirement

3.0.0 automatically removes positively identified Home Assistant v5 endpoints.
This includes devices outside historical selections. Identification uses provider
metadata/HA descriptions and exact IDs, never friendly names. Every `native:` ID,
including wrapped/nested and disabled IDs, unrelated vendors and Echos is protected.

Old Alexa groups/routines referring to removed v5 IDs may need reassignment to v6.
The migration page and API are no longer registered; `/migration` redirects to the
main device editor. Historical JSON remains available for reference.

## Diagnostics

The main counters count logical native endpoint IDs, not bound HA rows. A cistern
with two values counts once. Old v5 copies cannot satisfy a native pending count.
The native lifecycle status records publication errors, accepted reports, remaining
v5 devices and whether a fresh inventory confirmed deletion.

CloudWatch Discovery logs contain only the adapter version and endpoint count.
No OAuth tokens or private event response bodies are returned to the UI.
