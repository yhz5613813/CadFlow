---
name: cadflow-realtime-preview
description: Add, operate, or debug revision-driven real-time rendering for CadFlow native Shape objects and the stateful Agent DSL. Use when work involves preview mesh buffers, browser-ready GLB output, Scene 1.0 compilation, background tessellation, SSE revision events, the Three.js preview workbench, or stale-render and preview-latency problems in this repository.
---

# CadFlow Real-Time Preview

## Overview

Build previews at committed revision boundaries. Keep native tessellation in
C++, use public `cadflow` interfaces in Python, and publish only complete Scene
artifacts to the browser.

## Choose the Path

- Use `Shape.preview_mesh_buffer()` for a custom renderer that needs compact
  float32 positions/normals and uint16/uint32 indices.
- Use `Shape.preview_glb()` or `Shape.export_preview_glb()` for a direct native
  model preview without Scene semantics or CAD edge assets.
- Use `agent_dsl.RealtimePreview` for stateful DSL revisions, Scene manifests,
  edge GLBs, SSE delivery, and the bundled Three.js workbench.

Do not route user code through `cadflow._engine`, OCP objects, native handles,
or direct shared-library loading. Import `cadflow as cad` and use the public
frontend or Scene facade.

## Implement a Revision Preview

1. Apply or merge the DSL document through `ModelStore`; never render an
   uncommitted prospective model.
2. Obtain the committed live result through `apply_with_model()` and
   `AgentModel.result_value` to avoid a second replay. When the document has a
   `preview SHAPE QUALITY` effect, resolve that committed target through
   `AgentModel.named_value()` instead of silently falling back to `result`.
3. Schedule one background build per model. Replace pending work with the
   newest build and check the build ID again before promotion.
4. Compile draft Scenes with linear/angular tolerances `0.35/0.22`; compile
   final Scenes with `0.1/0.08`.
5. Write blobs first, write `scene.json` last, then atomically promote the
   latest descriptor.
6. Emit `revision_pending`, `revision_ready`, or `revision_failed`. Include
   model, revision, build, quality, and the manifest URL where applicable.
7. In the viewer, reject older revision/build pairs, swap the model root as one
   operation, preserve OrbitControls state, and fit the camera only for the
   first successful scene.

Treat `preview SHAPE [draft|final]` as an effect. Keep it out of durable command
history and do not increment the revision for an effect-only submission.

## Preserve the Native Contract

Keep the `CFMB` buffer versioned and little-endian. Its header is
`<4sIIII6f>`, followed by position float32 values, normal float32 values, and
triangle indices. Convert CAD `(x, y, z)` millimeters to glTF
`(x, z, -y) / 1000`. Correct reversed faces, normalize vertex normals, encode
positive zero, rotate each triangle to its minimum cyclic ordering, and sort
triangle records before wrapping the buffer as a closed-profile GLB.

Always validate native GLBs with:

```python
cad.scene.preflight_glb(payload, expected_kind="triangle")
```

## Run and Verify

Build and test with the requested project environment:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE=/data/yihongzhu/SimpleCADAPI-venv/bin/python
cmake --build build --parallel 2

/data/yihongzhu/SimpleCADAPI-venv/bin/python -m pip install \
  --no-build-isolation --no-deps .

PYTHONPATH=.:python /data/yihongzhu/SimpleCADAPI-venv/bin/python \
  -m pytest -q agent_dsl/tests/test_realtime.py

PYTHONPATH=python \
CADFLOW_CORE_LIBRARY="$PWD/build/native/libcadflow_core.so" \
  /data/yihongzhu/SimpleCADAPI-venv/bin/python \
  -m pytest -q tests/test_native_backend.py::test_native_preview_buffer_and_glb_profile
```

Start the workbench with:

```bash
PYTHONPATH=.:python /data/yihongzhu/SimpleCADAPI-venv/bin/python \
  -m agent_dsl.realtime --host 127.0.0.1 --port 8765
```

Verify `/`, submit one revision through `/models/{id}/apply`, wait for
`revision_ready`, fetch its manifest and GLBs, and inspect the workbench at a
desktop and mobile viewport. Check the browser console and confirm the canvas
contains non-background pixels before finishing frontend changes.

## Diagnose Failures

- If the C ABI symbol is missing, rebuild/install CadFlow and confirm
  `cadflow.__file__` and `CADFLOW_CORE_LIBRARY` point at the intended build.
- If strict GLB preflight fails, fix canonical buffer ordering or padding; do
  not weaken the validator.
- If the browser shows stale geometry, compare both revision and build ID and
  confirm only the current build promotes `latest.json`.
- If the model is blank, inspect `revision_failed`, fetch the manifest and GLBs
  directly, then check WebGL canvas pixels and the browser console.
- If latency grows with history, ensure the preview uses the live model
  returned by `apply_with_model()` rather than calling `ModelStore.open()`
  immediately after every apply.
