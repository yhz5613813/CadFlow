# 难样本运行记录：138539_b5a9ff56_0000

这是比 `118433_f14b7df9_0000` 更复杂的一条 Fusion 360 Gallery Reconstruction 数据。

## 复杂度

- 活动特征：29 个
- `NewBody`：1 个
- `Join`：14 个
- `Cut`：14 个
- 多 profile 特征：4 个，分别包含 4、2、2、2 个 profile
- 全部 profile carrier：`Line3D`，因此复杂度主要来自长布尔历史和多 profile 语义
- 参考 STEP：110 面、326 边、207 点

## 实际执行

- 工具调用：133 次
- 工具类型：9 类
- 所有调用成功
- 每个特征后都调用 `cad_inspect_model`
- `ModelResult.replay(strict=True)` 成功
- 渲染 PNG 已生成

工具轨迹中多 profile 特征会产生多个 `cad_create_profile` 和
`cad_extrude_profile` 调用，然后把多个 solid handle 放进一次
`cad_apply_feature`。Join/Cut 按 profile 顺序逐个执行，保持了单实体
Fusion 历史的材料语义。

## 评估

- 目标体积：`333565532.9999999 mm3`
- 候选体积：`333565532.99999946 mm3`
- 相对体积误差：`1.25e-15`
- 表面积误差：`0`
- 包围盒最大误差：`0`
- 双向材料差体积：`0 / 0`
- 边界 Hausdorff 近似：`0`
- 候选拓扑：`110 / 326 / 207`
- 严格 B-Rep：通过

同域修复前候选为 `115 / 335 / 211`，`cad_heal_same_domain` 将近似共面
分割面归一化为目标拓扑 `110 / 326 / 207`。

## 产物

产物位于：

```text
/data/yihongzhu/CadFlow/examples/agentic_reconstruction_dataset/out_hard/
```

主要文件：

- `agentic_reconstruction_sample.jsonl`
- `138539_b5a9ff56_0000.raw.step`
- `138539_b5a9ff56_0000.candidate.step`
- `138539_b5a9ff56_0000.candidate.views.png`
- `138539_b5a9ff56_0000.model.json`
- `138539_b5a9ff56_0000.evaluation.json`

## 重跑

```bash
cd /data/yihongzhu/CadFlow
CADFLOW_SAMPLE_ID=138539_b5a9ff56_0000 \
CADFLOW_AGENT_OUTPUT=/data/yihongzhu/CadFlow/examples/agentic_reconstruction_dataset/out_hard \
/data/yihongzhu/CadFlow-venv/bin/python \
examples/agentic_reconstruction_dataset/generate_example.py
```
