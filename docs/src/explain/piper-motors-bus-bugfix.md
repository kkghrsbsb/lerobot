# 变更说明：PiperMotorsBus 缺陷修复

## 说明范围

本次修复涵盖代码审查（`docs/src/review/piper-motors-bus-write-and-general.md`）中记录的全部遗留问题，
共涉及两个文件：

- `src/lerobot/motors/piper/piper.py`
- `src/lerobot/robots/piper_follower/piper_follower.py`

---

## 变更一：`PiperMotorsBusConfig.port` 改为延迟求值

**文件**：`piper.py:2,51–53`

### 改动前

```python
from dataclasses import dataclass

@dataclass
class PiperMotorsBusConfig:
    port = connect_can()          # 无类型注解 → 类变量
    motors: dict[str, tuple[int, str]]
```

### 改动后

```python
from dataclasses import dataclass, field

@dataclass
class PiperMotorsBusConfig:
    motors: dict[str, tuple[int, str]]
    port: list[str] = field(default_factory=connect_can)
```

### 说明

Python `@dataclass` 只把**有类型注解**的属性作为实例字段；没有注解的赋值语句是类变量，在类定义时（即模块 import 时）就会求值。

改动前，`connect_can()` 在 `import piper` 的瞬间就被调用，试图激活 CAN 硬件。
改动后，`field(default_factory=connect_can)` 将调用时机推迟到 `PiperMotorsBusConfig(motors=...)` 被显式构造时，只有真正要连接机械臂的代码路径才会触发 CAN 操作。

副作用：`motors` 字段没有默认值，`port` 有默认值，因此 `motors` 必须排在前面（Python dataclass 要求无默认值字段在有默认值字段之前），两个字段的顺序随之调整。

---

## 变更二：`PiperMotorsBus` 补回连接状态字段和 property

**文件**：`piper.py:61–73`

### 改动前

```python
def __init__(self, config: PiperMotorsBusConfig) -> None:
    self.motors = config.motors
    self.robot = piper_interface.PiperInterface(can_port=config.port[0])
```

### 改动后

```python
def __init__(self, config: PiperMotorsBusConfig) -> None:
    self.motors = config.motors
    self.robot = piper_interface.PiperInterface(can_port=config.port[0])
    self._is_connected = False
    self._is_calibrated = False

@property
def is_connected(self) -> bool:
    return self._is_connected

@property
def is_calibrated(self) -> bool:
    return self._is_calibrated
```

### 说明

`PIPERFollower.is_connected` 和 `PIPERLeader.is_connected` 都通过 `self.bus.is_connected` 向 Bus 层查询连接状态；`PIPERFollower.is_calibrated` 同样读取 `self.bus.is_calibrated`。
这两个 property 曾在早期版本中存在，但在某次清理中被误删，导致上层调用时抛出 `AttributeError`。
本次补回两个私有字段和对应的只读 property，恢复 Bus 层对外的状态接口。

---

## 变更三：`connect()` 在使能/失能后正确更新 `_is_connected`

**文件**：`piper.py:181–185`

### 改动前

```python
            self.robot.show_status()
        else:
            self.safe_shutdown()
```

### 改动后

```python
            self.robot.show_status()
            self._is_connected = True
        else:
            self.safe_shutdown()
            self._is_connected = False
```

### 说明

`connect(enable=True)` 完成后需要将 `_is_connected` 置 `True`，
`connect(enable=False)`（即 `safe_shutdown` 路径）完成后需要置 `False`，
这样 `is_connected` property 才能反映真实的连接状态，
Leader / Follower 的状态检查和 guard 逻辑（如 `DeviceNotConnectedError`）才能正确工作。

---

## 变更四：`apply_calibration*` 完成后置 `_is_calibrated = True`

**文件**：`piper.py:203,208`

### 改动前

```python
def apply_calibration(self) -> None:
    """移动到初始位置"""
    self.builtin_control_move(reach_position=INIT_JOINT_POSITION)

def apply_calibration_master(self) -> None:
    """master移动到初始位置"""
    self.builtin_control_move(reach_position=INIT_JOINT_POSITION)
```

### 改动后

```python
def apply_calibration(self) -> None:
    """移动到初始位置"""
    self.builtin_control_move(reach_position=INIT_JOINT_POSITION)
    self._is_calibrated = True

def apply_calibration_master(self) -> None:
    """master移动到初始位置"""
    self.builtin_control_move(reach_position=INIT_JOINT_POSITION)
    self._is_calibrated = True
```

### 说明

`PIPERFollower.calibrate()` 调用 `bus.apply_calibration()` 后会自行设置 `self._is_calibrated = True`，
但 `PIPERFollower.is_calibrated` 读取的是 `self.bus.is_calibrated`，
若 Bus 层不更新自己的标志，这个 property 永远返回 `False`，上层的标定状态判断会始终出错。
两个方法各加一行，确保 Bus 层状态与操作结果一致。

---

## 变更五：`piper_follower.py` 相机连接后立即检查结果

**文件**：`piper_follower.py:131–134`

### 改动前

```python
for name in self.cameras:
    self.cameras[name].connect()
    self._is_connected = self._is_connected and self.cameras[name].is_connected
    print(f"camera {name} connected")
```

### 改动后

```python
for name in self.cameras:
    self.cameras[name].connect()
    if not self.cameras[name].is_connected:
        raise RuntimeError(f"Camera {name} failed to connect")
    print(f"camera {name} connected")
```

### 说明

改动前的赋值 `self._is_connected = self._is_connected and ...` 存在逻辑短路问题：
`self._is_connected` 在此时仍为 `False`（bus 刚 connect 完，Follower 自身的标志尚未置 `True`），
`False and anything` 始终为 `False`，相机是否真正连接成功完全不影响结果。
随后第 137 行无条件写入 `True`，相机连接失败会被静默忽略，后续读取图像时才报错，难以定位。

改动后，每个相机 connect 后立即校验，失败则抛出 `RuntimeError` 并指明相机名称，
connect 阶段即快速失败，错误信息清晰。

---

## 数据流影响

```
PiperMotorsBusConfig(motors=...)   ← connect_can() 在此刻调用（延迟到构造时）
    ↓
PiperMotorsBus.__init__
    _is_connected = False
    _is_calibrated = False
    ↓
bus.connect(enable=True)
    → probe / reset arm & gripper
    → _is_connected = True          ← 新增
    ↓
bus.apply_calibration()
    → builtin_control_move → 回零位
    → _is_calibrated = True         ← 新增
    ↓
PIPERFollower.is_connected  →  bus.is_connected  →  True  ✓
PIPERFollower.is_calibrated →  bus.is_calibrated →  True  ✓
PIPERLeader.is_connected    →  bus.is_connected  →  True  ✓
```

---

## 未改动项

- `write()` 在上一轮已修复（去掉 `controller` 参数，改用 `self.robot.command_joint_positions(q)`），本次不再重复修改。
- `PIPERLeader` 无相机逻辑，不受变更五影响。
