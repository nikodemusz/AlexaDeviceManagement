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

[`native_skill/test_events.json`](../native_skill/test_events.json) contains 15
named examples. Each **value** is a complete Lambda test event; the entire outer
mapping is not an Alexa event. The offline suite executes all examples too.

For a manual AWS test, copy one example into the Lambda console. Replace the
synthetic `native:desk`, `native:blind`, etc. with an exact endpoint ID from your
native Discovery result, and set the scope token privately to the existing
Alexa-linked HA user's current OAuth access token. A Supervisor token or gateway
machine token does not replace that user token. Do not commit or share populated
events or logs containing tokens. No token is needed to run the offline suite.

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
