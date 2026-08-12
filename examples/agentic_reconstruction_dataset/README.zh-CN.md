# 基于 Reconstruction 的 Agentic CAD 数据样例

这个目录把 Fusion 360 Gallery Reconstruction 中的一条真实记录，转换成了一条已经实际执行过的 Agent 工具调用轨迹。所有源码、数据和产物都位于 `/data/yihongzhu`。

## 选用的数据

- 样本：`118433_f14b7df9_0000`
- 输入：Reconstruction JSON
- 参考答案：同名 STEP 和 PNG
- 建模历史：一次新建实体、一次对称切除、一次对称合并
- 最终形状：带中部缺口和后伸连接部的支架实体

这不是把几个现成零件做装配，而是根据草图轮廓和特征时间线，重新执行三次参数化拉伸及其布尔操作。

## 一条轨迹里有哪些工具

共执行 17 次调用，覆盖 9 类工具：

1. `reconstruction_read_sample`：解析 JSON 和特征时间线。
2. `brep_inspect_step`：检查参考 STEP 的实体、尺寸和拓扑。
3. `cad_create_profile`：把 Fusion 草图轮廓转换成边、线框和面。
4. `cad_extrude_profile`：执行单向或对称拉伸。
5. `cad_apply_feature`：执行 NewBody、Cut、Join。
6. `cad_inspect_model`：每步检查体积以及面、边、点数量。
7. `cad_export_artifacts`：导出 STEP 和可重放的模型图，并实际重放。
8. `cad_heal_same_domain`：处理当前公开接口没有暴露的容差化共面修复。
9. `brep_evaluate_reconstruction`：将最终 STEP 与参考答案做几何和拓扑比较。

工具定义采用 OpenAI function calling 格式，完整 schema 在 `out/tool_schemas.json`，完整 messages/tool results 在 `out/agentic_reconstruction_sample.jsonl`。轨迹不保存大模型隐藏思维链，只保存可审计的调用、参数、观察结果和最终结论。

## 如何与 CadFlow 接口衔接

主要建模过程只使用 CadFlow 已公开的接口：

- `make_line_redge`
- `make_wire_from_edges_rwire`
- `make_face_from_wires_rface`
- `extrude_rsolid`
- `translate_shape`
- `cut_rsolid`
- `union_rsolid`
- `ql.faces/edges/vertices`
- `export_step`
- `ModelResult.replay`

两个系统的语义并不完全相同，因此增加了明确的适配层：

- Fusion 草图局部坐标通过原点和三个基向量变换到世界坐标。
- Reconstruction 使用厘米，STEP/OpenCascade 使用毫米，进入内核前统一乘 10。
- 对称拉伸转换为“按总长度单向拉伸，再反向平移半个长度”。
- 只读取被特征选中的 profile loop，不把辅助线和参考线误当成实体边界。
- NewBody、Join、Cut 分别映射为当前实体赋值、并集和差集。

## 当前接口缺失能力怎么处理

这条数据混用了近似单精度草图坐标 `38.099999427795 mm` 和精确特征尺寸 `38.1 mm`。两者只差 `5.72e-7 mm`，Fusion 会把对应平面合并，但 CadFlow 的 `union_rsolid(clean=True)` 尚未把“同域面清理容差”暴露出来，因此初始结果会多两张共面分割面。

`brep_adapter.py` 将这个缺口包装成独立工具：

1. 调用 OpenCascade `ShapeUpgrade_UnifySameDomain`。
2. 设置 `1e-6 mm` 线性容差。
3. 导出 STEP。
4. 通过公开的 `brep.load_step_rshape(require_valid=True)` 重新读入并验证。

模型图本身不假装支持这个操作。`*.raw.step` 是模型图可直接重放的结果，`*.candidate.step` 是执行完整 Agent 工具链后的最终结果。

## 实际结果

- 17 次工具调用全部成功。
- CadFlow 模型图严格重放成功。
- 修复前拓扑：16 面、38 边、24 点。
- 修复后及目标拓扑：14 面、36 边、24 点。
- 目标体积：`419959.472656746 mm3`。
- 候选体积：`419959.472435985 mm3`。
- 相对体积误差：约 `5.26e-10`。
- 包围盒最大坐标误差：约 `5.70e-12 mm`。
- 双向材料差体积：均为 0。
- 普通几何验收：通过。
- 严格 B-Rep 门槛：未通过，因为它要求 `1e-6 mm3` 的绝对体积一致性和完全一致的带几何标签关联图，精度高于这份源 JSON 能表达的精度。

## 运行

```bash
cd /data/yihongzhu/CadFlow
/data/yihongzhu/CadFlow-venv/bin/python \
  examples/agentic_reconstruction_dataset/generate_example.py
```

主要产物位于 `examples/agentic_reconstruction_dataset/out/`。
