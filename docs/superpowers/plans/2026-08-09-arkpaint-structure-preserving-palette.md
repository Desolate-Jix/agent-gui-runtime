# ArkPaint Structure-Preserving Palette Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild and overwrite `C:\Users\DesolateJix\Desktop\ArkPaint_v1.0.exe` with an interface-compatible build that adds deterministic structure-preserving mapping while retaining all four existing mapping methods.

**Architecture:** Extract the PyInstaller archive into a reproducible workspace and inventory the exact callable contracts used by the GUI. Implement the new mapper as an independently tested module, bridge it into the recovered application with the smallest compatible patch, build to a temporary path, run offline and GUI smoke checks, and only then replace the desktop EXE.

**Tech Stack:** Python 3.13, NumPy, Pillow, OpenCV, PySide6, PyInstaller, pytest, Python `dis`/`marshal` tooling.

## Global Constraints

- Do not create an extra backup or a second versioned desktop executable.
- Final delivery path is exactly `C:\Users\DesolateJix\Desktop\ArkPaint_v1.0.exe`.
- Do not alter ADB drawing coordinates, palette order, publish, confirmation, or other risky click behavior.
- All Chinese source comments and documents must remain UTF-8.
- Never overwrite the desktop EXE unless unit tests, sample regression, temporary build startup, and import/preview smoke checks pass.
- Never start real drawing or click publish/final confirmation during verification.

---

### Task 1: Recover and record the executable contract

**Files:**
- Create: `tools/arkpaint_rebuild/extract_contract.py`
- Create: `tools/arkpaint_rebuild/contract.json`
- Create: `tests/arkpaint_rebuild/test_contract.py`

**Interfaces:**
- Consumes: `C:\Users\DesolateJix\Desktop\ArkPaint_v1.0.exe`.
- Produces: `extract_contract(exe_path: Path, output_dir: Path) -> dict` and a checked contract containing module names, function signatures, palette order, mapping labels, resources, entry point, and original SHA-256.

- [ ] **Step 1: Write the failing contract test**

```python
def test_contract_contains_required_mapping_surface(contract):
    assert contract["python_version"] == "3.13"
    assert contract["palette_size"] == 40
    assert contract["mapping_methods"] >= {"oklab", "lab", "weighted_rgb", "rgb"}
    assert "arkpaint.imaging.processing" in contract["modules"]
    assert "arkpaint.gui.main_window" in contract["modules"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run pytest tests/arkpaint_rebuild/test_contract.py -q`

Expected: FAIL because the extractor and contract do not exist.

- [ ] **Step 3: Implement bounded PyInstaller extraction**

Use `PyInstaller.archive.readers.CArchiveReader` and its embedded `PYZ-00.pyz` reader. Write extracted code objects as Python 3.13 `.pyc` files with `importlib.util.MAGIC_NUMBER`, record `co_name`, `co_argcount`, annotations/constants, and extract non-code resources without executing recovered modules.

- [ ] **Step 4: Generate and inspect the contract**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
uv run python tools/arkpaint_rebuild/extract_contract.py `
  --exe C:\Users\DesolateJix\Desktop\ArkPaint_v1.0.exe `
  --output artifacts/arkpaint_rebuild/recovered
```

Expected: `contract.json` records 40 colors, the four mapping identifiers, recovered GUI/processing modules, resources, and SHA-256 `50652fa057188953d0c590020e47a897bf3a283dd9be53483badd22d62c3e178`.

- [ ] **Step 5: Run the contract test**

Run: `uv run pytest tests/arkpaint_rebuild/test_contract.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the recovery tooling**

```powershell
git add tools/arkpaint_rebuild/extract_contract.py tools/arkpaint_rebuild/contract.json tests/arkpaint_rebuild/test_contract.py
git commit -m "test: capture ArkPaint executable contract"
```

---

### Task 2: Implement the deterministic structure-preserving mapper

**Files:**
- Create: `tools/arkpaint_rebuild/structure_mapper.py`
- Create: `tests/arkpaint_rebuild/test_structure_mapper.py`

**Interfaces:**
- Consumes: `rgb: np.ndarray[H, W, 3]`, `palette_rgb: np.ndarray[40, 3]`.
- Produces: `map_structure_preserving(rgb: np.ndarray, palette_rgb: np.ndarray) -> np.ndarray[H, W]` containing palette indices in `[0, 39]`.
- Produces: `MappingDiagnostics` with source cluster count, output color count, per-index counts, adjacent-collapse count, and deterministic cost summary.

- [ ] **Step 1: Write failing tests for invariants**

```python
def test_official_colors_are_fixed_points():
    image = PALETTE_RGB.reshape(5, 8, 3)
    indices, diagnostics = map_structure_preserving(image, PALETTE_RGB)
    assert np.array_equal(PALETTE_RGB[indices], image)

def test_same_source_color_maps_consistently():
    image = np.array([[[31, 24, 25], [31, 24, 25]], [[52, 48, 50], [31, 24, 25]]], dtype=np.uint8)
    indices, _ = map_structure_preserving(image, PALETTE_RGB)
    assert indices[0, 0] == indices[0, 1] == indices[1, 1]

def test_adjacent_dark_clusters_do_not_all_collapse_to_black():
    image = DARK_CLUSTER_FIXTURE
    indices, diagnostics = map_structure_preserving(image, PALETTE_RGB)
    assert len(np.unique(indices)) >= 3
    assert diagnostics.adjacent_collapse_count < RGB_BASELINE_COLLAPSE_COUNT
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/arkpaint_rebuild/test_structure_mapper.py -q`

Expected: FAIL because the mapper does not exist.

- [ ] **Step 3: Implement source-cluster statistics and adjacency graph**

Use exact RGB tuples as stable clusters. Compute count, relative luminance, OKLab coordinate, bounding mask, and four-neighbor shared-boundary weights. Keep code comments minimal and in Chinese.

- [ ] **Step 4: Implement deterministic assignment**

Assign official fixed points first. Sort remaining clusters by `(-pixel_count, -boundary_weight, rgb_tuple)`. Evaluate candidates with:

```python
cost = (
    oklab_distance
    + 0.35 * luminance_order_penalty
    + 0.90 * adjacent_merge_penalty
    + 0.25 * palette_reuse_penalty
)
```

Resolve equal costs by palette index so repeated runs are byte-identical.

- [ ] **Step 5: Run focused mapper tests**

Run: `uv run pytest tests/arkpaint_rebuild/test_structure_mapper.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the mapper**

```powershell
git add tools/arkpaint_rebuild/structure_mapper.py tests/arkpaint_rebuild/test_structure_mapper.py
git commit -m "feat: add structure-preserving 40-color mapping"
```

---

### Task 3: Add the real 24×24 regression fixture

**Files:**
- Create: `tests/fixtures/arkpaint/26.8.9_19.31_24x24.png`
- Create: `tests/fixtures/arkpaint/expected_metrics.json`
- Create: `tests/arkpaint_rebuild/test_real_image_regression.py`
- Create: `tools/arkpaint_rebuild/compare_mapping.py`

**Interfaces:**
- Consumes: the user sample at `C:\Users\DesolateJix\Desktop\26.8.9_19.31_24x24.png`.
- Produces: a normalized `24×24` logical-pixel fixture, baseline and structure-preserving metrics, and comparison previews under `artifacts/arkpaint_rebuild/regression/`.

- [ ] **Step 1: Write a failing logical-grid test**

```python
def test_sample_regression_preserves_grid_and_palette(sample_rgb):
    indices, metrics = map_structure_preserving(sample_rgb, PALETTE_RGB)
    assert indices.shape == (24, 24)
    assert metrics.total_pixels == 576
    assert metrics.black_count < 211
    assert metrics.output_color_count > 12
```

- [ ] **Step 2: Normalize the fixture without interpolation**

Verify the `384×384` source consists of constant `16×16` blocks, then sample one pixel per block to create the exact `24×24` fixture. Reject the fixture if any block is non-uniform.

- [ ] **Step 3: Run the regression and inspect previews**

Run:

```powershell
uv run python tools/arkpaint_rebuild/compare_mapping.py `
  --input tests/fixtures/arkpaint/26.8.9_19.31_24x24.png `
  --output artifacts/arkpaint_rebuild/regression
uv run pytest tests/arkpaint_rebuild/test_real_image_regression.py -q
```

Expected: both commands pass; the structure preview keeps the head/background/green-region boundaries, uses only official colors, reduces black below 211, and uses more than 12 colors without obvious hue inversion.

- [ ] **Step 4: Commit the regression assets**

```powershell
git add tests/fixtures/arkpaint tests/arkpaint_rebuild/test_real_image_regression.py tools/arkpaint_rebuild/compare_mapping.py
git commit -m "test: add ArkPaint dark-region regression"
```

---

### Task 4: Bridge the mapper into the recovered GUI contract

**Files:**
- Create: `tools/arkpaint_rebuild/patch_processing.py`
- Create: `tools/arkpaint_rebuild/replacement/arkpaint/imaging/structure_mapping.py`
- Modify: recovered `arkpaint/imaging/processing.pyc` or its interface-compatible replacement generated under `artifacts/arkpaint_rebuild/work/`
- Modify: recovered `arkpaint/gui/main_window.pyc` or its interface-compatible replacement generated under `artifacts/arkpaint_rebuild/work/`
- Create: `tests/arkpaint_rebuild/test_gui_bridge.py`

**Interfaces:**
- Consumes: recovered method dispatcher and GUI label contract from Task 1; `map_structure_preserving` from Task 2.
- Produces: mapping identifier `structure_preserving`, label `结构保持40色`, and preview/export/draw paths that reuse the same computed palette-index matrix.

- [ ] **Step 1: Write failing bridge tests**

```python
def test_new_mapping_method_is_exposed(patched_contract):
    assert patched_contract["mapping_labels"]["structure_preserving"] == "结构保持40色"

def test_preview_export_and_draw_share_latest_indices(bridge):
    result = bridge.process(FIXTURE, method="structure_preserving")
    assert bridge.preview_indices is result.indices
    assert bridge.export_indices is result.indices
    assert bridge.draw_indices is result.indices
```

- [ ] **Step 2: Run bridge tests and verify they fail**

Run: `uv run pytest tests/arkpaint_rebuild/test_gui_bridge.py -q`

Expected: FAIL because the new method is not registered.

- [ ] **Step 3: Implement the smallest interface-compatible patch**

Patch only the method registry, label registry, processing dispatcher, and cached result handoff. If bytecode replacement cannot preserve the original callable signatures, stop and report the exact incompatible symbol rather than patching unrelated GUI code.

- [ ] **Step 4: Run bridge and mapper tests**

Run: `uv run pytest tests/arkpaint_rebuild/test_gui_bridge.py tests/arkpaint_rebuild/test_structure_mapper.py tests/arkpaint_rebuild/test_real_image_regression.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the bridge**

```powershell
git add tools/arkpaint_rebuild/patch_processing.py tools/arkpaint_rebuild/replacement tests/arkpaint_rebuild/test_gui_bridge.py
git commit -m "feat: expose structure-preserving mapping in ArkPaint"
```

---

### Task 5: Build and verify a temporary executable

**Files:**
- Create: `tools/arkpaint_rebuild/arkpaint_rebuild.spec`
- Create: `tools/arkpaint_rebuild/build.ps1`
- Create: `tests/arkpaint_rebuild/test_built_executable.py`
- Create: `artifacts/arkpaint_rebuild/build-manifest.json`

**Interfaces:**
- Consumes: recovered modules/resources and replacement module.
- Produces: `artifacts/arkpaint_rebuild/dist/ArkPaint_v1.0.exe` plus manifest containing source hash, build hash, size, Python/PyInstaller versions, and verification results.

- [ ] **Step 1: Write failing artifact checks**

```python
def test_build_manifest_is_bound_to_verified_artifact(manifest):
    exe = Path(manifest["artifact_path"])
    assert exe.exists()
    assert sha256(exe) == manifest["artifact_sha256"]
    assert manifest["tests_passed"] is True
    assert manifest["gui_smoke_passed"] is True
```

- [ ] **Step 2: Build to the temporary output only**

Run: `powershell -ExecutionPolicy Bypass -File tools/arkpaint_rebuild/build.ps1`

Expected: a one-file GUI executable appears only under `artifacts/arkpaint_rebuild/dist/`; the desktop EXE remains unchanged.

- [ ] **Step 3: Run offline verification**

Run:

```powershell
uv run pytest tests/arkpaint_rebuild -q
Get-FileHash -Algorithm SHA256 artifacts/arkpaint_rebuild/dist/ArkPaint_v1.0.exe
```

Expected: all tests pass and the artifact hash matches the manifest.

- [ ] **Step 4: Run the temporary GUI smoke**

Launch the temporary EXE visibly. Verify the target window title is `ArkPaint`, the mapping selector includes `结构保持40色`, importing the sample produces a `24×24` preview, and no draw/publish/final-confirm action is invoked.

- [ ] **Step 5: Commit build tooling and manifest schema**

```powershell
git add tools/arkpaint_rebuild/arkpaint_rebuild.spec tools/arkpaint_rebuild/build.ps1 tests/arkpaint_rebuild/test_built_executable.py
git commit -m "build: package patched ArkPaint executable"
```

---

### Task 6: Replace the desktop EXE and verify the final path

**Files:**
- Modify: `C:\Users\DesolateJix\Desktop\ArkPaint_v1.0.exe`
- Create: `artifacts/arkpaint_rebuild/final-verification.json`
- Update: `docs/superpowers/specs/2026-08-09-arkpaint-structure-preserving-palette-design.md` only if implementation constraints changed.

**Interfaces:**
- Consumes: verified temporary artifact and manifest from Task 5.
- Produces: the final executable at the exact user-approved path and a verification record bound to its SHA-256.

- [ ] **Step 1: Verify replacement preconditions**

Require all test and smoke flags in `build-manifest.json` to be true, confirm the source desktop path resolves exactly to `C:\Users\DesolateJix\Desktop\ArkPaint_v1.0.exe`, and close only the running ArkPaint process bound to that path.

- [ ] **Step 2: Replace the file atomically without creating a backup**

Copy the verified artifact to a sibling temporary filename, verify its SHA-256, then use a same-directory atomic replace to set the exact target path. Do not create `.bak`, `v1.1`, or another desktop copy.

- [ ] **Step 3: Verify the final artifact hash**

Run: `Get-FileHash -Algorithm SHA256 C:\Users\DesolateJix\Desktop\ArkPaint_v1.0.exe`

Expected: the hash equals the verified temporary artifact hash.

- [ ] **Step 4: Run final-path read-only smoke**

Launch the final path, verify the title and new selector, import the sample, confirm a legal 24×24 preview, and stop before drawing. Record window identity, artifact hash, output-color count, black count, and smoke result in `final-verification.json`.

- [ ] **Step 5: Run final focused verification**

Run: `uv run pytest tests/arkpaint_rebuild -q`

Expected: PASS with the final-path hash check included.

- [ ] **Step 6: Commit final verification documentation**

```powershell
git add artifacts/arkpaint_rebuild/build-manifest.json artifacts/arkpaint_rebuild/final-verification.json docs/superpowers/specs/2026-08-09-arkpaint-structure-preserving-palette-design.md
git commit -m "docs: record verified ArkPaint rebuild"
```

