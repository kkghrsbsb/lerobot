# 代码审查：PiperMotorsBus 及上层调用链（第二轮）

## 审查范围

第一轮审查后用户修改了 `piper.py`，本文档同步更新各问题的当前状态。

## 审查文件

- `src/lerobot/motors/piper/piper.py`（已修改）
- `src/lerobot/robots/piper_follower/piper_follower.py`
- `src/lerobot/teleoperators/piper_leader/piper_leader.py`

---

## 本轮修改内容

用户在 `piper.py` 中做了以下改动：

1. `write()` 去掉了 `controller` 参数，改为直接调用 `self.robot.command_joint_positions(q)`。
2. `PiperMotorsBus.__init__` 中移除了 `self._is_connected = False` 和 `self._is_calibrated = False`。
3. 相应地，`is_connected` 和 `is_calibrated` property 也被删除。

---

## 各问题当前状态

### ✅ 问题 1（已修复）— `write()` 签名与调用方不匹配

`controller` 参数已移除，改为调用 `self.robot.command_joint_positions(q)`。

`command_joint_positions` 是 `piper_interface.PiperInterface` 的真实方法，API 存在，调用正确。
`send_action → bus.write(target_joints)` 调用链现在可以正常运行。

---

### ✅ 问题 5（已修复）— Docstring 缺少 `controller` 参数说明

随问题 1 一并消除，lint 警告不再出现。

---

### 🔴 问题 2（变严重）— `PiperMotorsBus` 不再有 `is_connected` 属性

**位置**：`piper.py`（已删除），`piper_follower.py:107`，`piper_leader.py:60`

修改前：`bus.is_connected` 存在但永远返回 False。
修改后：`bus.is_connected` **属性不存在**，上层调用会抛出 `AttributeError`：

```python
# piper_follower.py:107
return self.bus.is_connected and all(...)   # AttributeError: 'PiperMotorsBus' object has no attribute 'is_connected'

# piper_leader.py:60
return self.bus.is_connected                # AttributeError
```

**修复**：在 `PiperMotorsBus` 中补回 `_is_connected` 字段和 `is_connected` property，并在 `connect(enable=True)` 末尾置 `True`，`connect(enable=False)` 末尾置 `False`：

```python
def __init__(self, config: PiperMotorsBusConfig) -> None:
    self.motors = config.motors
    self.robot = piper_interface.PiperInterface(can_port=config.port[0])
    self._is_connected = False

@property
def is_connected(self) -> bool:
    return self._is_connected
```

---

### 🔴 问题 3（变严重）— `PiperMotorsBus` 不再有 `is_calibrated` 属性

**位置**：`piper.py`（已删除），`piper_follower.py:112`

同上，`bus.is_calibrated` 被删除后，`PIPERFollower.is_calibrated` 会抛出 `AttributeError`：

```python
# piper_follower.py:112
return self.bus.is_calibrated   # AttributeError
```

**修复**：补回 `_is_calibrated` 字段、`is_calibrated` property，并在 `apply_calibration` / `apply_calibration_master` 末尾置 `True`：

```python
self._is_calibrated = False   # 在 __init__

@property
def is_calibrated(self) -> bool:
    return self._is_calibrated
```

---

### 🔴 问题 4（未修复）— `PiperMotorsBusConfig.port` 在 import 时触发 CAN 连接

**位置**：`piper.py:50–52`

```python
@dataclass
class PiperMotorsBusConfig:
    port = connect_can()      # 没有类型注解 → 类变量，import 时立即执行
    motors: dict[str, tuple[int, str]]
```

`connect_can()` 在模块被 import 时就运行，导致：

- 任何 import `piper.py` 的场景（测试、文档生成、脚本启动）都会立即尝试连接 CAN 硬件。
- 若硬件未连接，import 直接抛出 `ValueError`，程序启动失败。
- 所有实例共享同一个类变量 `port`，无法在实例化时传入不同端口。

**修复**（推荐）：

```python
from dataclasses import dataclass, field

@dataclass
class PiperMotorsBusConfig:
    motors: dict[str, tuple[int, str]]
    port: list[str] = field(default_factory=connect_can)
```

这样 `connect_can()` 只在显式构造 `PiperMotorsBusConfig()` 实例时才会调用，而不是 import 时。

---

### ⚠️ 问题 6（未修复）— `PIPERFollower.connect()` 相机连接状态检查逻辑错误

**位置**：`piper_follower.py:133`

```python
self._is_connected = self._is_connected and self.cameras[name].is_connected
```

`self._is_connected` 在此时为 `False`（bus 连接刚完成，_is_connected 尚未置 True），
`False and anything = False`，循环内赋值无意义。
随后第 137 行无条件设为 `True`，相机是否真正连接成功被忽略。

**建议修复**：

```python
for name in self.cameras:
    self.cameras[name].connect()
    if not self.cameras[name].is_connected:
        raise RuntimeError(f"Camera {name} failed to connect")
```

---

## 严重性汇总（当前）

| # | 问题 | 状态 | 严重性 | 影响 |
|---|------|------|--------|------|
| 1 | `write()` 签名与调用方不匹配 | ✅ 已修复 | — | — |
| 5 | Docstring 缺少 `controller` 参数 | ✅ 已修复 | — | — |
| 2 | `bus.is_connected` 属性不存在 | 🔴 变严重 | **严重** | 调用即 AttributeError |
| 3 | `bus.is_calibrated` 属性不存在 | 🔴 变严重 | **严重** | 调用即 AttributeError |
| 4 | `PiperMotorsBusConfig.port` import 时触发 CAN 连接 | 🔴 未修复 | **严重** | import 即连硬件 |
| 6 | 相机连接状态检查逻辑错误 | ⚠️ 未修复 | 轻微 | 连接失败时静默继续 |

---

## 建议修复顺序

1. **问题 2 + 3**：在 `__init__` 中重新加入 `_is_connected = False` 和 `_is_calibrated = False`，恢复两个 property，并在适当位置置 `True`。
2. **问题 4**：将 `port = connect_can()` 改为带类型注解的 `field(default_factory=connect_can)`。
3. **问题 6**：修复相机连接状态检查逻辑。
