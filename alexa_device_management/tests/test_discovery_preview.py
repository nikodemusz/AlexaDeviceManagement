from __future__ import annotations

import pathlib
import sys

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from discovery_preview import build_preview


def inventory():
    return [
        {
            "device_id": "device-1",
            "name": "Wohnzimmerlicht",
            "area_name": "Wohnzimmer",
            "floor_name": "EG",
            "entities": [
                {
                    "entity_id": "light.wohnzimmer",
                    "domain": "light",
                    "name": "Wohnzimmerlicht",
                    "category_suggestion": "LIGHT",
                    "state": "on",
                },
                {
                    "entity_id": "sensor.temperatur",
                    "domain": "sensor",
                    "name": "Temperatur",
                    "category_suggestion": "TEMPERATURE_SENSOR",
                    "state": "21.4",
                },
            ],
        }
    ]


def test_preview_counts_selected_endpoints():
    result = build_preview(
        {
            "entities": {
                "light.wohnzimmer": {
                    "enabled": True,
                    "name": "Licht Wohnzimmer",
                    "display_category": "LIGHT",
                },
                "sensor.temperatur": {
                    "enabled": True,
                    "name": "Temperatur Wohnzimmer",
                    "display_category": "TEMPERATURE_SENSOR",
                },
            }
        },
        inventory(),
    )

    assert result["ok"] is True
    assert result["endpoint_count"] == 2
    assert result["category_counts"] == {"LIGHT": 1, "TEMPERATURE_SENSOR": 1}
    assert result["area_counts"] == {"Wohnzimmer": 2}


def test_preview_reports_missing_entities():
    result = build_preview(
        {"entities": {"switch.entfernt": {"enabled": True, "name": "Alt"}}},
        inventory(),
    )

    assert result["ok"] is False
    assert result["endpoint_count"] == 0
    assert result["missing_entities"] == ["switch.entfernt"]
    assert result["error_count"] == 1


def test_preview_reports_duplicate_names_case_insensitively():
    result = build_preview(
        {
            "entities": {
                "light.wohnzimmer": {"enabled": True, "name": "Wohnzimmer"},
                "sensor.temperatur": {"enabled": True, "name": "wohnzimmer"},
            }
        },
        inventory(),
    )

    assert result["ok"] is True
    assert result["warning_count"] == 1
    assert result["duplicate_names"][0]["entities"] == [
        "light.wohnzimmer",
        "sensor.temperatur",
    ]
