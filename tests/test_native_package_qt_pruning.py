from __future__ import annotations

import importlib.util
import json
import runpy
import struct
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "packaging" / "qt_pruning.py"
SPEC = ROOT / "packaging" / "agent_review.spec"


def _module():
    spec = importlib.util.spec_from_file_location("qt_pruning", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qt_webengine_pruning_removes_only_measured_pyside_inputs_and_keeps_unrelated_names():
    helper = _module()
    entries = [
        (r"C:\runtime\PySide6\QtWebEngineCore.pyd", "PySide6"),
        (r"C:\runtime\PySide6\Qt6WebEngineCore.dll", "PySide6"),
        (r"C:\runtime\PySide6\resources\icudtl.dat", "PySide6\resources"),
        (r"C:\runtime\PySide6\resources\v8_context_snapshot.bin", "PySide6\resources"),
        (r"C:\runtime\PySide6\Qt6Core.dll", "PySide6"),
        (r"C:\runtime\PySide6\QtWidgets.pyd", "PySide6"),
        (r"C:\runtime\PySide6\plugins\platforms\qwindows.dll", r"PySide6\plugins\platforms"),
        (r"C:\runtime\PySide6\plugins\imageformats\qjpeg.dll", r"PySide6\plugins\imageformats"),
        # 父目录可含 webengine，PySide6 自有尾部不含时不得误删。
        (r"D:\webengine-project\PySide6\Qt6Core.dll", "PySide6"),
        # 同名 Chromium 资源不属于 PySide6 时不得误删。
        (r"C:\third_party\icudtl.dat", "resources"),
    ]
    result = helper.prune_qt_webengine(entries)
    paths = {item[0] for item in result}
    assert {
        r"C:\runtime\PySide6\QtWebEngineCore.pyd",
        r"C:\runtime\PySide6\Qt6WebEngineCore.dll",
        r"C:\runtime\PySide6\resources\icudtl.dat",
        r"C:\runtime\PySide6\resources\v8_context_snapshot.bin",
    }.isdisjoint(paths)
    assert {
        r"C:\runtime\PySide6\Qt6Core.dll",
        r"C:\runtime\PySide6\QtWidgets.pyd",
        r"C:\runtime\PySide6\plugins\platforms\qwindows.dll",
        r"C:\runtime\PySide6\plugins\imageformats\qjpeg.dll",
        r"D:\webengine-project\PySide6\Qt6Core.dll",
        r"C:\third_party\icudtl.dat",
    } <= paths


def test_spec_filters_analysis_reintroduced_webengine_from_final_collect_and_excludes_modules(tmp_path, monkeypatch):
    manifest = tmp_path / "runtime-manifest.json"
    manifest.write_text(json.dumps({"packages": []}), encoding="utf-8")
    monkeypatch.setenv("AGENT_REVIEW_RUNTIME_MANIFEST", str(manifest))
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda package, **kwargs: [(r"C:\runtime\PySide6\Qt6Core.dll", "PySide6")] if package == "PySide6" else []
    hooks.collect_dynamic_libs = lambda package: [(r"C:\runtime\PySide6\QtWidgets.pyd", "PySide6")] if package == "PySide6" else []
    hooks.copy_metadata = lambda package: []
    monkeypatch.setitem(sys.modules, "PyInstaller", ModuleType("PyInstaller"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", ModuleType("PyInstaller.utils"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    captured = {}

    def analyze(entries, **kwargs):
        captured["analysis"] = kwargs
        return SimpleNamespace(
            pure=[],
            scripts=[],
            binaries=[
                *kwargs["binaries"],
                ("PySide6/Qt6WebEngineCore.dll", r"C:\runtime\PySide6\Qt6WebEngineCore.dll", "BINARY"),
            ],
            datas=[
                *kwargs["datas"],
                ("PySide6/resources/icudtl.dat", r"C:\runtime\PySide6\resources\icudtl.dat", "DATA"),
                ("resources/icudtl.dat", r"C:\third_party\icudtl.dat", "DATA"),
            ],
        )

    def collect(*args, **kwargs):
        captured["collect"] = args

    runpy.run_path(
        str(SPEC),
        init_globals={
            "SPECPATH": str(ROOT / "packaging"),
            "Analysis": analyze,
            "PYZ": lambda *args, **kwargs: None,
            "EXE": lambda *args, **kwargs: None,
            "COLLECT": collect,
        },
    )
    final_toc = [entry for argument in captured["collect"][2:] for entry in argument]
    assert not any("webengine" in str(entry).casefold() for entry in final_toc)
    assert not any("pyside6/resources/icudtl.dat" in str(entry).replace("\\", "/").casefold() for entry in final_toc)
    assert any("qt6core.dll" in str(entry).casefold() for entry in final_toc)
    assert any("qtwidgets.pyd" in str(entry).casefold() for entry in final_toc)
    assert ("resources/icudtl.dat", r"C:\third_party\icudtl.dat", "DATA") in final_toc
    excluded = captured["analysis"]["excludes"]
    assert {"PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets"} <= set(excluded)


def _pe_layout(path: Path):
    raw = path.read_bytes()
    offset = struct.unpack_from("<I", raw, 0x3C)[0]
    assert raw[offset:offset + 4] == b"PE\0\0"
    sections = struct.unpack_from("<H", raw, offset + 6)[0]
    optional_size = struct.unpack_from("<H", raw, offset + 20)[0]
    optional = offset + 24
    magic = struct.unpack_from("<H", raw, optional)[0]
    assert magic in {0x10B, 0x20B}
    directory = optional + (112 if magic == 0x20B else 96)
    image_base = struct.unpack_from("<Q" if magic == 0x20B else "<I", raw, optional + (24 if magic == 0x20B else 28))[0]
    section_start = optional + optional_size
    ranges = []
    for index in range(sections):
        base = section_start + index * 40
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from("<IIII", raw, base + 8)
        ranges.append((virtual_address, max(virtual_size, raw_size), raw_offset))

    def file_offset(rva: int) -> int:
        for virtual_address, size, raw_offset in ranges:
            if virtual_address <= rva < virtual_address + size:
                return raw_offset + rva - virtual_address
        raise AssertionError(f"import RVA {rva:x} not mapped")

    return raw, directory, image_base, file_offset


def _pe_imports(path: Path) -> set[str]:
    """读取直接与 delay import，检查保留 PySide6 DLL/pyd 的闭合关系。"""
    raw, directory, image_base, file_offset = _pe_layout(path)

    def name_at(rva: int) -> str:
        start = file_offset(rva)
        end = raw.index(b"\0", start)
        return raw[start:end].decode("ascii").casefold()

    names = set()
    import_rva = struct.unpack_from("<I", raw, directory + 8)[0]
    if import_rva:
        entry = file_offset(import_rva)
        while True:
            _lookup, _stamp, _forwarder, name_rva, _thunk = struct.unpack_from("<IIIII", raw, entry)
            if name_rva == 0:
                break
            names.add(name_at(name_rva))
            entry += 20

    # IMAGE_DELAYLOAD_DESCRIPTOR，DataDirectory[13]，每个描述符 32 字节。
    delay_rva = struct.unpack_from("<I", raw, directory + 13 * 8)[0]
    if delay_rva:
        entry = file_offset(delay_rva)
        while True:
            attributes, name_rva, _hmod, _iat, _int, _bound, _unload, _stamp = struct.unpack_from("<IIIIIIII", raw, entry)
            if not any((attributes, name_rva, _hmod, _iat, _int, _bound, _unload, _stamp)):
                break
            if not attributes & 1:
                name_rva -= image_base
            names.add(name_at(name_rva))
            entry += 32
    return names


def test_all_retained_pyside_dll_and_extension_imports_do_not_link_qtwebengine():
    import PySide6

    root = Path(PySide6.__file__).resolve().parent
    helper = _module()
    retained = [path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() in {".dll", ".pyd"}
                and not helper.is_qt_webengine_entry((str(path), "PySide6"))]
    assert len(retained) > 6
    dependencies = {str(path.relative_to(root)): _pe_imports(path) for path in retained}
    assert "qt6core.dll" in dependencies["Qt6Widgets.dll"]
    assert "qt6gui.dll" in dependencies["Qt6Widgets.dll"]
    assert not any("webengine" in dependency for names in dependencies.values() for dependency in names)


def test_current_native_entry_sources_do_not_import_qtwebengine():
    sources = [*(ROOT / "app").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")]
    hits = [path for path in sources if "qtwebengine" in path.read_text(encoding="utf-8").casefold()]
    assert hits == []
