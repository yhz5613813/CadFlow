# CadFlow

[English](README.md) | [简体中文](README_zh.md)

CadFlow 是一个以 Python 为前端、以句柄式 C++17 OpenCascade 内核为后端的
CAD 项目。

## 从源码安装

CadFlow 支持 Python 3.10 至 3.13。从源码安装时，会在用户本机编译 C++17
后端，因此需要：

- CMake 3.16 或更高版本
- 支持 C++17 的编译器，例如 GCC、Clang 或 MSVC
- Python 开发头文件

Ubuntu/Debian 用户先安装系统构建工具：

```bash
sudo apt update
sudo apt install build-essential cmake python3-dev
```

克隆项目、创建独立虚拟环境并安装 CadFlow：

```bash
git clone https://github.com/yhz5613813/CadFlow.git
cd CadFlow

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install "cadquery-ocp==7.9.3.1"
python -m pip install --no-build-isolation .
```

应当先安装 `cadquery-ocp`，使 CMake 能找到与 OpenCascade 7.9.3 匹配的共享库。
`--no-build-isolation` 允许源码构建使用当前虚拟环境中的这些库。如果没有找到
这些库，CMake 可能只构建不依赖 OpenCascade 的解析式 fallback 后端，而不是完整
CAD 后端。

也可以直接安装源码压缩包：

```bash
python -m pip install "cadquery-ocp==7.9.3.1"
python -m pip install --no-build-isolation ./cadflow-0.1.0.tar.gz
```

如果需要输出 PNG 或检查图片，请安装可选的渲染依赖：

```bash
python -m pip install vtk pillow
```

安装后，使用下面的最小建模程序同时验证 Python 包和编译后的 C++ 后端：

```bash
python - <<'PY'
import cadflow

with cadflow.Model() as model:
    box = model.box(2, 3, 4)
    print("CadFlow", cadflow.__version__, "box volume:", box.volume)
PY
```

正常情况下，长方体体积应为 `24.0`。

目前只有 Linux x86_64 环境经过完整的 OCCT 后端源码构建测试。现有 CMake 库发现
逻辑针对 Linux `.so` 文件；Windows 和 macOS 仍需要补充对应的平台构建支持。

## 项目结构

```text
python/cadflow/           Python 模型对象、类型化计算图和分发层
python/cadflow/_engine/   按领域划分的 Python 实现
native/                   C++17 会话存储和计算图执行器
tests/                    原生后端、打包和兼容性测试
```

原生实现按照职责分层：

```text
native/src/c_api.cpp       稳定的 C ABI
native/src/core/           会话所有权、句柄和错误边界
native/src/kernel/         构造、特征、布尔运算、变换和查询
native/src/io/             网格和 CAD 数据交换
native/src/runtime/        批量计算图解释器
```

原生层通过 `ctypes` 加载一个小型 C ABI，不会跨 ABI 边界传递 `TopoDS_Shape`
对象。完整的 OpenCascade 兼容功能包含在安装包中，并可通过 `cadflow.compat`
使用。CadFlow 不会从其他源码目录动态加载文件。

当前原生后端支持基本体、折线、圆、圆弧、样条曲线、螺旋线、Bezier 曲面、拟合
网格曲面、面构造、拉伸、旋转、放样、扫掠、圆角、倒角、抽壳、布尔运算、刚体
变换、缩放、几何属性、拓扑计数、三角化、STEP 导入导出、STL 导出和批量计算图
执行。边和面以从零开始的索引跨 ABI 传递。装配、约束、语义跟踪、Scene 归档、
转换器和标准件仍由 Python 层编排。

## 构建与测试

直接开发原生后端时可以执行：

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
python -m pytest -q
python -m pip wheel . --no-deps -w dist
```

默认构建会在可用时使用匹配的 OCCT 7.9.3 头文件和共享库。可以使用
`-DCADFLOW_USE_OCCT=OFF` 构建用于冒烟测试、不依赖 OCCT 的解析式 fallback。
当 OCCT 数据交换头文件可用时，原生 STEP 写入会自动启用；也可以设置
`-DCADFLOW_WITH_STEP=OFF` 生成更小的构建。无论是否启用此选项，现有完整 STEP
API 仍可通过 `cadflow.compat` 使用。

构建生成的 wheel 包含 `libcadflow_core`、`cadflow/include/` 下的稳定公共头文件，
以及指向 `cadquery-ocp` 所提供 OCCT 动态库的相对运行时路径。只有使用外部编译
的核心库时才需要设置 `CADFLOW_CORE_LIBRARY`。新代码应优先使用 `cadflow.Model`
或 `cadflow.Graph`；完整兼容实现也包含在同一个安装包中。
