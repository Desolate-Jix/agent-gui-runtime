import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.desktop_review import installed_applications as installed


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows application discovery")


def test_explicit_executable_has_stable_identity_and_no_capabilities(tmp_path):
    executable = tmp_path / "Example App.exe"
    executable.write_bytes(b"fixture")
    first = installed.explicit_application(str(executable))
    second = installed.explicit_application(str(executable).upper())
    assert first["app_id"] == second["app_id"]
    assert first["launch_command"] == second["launch_command"]
    assert first["app_id"].startswith("discovered-")
    assert first["launch_command"] == [str(executable).lower()]
    assert first["capabilities"] == []


@pytest.mark.parametrize("value", ["app.exe", r"C:app.exe", r"\\server\share\app.exe",
                                  r"\\?\C:\app.exe", "https://example.com/app.exe",
                                  "C:\\bad\napp.exe"])
def test_explicit_rejects_nonlocal_or_relative_paths(value):
    with pytest.raises(ValueError, match="local|absolute|control"):
        installed.explicit_application(value)


def test_explicit_rejects_missing_directory_and_wrong_type(tmp_path):
    with pytest.raises(ValueError, match="exist"):
        installed.explicit_application(str(tmp_path / "missing.exe"))
    folder = tmp_path / "folder.exe"
    folder.mkdir()
    with pytest.raises(ValueError, match="file"):
        installed.explicit_application(str(folder))
    text = tmp_path / "example.txt"
    text.write_text("fixture", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.exe.*\.lnk"):
        installed.explicit_application(str(text))


def test_shortcut_keeps_windows_arguments_and_working_directory(tmp_path, monkeypatch):
    executable = tmp_path / "Example.exe"
    executable.touch()
    shortcut = tmp_path / "Example.lnk"
    shortcut.touch()
    args = ["--profile", "A B", "", 'a"b', "C:\\space dir\\", "&not-shell"]
    monkeypatch.setattr(installed, "_read_shortcut", lambda path: (
        str(executable), subprocess.list2cmdline(args), str(tmp_path)))
    entry = installed.explicit_application(str(shortcut))
    assert entry["launch_command"] == [str(executable).lower(), *args]
    assert entry["working_directory"] == str(tmp_path).lower()


def test_shortcut_rejects_broken_target_and_working_directory(tmp_path, monkeypatch):
    shortcut = tmp_path / "Broken.lnk"
    shortcut.touch()
    monkeypatch.setattr(installed, "_read_shortcut", lambda path: (
        str(tmp_path / "gone.exe"), "", ""))
    with pytest.raises(ValueError, match="exist"):
        installed.explicit_application(str(shortcut))
    executable = tmp_path / "Example.exe"
    executable.touch()
    monkeypatch.setattr(installed, "_read_shortcut", lambda path: (
        str(executable), "", str(tmp_path / "gone")))
    with pytest.raises(ValueError, match="working directory"):
        installed.explicit_application(str(shortcut))


def test_discovery_deduplicates_command_and_cwd_not_names(tmp_path, monkeypatch):
    executable = tmp_path / "Example.exe"
    executable.touch()
    paths = [tmp_path / f"{name}.lnk" for name in ("A", "B", "C", "D", "Broken")]
    for path in paths:
        path.touch()
    targets = {
        "a.lnk": (str(executable), "", ""),
        "b.lnk": (str(executable).upper(), "", ""),
        "c.lnk": (str(executable), "--Profile", ""),
        "d.lnk": (str(executable), "--profile", str(tmp_path)),
        "broken.lnk": (str(tmp_path / "gone.exe"), "", ""),
    }
    monkeypatch.setattr(installed, "_shortcut_paths", lambda: iter(reversed(paths)))
    monkeypatch.setattr(installed, "_read_shortcut", lambda path: targets[Path(path).name.lower()])
    monkeypatch.setattr(installed, "_app_path_executables", lambda: iter([str(executable)]))
    entries = installed.discover_installed_applications()
    assert len(entries) == 3
    assert entries[0]["name"] == "A"
    assert entries[0]["aliases"] == ["B", "Example"]
    assert len({entry["app_id"] for entry in entries}) == 3
    assert sorted(entry["launch_command"][1:] for entry in entries) == [[], ["--Profile"], ["--profile"]]
    monkeypatch.setattr(installed, "_shortcut_paths", lambda: iter(paths))
    assert installed.discover_installed_applications() == entries


def test_shortcut_scan_stays_under_known_roots_and_depth_limit(tmp_path, monkeypatch):
    root = tmp_path / "Desktop"
    root.mkdir()
    (root / "visible.lnk").touch()
    (tmp_path / "outside.lnk").touch()
    (root / "not-shortcut.txt").touch()
    child = root / "nested"
    child.mkdir()
    (child / "hidden.lnk").touch()
    monkeypatch.setattr(installed, "_shortcut_roots", lambda: [root])
    monkeypatch.setattr(installed, "_MAX_SHORTCUT_DEPTH", 0)
    assert list(installed._shortcut_paths()) == [root / "visible.lnk"]


def test_registry_covers_both_hives_and_views_without_treating_path_value_as_cwd(monkeypatch):
    class Key:
        def __init__(self, hive, view, child=False):
            self.hive, self.view, self.child = hive, view, child

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def open_key(parent, name, reserved, access):
        if isinstance(parent, Key):
            return Key(parent.hive, parent.view, True)
        if name != r"Software\Microsoft\Windows\CurrentVersion\App Paths":
            raise AssertionError("unexpected registry scan scope")
        return Key(parent, access & 6)

    def query_value(key, name):
        if name != "" or not key.child:
            raise AssertionError("only default executable values are supported")
        return f'"C:\\Apps\\{key.hive}-{key.view}.exe"', 1

    fake = SimpleNamespace(HKEY_CURRENT_USER="user", HKEY_LOCAL_MACHINE="machine",
                           KEY_WOW64_32KEY=2, KEY_WOW64_64KEY=4, KEY_READ=8,
                           REG_SZ=1, REG_EXPAND_SZ=2, OpenKey=open_key,
                           QueryInfoKey=lambda key: (1, 0, 0),
                           EnumKey=lambda key, index: "Example.exe", QueryValueEx=query_value)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert set(installed._app_path_executables()) == {
        r"C:\Apps\user-2.exe", r"C:\Apps\user-4.exe",
        r"C:\Apps\machine-2.exe", r"C:\Apps\machine-4.exe"}


def test_missing_known_folder_does_not_hide_other_known_roots(tmp_path, monkeypatch):
    import pywintypes
    from win32com.shell import shell, shellcon

    def folder_path(hwnd, folder, token, flags):
        if folder == shellcon.CSIDL_COMMON_DESKTOPDIRECTORY:
            raise pywintypes.com_error(-2147024894, "missing known folder", None, None)
        return str(tmp_path)

    monkeypatch.setattr(shell, "SHGetFolderPath", folder_path)
    assert installed._shortcut_roots() == [Path(str(tmp_path).lower())]


def test_real_shortcut_resolution_is_read_only_and_com_cleanup_is_balanced(tmp_path):
    import pythoncom
    from win32com.client import Dispatch

    executable = tmp_path / "Example.exe"
    executable.touch()
    shortcut_path = tmp_path / "Example.lnk"
    pythoncom.CoInitialize()
    try:
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(shortcut_path))
        shortcut.TargetPath = str(executable)
        shortcut.Arguments = '--mode "read only"'
        shortcut.WorkingDirectory = str(tmp_path)
        shortcut.Save()
        shortcut = shell = None
    finally:
        pythoncom.CoUninitialize()
    before = shortcut_path.read_bytes()
    script = ("import sys; from app.desktop_review.installed_applications import explicit_application; "
              "entries=[explicit_application(sys.argv[1]) for _ in range(12)]; "
              "assert all(x == entries[0] for x in entries); "
              "assert entries[0]['launch_command'][1:] == ['--mode', 'read only']; print('ok')")
    run = subprocess.run([sys.executable, "-c", script, str(shortcut_path)],
                         cwd=Path(__file__).resolve().parents[1],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "ok"
    assert not run.stderr
    assert shortcut_path.read_bytes() == before
