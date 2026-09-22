"""只读发现 Windows 桌面应用；不启动程序、不执行快捷方式命令。"""

import ctypes
import hashlib
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import stat

from app.core.launch_text import has_launch_display_controls


_MAX_SHORTCUT_DEPTH = 8
_MAX_SCAN_ENTRIES = 20000
_MAX_APP_PATHS = 2048


def _local_path(value, *, directory=False):
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError("application path must be an absolute local path")
    text = os.fspath(value)
    if not isinstance(text, str) or has_launch_display_controls(text):
        raise ValueError("application path contains unsupported control characters")
    path = PureWindowsPath(text)
    if (not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ":"
            or any(part == ".." or ":" in part for part in path.parts[1:])):
        raise ValueError("application path must be an absolute local drive path")
    if os.name != "nt":
        raise ValueError("installed application discovery requires Windows")
    if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
        raise ValueError("application path must be local, not a network drive")
    try:
        resolved = Path(text).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("application path does not exist or cannot be resolved") from error
    resolved_path = PureWindowsPath(resolved)
    if len(resolved_path.drive) != 2 or ctypes.windll.kernel32.GetDriveTypeW(resolved_path.anchor) == 4:
        raise ValueError("application path must resolve to a local drive")
    if directory:
        if not resolved.is_dir():
            raise ValueError("application working directory must be an existing directory")
    elif not resolved.is_file():
        raise ValueError("application path must be an existing file")
    return ntpath.normcase(str(resolved))


def _windows_arguments(arguments):
    if not isinstance(arguments, str) or len(arguments) > 32768 or has_launch_display_controls(arguments):
        raise ValueError("shortcut arguments contain unsupported controls or exceed the length limit")
    if not arguments:
        return []
    from ctypes import wintypes

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    argc = ctypes.c_int()
    argv = shell32.CommandLineToArgvW('"shortcut.exe" ' + arguments, ctypes.byref(argc))
    if not argv:
        raise ValueError("Windows could not parse the shortcut arguments")
    try:
        result = [argv[index] for index in range(1, argc.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(argv, wintypes.HLOCAL))
    if len(result) > 63 or any(len(arg) > 8192 for arg in result):
        raise ValueError("shortcut arguments exceed the application command limit")
    return result


def _read_shortcut(path):
    try:
        import pythoncom
        import pywintypes
        from win32com.client import Dispatch
    except ImportError as error:
        raise ValueError("shortcut resolution requires the installed pywin32 dependency") from error
    pythoncom.CoInitialize()
    shell = shortcut = None
    try:
        try:
            shell = Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(str(path))
            return shortcut.TargetPath, shortcut.Arguments, shortcut.WorkingDirectory
        except pywintypes.com_error as error:
            raise ValueError("shortcut cannot be read; select a valid local .exe or .lnk file") from error
    finally:
        # COM 对象必须在当前线程公寓释放前销毁。
        shortcut = shell = None
        pythoncom.CoUninitialize()


def _record(executable, name, arguments=(), working_directory=""):
    executable = _local_path(executable)
    if PureWindowsPath(executable).suffix != ".exe":
        raise ValueError("application target must be an existing local .exe file; UWP links are unsupported")
    cwd = ""
    if working_directory:
        try:
            cwd = _local_path(working_directory, directory=True)
        except ValueError as error:
            raise ValueError("shortcut working directory must be an existing local directory") from error
    command = [executable, *arguments]
    identity = json.dumps([command, cwd], ensure_ascii=False, separators=(",", ":"))
    record = {"app_id": "discovered-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32],
              "name": name, "launch_command": command, "capabilities": []}
    if cwd:
        record["working_directory"] = cwd
    return record


def explicit_application(path):
    """解析用户指定的现存本地 .exe/.lnk，失败时给出可操作的错误。"""
    normalized = _local_path(path)
    suffix = PureWindowsPath(normalized).suffix
    name = PureWindowsPath(os.fspath(path)).stem
    if suffix == ".exe":
        return _record(normalized, name)
    if suffix != ".lnk":
        raise ValueError("select an existing local .exe or .lnk file")
    executable, arguments, cwd = _read_shortcut(normalized)
    return _record(os.path.expandvars(executable), name, _windows_arguments(arguments), os.path.expandvars(cwd))


def _shortcut_roots():
    import pywintypes
    from win32com.shell import shell, shellcon

    roots = []
    for folder in (shellcon.CSIDL_DESKTOPDIRECTORY, shellcon.CSIDL_COMMON_DESKTOPDIRECTORY,
                   shellcon.CSIDL_STARTMENU, shellcon.CSIDL_COMMON_STARTMENU):
        try:
            roots.append(Path(_local_path(shell.SHGetFolderPath(0, folder, 0, 0), directory=True)))
        except (OSError, ValueError, pywintypes.com_error):
            continue
    return sorted(set(roots), key=lambda path: str(path).casefold())


def _shortcut_paths():
    examined = 0
    pending = [(root, 0) for root in reversed(_shortcut_roots())]
    while pending and examined < _MAX_SCAN_ENTRIES:
        folder, depth = pending.pop()
        try:
            with os.scandir(folder) as iterator:
                entries = []
                for entry in iterator:
                    examined += 1
                    entries.append(entry)
                    if examined >= _MAX_SCAN_ENTRIES:
                        break
            for entry in sorted(entries, key=lambda entry: (entry.name.casefold(), entry.name)):
                try:
                    # 不沿目录联接或符号链接越出四个已知目录。
                    if entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    if entry.is_dir(follow_symlinks=False) and depth < _MAX_SHORTCUT_DEPTH:
                        pending.append((Path(entry.path), depth + 1))
                    elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".lnk"):
                        yield Path(entry.path)
                except OSError:
                    continue
        except OSError:
            continue


def _app_path_executables():
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as parent:
                    names = []
                    for index in range(min(winreg.QueryInfoKey(parent)[0], _MAX_APP_PATHS)):
                        names.append(winreg.EnumKey(parent, index))
                    for name in sorted(names, key=str.casefold):
                        try:
                            with winreg.OpenKey(parent, name, 0, winreg.KEY_READ | view) as child:
                                value, kind = winreg.QueryValueEx(child, "")
                            if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str):
                                value = os.path.expandvars(value) if kind == winreg.REG_EXPAND_SZ else value
                                value = value.strip()
                                if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                                    value = value[1:-1]
                                yield value
                        except OSError:
                            continue
            except OSError:
                continue


def discover_installed_applications():
    """枚举有界桌面/开始菜单快捷方式及 HKCU/HKLM 的双视图 App Paths。"""
    if os.name != "nt":
        return []
    candidates = []
    for path in (*_shortcut_paths(), *_app_path_executables()):
        try:
            candidates.append(explicit_application(path))
        except (ValueError, OSError):
            continue
    unique = {}
    for item in sorted(candidates, key=lambda item: (item["name"].casefold(), item["name"], item["app_id"])):
        key = (tuple(item["launch_command"]), item.get("working_directory", ""))
        chosen = unique.setdefault(key, item)
        if item["name"].casefold() != chosen["name"].casefold():
            aliases = chosen.setdefault("aliases", [])
            if item["name"].casefold() not in {name.casefold() for name in aliases}:
                aliases.append(item["name"])
    return list(unique.values())
