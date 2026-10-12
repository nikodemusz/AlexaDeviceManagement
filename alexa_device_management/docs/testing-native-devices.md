# Discovery, control, and status tests

## Offline contract suite

From the repository root, with the web requirements, `pytest`, `jsonschema`, and
`voluptuous` installed:

```sh
python -m unittest discover -s alexa_device_management/tests -p test_native_device_contract.py -v
python -m unittest discover -s alexa_device_management/tests
python -m pytest -q alexa_device_management/tests
```

`tests/test_native_device_contract.py` runs the real Lambda handler, its request
serialization, gateway authentication, registered gateway routes, and status
serialization in one process. HTTP transport, native config reads, OAuth checks
against HA, and HA state/service responses use synthetic fixtures. It opens no
sockets, reads no live `/config` or credentials, and never switches real devices.

The suite checks:

- Stable unique Discovery IDs, disabled devices, and exactly one cistern endpoint
  with separate litres/percent instances and units.
- Power, brightness, toggle, cover position/relative position/stop, thermostat
  target/relative target/mode, and the exact HA service/entity payload.
- The control response followed by ReportState: the same endpoint, correlation
  token, actual readback values, timestamps, and all properties advertised by
  Discovery, including EndpointHealth.
- Temperature/contact/motion values, shared-entity reads, and distinct target
  versus actual thermostat temperature.
- Invalid values/instances, read-only sensors, missing/unavailable/non-finite
  states, missing/expired user authorization, wrong gateway credentials, disabled
  config, backend failures, and retired v5 endpoints.
- A successful service call with unchanged or unavailable HA readback cannot be
  mistaken for the requested state or a healthy state report.

These are protocol/backend regression tests. They do not prove AWS deployment,
Amazon device registration, physical device behavior, or Alexa voice support.
Proactive lifecycle reports have separate tests in `test_native_service_reports.py`
and `test_native_primary.py`.

## AWS Lambda console examples

[`native_skill/test_events/`](../native_skill/test_events/) contains 15 individual
JSON files, including `discovery.json`, `light_status.json`, `light_turn_on.json`,
`cover_position.json`, `thermostat_status.json`, and `cistern_status.json`. Each
file is a complete Lambda test event, ready to copy into the console. The offline
suite executes every file too.

For a manual AWS test, copy one example into the Lambda console. Replace the
synthetic `native:desk`, `native:blind`, etc. with an exact endpoint ID from your
native Discovery result, and set the scope token privately to the existing
Alexa-linked HA user's current OAuth access token. A Supervisor token or gateway
machine token does not replace that user token. Do not commit or share populated
events or logs containing tokens. No token is needed to run the offline suite.

### Set the token once through a local environment variable

The console receives [a literal JSON test event](https://docs.aws.amazon.com/lambda/latest/dg/testing-functions.html).
The supplied Lambda treats scope tokens as literal strings; `${VARIABLE}` in a
saved event is not a token reference. Use the local renderer to insert the current
token into all files, instead of editing each file. It uses only Python's standard
library and sends no requests.

Make the current linked HA OAuth access token available to your local Python
process as `HA_ALEXA_OAUTH_TOKEN`, using your existing private environment setup.
From the repository root:

```sh
python alexa_device_management/native_skill/render_test_events.py \
  --output-dir /tmp/alexa-private-test-events
```

This writes 15 separate JSON files with file mode `0600`; the new output directory
has mode `0700`. Output reports only the file count, never the token or JSON. The
source templates keep their placeholders. Choose an output directory outside the
repository; populated files contain credentials and must remain private.

For one event or a different variable name:

```sh
python alexa_device_management/native_skill/render_test_events.py \
  --token-env MY_HA_OAUTH_TOKEN --event discovery \
  --output-dir /tmp/alexa-private-discovery
```

Endpoint IDs can also be replaced once for all matching files. For example,
replace the synthetic desk ID with your actual ID from Discovery:

```sh
python alexa_device_management/native_skill/render_test_events.py \
  --endpoint desk=native:living_room \
  --output-dir /tmp/alexa-private-test-events --overwrite
```

After the token changes, update only the environment variable and run the renderer
again with `--overwrite`. Copy the regenerated file into the console before
testing. Previously saved console events do not update automatically. This tool
does not refresh an expired OAuth token or read tokens from HA storage. It never
adds a fallback token to the production Lambda or bypasses linked-user validation.

Start with `discovery` and `*_status`. Control examples execute real HA services
when run against a deployed Lambda; choose a suitable device and target value.
For Range/Toggle controllers, keep `header.instance` identical to Discovery.

Expected results:

- Discovery: `Discover.Response`, only active `native:` IDs, one endpoint for
  multi-value devices, and the expected capabilities/instances/units.
- Status: `StateReport`, the requested endpoint ID and correlation token, all
  retrievable properties and EndpointHealth. The cistern reports two rangeValue
  properties (`litres` and `percent`).
- Control: `Response`, then a separate ReportState returning the observed HA
  state. A cover or other slow device may still be moving on immediate readback;
  repeat the status request after completion.
- Missing or retired v5 IDs: `NO_SUCH_ENDPOINT`. Unavailable entity state:
  `ENDPOINT_UNREACHABLE`. Expired/missing user authorization:
  `INVALID_AUTHORIZATION_CREDENTIAL`.

Running Discovery in the AWS console returns a protocol response to the console;
it does not itself register those devices in the Alexa app. Use Alexa discovery
or the app's native synchronization for registration, and verify fresh inventory.
