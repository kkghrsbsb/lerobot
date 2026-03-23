# Review: 基于 lerobot_record.py 设计单臂纯观测数据采集脚本

## 审查范围

分析 `lerobot_record.py` 的完整调用链和数据流，评估在"单臂纯观测"场景下（无 teleoperator、不由采集脚本控制运动、机械臂运动由外部独立 CAN 命令驱动）如何新建一个采集脚本，使其产出兼容 lerobot 训练 pipeline 的数据集。

## 审查文件

| 文件 | 角色 |
|------|------|
| `src/lerobot/scripts/lerobot_record.py` | 原始数据采集脚本（不修改） |
| `src/lerobot/datasets/feature_utils.py` | feature 定义、frame 构建、校验逻辑 |
| `src/lerobot/datasets/pipeline_features.py` | pipeline → dataset feature 聚合 |
| `src/lerobot/datasets/lerobot_dataset.py` | `LeRobotDataset.create` / `add_frame` / `save_episode` |
| `src/lerobot/robots/piper_follower/piper_follower.py` | `PIPERFollower`（observation_features / action_features） |
| `src/lerobot/robots/robot.py` | Robot 基类 |
| `src/lerobot/processor/factory.py` | 默认 processor pipeline |
| `src/lerobot/utils/constants.py` | 常量定义（ACTION、OBS_STR 等） |

---

## 一、lerobot_record.py 完整调用链分析

### 1.1 入口与初始化（`record()` 函数，L437–L603）

```
record(cfg: RecordConfig)
  │
  ├── make_robot_from_config(cfg.robot)         → Robot 实例
  ├── make_teleoperator_from_config(cfg.teleop)  → Teleoperator 实例（可选）
  ├── make_default_processors()                  → 三个 IdentityProcessor pipeline
  │     ├── teleop_action_processor   (teleop_action, obs) → action
  │     ├── robot_action_processor    (action, obs) → action
  │     └── robot_observation_processor obs → obs
  │
  ├── dataset_features 构建 ──────────────────────────────────┐
  │     combine_feature_dicts(                                │
  │       aggregate_pipeline_dataset_features(                │
  │         pipeline=teleop_action_processor,                 │
  │         initial_features=create_initial_features(         │
  │           action=robot.action_features  ← 关键：来自 Robot │
  │         ),                                                │
  │       ),                                                  │
  │       aggregate_pipeline_dataset_features(                │
  │         pipeline=robot_observation_processor,             │
  │         initial_features=create_initial_features(         │
  │           observation=robot.observation_features          │
  │         ),                                                │
  │       ),                                                  │
  │     )                                                     │
  │     结果：{"action": {...}, "observation.state": {...},    │
  │            "observation.images.xxx": {...}}                │
  │                                                           │
  ├── LeRobotDataset.create(features=dataset_features)        │
  ├── robot.connect()                                         │
  ├── teleop.connect()（如果有）                                │
  └── 进入 episode 循环 ──→ record_loop()                      │
```

**关键发现**：

- `dataset_features` 的 **action 部分**来自 `robot.action_features`（而非 teleop）。代码注释也确认了这一点（L458: `# TODO: in future this should come from teleop or policy`）。
- `RecordConfig.__post_init__` 在 L242 强制要求 `teleop is not None or policy is not None`，否则 raise。**这是新脚本必须绕过的限制。**

### 1.2 record_loop 数据流（L282–L434）

每个 loop 迭代的完整数据流：

```
┌─────────────── record_loop 单次迭代 ───────────────────────┐
│                                                            │
│  1. obs = robot.get_observation()                          │
│     → dict: {"joint_1.pos": 0.1, ..., "gripper.pos": 0.0, │
│              "observation.images.cam": np.array}           │
│                                                            │
│  2. obs_processed = robot_observation_processor(obs)       │
│     → Identity，直接透传                                    │
│                                                            │
│  3. observation_frame = build_dataset_frame(               │
│       dataset.features, obs_processed, prefix="observation"│
│     )                                                      │
│     → {"observation.state": np.array([j1,j2,...,grip],     │
│         dtype=float32),                                    │
│        "observation.images.cam": np.array}                 │
│                                                            │
│  4. 获取 action（三选一）:                                   │
│     a) policy → predict_action → act_processed_policy      │
│     b) teleop → teleop.get_action() → teleop_action_proc  │
│        → act_processed_teleop                              │
│     c) 无 → warning + continue（跳过本帧！不存到数据集）     │
│                                                            │
│  5. robot_action_to_send = robot_action_processor(         │
│       (action_values, obs))                                │
│     → Identity，直接透传                                    │
│                                                            │
│  6. robot.send_action(robot_action_to_send)                │
│     → 发送控制指令到硬件                                    │
│                                                            │
│  7. action_frame = build_dataset_frame(                    │
│       dataset.features, action_values, prefix="action")    │
│     → {"action": np.array([j1,j2,...,grip], float32)}      │
│                                                            │
│  8. frame = {**observation_frame, **action_frame,          │
│              "task": single_task}                           │
│     dataset.add_frame(frame)                               │
│                                                            │
│  9. precise_sleep(1/fps - dt)                              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**关键发现**：

- **步骤 4c**：若既无 teleop 也无 policy，循环会 `continue`，**不会记录任何帧**。这就是为什么原脚本不适用于"纯观测"模式——它认为没有 action 源就没有数据可记录。
- **步骤 6**：`robot.send_action()` 是硬耦合在循环中的。在纯观测模式下必须移除。
- **步骤 7**：`build_dataset_frame` 根据 `dataset.features` 中的 `"action"` key 提取对应 names，从 `action_values` dict 中按 name 组装 numpy array。names 来自 `robot.action_features` 的键列表。

### 1.3 build_dataset_frame 详解（feature_utils.py L140–L166）

```python
def build_dataset_frame(ds_features, values, prefix):
    frame = {}
    for key, ft in ds_features.items():
        if key in DEFAULT_FEATURES or not key.startswith(prefix):
            continue
        elif ft["dtype"] == "float32" and len(ft["shape"]) == 1:
            # 对于 "action" 和 "observation.state"：
            # 按 ft["names"] 的顺序，从 values dict 取对应值
            frame[key] = np.array(
                [values[name] for name in ft["names"]], dtype=np.float32
            )
        elif ft["dtype"] in ["image", "video"]:
            frame[key] = values[key.removeprefix(f"{prefix}.images.")]
    return frame
```

- 对于 `prefix="action"`：只处理 key 以 `"action"` 开头的 feature → 即 `"action"` 本身。
- `ft["names"]` = `["joint_1.pos", "joint_2.pos", ..., "gripper.pos"]`（来自 `robot.action_features`）。
- 它从 `values` dict 中用这些 name 取值。所以 **action_values 的键必须包含 `joint_1.pos`, `joint_2.pos`, ..., `gripper.pos`**。

### 1.4 PIPERFollower 的 feature 定义

```python
# action_features (cached_property)
→ _motors_ft → {"joint_1.pos": float, ..., "gripper.pos": float}

# observation_features (cached_property)
→ {**_motors_ft, **_cameras_ft}
→ {"joint_1.pos": float, ..., "gripper.pos": float,
   "observation.images.cam": (480, 640, 3)}
```

经过 `aggregate_pipeline_dataset_features` + `hw_to_dataset_features` 转换后，最终 dataset_features 为：

```python
{
    "action": {
        "dtype": "float32",
        "shape": (7,),
        "names": ["joint_1.pos", ..., "gripper.pos"],
    },
    "observation.state": {
        "dtype": "float32",
        "shape": (7,),
        "names": ["joint_1.pos", ..., "gripper.pos"],
    },
    "observation.images.cam": {
        "dtype": "video",  # 或 "image"
        "shape": (480, 640, 3),
        "names": ["height", "width", "channels"],
    },
}
```

**结论**：action 和 observation.state 的 names 列表完全相同（都是 7 个关节+夹爪），形状相同 `(7,)`。

---

## 二、可直接复用的部分

| 组件 | 可否复用 | 说明 |
|------|---------|------|
| `DatasetRecordConfig` | ✅ 完全复用 | fps、video、push_to_hub 等配置不变 |
| `LeRobotDataset.create` | ✅ 完全复用 | 只要 features dict 格式正确 |
| `LeRobotDataset.add_frame` | ✅ 完全复用 | frame 是 dict，格式由 features 定义 |
| `LeRobotDataset.save_episode` | ✅ 完全复用 | 不关心数据来源 |
| `build_dataset_frame` | ✅ 完全复用 | 按 prefix 和 names 组装 |
| `combine_feature_dicts` | ✅ 完全复用 | 合并 action 和 observation features |
| `aggregate_pipeline_dataset_features` | ✅ 完全复用 | pipeline → dataset features |
| `make_default_processors` | ✅ 部分复用 | 只需 `robot_observation_processor`；action 相关的两个 processor 不再需要 |
| `init_keyboard_listener` | ✅ 复用 | episode 控制（exit_early、stop、rerecord）仍需要 |
| `VideoEncodingManager` | ✅ 复用 | 视频编码流程不变 |
| `robot.connect/disconnect` | ✅ 复用 | 连接逻辑不变 |
| `robot.get_observation` | ✅ 核心复用 | 这是新脚本的唯一数据源 |

## 三、必须修改或移除的部分

| 组件 | 处理方式 | 原因 |
|------|---------|------|
| `RecordConfig.__post_init__` 校验 | **新建** ObserveConfig 替代 | 原始校验 `teleop is None and policy is None → raise` |
| `teleop = make_teleoperator_from_config(...)` | **移除** | 无主臂 |
| `teleop.connect()` / `teleop.disconnect()` | **移除** | 无主臂 |
| `teleop.get_action()` | **移除** | 无外部 action 源 |
| `teleop_action_processor` | **移除** | 无 teleop action |
| `robot_action_processor` | **移除** | 无 action 发送 |
| `policy` 相关全部代码 | **移除** | 纯观测模式不需要策略 |
| `robot.send_action()` | **移除** | 采集脚本不控制运动 |
| `predict_action()` | **移除** | 无策略推理 |
| record_loop 中的 action 获取分支 | **用 obs-as-action 替代** | 见下节 |

---

## 四、action 字段处理建议

### 4.1 问题本质

lerobot 的数据集格式和训练 pipeline 强制要求 `"action"` 字段存在：

1. **`LeRobotDataset` 层面**：`add_frame` 的 `validate_frame` 要求 frame 中包含 features 定义的所有键，`"action"` 是 features 的一部分。
2. **训练 pipeline 层面**：ACT 等模仿学习算法将 `(observation, action)` 对作为训练样本。`action` 是必需的监督信号。如果缺失 action，数据集无法用于训练。
3. **数据集统计**：`save_episode` 会对 action 计算 min/max/mean/std，用于后续归一化。

### 4.2 推荐方案：action = 当前观测 state（"echo action"）

**将当前帧观测到的关节状态直接作为该帧的 action 值。**

```python
obs = robot.get_observation()
# obs = {"joint_1.pos": 0.1, ..., "gripper.pos": 0.05, "observation.images.cam": ...}

# 从 obs 中提取关节状态作为 action
action_values = {k: v for k, v in obs.items() if not k.startswith("observation.images.")}
```

**优势**：
- **完全兼容数据集格式**：action 的 names 和 shape 与 observation.state 完全一致。
- **物理含义合理**：在外部独立控制的场景下，机械臂在时刻 t 的实际位置就是"在那个时刻执行的动作的结果"。对于低频采集（30Hz），当前 state 近似等于导致该 state 的 action。
- **训练兼容性好**：ACT 等算法在训练时学习的是 `observation → action` 的映射。如果 action 就是 "下一时刻应该到达的位置"，那么 `action[t] ≈ state[t]` 在没有时间差的情况下是一个合理的退化形式。真正训练时，可以考虑用 `action[t] = state[t+1]`（见备选方案）。
- **实现极简**：无需额外的硬件通信或数据源。

### 4.3 备选方案：action = 下一帧 state（"next-state action"）

```python
# 采集时先全部存为 action[t] = state[t]（echo）
# 后处理脚本中平移：action[t] = state[t+1]，最后一帧丢弃或复制
```

**优势**：更符合因果关系，action[t] 表示 "时刻 t 的控制目标导致了时刻 t+1 的状态"。

**劣势**：需要后处理步骤；episode 最后一帧需要特殊处理。

**建议**：**先用方案 4.2 落地**，后续如训练效果不佳再通过离线后处理转为 4.3。两者在数据集格式上完全一致，只是数值有一帧时移。

### 4.4 不推荐的方案

- **填零 action**：`action = [0, 0, ..., 0]`。会导致归一化统计失真，训练时学到"永远不动"。
- **省略 action 字段**：不可行，`validate_frame` 和 `validate_episode_buffer` 都要求 features 完整匹配。
- **修改 LeRobotDataset 使 action 可选**：侵入框架代码，违反修改范围约束，且训练 pipeline 也需要 action。

---

## 五、新脚本设计建议

### 5.1 文件位置与命名

```
src/lerobot/scripts/piper_observe.py   ← 新建
```

不修改 `lerobot_record.py`。

### 5.2 入口配置

```python
@dataclass
class ObserveConfig:
    robot: RobotConfig
    dataset: DatasetRecordConfig     # 完全复用
    display_data: bool = False
    display_ip: str | None = None
    display_port: int | None = None
    display_compressed_images: bool = False
    play_sounds: bool = True
    resume: bool = False
    # 无 teleop、无 policy 字段

    # 无需 __post_init__ 中的 teleop/policy 校验
```

### 5.3 observe_loop 核心（简化版 record_loop）

```python
def observe_loop(
    robot: Robot,
    events: dict,
    fps: int,
    robot_observation_processor: RobotProcessorPipeline,
    dataset: LeRobotDataset,
    control_time_s: float,
    single_task: str,
    display_data: bool = False,
    display_compressed_images: bool = False,
):
    timestamp = 0
    start_episode_t = time.perf_counter()

    while timestamp < control_time_s:
        start_loop_t = time.perf_counter()

        if events["exit_early"]:
            events["exit_early"] = False
            break

        # 1. 读取观测（关节 + 相机）
        obs = robot.get_observation()
        obs_processed = robot_observation_processor(obs)

        # 2. 构建 observation frame
        observation_frame = build_dataset_frame(
            dataset.features, obs_processed, prefix=OBS_STR
        )

        # 3. echo action：用当前关节状态作为 action
        action_values = {
            k: v for k, v in obs_processed.items()
            if not k.startswith("observation.images.")
        }
        action_frame = build_dataset_frame(
            dataset.features, action_values, prefix=ACTION
        )

        # 4. 存帧
        frame = {**observation_frame, **action_frame, "task": single_task}
        dataset.add_frame(frame)

        # 5. 可视化（可选）
        if display_data:
            log_rerun_data(
                observation=obs_processed,
                action=action_values,
                compress_images=display_compressed_images,
            )

        # 6. 帧率控制
        dt_s = time.perf_counter() - start_loop_t
        precise_sleep(max(1 / fps - dt_s, 0.0))
        timestamp = time.perf_counter() - start_episode_t
```

**对比 record_loop 的精简**：

| record_loop 步骤 | observe_loop | 说明 |
|-----------------|-------------|------|
| robot.get_observation() | ✅ 保留 | 唯一数据源 |
| robot_observation_processor | ✅ 保留 | 透传即可 |
| build_dataset_frame(obs) | ✅ 保留 | 不变 |
| teleop.get_action() | ❌ 移除 | 无主臂 |
| teleop_action_processor | ❌ 移除 | |
| predict_action() | ❌ 移除 | 无策略 |
| robot_action_processor | ❌ 移除 | |
| robot.send_action() | ❌ 移除 | 不控制运动 |
| build_dataset_frame(action) | ✅ 保留 | 用 echo action |
| dataset.add_frame() | ✅ 保留 | 不变 |

### 5.4 observe() 主函数框架

```python
@parser.wrap()
def observe(cfg: ObserveConfig) -> LeRobotDataset:
    # 初始化同 record()，但：
    # - 无 teleop
    # - 无 policy
    # - dataset_features 仍需包含 action（来自 robot.action_features）
    #   和 observation（来自 robot.observation_features）

    robot = make_robot_from_config(cfg.robot)

    _, _, robot_observation_processor = make_default_processors()

    # feature 构建：action features 仍需声明（echo action 用）
    dataset_features = combine_feature_dicts(
        hw_to_dataset_features(robot.action_features, ACTION, cfg.dataset.video),
        aggregate_pipeline_dataset_features(
            pipeline=robot_observation_processor,
            initial_features=create_initial_features(
                observation=robot.observation_features
            ),
            use_videos=cfg.dataset.video,
        ),
    )

    # dataset 创建（同 record）
    dataset = LeRobotDataset.create(...)

    robot.connect()
    listener, events = init_keyboard_listener()

    with VideoEncodingManager(dataset):
        recorded_episodes = 0
        while recorded_episodes < cfg.dataset.num_episodes and not events["stop_recording"]:
            observe_loop(...)

            # reset 阶段：不调 observe_loop（无 teleop 可操作）
            # 直接等待用户手动 reset + 按键确认
            if ...:
                log_say("Reset the environment", cfg.play_sounds)
                # 等待 exit_early 事件
                wait_for_user_signal(events, timeout=cfg.dataset.reset_time_s)

            if events["rerecord_episode"]:
                ...
                continue

            dataset.save_episode()
            recorded_episodes += 1

    # finally 同 record()
```

### 5.5 action feature 构建的注意事项

在 `record()` 中，action features 走了 `aggregate_pipeline_dataset_features(pipeline=teleop_action_processor, ...)`。由于 `teleop_action_processor` 是 IdentityProcessor，实际效果等价于直接调用 `hw_to_dataset_features(robot.action_features, ACTION, use_video)`。

在新脚本中，可以直接调用 `hw_to_dataset_features` 跳过不必要的 pipeline：

```python
from lerobot.datasets.feature_utils import hw_to_dataset_features

action_ds_features = hw_to_dataset_features(
    robot.action_features, ACTION, use_video=cfg.dataset.video
)
```

这样更简洁，也避免了引入 `teleop_action_processor` 的依赖。

---

## 六、兼容性分析

### 6.1 数据集格式兼容性

| 维度 | 是否兼容 | 说明 |
|------|---------|------|
| features 结构 | ✅ | action(7,)、observation.state(7,)、observation.images.* 完全一致 |
| frame 格式 | ✅ | add_frame 只检查 features 和 task 是否完整 |
| episode 存储 | ✅ | save_episode 不关心数据来源 |
| 统计信息 | ✅ | echo action 的 min/max/mean/std 与 state 相同，归一化正常 |
| video 编码 | ✅ | streaming encoding 可正常使用 |

### 6.2 训练 pipeline 兼容性

| 维度 | 是否兼容 | 说明 |
|------|---------|------|
| ACT 训练输入格式 | ✅ | (observation, action) 对结构正确 |
| 归一化 | ✅ | action 统计值有意义 |
| action chunking | ⚠️ 需注意 | ACT 用 action chunk（多步 action 序列），echo action 下 action[t:t+k] 就是 state[t:t+k]，物理含义是"维持当前轨迹"。这在大多数情况下可用，但精确度取决于采集帧率和运动速度 |
| delta action | ⚠️ 需注意 | 如果训练用 delta action 模式（action = 位移而非绝对位置），echo action 在该模式下的 delta 为 state[t]-state[t-1]，需确认算法端是否正确处理 |

### 6.3 PIPERFollower 连接行为

当前 `PIPERFollower.connect()` 流程：
1. `bus.connect(enable=True)` → 使能机械臂 + 夹爪
2. `bus.apply_calibration()` → 机械臂阻塞式移动到零位

在纯观测模式下，`connect(enable=True)` 会使能机械臂并占据 CAN 通信。**可能问题**：如果外部脚本也通过 CAN 发送控制命令，两者可能冲突。

**建议**：可能需要为 `PIPERFollower` 增加一个 `observe_only=True` 模式（或新建 `PiperObserver` Robot 子类），在此模式下：
- `connect()` 只建立 CAN 连接和相机连接，**不使能机械臂**（不调 `reset_arm`）
- `calibrate()` 为 no-op（不移动到零位）
- `send_action()` 为 no-op 或直接 raise
- `get_observation()` 不变（只读操作，不需要使能也能读取关节状态——需验证 `piper_control` 在未使能状态下是否能 `get_joint_positions()`）

> **风险**：需要验证 `piper_control.PiperInterface` 在机械臂未使能的情况下，`get_joint_positions()` 和 `get_gripper_state()` 是否仍然返回有效数据。如果不能，则仍需使能，但不发送控制命令。

---

## 七、实现步骤建议

1. **验证 piper_control 只读可用性**：在硬件上测试未使能状态下 `get_joint_positions()` 是否返回有效值
2. **新建 `src/lerobot/scripts/piper_observe.py`**：包含 `ObserveConfig`、`observe_loop`、`observe` 函数
3. **考虑是否需要 `PiperObserver` Robot 子类**：取决于步骤 1 的结果
4. **端到端测试**：运行新脚本，同时用外部脚本控制机械臂运动，验证数据集格式和内容
5. **训练验证**：用采集的数据集训练 ACT 模型，确认 echo action 的训练效果

---

## 八、总结

| 问题 | 结论 |
|------|------|
| 能否基于 lerobot_record.py 改造？ | 可以，新建脚本复用大部分基础设施 |
| 需要修改多少代码？ | 新脚本约 150–200 行；可能需要新 Robot 子类或配置选项 |
| action 怎么处理？ | 推荐 echo action（action=当前 state），后续可离线转为 next-state |
| 训练 pipeline 兼容吗？ | 完全兼容，echo action 有合理的物理含义 |
| 最大风险？ | CAN 通信冲突（采集脚本与外部控制脚本共用 CAN）和未使能下只读可用性 |
