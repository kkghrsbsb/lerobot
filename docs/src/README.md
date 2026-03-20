# Piper 机械臂 lerobot 适配项目

## 项目目标

本仓库是 [huggingface/lerobot](https://github.com/huggingface/lerobot) 的 fork，在 `feat/piper-robot-adapter` 分支上进行 **Piper 机械臂** 的适配工作。

最终目标：让 Piper 机械臂能够通过 lerobot 的标准流程完成 **数据采集（`lerobot_record.py`）、模型训练、策略评估** 三大环节，实现基于 ACT 等模仿学习算法的自主操作。

## 架构概览

lerobot 框架对硬件的抽象分为三层：

```
lerobot_record.py
  ├── Robot (从臂 / follower) — 接收动作指令，驱动关节运动，采集观测
  ├── Teleoperator (主臂 / leader) — 读取操作员的关节动作作为遥操作信号
  └── MotorsBus — 底层电机总线通信
```

Piper 适配需要实现以下三个模块，使其符合框架的抽象接口：

| 层级 | 基类 | Piper 实现 | 文件 |
|------|------|-----------|------|
| Robot | `Robot` (robot.py) | `PIPERFollower` | `src/lerobot/robots/piper_follower/piper_follower.py` |
| Teleoperator | `Teleoperator` (teleoperator.py) | `PIPERLeader` | `src/lerobot/teleoperators/piper_leader/piper_leader.py` |
| MotorsBus | — | `PiperMotorsBus` | `src/lerobot/motors/piper/piper.py` |

## 控制库

- **`piper_control`**（通过 `uv add piper-control` 安装）：对底层 `piper_sdk` 的高层封装，提供 CAN 连接管理、关节位置控制器、安全断连等功能。
- **`piper_sdk`**（`piper_control` 的底层依赖）：直接与 Piper 硬件通信的 CAN 协议库。

适配代码应当基于 `piper_control` 编写，而非直接调用 `piper_sdk`。

### `piper_control` API 速查

以下 API 来自用户的实验仓库 `piper_control_demo`（导出在 `docs/ref_project/` 下），展示了 `piper_control` 的典型用法：

**连接与初始化**
```python
from piper_control import piper_connect, piper_init, piper_interface, piper_control

# CAN 连接
ports = piper_connect.find_ports()
piper_connect.activate(ports)
ports = piper_connect.active_ports()  # e.g. ["can0"]

# 创建机器人句柄
robot = piper_interface.PiperInterface(can_port=ports[0])
robot.set_installation_pos(piper_interface.ArmInstallationPos.UPRIGHT)

# 使能（内置位置/速度模式）
piper_init.reset_arm(
    robot,
    arm_controller=piper_interface.ArmController.POSITION_VELOCITY,
    move_mode=piper_interface.MoveMode.JOINT,
)
piper_init.reset_gripper(robot)
robot.enable_gripper()
```

**读取状态**（单位已经是弧度，无需手动转换）
```python
robot.get_joint_positions()    # → list[float], 6 个关节，单位 rad
robot.get_joint_velocities()   # → list[float]
robot.get_gripper_state()      # → (gripper_pos, gripper_effort)
robot.is_arm_enabled()         # → bool
robot.is_gripper_enabled()     # → bool
robot.gripper_angle_max        # 夹爪最大开度
robot.gripper_effort_max       # 夹爪最大力
```

**关节控制（内置位置/速度模式）**
```python
with piper_control.BuiltinJointPositionController(robot, rest_position=None) as ctrl:
    robot.set_arm_mode(speed=10)  # speed ∈ [0, 100]，低值更安全
    ctrl.command_joints([j1, j2, j3, j4, j5, j6])       # 发送 6 关节目标位
    ctrl.move_to_position(target, threshold=0.01, timeout=12.0)  # 阻塞式到位
    robot.command_gripper(position, effort)               # 夹爪指令
```

**安全关闭**
```python
piper_init.disable_arm(robot)   # 失能机械臂
robot.disable_gripper()          # 失能夹爪
robot.disable_arm()              # 也可直接调用
```

**碰撞保护**
```python
robot.set_collision_protection([5, 5, 5, 5, 5, 5])  # 6 关节各自的等级
robot.get_collision_protection()                       # 读回验证
```

> **关键发现**：`piper_control` 已内置弧度单位转换。`robot.get_joint_positions()` 直接返回 rad，`command_joints()` 接受 rad。
> 这意味着参考实现（`ref_only_*`）中的 `joint_factor = 57324.840764` 手动换算在新实现中 **不需要**。

## 当前进度

### 已完成

- 项目结构搭建：三个适配模块的目录和配置文件已创建。
- `PIPERFollowerConfig` / `PIPERLeaderConfig` 已通过 `@RobotConfig.register_subclass` / `@TeleoperatorConfig.register_subclass` 注册到框架。
- 参考实现（`ref_only_*` 文件）已从 [Kane1440/lerobot_piper2](https://github.com/Kane1440/lerobot_piper2) 引入，作为只读对照。
- `piper_follower.py` 和 `piper_leader.py` 已有初步实现，包括 `connect`、`disconnect`、`calibrate`、`get_observation`/`get_action`、`send_action` 等方法骨架。

### 进行中 / 待完成

1. **`PiperMotorsBus` 重写**（`piper.py`）
   - 当前状态：仅有 `connect_can()` 和构造函数的框架代码，标注了 `# todo: 参考 ref_only_piper.py`。
   - 需要实现：`connect`、`read`、`write`、`safe_disconnect`、`apply_calibration` 等核心方法，全部基于 `piper_control` API 而非 `piper_sdk`。
   - 这是整个适配的 **核心瓶颈**——Follower 和 Leader 都依赖此类。

2. **框架注册**
   - `piper_follower` 和 `piper_leader` 尚未在 `lerobot_record.py` 的 import 列表中注册。需要在 `src/lerobot/robots/__init__.py`（或 `lerobot_record.py` 的显式 import）中添加，才能通过 `--robot.type=piper_follower` 调用。

3. **单位与标定**
   - 参考实现中关节单位为 0.001 度（piper_sdk 原始单位），通过 `joint_factor = 57324.840764` 转换为弧度。
   - **已确认**：`piper_control` 的 `get_joint_positions()` 直接返回弧度，`command_joints()` 接受弧度。新实现中不需要 `joint_factor` 换算。
   - 夹爪单位：`piper_control` 提供 `robot.gripper_angle_max` 属性，`command_gripper(position, effort)` 的 position 范围约为 `[0, 0.1]`。需确认与 lerobot 数据格式的对齐。

4. **安全机制**
   - 断连流程：当前 `disconnect()` 中先 `safe_disconnect()`（移到安全位置），等待 5 秒，再 disable。需要验证 `piper_control` 是否提供了更可靠的关闭序列。
   - 急停（e-stop）：当前代码中未实现键盘急停。`piper_control` 提供了软件层 e-stop 能力，应在控制循环中集成。

5. **相机集成**
   - `PIPERFollowerConfig` 中相机配置已注释掉（默认空 dict）。实际采集时需要配置 OpenCV 相机。

6. **端到端验证**
   - 最终需要通过 `lerobot-record --robot.type=piper_follower --teleop.type=piper_leader ...` 完成一次完整的数据采集，确认数据格式、帧率、关节角度范围均正确。

## 关键路径（依赖顺序）

```
PiperMotorsBus 完整实现 (piper.py)
    ↓
PIPERFollower + PIPERLeader 调通 (调用 PiperMotorsBus)
    ↓
框架注册 (lerobot_record.py 可识别 piper_follower / piper_leader)
    ↓
单机遥操作测试 (主臂读 → 从臂写)
    ↓
lerobot-record 端到端数据采集
    ↓
ACT 模型训练与评估
```

## 文件索引

### 适配代码（活跃开发）

| 文件 | 说明 |
|------|------|
| `src/lerobot/motors/piper/piper.py` | `PiperMotorsBus` — 电机总线封装（**核心，待完成**） |
| `src/lerobot/robots/piper_follower/piper_follower.py` | `PIPERFollower` — 从臂 Robot 适配 |
| `src/lerobot/robots/piper_follower/config_piper_follower.py` | 从臂配置（含相机定义） |
| `src/lerobot/teleoperators/piper_leader/piper_leader.py` | `PIPERLeader` — 主臂遥操作适配 |
| `src/lerobot/teleoperators/piper_leader/config_piper_leader.py` | 主臂配置 |

### 参考代码（只读，基于 piper_sdk）

| 文件 | 说明 |
|------|------|
| `src/lerobot/motors/piper/ref_only_piper.py` | 参考 PiperMotorsBus 实现 |
| `src/lerobot/robots/piper_follower/ref_only_piper_follower.py` | 参考 PIPERFollower 实现 |
| `src/lerobot/teleoperators/piper_leader/ref_only_piper_leader.py` | 参考 PIPERLeader 实现 |

### 框架入口

| 文件 | 说明 |
|------|------|
| `src/lerobot/scripts/lerobot_record.py` | 数据采集主脚本 |
| `src/lerobot/robots/robot.py` | `Robot` 抽象基类 |
| `src/lerobot/teleoperators/teleoperator.py` | `Teleoperator` 抽象基类 |

## 硬件信息

- **Piper 机械臂**：6 自由度关节 + 1 夹爪，通过 CAN 总线通信。
- 典型配置：一对 Piper 臂（主臂 + 从臂），主臂用于遥操作，从臂执行动作。
- CAN 端口命名约定：从臂 `can_follower`，主臂 `can_master`。

## 相关参考资料

- `docs/ref_project/kkghrsbsb-piper_control_demo-*.txt` — 用户的 `piper_control_demo` 实验仓库导出，展示了 `piper_control` 库在真实硬件上的完整使用模式（连接、使能、控制、状态读取、安全关闭）。是适配工作中 `piper_control` API 用法的核心参考。
- `docs/src/reference/piper-act-deployment/` — 知乎专栏系列文章，记录了 Piper + ACT 的部署过程。
