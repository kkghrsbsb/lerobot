# Explain: piper_observe.py 单臂纯观测采集脚本

## 说明范围

解释新建的 `src/lerobot/scripts/piper_observe.py` 的设计思路、与原始 `lerobot_record.py` 的差异、数据流细节，以及 echo action 策略为何可行。

## 涉及文件

| 文件 | 角色 |
|------|------|
| `src/lerobot/scripts/piper_observe.py` | 本次新建的脚本 |
| `src/lerobot/scripts/lerobot_record.py` | 原始脚本（对照，不修改） |
| `src/lerobot/datasets/feature_utils.py` | `build_dataset_frame`、`hw_to_dataset_features` |
| `src/lerobot/datasets/pipeline_features.py` | `aggregate_pipeline_dataset_features` |
| `src/lerobot/robots/piper_follower/piper_follower.py` | `PIPERFollower`（Robot 子类） |

---

## 一、为什么需要新脚本

`lerobot_record.py` 假设必须有 action 来源（teleop 或 policy），否则：

1. `RecordConfig.__post_init__`（L242）直接 raise：
   ```python
   if self.teleop is None and self.policy is None:
       raise ValueError("Choose a policy, a teleoperator or both")
   ```
2. `record_loop` 中无 teleop/policy 时走 else 分支（L389），`continue` 跳过当前帧，**不会存任何数据**。

而单臂纯观测场景下，机械臂运动由外部独立 CAN 脚本控制，采集脚本只做读取和存储。无法也不需要提供 teleop 或 policy。

---

## 二、脚本结构

```
piper_observe.py
├── ObserveConfig          — 入口配置（无 teleop/policy 字段）
├── observe_loop()         — 单 episode 采集循环
└── observe()              — 主函数（初始化、episode 循环、清理）
    └── main()             — 入口点（注册为 piper-observe 命令）
```

### 2.1 ObserveConfig vs RecordConfig

| 字段 | RecordConfig | ObserveConfig | 说明 |
|------|-------------|--------------|------|
| `robot` | ✅ | ✅ | 不变 |
| `dataset` | ✅ | ✅ | 完全复用 `DatasetRecordConfig` |
| `teleop` | ✅ | ❌ 移除 | 无主臂 |
| `policy` | ✅ | ❌ 移除 | 无策略 |
| `display_data` | ✅ | ✅ | 不变 |
| `play_sounds` | ✅ | ✅ | 不变 |
| `resume` | ✅ | ✅ | 不变 |
| `__post_init__` 校验 | teleop/policy 必有一个 | 无校验 | 核心差异 |

### 2.2 observe_loop vs record_loop

```
record_loop（每帧）:                      observe_loop（每帧）:
  1. get_observation()                       1. get_observation()
  2. robot_observation_processor(obs)        2. robot_observation_processor(obs)
  3. build_dataset_frame(obs)                3. build_dataset_frame(obs)
  4. teleop.get_action() 或 policy          4. echo action = obs 中的关节状态
     → teleop_action_processor
  5. robot_action_processor                  （无）
  6. robot.send_action()                     （无，运动由外部控制）
  7. build_dataset_frame(action)             5. build_dataset_frame(echo_action)
  8. dataset.add_frame(frame)                6. dataset.add_frame(frame)
  9. precise_sleep(1/fps - dt)               7. precise_sleep(1/fps - dt)
```

移除了步骤 4（teleop/policy 获取 action）、5（robot_action_processor）、6（send_action）。

### 2.3 episode 间 reset 阶段

`lerobot_record.py` 在 episode 之间调用另一次 `record_loop`（不带 dataset），用 teleop 控制机械臂回到初始位置。

`piper_observe.py` 无 teleop 可操作，改为简单等待：
```python
while elapsed < reset_time_s and not events["exit_early"] and not events["stop_recording"]:
    precise_sleep(0.1)
```
用户手动 reset 环境后按键（触发 `exit_early`）确认。

---

## 三、echo action 数据流详解

### 3.1 数据来源

```python
obs = robot.get_observation()
# obs = {
#     "joint_1.pos": 0.12,      ← float
#     "joint_2.pos": -0.34,
#     ...
#     "gripper.pos": 0.05,
#     "observation.images.cam": np.ndarray(480, 640, 3)   ← 图像
# }
```

### 3.2 echo action 提取

```python
# 只取 action_features 中声明的 key（关节+夹爪），排除相机
action_values = {
    k: v for k, v in obs_processed.items()
    if k in robot.action_features
}
# action_values = {
#     "joint_1.pos": 0.12,
#     "joint_2.pos": -0.34,
#     ...
#     "gripper.pos": 0.05,
# }
```

用 `robot.action_features` 的 key 集合做过滤，比硬编码前缀更健壮。
相机 key 现在是裸名（如 `"cam"`），不会被误匹配。

### 3.3 frame 构建

```python
observation_frame = build_dataset_frame(dataset.features, obs_processed, prefix="observation")
# → {
#     "observation.state": np.array([0.12, -0.34, ..., 0.05], dtype=float32),  # shape (7,)
#     "observation.images.cam": np.ndarray(480, 640, 3),
# }

action_frame = build_dataset_frame(dataset.features, action_values, prefix="action")
# → {
#     "action": np.array([0.12, -0.34, ..., 0.05], dtype=float32),  # shape (7,)
# }

frame = {**observation_frame, **action_frame, "task": "Pick up the cube"}
# → {
#     "observation.state": np.array([...], float32),   # (7,)
#     "observation.images.cam": np.ndarray,
#     "action": np.array([...], float32),              # (7,)  — 与 observation.state 值相同
#     "task": "Pick up the cube",
# }
```

### 3.4 build_dataset_frame 内部如何工作

`build_dataset_frame(ds_features, values, prefix)` 遍历 `ds_features`：

- 对于 `key="action", ft={"dtype":"float32", "shape":(7,), "names":["joint_1.pos",...,"gripper.pos"]}`：
  - 条件：`key.startswith("action")` ✅，`dtype=="float32"` ✅，`len(shape)==1` ✅
  - 执行：`np.array([values["joint_1.pos"], values["joint_2.pos"], ..., values["gripper.pos"]], dtype=float32)`
  - 这些 key 在 `action_values` 中都存在 ✅

- 对于 `key="observation.state"` + `prefix="observation"`：同理。

- 对于 `key="observation.images.cam"` + `prefix="observation"`：
  - 条件：`dtype in ["image","video"]` ✅
  - 执行：`values["cam"]`（去掉 `"observation.images."` 前缀后的 key）
  - 但 `obs_processed` 的图像 key 是 `"observation.images.cam"`，去掉前缀后是 `"cam"`
  - `obs_processed` 中没有 `"cam"` 这个 key，但有 `"observation.images.cam"`
  - 源码：`values[key.removeprefix(f"{prefix}.images.")]` → `values["observation.images.cam".removeprefix("observation.images.")]` → `values["cam"]`

> 注意：`obs_processed` 中图像 key 是 `"observation.images.cam"`，但 `build_dataset_frame` 用 `key.removeprefix(f"{prefix}.images.")` 计算出 `"cam"`，然后从 values 中取 `"cam"`。PIPERFollower.get_observation() 返回的图像 key 格式是 `"observation.images.{name}"`。所以 `values["cam"]` 会 KeyError。
>
> **但这和 `lerobot_record.py` 面对的是相同的问题**——原始脚本也调用 `build_dataset_frame(dataset.features, obs_processed, prefix=OBS_STR)`，obs_processed 来自 `robot.get_observation()`。原始脚本能正常工作，说明框架的其他 Robot 实现在 get_observation 中返回的图像 key 不带 `"observation.images."` 前缀。
>
> PIPERFollower 的 `get_observation()` 使用了 `f"observation.images.{name}"` 作为 key。这可能是一个潜在的兼容性问题，需要在硬件测试中验证。如果确有问题，需将 key 改为不带前缀的 `name`。

---

## 四、dataset features 构建对比

### lerobot_record.py 的方式

```python
dataset_features = combine_feature_dicts(
    aggregate_pipeline_dataset_features(
        pipeline=teleop_action_processor,                    # IdentityProcessor
        initial_features=create_initial_features(
            action=robot.action_features                     # 来自 Robot
        ),
    ),
    aggregate_pipeline_dataset_features(
        pipeline=robot_observation_processor,                 # IdentityProcessor
        initial_features=create_initial_features(
            observation=robot.observation_features
        ),
    ),
)
```

action features 经过 `teleop_action_processor` pipeline（Identity），再经 `aggregate_pipeline_dataset_features` 转换。由于 pipeline 是 Identity，等价于直接调用 `hw_to_dataset_features`。

### piper_observe.py 的方式

```python
dataset_features = combine_feature_dicts(
    hw_to_dataset_features(robot.action_features, ACTION, use_video=cfg.dataset.video),
    aggregate_pipeline_dataset_features(
        pipeline=robot_observation_processor,
        initial_features=create_initial_features(
            observation=robot.observation_features
        ),
        use_videos=cfg.dataset.video,
    ),
)
```

直接调用 `hw_to_dataset_features` 跳过了 teleop_action_processor pipeline（因为没有 teleop）。**产出完全一致**：

```json
{
  "action":            {"dtype": "float32", "shape": [7], "names": ["joint_1.pos", ..., "gripper.pos"]},
  "observation.state": {"dtype": "float32", "shape": [7], "names": ["joint_1.pos", ..., "gripper.pos"]},
  "observation.images.cam": {"dtype": "video", "shape": [480, 640, 3], "names": ["height", "width", "channels"]}
}
```

经实际构建验证（`.venv/bin/python` 执行），输出与上述结构完全一致。

---

## 五、训练兼容性说明

### echo action 的物理含义

在时刻 t，`action[t] = state[t]`。含义是："在时刻 t 观测到的位置，就是机械臂在那个时刻所处的位置。"

对于 ACT 等模仿学习算法：
- 训练目标：给定 observation，预测 action
- echo action 下：`observation.state[t] == action[t]`（值完全相同）
- 看似退化，但 **action chunking**（ACT 预测未来 k 步 action 序列）使其非平凡：
  - `action[t:t+k] = state[t:t+k]`，即预测当前轨迹的未来 k 步位置
  - 如果轨迹是运动中的，这就是一个有意义的预测目标

### 后续可改进方向

- **next-state action**：离线后处理 `action[t] = state[t+1]`，更符合因果关系
- **velocity action**：`action[t] = state[t+1] - state[t]`（delta action）
- 这些都可以在采集后离线完成，**不需要修改采集脚本**

---

## 六、已知限制与风险

| 风险 | 状态 | 说明 |
|------|------|------|
| CAN 通信冲突 | **已验证无冲突** | 通过 `tests/piper/test_observe_connect.py` + `test_can_coexist.py` 确认：采集脚本 `connect(enable=True)` 使能后，外部控制脚本通过独立 PiperInterface 连接同一 CAN 总线可正常共存读写（2026-03-23 验证） |
| 图像 key 前缀 | **已修复** | `_cameras_ft` 和 `get_observation()` 已改为使用裸相机名（如 `"cam"`），与框架其他 Robot 实现一致（OpenArmFollower、LeKiwi 等均使用裸名）。`hw_to_dataset_features` 自动添加 `"observation.images."` 前缀 |
| `PiperMotorsBusConfig.port` | **已修复** | `port` 字段改为 `str | None = None`，CAN 发现延迟到 `_ensure_robot()`（首次 `connect()` 时调用）。Config 实例化和 Bus 创建均不再触发 CAN 连接 |
