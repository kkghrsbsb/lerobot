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
2. `teleop.connect()` → `bus.connect(enable=True)` → 主臂使能 + 失能（允许手动拖动）
3. 循环：`teleop.get_action()` → `robot.send_action(action)` → `robot.get_observation()`
4. `robot.disconnect()` → `bus.safe_shutdown()` → 回安全位 + 失能

---

## 各模块当前状态

### `motors/piper/piper.py` — PiperMotorsBus

| 方法 | 状态 | 说明 |
|------|------|------|
| `connect_can()` | ✅ 可用 | 发现并激活 CAN 端口 |
| `connect(enable=True)` | ✅ 基本可用 | 使能臂和夹爪，有多次采样防误判 |
| `connect(enable=False)` | ⚠️ 有重复 | 调用 safe_shutdown()，但 disconnect() 也已调用一次 |
| `read()` | ✅ 可用 | 返回 7 维 dict（joint_1..6 + gripper），单位 rad |
| `write(target_joints)` | ❌ 有 bug | 引用了 `self.controller` 但 `__init__` 中未赋值 |
| `apply_calibration()` | ⚠️ 待验证 | 调用 `self.controller.move_to_position()`，依赖未初始化的 controller |
| `apply_calibration_master()` | ⚠️ 待验证 | 同上 |
| `safe_shutdown()` | ✅ 逻辑正确 | 用 BuiltinJointPositionController 回安全位后失能 |
| `probe_arm_enabled_state()` | ✅ 可用 | 多次采样防止单次误判 |

**已知问题**：
- `PiperMotorsBusConfig.port` 是类级别字段调用 `connect_can()`，会在 **import 时** 触发 CAN 连接（严重问题）
- `self.controller` 从未在 `__init__` 中赋值；`write()`、`apply_calibration()` 等均会在运行时抛 `AttributeError`
- `is_connected` 属性返回 `self._is_connected`，但 `connect()` 方法从未将其设为 `True`

---

### `robots/piper_follower/piper_follower.py` — PIPERFollower

| 方法 | 状态 | 说明 |
|------|------|------|
| `connect()` | ⚠️ 部分可用 | 流程正确，但依赖有 bug 的 bus.connect/calibrate |
| `disconnect()` | ⚠️ 逻辑冗余 | 先调 `safe_shutdown()` 再调 `connect(enable=False)`，后者重复 shutdown |
| `calibrate()` | ⚠️ 待验证 | 调用 `bus.apply_calibration()`，依赖 controller |
| `get_observation()` | ✅ 逻辑正确 | 读关节 + 相机图像，返回 obs dict |
| `send_action()` | ⚠️ 待验证 | 调用 `bus.write()`，依赖未修复的 write() |
| `motor_features` / `action_features` | ✅ 可用 | 格式符合框架要求 |

**已知问题**：
- import 路径错误：`from lerobot.utils.errors` 应为 `from lerobot.errors`
- `is_connected` 在 connect() 结束时更新逻辑有误（相机循环中 `and` 初始为 False 导致永远 False）

---

### `teleoperators/piper_leader/piper_leader.py` — PIPERLeader

| 方法 | 状态 | 说明 |
|------|------|------|
| `connect()` | ⚠️ 部分可用 | 流程正确，但依赖有 bug 的 bus.connect |
| `calibrate()` | ⚠️ 待验证 | 调用 `bus.apply_calibration_master()` |
| `get_action()` | ✅ 逻辑正确 | 调用 `bus.read()`，已验证 read() 可用 |
| `disconnect()` | ❌ 有 bug | 调用 `bus.safe_disconnect()`，但该方法不存在（应为 `safe_shutdown()`） |
| `action_features` | ✅ 正确 | 7 维 float dict |

**已知问题**：
- `PiperMotorsBusConfig(port="can_master", ...)` 传入字符串，但类字段已 override 为 `connect_can()` 的结果

---

## 待完成工作（按优先级）

### P0 — 阻塞 end-to-end 运行的 bug

1. **`PiperMotorsBusConfig.port` 不应在类定义时调用 `connect_can()`**
   - 需改为实例级别初始化或传入参数
2. **`self.controller` 未在 `__init__` 中初始化**
   - `PiperMotorsBus` 需要在 `connect(enable=True)` 内创建 `BuiltinJointPositionController` 并挂到 `self.controller`
3. **`piper_leader.disconnect()` 调用不存在的 `bus.safe_disconnect()`**
   - 改为 `bus.safe_shutdown()`
4. **`piper_follower.py` 错误 import 路径**
   - `from lerobot.utils.errors` → `from lerobot.errors`

### P1 — 逻辑不完整

5. **`is_connected` 状态跟踪不正确**（`PiperMotorsBus` 的 `_is_connected` 始终为 False）
6. **`PIPERFollower.disconnect()` 双重 shutdown**（先 `safe_shutdown()` 再 `connect(enable=False)`）
7. **相机连接状态检测逻辑有误**（初始值 False 与 `and` 运算符冲突）

### P2 — 功能增强

8. **键盘急停（e-stop）集成**（CLAUDE.md 要求评估复用 BuiltinJointPositionController 键盘急停能力）
9. **相机配置完善**（`config_piper_follower.py` 中相机配置已注释掉，需按实际硬件补全）
10. **end-to-end 联调**：用实体 Piper 运行 `lerobot-record`

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
