"""使用现有 Host 静态边界，不安装扩展、不启动 MCP。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/amadeus_agent_gui"
HOST = os.environ.get("AGENT_GUI_TEST_HOST_ROOT", "")


@unittest.skipUnless(HOST, "Set AGENT_GUI_TEST_HOST_ROOT to the existing Amadeus source tree")
class HostContractTests(unittest.TestCase):
    def test_canonical_manifest_and_skill_resources_are_accepted(self):
        manifest = PACKAGE / "amadeus-extension.json"
        self.assertTrue(manifest.is_file(), "MCP and Skill manifest has not been supplied")
        result = subprocess.run([sys.executable, "-I", "-B", str(Path(HOST) / "tools/extension_package.py"),
                                 "validate-installed", str(PACKAGE), "--manifest", str(manifest)],
                                capture_output=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_native_projection_binds_secret_only_in_env_and_defaults_input_off(self):
        manifest = PACKAGE / "amadeus-extension.json"
        self.assertTrue(manifest.is_file(), "MCP projection needs the package manifest")
        script = '''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from agent_host.extension_mcp import project_extension_mcp_connections
m=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
entry={'manifest':m,'enabled':True,'providers':['pi'],'python_path':sys.executable,
 'package_path':str(Path(sys.argv[2]).parent),'data_path':'D:/synthetic extension data',
 'config':{'runtime_root':'D:/synthetic Runtime','runtime_python':'D:/runtime python/python.exe',
 'api_profile':'D:/profiles/vision.json','decision_profile':'D:/profiles/decision.json'},
 'secrets':{'api_key':'synthetic-binding-secret'}}
s=project_extension_mcp_connections(entry)[0]
assert s.command==sys.executable
assert list(s.arguments)==['-I','-m','amadeus_agent_gui']
assert s.environment['OPENAI_API_KEY']=='synthetic-binding-secret'
assert s.environment['AGENT_GUI_RUNTIME_INPUT_ALLOWED']=='false'
assert s.environment['AGENT_GUI_RUNTIME_ROOT']=='D:/synthetic Runtime'
assert s.environment['AGENT_GUI_RUNTIME_PYTHON']=='D:/runtime python/python.exe'
assert s.environment['AGENT_GUI_RUNTIME_DATA']=='D:/synthetic extension data/runtime'
assert 'synthetic-binding-secret' not in s.command+' '.join(s.arguments)
assert tuple(s.provider_ids)==('pi',)
entry['enabled']=False
assert project_extension_mcp_connections(entry)==()
print('native-projection-ok')
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", script, HOST, str(manifest)],
                                capture_output=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), b"native-projection-ok")


if __name__ == "__main__":
    unittest.main()
