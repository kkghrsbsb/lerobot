# Piper × LeRobot 适配项目总览

本文档是理解和维护本仓库的首要入口。每次改动涉及项目结构、脚本用法、依赖关系或安全注意事项时，应同步更新此文件。

---

## 项目背景

本仓库是 [huggingface/lerobot](https://github.com/huggingface/lerobot) 的 fork，工作分支为 `feat/piper-robot-adapter`。

**目标**：将 AgileX Piper 六轴机械臂（含夹爪）接入 lerobot 框架，使其能够通过 `lerobot-record` 脚本完成遥操作数据采集，并最终支持训练和评估流程。

**控制库**：`piper_control`（通过 `uv add piper-control` 安装），是对底层 `piper_sdk` 的高层封装，屏蔽了 CAN 协议细节并内置单位转换（返回 rad）。

---

## 仓库结构（适配相关部分）

```
src/lerobot/
├── motors/piper/
│   ├── piper.py                  ← 主动开发：PiperMotorsBus（电机总线封装）
│   └── ref_only_piper.py         ← 只读参考：原始 piper_sdk 实现，禁止修改
│
├── robots/piper_follower/
│   ├── piper_follower.py         ← 主动开发：PIPERFollower（Robot 子类）
│   ├── config_piper_follower.py  ← PIPERFollowerConfig（已注册到框架）
│   ├── ref_only_piper_follower.py← 只读参考，禁止修改
│   └── __init__.py
│
└── teleoperators/piper_leader/
    ├── piper_leader.py           ← 主动开发：PIPERLeader（Teleoperator 子类）
    ├── config_piper_leader.py    ← PIPERLeaderConfig（已注册到框架）
    ├── ref_only_piper_leader.py  ← 只读参考，禁止修改
    └── __init__.py

src/lerobot/scripts/
└── lerobot_record.py             ← 框架主入口，适配工作最终目标，禁止修改
```

> `ref_only_*` 文件来自 [Kane1440/lerobot_piper2](https://github.com/Kane1440/lerobot_piper2)，基于裸 `piper_sdk` 实现，仅供对照阅读，**不得修改**。

---

## 调用链与接口关系

```
lerobot-record
    │
    ├── Robot: PIPERFollower          (robots/piper_follower/piper_follower.py)
    │       └── PiperMotorsBus        (motors/piper/piper.py)
    │               └── piper_control.piper_interface.PiperInterface   ← CAN 通信
    │
    └── Teleoperator: PIPERLeader     (teleoperators/piper_leader/piper_leader.py)
            └── PiperMotorsBus        (motors/piper/piper.py)
                    └── piper_control.piper_interface.PiperInterface   ← CAN 通信
```

`lerobot-record` 的调用流程（每 episode）：
1. `robot.connect()` → `bus.connect(enable=True)` → CAN 使能 + `robot.calibrate()`
2. `teleop.connect()` → `bus.connect(enable=True)` → 主臂使能（允许手动拖动读取位置）
3. 循环：`teleop.get_action()` → `robot.send_action(action)` → `robot.get_observation()`
4. `robot.disconnect()` → `bus.safe_shutdown()` → 回安全位 + 失能

---

## 各模块当前状态

### `motors/piper/piper.py` — PiperMotorsBus

| 方法 | 状态 | 说明 |
|------|------|------|
| `connect_can()` | ✅ 可用 | 发现并激活 CAN 端口 |
| `connect(enable=True)` | ✅ 可用 | 使能臂和夹爪，末尾正确设置 `_is_connected = True` |
| `connect(enable=False)` | ✅ 可用 | 调用 `safe_shutdown()` 后设 `_is_connected = False` |
| `read()` | ✅ 可用 | 返回 7 维 dict（joint_1..6 + gripper），单位 rad |
| `write(target_joints)` | ✅ 可用 | 直接调用 `robot.command_joint_positions()` 和 `command_gripper()`，不再依赖 `self.controller` |
| `apply_calibration()` | ✅ 可用 | 通过 `builtin_control_move()` 移动到 `INIT_JOINT_POSITION` |
| `apply_calibration_master()` | ✅ 可用 | 同上 |
| `safe_shutdown()` | ✅ 可用 | 通过 `builtin_control_move()` 回 `SAFE_DISABLE_POSITION` 后失能 |
| `probe_arm_enabled_state()` | ✅ 可用 | 多次采样防止单次误判 |
| `builtin_control_move()` | ✅ 可用 | 封装阻塞式位置移动，供 calibration 和 shutdown 复用 |

**已知问题**：
- `PiperMotorsBusConfig.port` 使用 `field(default_factory=connect_can)`，实例化 Config 时即触发 CAN 连接；如果需要在无硬件环境下 import 或测试，需改为延迟初始化

---

### `robots/piper_follower/piper_follower.py` — PIPERFollower

| 方法 | 状态 | 说明 |
|------|------|------|
| `connect()` | ✅ 可用 | 调用 bus.connect(enable=True) → calibrate()，相机失败时 raise RuntimeError |
| `disconnect()` | ✅ 可用 | 等待 2s 后调用 bus.connect(enable=False)（单路 shutdown，无重复） |
| `calibrate()` | ✅ 可用 | 调用 bus.apply_calibration()，is_calibrated 状态由 bus 维护 |
| `get_observation()` | ✅ 可用 | 读关节 + 相机图像，返回 obs dict |
| `send_action()` | ✅ 可用 | 调用 bus.write(target_joints)，write() 已修复 |
| `is_connected` | ✅ 正确 | 委托给 bus.is_connected 且对所有相机做 and 检查 |
| `motor_features` / `action_features` | ✅ 可用 | 格式符合框架要求 |

无已知阻塞性问题。

---

### `teleoperators/piper_leader/piper_leader.py` — PIPERLeader

| 方法 | 状态 | 说明 |
|------|------|------|
| `connect()` | ✅ 可用 | 调用 bus.connect(enable=True)，依赖 bus（已修复） |
| `calibrate()` | ✅ 可用 | 调用 `bus.apply_calibration_master()`（已修复） |
| `get_action()` | ✅ 可用 | 直接透传 bus.read() 返回值（已去除手动 joint_factor 换算） |
| `disconnect()` | ✅ 可用 | 调用 `bus.safe_shutdown()`（已从不存在的 safe_disconnect 修正） |
| `action_features` | ✅ 正确 | 7 维 float dict |

无已知阻塞性问题。

---

## 待完成工作（按优先级）

### P0 — 尚存的阻塞性问题

1. **`PiperMotorsBusConfig.port` 在实例化 Config 时即触发 CAN 连接**
   - 当前用 `field(default_factory=connect_can)` 实现；只要创建 Config 对象就会扫描 CAN 端口
   - 需改为：构造时接受字符串参数，由 `PiperMotorsBus.connect()` 在运行时调用 `connect_can()`

### P1 — 功能增强

2. **键盘急停（e-stop）集成**：在控制循环中评估并复用 `BuiltinJointPositionController` 的软件层急停能力（见 CLAUDE.md 安全规则）
3. **相机配置完善**：`config_piper_follower.py` 中相机字段已注释，需按实际硬件填写
4. **end-to-end 联调**：用实体 Piper 运行 `lerobot-record --robot.type=piper_follower --teleop.type=piper_leader`

---

## 依赖关系

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| `piper_control` | Piper 高层控制 API | `uv add piper-control` |
| `piper_sdk` | piper_control 的底层依赖，CAN 通信 | 随 piper_control 自动安装 |
| `lerobot` 框架 | Robot / Teleoperator 基类，record 脚本 | 当前 repo（fork） |

`piper_control` 核心 API：
- `piper_connect.find_ports()` / `activate()` / `active_ports()`
- `piper_interface.PiperInterface(can_port=...)` — 主通信对象
- `piper_init.reset_arm()` / `reset_gripper()` / `disable_arm()`
- `piper_control.BuiltinJointPositionController` — 内置位置控制器（context manager）
- `robot.get_joint_positions()` / `get_gripper_state()` — 读取
- `robot.command_gripper()` — 夹爪指令

---

## 安全注意事项

- 在任何含 `BuiltinJointPositionController` 的控制循环中，应评估并复用软件层键盘急停能力。
- `safe_shutdown()` 在失能前会先运动到 `SAFE_DISABLE_POSITION`（`[0, 0, 0, 0.02, 0.5, 0]` rad），失能后臂会掉落，操作前须确认周边安全。
- 不得在未确认的情况下删除或弱化急停、关节限位检查等安全机制。

---

## 参考资料

- 参考实现来源：[Kane1440/lerobot_piper2](https://github.com/Kane1440/lerobot_piper2)（使用裸 piper_sdk，见 `ref_only_*` 文件）
- 框架上游：[huggingface/lerobot](https://github.com/huggingface/lerobot)
- 用户的 piper_control 实验笔记：见 memory 中 `reference_piper_control_demo.md`
