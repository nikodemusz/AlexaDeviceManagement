from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = (ROOT / "rootfs/opt/alexa_device_management/web/static/device_overview.js").read_text(encoding="utf-8")
HTML = (ROOT / "rootfs/opt/alexa_device_management/web/static/device_overview.html").read_text(encoding="utf-8")


class AlexaBulkDeleteUiTests(unittest.TestCase):
    def test_alexa_only_devices_can_be_selected_individually_or_as_visible_set(self):
        self.assertIn('data-alexa-select="${key}"', SCRIPT)
        self.assertIn('id="select-visible-alexa"', SCRIPT)
        self.assertIn('target.id === "select-visible-alexa"', SCRIPT)
        self.assertIn("alexaOnlyMatchesFilter(item, filters())", SCRIPT)


    def test_bulk_delete_requires_confirmation_and_uses_persistent_job_endpoint(self):
        self.assertIn("dauerhaft aus Alexa löschen?", SCRIPT)
        self.assertIn('request("/api/devices/delete-job", {', SCRIPT)
        self.assertIn("serial: item.serial", SCRIPT)
        self.assertIn("source: item.source", SCRIPT)
        self.assertIn('appliance_id: item.appliance_id || ""', SCRIPT)
        self.assertIn('request("/api/devices/delete-job")', SCRIPT)

    def test_device_group_editor_is_present_and_posts_the_explicit_entity_selection(self):
        self.assertIn('id="device-group-dialog"', HTML)
        self.assertIn('name="device-group-mode" value="combined"', HTML)
        self.assertIn('name="device-group-mode" value="separate"', HTML)
        self.assertIn('data-group-name=', SCRIPT)
        self.assertIn('request("/api/native-export/group"', SCRIPT)
        self.assertIn("Abgewählte Entitäten werden aus dem Alexa-Export entfernt", HTML)


    def test_failed_bulk_delete_targets_remain_selected_and_versioned_assets_refresh(self):
        self.assertIn("Fehlgeschlagene Geräte bleiben in der Auswahl.", SCRIPT)
        self.assertIn("selectedAlexaKeys.delete(item.key)", SCRIPT)
        self.assertIn("device_overview.js?v=3.6.0", HTML)
        self.assertIn("device_overview.css?v=3.6.0", HTML)
