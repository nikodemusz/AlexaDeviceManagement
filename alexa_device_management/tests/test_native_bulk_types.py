"""Bulk v6 migration and additional native interfaces."""
from __future__ import annotations
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"rootfs/opt/alexa_device_management/web"))
from native_migration import prepare
from native_skill_config import NativeSkillConfigStore
from device_model import DeviceModelError
import native_migration_ui
from config_store import ConfigStore

spec=importlib.util.spec_from_file_location("bulk_skill_lambda",ROOT/"native_skill/lambda_function.py")
skill=importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)


class AdditionalTypeTests(unittest.TestCase):
    def test_migrate_classified_sensors_and_climate(self):
        legacy={"entities":{
            "climate.office":{"enabled":True,"name":"Heizung"},
            "binary_sensor.door":{"enabled":True,"display_category":"CONTACT_SENSOR"},
            "binary_sensor.motion":{"enabled":True,"display_category":"MOTION_SENSOR"},
            "binary_sensor.other":{"enabled":True},
            "sensor.temp":{"enabled":True,"display_category":"TEMPERATURE_SENSOR"},
            "sensor.humidity":{"enabled":True},
        }}
        native, report=prepare(legacy,NativeSkillConfigStore.default())
        self.assertEqual(report["added"],["binary_sensor.door","binary_sensor.motion","climate.office","sensor.temp"])
        self.assertEqual(report["unsupported"],["binary_sensor.other","sensor.humidity"])
        self.assertFalse(native["devices"]["ha:climate.office"]["enabled"])
        NativeSkillConfigStore.validate(native)

    def test_sensor_report_values(self):
        bindings=[
            {"interface":"Alexa.ContactSensor","entity_id":"binary_sensor.door"},
            {"interface":"Alexa.MotionSensor","entity_id":"binary_sensor.motion"},
            {"interface":"Alexa.TemperatureSensor","entity_id":"sensor.temp"},
            {"interface":"Alexa.ThermostatController","entity_id":"climate.office"},
        ]
        states={
            "binary_sensor.door":{"state":"on"},
            "binary_sensor.motion":{"state":"off"},
            "sensor.temp":{"state":"22.5"},
            "climate.office":{"state":"heat","attributes":{"temperature":21}},
        }
        props=skill.state_properties(bindings,states)
        self.assertEqual(props[0]["value"],"DETECTED")
        self.assertEqual(props[1]["value"],"NOT_DETECTED")
        self.assertEqual(props[2]["value"],{"value":22.5,"scale":"CELSIUS"})
        self.assertEqual(props[3]["name"],"targetSetpoint")
        self.assertEqual(props[4]["value"],"HEAT")
        caps=skill.discovery({"directive":{"header":{"messageId":"test"}}},
            {"devices":{"office":{"name":"Büro","capabilities":bindings}}})["event"]["payload"]["endpoints"][0]["capabilities"]
        self.assertIn("Alexa.ThermostatController",[cap["interface"] for cap in caps])
        self.assertIn("Alexa.EndpointHealth",[cap["interface"] for cap in caps])

    def test_invalid_sensor_binding_is_rejected(self):
        with self.assertRaises(DeviceModelError):
            NativeSkillConfigStore.validate({"schema_version":6,"enabled":True,"locale":"de-DE","devices":{
                "wrong":{"name":"Wrong","capabilities":[{"interface":"Alexa.ContactSensor","entity_id":"switch.door"}]}
            }})


class BulkApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        self.temp=tempfile.TemporaryDirectory()
        root=pathlib.Path(self.temp.name)
        self.store=ConfigStore(root/"legacy.json",root/"old.json",root/"alexa.yaml")
        self.store.save({"entities":{"light.a":{"enabled":True},"light.b":{"enabled":True}}},create_backup=False)
        self.native=NativeSkillConfigStore(root/"native.yaml")
        config=self.native.default()
        config["enabled"]=True
        config["devices"]={
            "ha:light.a":{"name":"A","enabled":False,"replaces_legacy_endpoint":"light#a",
               "capabilities":[{"interface":"Alexa.PowerController","entity_id":"light.a"}]},
            "ha:light.b":{"name":"B","enabled":False,"replaces_legacy_endpoint":"light#b",
               "capabilities":[{"interface":"Alexa.PowerController","entity_id":"light.b"}]},
        }
        self.native.save(config)
        self.original= self.store.path.read_bytes()
        self.patcher=patch.object(native_migration_ui,"NATIVE_STORE",self.native)
        self.patcher.start()
        app=web.Application()
        native_migration_ui.register_routes(app,self.store)
        self.client=TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.patcher.stop()
        self.temp.cleanup()

    async def test_batch_activation_and_rollback(self):
        initial=await (await self.client.get("/api/native-migration/config")).json()
        resp=await self.client.post("/api/native-migration/bulk",json={
            "ids":["ha:light.a","ha:light.b"],"enabled":True,"revision":initial["revision"]})
        self.assertEqual(resp.status,200)
        result=await resp.json()
        self.assertEqual(result["changed"],2)
        self.assertTrue(self.native.load()["devices"]["ha:light.a"]["enabled"])
        resp=await self.client.post("/api/native-migration/bulk",json={
            "ids":["ha:light.a","ha:light.b"],"enabled":False,"revision":result["config"]["revision"]})
        self.assertEqual(resp.status,200)
        self.assertFalse(self.native.load()["devices"]["ha:light.b"]["enabled"])
        self.assertEqual(self.original,self.store.path.read_bytes())

    async def test_batch_is_atomic_on_invalid_id(self):
        initial=await (await self.client.get("/api/native-migration/config")).json()
        resp=await self.client.post("/api/native-migration/bulk",json={
            "ids":["ha:light.a","nonexistent"],"enabled":True,"revision":initial["revision"]})
        self.assertEqual(resp.status,400)
        self.assertFalse(self.native.load()["devices"]["ha:light.a"]["enabled"])

if __name__=="__main__":
    unittest.main()
