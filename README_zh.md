<p align="center">
  <img src="docs/assets/cadflow-logo.png" width="168" alt="CadFlow logo">
</p>

<h1 align="center">CadFlow</h1>

<p align="center">
  <strong>面向智能体的 CAD 基础设施</strong>
</p>

<p align="center">
  提供一个Agentic CAD Infra框架，构建可编程几何、获取结构化反馈
</p>

<p align="center">
  <a href="https://www.python.org/"><img alt="Python 3.10–3.13" src="https://img.shields.io/badge/Python-3.10--3.13-3776AB?logo=python&logoColor=white"></a>
  <img alt="C++ 17" src="https://img.shields.io/badge/C++-17-00599C?logo=cplusplus&logoColor=white">
  <img alt="OpenCascade 7.9.3" src="https://img.shields.io/badge/OpenCascade-7.9.3-334155">
  <img alt="Platform Linux x86-64" src="https://img.shields.io/badge/Platform-Linux%20x86--64-FCC624?logo=linux&logoColor=black">
  <a href="http://119.28.82.252/"><img alt="在线文档" src="https://img.shields.io/badge/Docs-Online-2563EB?logo=readthedocs&logoColor=white"></a>
  <a href="LICENSE"><img alt="License MIT" src="https://img.shields.io/badge/License-MIT-0F766E"></a>
  <img alt="Status Alpha" src="https://img.shields.io/badge/Status-Alpha-F59E0B">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README_zh.md">简体中文</a>
</p>

<p align="center">
  <a href="#why-cadflow">🧭 核心优势</a> ·
  <a href="#quick-start">🚀 快速开始</a> ·
  <a href="#capabilities">🧰 能力概览</a> ·
  <a href="#roadmap">🗺️ 未来规划</a> ·
  <a href="#architecture">🏗️ 系统架构</a> ·
  <a href="#agent-workflows">🤖 Agent 工作流</a>
</p>

---

CadFlow 是面向**程序化建模与几何驱动智能体**的 CAD SDK。CadFlow 不是 Text-to-3D 模型，也不是 LLM 应用。它是这些系统下方的确定性 Agentic CAD Infra：Python 程序或智能体描述建模意图，CadFlow 构建并测量几何，将可操作的事实反馈给调用方。

<a id="why-cadflow"></a>

## 🧭 为什么选择 CadFlow

### 为智能体设计的 CAD 执行边界

`Shape.describe()`、`Shape.validate()`、`Model.capabilities()`、`Model.preflight()` 和 `Model.apply()` 返回结构化、JSON-safe 的报告。智能体可以直接判断操作支持情况、无效拓扑、实体数量、包围盒、体积和修复建议，而不必解析不稳定的控制台文本。

### 原生几何计算，不泄漏内核对象

Python 侧只持有轻量的 `(session_token, shape_id)` 句柄，不会让 `TopoDS_Shape` 跨越 ABI 边界。C++ Session 管理几何对象，并在靠近 OpenCascade 的位置完成构造、布尔运算、三角化、测量和数据交换等高成本操作。

### 可编辑、可重放的工程状态

CadFlow 同时支持直接 Session 建模、类型化批处理图、可重放 Model JSON、语义标签、来源映射和谱系记录。最终结果保留为可检查的 Python 程序和结构化数据，而不是一次不透明的网格生成过程。

### 从建模到交付的一体化路径

同一个软件包覆盖几何构造、拓扑检查、BREP 对比、STEP/STL 交换、GLB 预览、装配和经过验证的 Scene 归档。建模、验证与交付共享同一个几何事实来源。

<a id="quick-start"></a>

## 🚀 快速开始

```python
import cadflow as cad


with cad.Model() as model:
    plate = model.box(80, 50, 8)

    bore = model.cylinder(radius=6, height=12)
    bore = model.translate(bore, 20, 25, -2)
    part = model.cut(plate, bore)

    report = part.validate()
    if not report.ok:
        raise RuntimeError(report.to_dict())

    print(part.describe())
    part.export_step("mounting_plate.step")
    part.export_preview_glb("mounting_plate.glb")
```

`cadflow.Model` 管理原生 Session，返回的每个 `cadflow.Shape` 都归属于该 Session。应用代码无需接触 OpenCascade 对象，即可查询、验证、三角化或导出最终 Shape。

根据工作流选择合适的 API 层：

| API | 适用场景 |
| --- | --- |
| `cadflow.Model` / `cadflow.Shape` | 交互式构造、检查与导出 |
| `cadflow.Graph` | 通过一次原生调用执行类型化的多操作计划 |
| 领域模块 | 草图、装配、Scene 归档、序列化、检查和标准件 |
| `cadflow.compat` | 原生迁移期间保持完整兼容功能面 |

新的集成应优先从 `cadflow.Model` 或 `cadflow.Graph` 开始，并通过公开领域模块使用更高层工作流。

<a id="capabilities"></a>

## 🧰 能力概览

| 领域 | 当前能力 |
| --- | --- |
| 实体建模 | 长方体、圆柱、球体、圆台、轮廓、面、拉伸、旋转、放样、扫掠、圆角、倒角和抽壳 |
| 几何操作 | 精确 OCCT 布尔运算、刚体变换、缩放、缝合、壳转实体和子形状提取 |
| 曲线与曲面 | 直线、圆弧、样条、螺旋线、Bezier 曲面、拟合 B-spline 曲面、直纹/填充/Gordon 曲面和扭转扫掠 |
| 草图与上下文 | 不可变坐标系、工作平面、声明式草图、约束和 `py-slvs` 求解 |
| 几何检查 | 体积、面积、长度、质心、距离、包围盒、拓扑计数、法向、曲率、自由边界和 BREP 对比 |
| 数据交换与预览 | STEP 导入导出、BREP/STL 导入、STL 导出、原生网格缓冲区和经过验证的三角形 GLB 预览 |
| 产品结构 | 装配、连接器、约束报告、语义标签、来源映射、谱系、材料和标准件 |
| 结构化产物 | Model JSON、严格重放、Schema 验证，以及包含可渲染几何和结构化元数据的便携式 Scene 归档 |

几何密集型操作正逐步迁移到原生 C++ Session。约束、装配、语义、诊断、序列化和其他结构化数据工作流则有意保留在 Python：将它们迁移到 ABI 另一侧只会增加复杂度，并不能消除几何计算瓶颈。

<a id="roadmap"></a>

## 🗺️ 未来规划

CadFlow 正在持续开发。后续工作将重点围绕以下方向展开：

- [ ] 支持跨平台部署。
- [ ] 开源配套的 Agentic Model，以及对应的训练数据和训练代码。
- [ ] 支持 CUDA 加速。

<a id="architecture"></a>

## 🏗️ 系统架构

<p align="center">
  <img src="docs/assets/cadflow-architecture.svg" width="100%" alt="CadFlow 系统架构：Python 应用与 CAD 智能体通过公开 Python 前端，跨越稳定 C ABI 进入原生运行时和 OpenCascade，最终生成经过验证的 CAD、预览、Scene 与诊断产物。">
</p>

核心路径为：**Python 前端 → 稳定 C ABI → C++ Session / ShapeHandle → OpenCascade**。高层编排保留在 Python，几何所有权和计算密集型任务则留在原生层。

如需了解框架模型，请阅读 [ARCHITECTURE.md](ARCHITECTURE.md)。

<a id="agent-workflows"></a>

## 🤖 Agent 工作流

CadFlow 为 CAD 智能体提供稳定的执行与反馈边界。

```text
自然语言 CAD 任务
        ↓
智能体编写 Python 建模程序
        ↓
CadFlow 构建并检查确定性几何
        ↓
结构化诊断 ──→ 有针对性的源码修复
        ↓
经过验证的 CAD / Scene 产物
```

仓库提供按需展开的 [CAD Skills](skills/)，覆盖刚性零件建模、柔性几何、STEP/BREP 重建、验证导出和实时预览。智能体可以只加载当前任务需要的工作流和准确 API 参考，而不必在每次提示中塞入完整 CAD 手册。

[CadFlowAgent](https://github.com/zion-zion-zion/CadFlowAgent) 是基于这一边界构建的独立上层应用。它提供 LLM Harness、项目工作区、执行与修复循环、实时进度、浏览器 Viewer 和运行记录；CadFlow 则负责几何、测量、数据交换和 Scene 编译。

> [!NOTE]
> [`agent_dsl/`](agent_dsl/) 是用于紧凑有状态指令协议的隔离实验层，它可以大幅度减少生成过程的token消耗，我们将在后续版本逐步优化。

## 📦 从源码安装

### 环境要求

- Linux x86_64，用于当前已测试的完整 OCCT 构建
- Python 3.10 至 3.13
- CMake 3.16 或更高版本
- 支持 C++17 的编译器
- Python 开发头文件

Ubuntu 或 Debian 用户可以执行：

```bash
sudo apt update
sudo apt install build-essential cmake python3-dev
```

克隆仓库，并在构建 CadFlow 前安装 OpenCascade 运行时：

```bash
git clone https://github.com/yhz5613813/CadFlow.git
cd CadFlow

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install "cadquery-ocp==7.9.3.1"
python -m pip install --no-build-isolation .
```

先安装 `cadquery-ocp`，可以让 CMake 找到匹配的 OpenCascade 7.9.3 头文件和共享库。`--no-build-isolation` 允许源码构建发现当前环境中的这些文件。

验证 Python 包和编译后的后端：

```bash
python - <<'PY'
import cadflow

with cadflow.Model() as model:
    box = model.box(2, 3, 4)
    print("CadFlow", cadflow.__version__, "box volume:", box.volume)
PY
```

预期体积为 `24.0`。

如需 PNG 渲染和图片检查，请安装可选运行时工具：

```bash
python -m pip install vtk pillow
```


## 🗂️ 仓库结构

```text
CadFlow/
├── python/cadflow/          公开 Python 前端与领域 Facade
├── python/cadflow/_engine/  内置的完整 Python 功能层
├── native/                  C++17 Session、几何内核、数据交换与计算图运行时
├── scene-contract/          跨语言 Scene Schema 与验证器
├── skills/                  面向 Agent 的 CAD 工作流与 API 参考
├── examples/                零件、装配、柔性模型与重建示例
├── docs/                    架构、指南与自动生成的 API 文档
├── agent_dsl/               可选的实验性有状态 Agent 封装
└── tests/                   原生、打包、兼容性与工作流测试
```

推荐从以下内容开始探索：

- [现代 Python 前端](docs/guides/modern-frontend.md)
- [架构与原生所有权](ARCHITECTURE.md)
- [原生迁移矩阵](MIGRATION_MATRIX.md)
- [工程指南](docs/guides/)
- [API 参考](docs/api/)
- [标准件](docs/stdlib/)
- [柔性建模](docs/flexible-modeling.md)
- [示例](examples/)
- [Scene Contract](scene-contract/)

## 🧪 构建与测试

开发原生后端时可以执行：

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
python -m pytest -q
python -m pip wheel . --no-deps -w dist
```

默认构建会在可用时使用匹配的 OCCT 7.9.3 头文件和库。使用 `-DCADFLOW_USE_OCCT=OFF` 可以构建解析式 fallback；使用 `-DCADFLOW_WITH_STEP=OFF` 可以生成不包含原生 STEP 写入功能的较小构建。完整的兼容 STEP API 仍可通过 `cadflow.compat` 使用。

构建生成的 wheel 包含 `libcadflow_core`、`cadflow/include/` 下的稳定公共头文件，以及指向 `cadquery-ocp` 所提供 OCCT 动态库的相对运行时路径。只有明确使用外部编译的核心库时，才需要设置 `CADFLOW_CORE_LIBRARY`。

## 🙏 致谢

CadFlow 基于 [Open CASCADE Technology（OCCT）](https://dev.opencascade.org/) 构建，感谢其提供稳健的 CAD 几何基础；同时感谢 [SimpleCADAPI](https://github.com/NiJingzhe/SimpleCADAPI) 项目的开源工作与启发。

## 📄 许可证

CadFlow 采用 [MIT License](LICENSE)。OpenCascade 相关声明见 [NOTICE-OCCT.md](NOTICE-OCCT.md)。
