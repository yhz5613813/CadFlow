# CadFlow

[English](README.md) | [简体中文](README_zh.md)

CadFlow is a Python-first CAD frontend backed by a handle-oriented C++17
OpenCascade kernel.

## Installation from source

CadFlow supports Python 3.10 through 3.13. Installing from source compiles the
C++17 backend on the user's machine. The build requires:

- CMake 3.16 or newer
- A C++17 compiler (GCC, Clang, or MSVC)
- Python development headers

On Ubuntu/Debian, install the system build tools first:

```bash
sudo apt update
sudo apt install build-essential cmake python3-dev
```

Clone the repository, create an isolated environment, and install CadFlow:

```bash
git clone https://github.com/yhz5613813/CadFlow.git
cd CadFlow

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install "cadquery-ocp==7.9.3.1"
python -m pip install --no-build-isolation .
```

Installing `cadquery-ocp` before CadFlow makes the matching OpenCascade 7.9.3
shared libraries visible to CMake. `--no-build-isolation` lets the source build
use those libraries from the active virtual environment. Without them, CMake
can build the dependency-free analytic fallback instead of the complete CAD
backend.

The same process works with a source archive:

```bash
python -m pip install "cadquery-ocp==7.9.3.1"
python -m pip install --no-build-isolation ./cadflow-0.1.0.tar.gz
```

For PNG rendering and image inspection, install the optional runtime tools:

```bash
python -m pip install vtk pillow
```

Verify both the Python package and the compiled backend:

```bash
python - <<'PY'
import cadflow

with cadflow.Model() as model:
    box = model.box(2, 3, 4)
    print("CadFlow", cadflow.__version__, "box volume:", box.volume)
PY
```

The expected box volume is `24.0`.

For an interactive renderer, export the native tessellation directly as GLB:

```python
with cadflow.Model() as model:
    shape = model.box(80, 50, 8)
    shape.export_preview_glb("preview.glb", deflection=0.35)
```

`Shape.preview_mesh_buffer()` exposes the versioned C++ mesh buffer when a
custom renderer needs positions, normals, and compact indices without JSON.
`Shape.preview_glb()` wraps that buffer in CadFlow's validated triangle GLB
profile. The optional stateful Agent DSL includes an SSE/Three.js preview
service; see `agent_dsl/README.md`.

The complete OCCT-backed source build is currently tested on Linux x86_64. The
current CMake library discovery targets Linux `.so` files; Windows and macOS
builds require platform-specific CMake support that is not yet provided.

```text
python/cadflow/          Python model objects, typed graph and dispatch
python/cadflow/_engine/   domain-owned Python implementation
native/                  C++17 session store and graph executor
tests/                   native, packaging, and full compatibility tests
```

The native implementation is layered by responsibility:

```text
native/src/c_api.cpp       stable C ABI only
native/src/core/           session ownership, handles, error boundary
native/src/kernel/         construction, features, booleans, transforms, queries
native/src/io/             mesh and CAD exchange
native/src/runtime/        batch graph interpreter
```

The native layer uses a small C ABI loaded with `ctypes`, so it does not pass
`TopoDS_Shape` objects across an ABI boundary. The complete OpenCascade-based
compatibility feature set is bundled inside the installed package and remains
available through `cadflow.compat`. CadFlow does not load source files from
another checkout.

The native vertical slice includes primitives, polygon/circle/arc/spline/helix
curves, Bezier and fitted-grid surfaces, face construction, extrusion,
revolution, loft, sweep, indexed fillet/chamfer/shell features, booleans, rigid
and scale transforms, geometry properties (including length, center of mass,
and distance), topology counts, tessellation, STEP import/export, STL export,
and batch graph execution. Edge and face selections cross the ABI as zero-based
indices, never as OpenCascade objects. Assemblies, constraints, semantic
tracking, Scene archives, translators, and standard parts remain Python
orchestration.

## Build and test

For contributors working directly on the native backend:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
python -m pytest -q
python -m pip wheel . --no-deps -w dist
```

The default build uses the matching OCCT 7.9.3 headers and shared libraries
when they are available. Use `-DCADFLOW_USE_OCCT=OFF` for the dependency-free
analytic fallback used by smoke tests.
Native STEP writing is enabled when its OCCT data-exchange headers are
available; use `-DCADFLOW_WITH_STEP=OFF` for a smaller build. The complete
existing STEP API remains available through `cadflow.compat` regardless of this
option.

Built wheels contain `libcadflow_core`, the stable public header under
`cadflow/include/`, and a relative runtime path to the OCCT libraries supplied
by `cadquery-ocp`. Set `CADFLOW_CORE_LIBRARY` only when using an externally
built core. New code should use `cadflow.Model` or `cadflow.Graph`; the complete
compatibility implementation is bundled in the same wheel.
