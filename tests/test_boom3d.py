"""Regression tests for Boom3D routing; no real audio changes or profile writes."""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import audio
import main


def device(item_id, friendly, direction="render", default=False):
    return {"id": item_id, "friendly": friendly, "name": friendly,
            "direction": direction, "is_default": default,
            "is_default_comm": False, "state": "Active"}


class Boom3DTests(unittest.TestCase):
    def setUp(self):
        self.output = device("physical", "Speakers (FiiO K11)")
        self.boom = device("boom", "Speakers (Boom Audio)", default=True)
        self.input = device("mic", "Microphone (Yeti)", "capture", default=True)
        self.devices = [self.output, self.boom, self.input]
        self.profile = {"output": {"endpointId": "physical", "friendlyName": "FiiO K11"},
                        "input": {"endpointId": "mic", "friendlyName": "Yeti"}}

    def invoke(self, method="set_default_output", params=None, enabled=True,
               devices=None, active=None, outcomes=None, read_error=None):
        devices = self.devices if devices is None else devices
        active = devices if active is None else active
        params = ["physical", "FiiO K11"] if params is None else params
        outcomes = {} if outcomes is None else outcomes

        def get_devices(include_inactive=False):
            if read_error:
                raise read_error
            return devices if include_inactive else active

        def set_default(item_id, role="all"):
            outcome = outcomes.get(item_id, True)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        settings = {} if enabled is None else {"boom3d_compatibility": enabled}
        request = {"method": method, "parameters": params, "settings": settings}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["main.py", json.dumps(request)]), \
                patch.object(audio, "get_devices", side_effect=get_devices), \
                patch.object(audio, "set_default", side_effect=set_default) as setter, \
                patch.object(main.profiles, "get_profile", return_value=self.profile), \
                patch.object(main.time, "sleep"), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            main.AudioCowboy()
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())  # also rejects multiple JSON payloads
        self.assertEqual(payload["method"], "Flow.Launcher.ShowMsg")
        return payload["parameters"], setter.call_args_list

    def test_strict_mode_is_default(self):
        for enabled in (None, False):
            with self.subTest(enabled=enabled):
                msg, _ = self.invoke(enabled=enabled)
                self.assertEqual(msg[0], "Output device may not have changed")
                self.assertTrue(msg[2].endswith("warning.png"))

    def test_accepted_output_redirect_is_a_request_confirmation(self):
        msg, calls = self.invoke()
        self.assertEqual(msg[0], "Output switch requested (Boom3D)")
        self.assertIn("Speakers (Boom Audio)", msg[1])
        self.assertIn("Final output is managed by Boom3D", msg[1])
        self.assertTrue(msg[2].endswith("output.png"))
        self.assertEqual([call.args for call in calls], [("physical", "all")])

    def test_normal_verified_success_is_unchanged(self):
        output = dict(self.output, is_default=True)
        boom = dict(self.boom, is_default=False)
        msg, _ = self.invoke(devices=[output, boom, self.input])
        self.assertEqual(msg[0], "Output device set")

    def test_boom_endpoint_name_variants(self):
        for name in ("Speakers (BOOM AUDIO)", "Boom3D", "Boom 3D Virtual Output"):
            with self.subTest(name=name):
                msg, _ = self.invoke(devices=[self.output, dict(self.boom, friendly=name)])
                self.assertEqual(msg[0], "Output switch requested (Boom3D)")

    def test_other_virtual_outputs_keep_the_warning(self):
        other = dict(self.boom, friendly="Speakers (Other Virtual Audio)")
        msg, _ = self.invoke(devices=[self.output, other])
        self.assertEqual(msg[0], "Output device may not have changed")

    def test_absent_or_inactive_output_is_not_accepted(self):
        cases = (([self.boom, self.input], [self.boom, self.input]),
                 (self.devices, [self.boom, self.input]))
        for devices, active in cases:
            with self.subTest(active=active):
                msg, _ = self.invoke(devices=devices, active=active)
                self.assertEqual(msg[0], "Output device may not have changed")

    def test_backend_false_is_not_accepted(self):
        msg, _ = self.invoke(outcomes={"physical": False})
        self.assertEqual(msg[0], "Output device may not have changed")

    def test_backend_exception_is_not_suppressed(self):
        msg, _ = self.invoke(outcomes={"physical": audio.AudioError("COM failed")})
        self.assertEqual(msg[:2], ["Failed to set output device", "COM failed"])
        self.assertTrue(msg[2].endswith("error.png"))

    def test_missing_backend_is_not_suppressed(self):
        msg, _ = self.invoke(outcomes={"physical": audio.AudioBackendUnavailable("missing")})
        self.assertEqual(msg[0], "Audio backend unavailable")

    def test_unreadable_default_remains_unverified(self):
        msg, _ = self.invoke(read_error=audio.AudioError("Cannot enumerate"))
        self.assertEqual(msg[0], "Output device set (unverified)")
        self.assertTrue(msg[2].endswith("warning.png"))

    def test_input_switch_keeps_strict_verification(self):
        mic = dict(self.input, is_default=False)
        msg, _ = self.invoke(method="set_default_input", params=["mic", "Yeti"],
                             devices=[self.output, self.boom, mic])
        self.assertEqual(msg[0], "Input device may not have changed")

    def test_communication_only_remains_unverified(self):
        msg, calls = self.invoke(method="set_default_comm",
                                 params=["physical", "FiiO", "render"])
        self.assertEqual(msg[0], "Output (communication) device set (unverified)")
        self.assertEqual(calls[0].args, ("physical", "2"))

    def test_profile_accepts_redirect_and_verified_input(self):
        msg, calls = self.invoke(method="load_profile", params=["Gaming"])
        self.assertEqual(msg[0], "Profile requested (Boom3D): Gaming")
        self.assertIn("FiiO K11 (requested via Boom3D)", msg[1])
        self.assertIn("Yeti", msg[1])
        self.assertNotIn("Failed", msg[1])
        self.assertTrue(msg[2].endswith("profile.png"))
        self.assertEqual([call.args for call in calls], [("physical", "all"), ("mic", "all")])

    def test_profile_strict_mode_is_unchanged(self):
        msg, _ = self.invoke(method="load_profile", params=["Gaming"], enabled=False)
        self.assertIn("partial", msg[0])
        self.assertIn("Failed to set: FiiO K11", msg[1])

    def test_profile_input_failure_still_reports_partial(self):
        mic = dict(self.input, is_default=False)
        msg, _ = self.invoke(method="load_profile", params=["Gaming"],
                             devices=[self.output, self.boom, mic])
        self.assertIn("partial", msg[0])
        self.assertIn("FiiO K11 (requested via Boom3D)", msg[1])
        self.assertIn("Failed to set: Yeti", msg[1])
        self.assertTrue(msg[2].endswith("warning.png"))

    def test_profile_false_or_exception_is_not_accepted_as_redirect(self):
        for outcome in (False, audio.AudioError("COM failed")):
            with self.subTest(outcome=outcome):
                msg, _ = self.invoke(method="load_profile", params=["Gaming"],
                                     outcomes={"physical": outcome})
                self.assertIn("Failed to set: FiiO K11", msg[1])
                self.assertNotIn("requested via Boom3D", msg[1])

    def test_profile_absent_or_inactive_output_is_not_accepted(self):
        msg, _ = self.invoke(method="load_profile", params=["Gaming"],
                             devices=[self.boom, self.input])
        self.assertIn("Unavailable: FiiO K11", msg[1])
        msg, _ = self.invoke(method="load_profile", params=["Gaming"],
                             active=[self.boom, self.input])
        self.assertIn("Failed to set: FiiO K11", msg[1])

    def test_profile_unreadable_default_is_not_accepted_as_redirect(self):
        msg, _ = self.invoke(method="load_profile", params=["Gaming"],
                             read_error=audio.AudioError("Cannot enumerate"))
        self.assertEqual(msg[0], "Applied profile: Gaming")
        self.assertIn("unverified", msg[1])
        self.assertTrue(msg[2].endswith("warning.png"))


if __name__ == "__main__":
    unittest.main()
