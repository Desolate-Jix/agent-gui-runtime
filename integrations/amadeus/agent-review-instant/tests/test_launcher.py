"""只运行合成子进程，不能将其算作真实 Runtime 验收。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PYTHON311 = os.environ.get("AGENT_GUI_TEST_PYTHON311", "")
SECRET = "synthetic-key-must-not-be-logged-1742"
BOOT = "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('amadeus_agent_gui',run_name='__main__')"
FIXTURE = '''import json,os,sys
from pathlib import Path
args = sys.argv[1:]
data = Path(args[args.index('--data-dir')+1])
data.mkdir(parents=True, exist_ok=True)
snapshot = {'args': args, 'cwd': str(Path.cwd()),
 'secret_received': os.environ.get('OPENAI_API_KEY') == 'synthetic-key-must-not-be-logged-1742',
 'unrelated_present': 'UNRELATED_PROVIDER_KEY' in os.environ,
 'pythonpath_present': 'PYTHONPATH' in os.environ}
(data/'started.json').write_text(json.dumps(snapshot), encoding='utf-8')
sys.stdout.buffer.write(b'fixture-ready\\n'); sys.stdout.buffer.flush()
for line in sys.stdin.buffer:
 sys.stdout.buffer.write(b'echo:' + line); sys.stdout.buffer.flush()
(data/'eof.json').write_text(json.dumps({'eof': True}), encoding='utf-8')
sys.stdout.buffer.write(b'fixture-eof\\n'); sys.stdout.buffer.flush()
sys.stderr.buffer.write(b'fixture-stderr\\n'); sys.stderr.buffer.flush()
raise SystemExit(7)
'''


@unittest.skipUnless(sys.platform == "win32" and PYTHON311, "Set AGENT_GUI_TEST_PYTHON311 to an existing Python 3.11 on Windows")
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gui extension ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "\u4e2d\u6587 path"
        self.root = self.base / "Runtime install"
        (self.root / "scripts").mkdir(parents=True)
        self.script = self.root / "scripts/start_instant_mcp.py"
        self.script.write_text(FIXTURE, encoding="utf-8")
        self.marker = self.root / "execution-installation.json"
        self.marker.write_text(json.dumps({"schema": "execution_installation.v1", "component": "execution", "version": "0.1.4"}), encoding="utf-8")
        self.vision = self.base / "vision profile.json"
        self.decision = self.base / "decision profile.json"
        self.vision.write_text(json.dumps({"api_key_env": "OPENAI_API_KEY"}), encoding="utf-8")
        self.decision.write_text(json.dumps({"api_key_env": "OPENAI_API_KEY", "ordinary_review_api_key_env": "OPENAI_API_KEY"}), encoding="utf-8")
        self.data = self.base / "extension data"
        self.env = {key: value for key, value in os.environ.items() if key in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "COMSPEC", "PATHEXT", "USERPROFILE", "LOCALAPPDATA", "APPDATA"}}
        self.env.update({
            "AGENT_GUI_RUNTIME_ROOT": str(self.root),
            "AGENT_GUI_RUNTIME_PYTHON": str(Path(PYTHON311).resolve()),
            "AGENT_GUI_RUNTIME_API_PROFILE": str(self.vision),
            "AGENT_GUI_RUNTIME_DECISION_PROFILE": str(self.decision),
            "AGENT_GUI_RUNTIME_DATA": str(self.data),
            "OPENAI_API_KEY": SECRET,
            "UNRELATED_PROVIDER_KEY": "synthetic-unrelated-secret",
            "PYTHONPATH": "synthetic-untrusted-path",
        })
        self.command = [sys.executable, "-I", "-B", "-X", "utf8", "-c", BOOT, str(SRC)]

    def run_launcher(self, *, env=None, input=b""):
        return subprocess.run(self.command, env=env or self.env, input=input, capture_output=True, timeout=15, check=False)

    def assert_config_rejected(self, env, code):
        result = self.run_launcher(env=env)
        self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stdout, b"")
        self.assertIn(code.encode(), result.stderr)
        self.assertNotIn(SECRET.encode(), result.stderr)
        self.assertFalse((self.data / "started.json").exists())

    def test_real_stdio_is_unbuffered_and_child_receives_eof(self):
        # 捕获启动日志、代理缓冲或保留 stdin 写端都会破坏此边界。
        with subprocess.Popen(self.command, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
            self.assertEqual(proc.stdout.readline(), b"fixture-ready\n")
            payload = '{"text":"\u4e2d\u6587","id":42}\n'.encode("utf-8")
            proc.stdin.write(payload)
            proc.stdin.flush()
            self.assertEqual(proc.stdout.readline(), b"echo:" + payload)
            self.assertIsNone(proc.poll())
            proc.stdin.close()
            self.assertEqual(proc.wait(timeout=10), 7)
            self.assertEqual(proc.stdout.read(), b"fixture-eof\n")
            self.assertEqual(proc.stderr.read(), b"fixture-stderr\n")
        self.assertEqual(json.loads((self.data / "eof.json").read_text(encoding="utf-8")), {"eof": True})

    def test_explicit_paths_flags_and_secret_environment_reach_original_entry(self):
        result = self.run_launcher(input=b"one\ntwo\n")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout, b"fixture-ready\necho:one\necho:two\nfixture-eof\n")
        recorded = json.loads((self.data / "started.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded["args"], ["--data-dir", str(self.data), "--recognition-source", "external_api", "--api-profile", str(self.vision), "--decision-profile", str(self.decision)])
        self.assertEqual(recorded["cwd"], str(self.root))
        self.assertTrue(recorded["secret_received"])
        self.assertFalse(recorded["unrelated_present"])
        self.assertFalse(recorded["pythonpath_present"])
        self.assertNotIn(SECRET, json.dumps(recorded))
        self.assertNotIn(SECRET.encode(), result.stdout + result.stderr)

    def test_execution_015_marker_preserves_original_stdio(self):
        self.marker.write_text(json.dumps({"schema": "execution_installation.v1", "component": "execution", "version": "0.1.5"}), encoding="utf-8")
        result = self.run_launcher(input=b"candidate-015\n")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout, b"fixture-ready\necho:candidate-015\nfixture-eof\n")
        self.assertNotIn(SECRET.encode(), result.stdout + result.stderr)

    def test_input_requires_explicit_true_not_truthiness(self):
        env = {**self.env, "AGENT_GUI_RUNTIME_INPUT_ALLOWED": "true"}
        self.assertEqual(self.run_launcher(env=env).returncode, 7)
        recorded = json.loads((self.data / "started.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded["args"][-1], "--allow-local-input")

    def test_explicit_false_does_not_enable_input(self):
        env = {**self.env, "AGENT_GUI_RUNTIME_INPUT_ALLOWED": "false"}
        self.assertEqual(self.run_launcher(env=env).returncode, 7)
        recorded = json.loads((self.data / "started.json").read_text(encoding="utf-8"))
        self.assertNotIn("--allow-local-input", recorded["args"])

    def test_interpreter_path_also_supports_spaces_and_chinese(self):
        # 仅创建不带 pip 的临时解释器 fixture，不安装系统依赖。
        fixture_python_root = self.base / "Python \u6267\u884c environment"
        created = subprocess.run([PYTHON311, "-I", "-B", "-m", "venv", "--without-pip", str(fixture_python_root)],
                                 capture_output=True, timeout=20, check=False)
        self.assertEqual(created.returncode, 0, created.stderr)
        env = {**self.env, "AGENT_GUI_RUNTIME_PYTHON": str(fixture_python_root / "Scripts/python.exe")}
        result = self.run_launcher(env=env, input=b"unicode-executable-path\n")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout, b"fixture-ready\necho:unicode-executable-path\nfixture-eof\n")

    def test_invalid_input_setting_fails_closed(self):
        for value in ["1", "True", "yes", "", SECRET]:
            with self.subTest(value=value):
                self.assert_config_rejected({**self.env, "AGENT_GUI_RUNTIME_INPUT_ALLOWED": value}, "input_setting_invalid")

    def test_required_config_never_falls_back_or_prints_values(self):
        for key in ["AGENT_GUI_RUNTIME_ROOT", "AGENT_GUI_RUNTIME_PYTHON", "AGENT_GUI_RUNTIME_API_PROFILE", "AGENT_GUI_RUNTIME_DECISION_PROFILE", "AGENT_GUI_RUNTIME_DATA", "OPENAI_API_KEY"]:
            with self.subTest(key=key):
                env = dict(self.env)
                env.pop(key)
                self.assert_config_rejected(env, "configuration_missing")

    def test_relative_or_absent_paths_are_rejected_without_value_echo(self):
        for key in ["AGENT_GUI_RUNTIME_ROOT", "AGENT_GUI_RUNTIME_PYTHON", "AGENT_GUI_RUNTIME_API_PROFILE", "AGENT_GUI_RUNTIME_DECISION_PROFILE", "AGENT_GUI_RUNTIME_DATA"]:
            with self.subTest(key=key):
                self.assert_config_rejected({**self.env, key: SECRET}, "path_invalid")
        self.assert_config_rejected({**self.env, "AGENT_GUI_RUNTIME_API_PROFILE": str(self.base / SECRET)}, "path_invalid")

    def test_wrong_python_version_is_rejected_before_entry(self):
        self.assert_config_rejected({**self.env, "AGENT_GUI_RUNTIME_PYTHON": sys.executable}, "python_3_11_required")

    def test_unlaunchable_interpreter_has_sanitized_error(self):
        fake = self.base / (SECRET + ".exe")
        fake.write_bytes(b"not an executable")
        self.assert_config_rejected({**self.env, "AGENT_GUI_RUNTIME_PYTHON": str(fake)}, "python_probe_failed")

    def test_only_explicit_execution_014_015_markers_are_accepted(self):
        for marker in [
            {"schema": "execution_installation.v1", "component": "execution", "version": "0.1.3"},
            {"schema": "execution_installation.v1", "component": "execution", "version": "0.1.6"},
            {"schema": "execution_installation.v1", "component": "execution", "version": "1.0.0"},
            {"schema": "execution_installation.v1", "component": "execution", "version": "0.1.5-rc.1"},
            {"schema": "other", "component": "execution", "version": "0.1.4"},
            {"schema": "execution_installation.v1", "component": "learning", "version": "0.1.5"},
        ]:
            with self.subTest(marker=marker):
                self.marker.write_text(json.dumps(marker), encoding="utf-8")
                self.assert_config_rejected(self.env, "execution_0_1_4_or_0_1_5_required")
        self.marker.unlink()
        self.assert_config_rejected(self.env, "execution_0_1_4_or_0_1_5_required")

    def test_missing_original_script_cannot_start_a_replacement(self):
        self.script.unlink()
        self.assert_config_rejected(self.env, "entrypoint_missing")

    def test_unsupported_profile_secret_env_is_not_silently_rewritten(self):
        for profile, field in [(self.vision, "api_key_env"), (self.decision, "api_key_env"), (self.decision, "ordinary_review_api_key_env")]:
            with self.subTest(profile=profile.name, field=field):
                original = profile.read_text(encoding="utf-8")
                value = json.loads(original)
                value[field] = SECRET
                profile.write_text(json.dumps(value), encoding="utf-8")
                self.assert_config_rejected(self.env, "profile_requires_OPENAI_API_KEY")
                self.assertEqual(json.loads(profile.read_text(encoding="utf-8"))[field], SECRET)
                profile.write_text(original, encoding="utf-8")

    def test_bad_profile_json_does_not_echo_credentials(self):
        self.vision.write_text('{"bad":"' + SECRET, encoding="utf-8")
        self.assert_config_rejected(self.env, "profile_json_invalid")


if __name__ == "__main__":
    unittest.main()
