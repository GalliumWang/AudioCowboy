"""Exercise the persistent Flow transport without changing real audio devices."""
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import main


class FlowV2Tests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.rpc = main.FlowV2(output_stream=self.output)

    def messages(self):
        return [json.loads(line) for line in self.output.getvalue().splitlines()]

    def test_hide_precedes_backend_and_notification_follows_verification(self):
        for method, args in (("set_default_output", ["out", "扬声器"]),
                             ("set_default_input", ["mic", "麦克风"]),
                             ("set_default_comm", ["out", "Speaker", "render"])):
            with self.subTest(method=method):
                self.output.seek(0)
                self.output.truncate()

                def switch(*_):
                    self.assertEqual(self.messages(), [{"jsonrpc": "2.0",
                                     "method": "HideMainWindow", "params": []}])
                    return True

                with patch.object(main.audio, "set_default", side_effect=switch), \
                        patch.object(main.AudioCowboy, "_is_now_default", return_value=True):
                    response = self.rpc.dispatch(method, [args])
                self.assertEqual(response, {"hide": False})
                self.assertEqual([m["method"] for m in self.messages()],
                                 ["HideMainWindow", "ShowMsg"])

    def test_backend_failure_still_notifies_after_hide(self):
        with patch.object(main.audio, "set_default", side_effect=RuntimeError("offline")):
            response = self.rpc.dispatch("set_default_output", [["out", "Speakers"]])
        self.assertFalse(response["hide"])
        messages = self.messages()
        self.assertEqual(messages[0]["method"], "HideMainWindow")
        self.assertEqual(messages[1]["params"][0], "Failed to set output device")

    def test_profile_hides_before_loading(self):
        def profile(_):
            self.assertEqual(self.messages()[0]["method"], "HideMainWindow")
            return None
        with patch.object(main.profiles, "get_profile", side_effect=profile):
            response = self.rpc.dispatch("load_profile", [["Gaming"]])
        self.assertFalse(response["hide"])
        self.assertEqual(self.messages()[1]["params"][0], "Profile not found")

    def test_query_settings_and_drill_keep_window_open(self):
        with patch.object(main.AudioCowboy, "_top_menu", return_value=[
                main.drill("Output", "", "o ")]) as menu:
            response = self.rpc.dispatch("query", [{"search": ""},
                                                  {"boom3d_compatibility": True}])
        menu.assert_called_once()
        action = response["result"][0]["JsonRPCAction"]
        self.assertEqual(action["method"], "flow_action")
        self.assertEqual(self.rpc.dispatch(action["method"], [action["parameters"]]),
                         {"hide": False})
        self.assertEqual(self.messages()[0]["method"], "ChangeQuery")

    def test_v2_boom_redirect_uses_saved_settings(self):
        with patch.object(main, "_saved_settings", return_value={"boom3d_compatibility": True}), \
                patch.object(main.audio, "set_default", return_value=True), \
                patch.object(main.AudioCowboy, "_is_now_default", return_value=False), \
                patch.object(main.audio, "get_devices", return_value=[
                    {"id": "out", "direction": "render", "is_default": False},
                    {"id": "boom", "direction": "render", "is_default": True,
                     "friendly": "Speakers (Boom Audio)"}]):
            self.rpc.dispatch("set_default_output", [["out", "Speakers"]])
        self.assertEqual(self.messages()[1]["params"][0], "Output switch requested (Boom3D)")

    def test_context_menu_action_shape(self):
        response = self.rpc.dispatch("context_menu", [["device", "render", "out", "Speaker"]])
        self.assertEqual(response["result"][0]["JsonRPCAction"]["method"], "set_default_output")

    def test_relist_keeps_window_open(self):
        with patch.object(main.profiles, "delete_profile", return_value=True):
            response = self.rpc.dispatch("delete_profile_relist", [["Gaming"]])
        self.assertFalse(response["hide"])
        self.assertEqual(self.messages()[0]["method"], "ChangeQuery")

    def test_persistent_wire_and_close(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": [{}]},
            {"jsonrpc": "2.0", "id": 2, "method": "query", "params": [{"search": "s 中文"}, {}]},
            {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 2}},
            {"jsonrpc": "2.0", "id": 3, "method": "context_menu",
             "params": [["device", "render", "out", "扬声器中文"]]},
            {"jsonrpc": "2.0", "id": 4, "method": "close", "params": []}]
        process = subprocess.run([sys.executable, os.path.join(ROOT, "main.py")],
                                 input="".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests),
                                 capture_output=True, encoding="utf-8", timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        messages = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([m["id"] for m in messages], [1, 2, 3, 4])
        self.assertEqual(messages[2]["result"]["result"][0]["SubTitle"], "扬声器中文")
        self.assertIsNone(messages[-1]["result"])

    def test_hide_is_flushed_while_backend_is_still_working(self):
        code = """import sys, time
sys.path.insert(0, sys.argv[1])
import main
def slow_switch(*args):
    time.sleep(2)
    return True
main.audio.set_default = slow_switch
main.AudioCowboy._is_now_default = lambda *a, **k: True
main.FlowV2().run()
"""
        process = subprocess.Popen([sys.executable, "-c", code, ROOT], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   encoding="utf-8")
        try:
            request = {"jsonrpc": "2.0", "id": 1, "method": "set_default_output",
                       "params": [["out", "Speaker"]]}
            started = time.monotonic()
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            lines = queue.Queue()
            reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
            reader.start()
            first = json.loads(lines.get(timeout=1.5))
            reader.join(timeout=1)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertEqual(first["method"], "HideMainWindow")
            self.assertIsNone(process.poll())
            stdout, stderr = process.communicate(timeout=10)
            messages = [json.loads(line) for line in stdout.splitlines()]
            self.assertEqual(messages[0]["method"], "ShowMsg")
            self.assertFalse(messages[1]["result"]["hide"])
            self.assertGreaterEqual(time.monotonic() - started, 2)
            self.assertEqual(stderr, "")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main()
