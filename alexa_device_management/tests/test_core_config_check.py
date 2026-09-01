from pathlib import Path


CONTROL = (
    Path(__file__).parents[1]
    / "rootfs/opt/alexa_device_management/web/ha_control.py"
).read_text(encoding="utf-8")


def test_config_check_uses_home_assistant_core_api_not_supervisor_manager_api():
    function = CONTROL.split("async def check_config()", 1)[1].split("async def checked_deploy", 1)[0]

    assert '_ha_post("/config/core/check_config"' in function
    assert '_supervisor_post("/core/check"' not in function
    assert 'body.get("result") == "valid"' in function
    assert 'body.get("errors")' in CONTROL
