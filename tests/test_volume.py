"""Volume preset menus, actions and endpoint control without changing real audio."""
import contextlib
import io
import json
import os
import sys
import types
import unittest
import warnings
from unittest.mock import Mock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import audio
import main


def state(percent=40, muted=False, friendly="Speakers (Boom Audio)"):
    return {"id": "output", "friendly": friendly, "percent": percent, "muted": muted}


class VolumeMenuTests(unittest.TestCase):
    def query(self, text, volume=None):
        with patch.object(audio, "get_output_volume", return_value=volume or state()):
            return main.FlowV2(output_stream=io.StringIO()).dispatch("query", [{"search": text}, {}])["result"]

    def test_presets_are_ordered_and_wire_actions_match(self):
        items = self.query("v")
        presets = items[:6]
        self.assertEqual([r["Title"] for r in presets], ["0%", "20%", "✓  40%", "60%", "80%", "100%"])
        self.assertEqual([r["JsonRPCAction"]["parameters"] for r in presets], [[n] for n in (0, 20, 40, 60, 80, 100)])
        self.assertEqual([r["JsonRPCAction"]["method"] for r in presets], ["set_volume"] * 6)
        self.assertEqual(sorted(presets, key=lambda r: r["Score"], reverse=True), presets)
        self.assertEqual(items[-1]["Title"], "← Back")

    def test_aliases(self):
        for keyword in ("v", "vol", "volume", "音量", "V"):
            with self.subTest(keyword=keyword):
                self.assertEqual(self.query(keyword)[0]["Title"], "0%")

    def test_muted_nonzero_volume_is_not_marked_current(self):
        items = self.query("v", state(40, True))
        self.assertEqual(items[2]["Title"], "40%")
        self.assertIn("muted", items[2]["SubTitle"])

    def test_top_menu_drills_into_volume_and_stays_open(self):
        rpc = main.FlowV2(output_stream=io.StringIO())
        with patch.object(audio, "get_devices", return_value=[]):
            items = rpc.dispatch("query", [{"search": ""}, {}])["result"]
        action = next(r["JsonRPCAction"] for r in items if "Volume" in r["Title"])
        self.assertEqual(action["parameters"], ["Flow.Launcher.ChangeQuery", ["ac v ", True], False])
        self.assertEqual(rpc.dispatch(action["method"], [action["parameters"]]), {"hide": False})

    def test_read_failure_is_visible(self):
        with patch.object(audio, "get_output_volume", side_effect=audio.AudioError("device disappeared")):
            items = main.FlowV2(output_stream=io.StringIO()).dispatch("query", [{"search": "v"}, {}])["result"]
        self.assertEqual(items[0]["Title"], "Could not read output volume")
        self.assertIn("device disappeared", items[0]["SubTitle"])

    def test_missing_backend_is_visible(self):
        with patch.object(audio, "get_output_volume", side_effect=audio.AudioBackendUnavailable("missing")):
            items = main.FlowV2(output_stream=io.StringIO()).dispatch("query", [{"search": "v"}, {}])["result"]
        self.assertIn("Audio backend unavailable", items[0]["Title"])


class VolumeActionTests(unittest.TestCase):
    def invoke(self, percent=60, returned=None, error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        rpc = main.FlowV2(output_stream=stdout)

        def set_volume(value):
            self.assertEqual(json.loads(stdout.getvalue())["method"], "HideMainWindow")
            if error:
                raise error
            return returned or state(value)

        with patch.object(audio, "set_output_volume", side_effect=set_volume) as setter, \
                contextlib.redirect_stderr(stderr):
            response = rpc.dispatch("set_volume", [[percent]])
        self.assertEqual(response, {"hide": False})
        self.assertEqual(stderr.getvalue(), "")
        messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([m["method"] for m in messages], ["HideMainWindow", "ShowMsg"])
        return messages[1]["params"], setter

    def test_all_six_presets_hide_before_setting_and_confirm(self):
        for percent in (0, 20, 40, 60, 80, 100):
            with self.subTest(percent=percent):
                msg, setter = self.invoke(percent)
                setter.assert_called_once_with(percent)
                self.assertEqual(msg[0], "Output volume set: %d%%" % percent)
                self.assertIn("Boom Audio", msg[1])

    def test_failed_write_is_not_reported_successful(self):
        msg, _ = self.invoke(error=audio.AudioError("access denied"))
        self.assertEqual(msg[0], "Could not set or verify output volume")
        self.assertIn("access denied", msg[1])

    def test_mismatched_readback_is_not_reported_successful(self):
        msg, _ = self.invoke(returned=state(20))
        self.assertEqual(msg[0], "Output volume may not have changed")

    def test_still_muted_positive_level_is_not_reported_successful(self):
        msg, _ = self.invoke(returned=state(60, True))
        self.assertEqual(msg[0], "Output volume may not have changed")
        self.assertIn("muted", msg[1])

    def test_zero_can_preserve_the_mute_flag(self):
        msg, _ = self.invoke(0, returned=state(0, True))
        self.assertEqual(msg[0], "Output volume set: 0%")

    def test_invalid_presets_never_touch_audio(self):
        for value in (-20, 30, 120, "60", True, False, 60.0):
            with self.subTest(value=value):
                msg, setter = self.invoke(value)
                self.assertEqual(msg[0], "Invalid volume preset")
                setter.assert_not_called()

    def test_v1_action_emits_one_json_without_stderr(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(audio, "set_output_volume", return_value=state(20)), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            main.AudioCowboy({"method": "set_volume", "parameters": [20]})
        self.assertEqual(json.loads(stdout.getvalue())["parameters"][0], "Output volume set: 20%")
        self.assertEqual(stderr.getvalue(), "")


class VolumeBackendTests(unittest.TestCase):
    def setUp(self):
        self.percent = 40
        self.muted = True
        self.endpoint = Mock()
        self.endpoint.GetMasterVolumeLevelScalar.side_effect = lambda: self.percent / 100.0
        self.endpoint.GetMute.side_effect = lambda: self.muted
        self.endpoint.SetMasterVolumeLevelScalar.side_effect = self.write
        self.endpoint.SetMute.side_effect = self.mute
        self.device = types.SimpleNamespace(id="output", FriendlyName="Speakers (Boom Audio)")

    def write(self, scalar, _context):
        self.percent = scalar * 100

    def mute(self, value, _context):
        self.muted = bool(value)

    def test_scalar_percentage_conversion_and_readback(self):
        with patch.object(audio, "_pycaw_ready", return_value=True), \
                patch.object(audio, "_output_volume_endpoint", return_value=(self.device, self.endpoint)):
            for percent in (0, 20, 40, 60, 80, 100):
                result = audio.set_output_volume(percent)
                self.endpoint.SetMasterVolumeLevelScalar.assert_called_with(percent / 100.0, None)
                self.assertAlmostEqual(result["percent"], percent)
                self.assertEqual(result["id"], "output")
                if percent > 0:
                    self.assertFalse(result["muted"])

    def test_zero_does_not_change_mute_flag(self):
        with patch.object(audio, "_pycaw_ready", return_value=True), \
                patch.object(audio, "_output_volume_endpoint", return_value=(self.device, self.endpoint)):
            result = audio.set_output_volume(0)
        self.endpoint.SetMute.assert_not_called()
        self.assertTrue(result["muted"])

    def test_action_resolves_output_again_after_menu_read(self):
        new_device = types.SimpleNamespace(id="new-output", FriendlyName="Headphones")
        with patch.object(audio, "_pycaw_ready", return_value=True), \
                patch.object(audio, "_output_volume_endpoint", side_effect=[
                    (self.device, self.endpoint), (new_device, self.endpoint)]) as resolver:
            self.assertEqual(audio.get_output_volume()["id"], "output")
            self.assertEqual(audio.set_output_volume(60)["id"], "new-output")
        self.assertEqual(resolver.call_count, 2)

    def test_invalid_values_fail_before_resolving_output(self):
        with patch.object(audio, "_output_volume_endpoint") as resolver:
            for value in (-1, 101, float("nan"), float("inf"), "60", True, None):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    audio.set_output_volume(value)
        resolver.assert_not_called()

    def test_backend_missing(self):
        with patch.object(audio, "_pycaw_ready", return_value=False):
            for func, args in ((audio.get_output_volume, []), (audio.set_output_volume, [20])):
                with self.assertRaises(audio.AudioBackendUnavailable):
                    func(*args)

    def test_no_output_device(self):
        backend = types.ModuleType("pycaw.pycaw")
        backend.AudioUtilities = types.SimpleNamespace(GetSpeakers=lambda: None)
        with patch.dict(sys.modules, {"pycaw": types.ModuleType("pycaw"), "pycaw.pycaw": backend}), \
                self.assertRaisesRegex(audio.AudioError, "No default output"):
            audio._output_volume_endpoint()

    def test_readback_failure_is_reported(self):
        self.endpoint.GetMasterVolumeLevelScalar.side_effect = RuntimeError("readback unavailable")
        with patch.object(audio, "_pycaw_ready", return_value=True), \
                patch.object(audio, "_output_volume_endpoint", return_value=(self.device, self.endpoint)), \
                self.assertRaisesRegex(audio.AudioError, "set or verify"):
            audio.set_output_volume(60)

    def test_nonfatal_warnings_do_not_escape_to_stderr(self):
        def resolver():
            warnings.warn("quirky endpoint")
            return self.device, self.endpoint
        stderr = io.StringIO()
        with patch.object(audio, "_pycaw_ready", return_value=True), \
                patch.object(audio, "_output_volume_endpoint", side_effect=resolver), \
                contextlib.redirect_stderr(stderr):
            audio.get_output_volume()
            audio.set_output_volume(20)
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
