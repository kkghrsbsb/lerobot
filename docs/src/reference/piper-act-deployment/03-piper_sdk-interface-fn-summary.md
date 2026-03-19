# piper sdk接口函数整理

## 一、现有问题

piper移植[lerobot](https://zhida.zhihu.com/search?content_id=262272320&content_type=Article&match_order=1&q=lerobot&zhida_source=entity)后，遇到了三个问题：

（1）启动piper有时候会出现端口连不上的的问题，发送指令会报错。现在的解决方式是断开两个机械臂的USB连接和电源，然后只连接一个机械臂的电源和USB，并按照机械臂单个调试的流程启动一个机械臂关节运动控制的demo，运行正常后再接上所有的线，开始跑lerobot。

（2）lerobot record过程中在夹爪不小心碰到桌面后会出现从臂停滞，主臂无法正常控制从臂（会出现非常长的控制间隔），只能中断采集。并且由于lerobot最新的包不支持本地resume（表面上支持，实际上每次都会尝试连接[huggingface](https://zhida.zhihu.com/search?content_id=262272320&content_type=Article&match_order=1&q=huggingface&zhida_source=entity)云端数据集，然后由于网络连接问题卡住不动），中断采集意味着需要重新来过，非常不方便，甚至可以说使得正常数据采集完全无法进行。在piper移植lerobot的过程中，我们选择了简单的演示任务来避免从臂碰撞卡死，但是这个并非长久之计。

（3）推理阶段似乎对于初始位置有一道高墙。第一次训练出来后发现机械臂没有动静，后续检查了代码、输出debug信息也没有找到问题，最后在绝望中胡乱尝试突然能够正常推理控制。推测原因是初始位置policy并没有学习到，因为采集过程中每次的初始位置我们摆放地很随意，所以可能对于从零点位置出发的机械臂，policy不能正常控制。

所以现在我们需要（1）寻找办法使得piper的初始化连接更加便捷；（2）使得piper在采集过程中不会掉线；（3）解决初始卡死的问题。对此，我们认为造成这些问题的主要原因在于piper方面，我们没有很好地利用sdk，或者错误使用了sdk，所以我们 打算首先详细研究一下piper的sdk接口函数。

## 二、接口函数技术文档关键信息罗列

### 1.Class C_PiperInterface_V2

其中包含了几个与所需解决问题相关的选项（出于简洁后续将直接罗列，罗列的信息都是与第一节所述问题相关的）：

`can_auto_init` (bool, default=True): Determines if the CAN port is automatically initialized.

`start_sdk_gripper_limit` (bool, default=True): Enable SDK gripper limits

这两条是实例化Piper时可选的。

### 2.ConnectPort

```python
 def ConnectPort(can_init: bool = False, piper_init: bool = True, start_thread: bool = True)
```

Starts a thread to process data from the connected CAN port.

Parameters:

- `can_init`: CAN port init flag. Set to True after using DisconnectPort().
- `piper_init`: Execute the robot arm initialization function
- `start_thread`: Start the reading thread

这个函数是连接函数，可能可以用于排查到底是连接通讯问题还是piper初始化问题。

### 3.EmergencyStop

```python
 def EmergencyStop(emergency_stop: Literal[0x00, 0x01, 0x02] = 0)
```

Emergency stop control command (CAN ID: 0x150)

Parameters:

- `emergency_stop`:
  - 0x00: Invalid
  - 0x01: Emergency stop
  - 0x02: Resume



这里有一个resume选项，但是似乎急停函数不太会用到。

### 4.ModeCtrl

```python
 def ModeCtrl(ctrl_mode: Literal[0x00, 0x01] = 0x01,
             move_mode: Literal[0x00, 0x01, 0x02, 0x03] = 0x01,
             move_spd_rate_ctrl: int = 50,
             is_mit_mode: Literal[0x00, 0xAD, 0xFF] = 0x00)
```

Mode control command (CAN ID: 0x151)

Parameters:

- `ctrl_mode`:
  - 0x00: Standby mode
  - 0x01: CAN command control mode



- `move_mode`:
  - 0x00: MOVE P (Position)
  - 0x01: MOVE J (Joint)
  - 0x02: MOVE L (Linear)
  - 0x03: MOVE C (Circular)



- `move_spd_rate_ctrl`: Movement speed percentage (0-100)
- is_mit_mode:
  - 0x00: Position-velocity mode
  - 0xAD: MIT mode
  - 0xFF: Invalid



这个是模式控制初始化函数，后续应该要经常用。

### 5.EnableArm

```python
 def EnableArm(motor_num: Literal[1, 2, 3, 4, 5, 6, 7, 0xFF] = 7,
              enable_flag: Literal[0x01, 0x02] = 0x02)
```

Enable motor(s) command (CAN ID: 0x471)

Parameters:

- `motor_num`: Motor number [1-7], 7 represents all motors
- `enable_flag`: 0x02 for enable

使能函数

### 6. GripperCtrl

```python
 def GripperCtrl(gripper_angle: int = 0,
                gripper_effort: int = 0,
                gripper_code: Literal[0x00, 0x01, 0x02, 0x03] = 0,
                set_zero: Literal[0x00, 0xAE] = 0)
```

Gripper control command (CAN ID: 0x159)

Parameters:

- `gripper_angle`: Gripper range, expressed as an integer, unit 0.001mm
- `gripper_effort`: Gripper torque (0.001 N/m, range 0-5000 corresponds to 0-5 N/m)
- `gripper_code`:
  - 0x00: Disable
  - 0x01: Enable
  - 0x02: Disable and clear error
  - 0x03: Enable and clear error



- `set_zero`:
  - 0x00: Invalid value
  - 0xAE: Set current position as zero point



这里有一个清楚报错的功能，后续可能有用。

### 7.GetArmJointMsgs

```python
 def GetArmJointMsgs()
```

Returns the joint angles (in 0.001 degrees)

Manual unit conversion of data is required.

获取关节角度的函数。

### 8.isOk

```python
 def isOk()
```

Returns whether the CAN data reading thread is functioning normally.

可用于检查是否正常。

### 9.JointConfig

```python
 def JointConfig(joint_num: Literal[1, 2, 3, 4, 5, 6, 7] = 7,
                set_zero: Literal[0x00, 0xAE] = 0,
                acc_param_is_effective: Literal[0x00, 0xAE] = 0,
                max_joint_acc: int = 500,
                clear_err: Literal[0x00, 0xAE] = 0)
```

Joint configuration command (CAN ID: 0x475)

Parameters:

- `joint_num`: Joint motor number (1-6, 7 for all joints)
- `set_zero`: Set current position as zero point (0xAE)
- `acc_param_is_effective`: Enable acceleration parameter (0xAE)
- `max_joint_acc`: Maximum joint acceleration (0.01 rad/s², range [0, 500] -> [0, 5.0 rad/s²])
- `clear_err`: Clear joint error code (0xAE)

这里也有清除报错的选项。

### 10.CrashProtectionConfig

```python
 def CrashProtectionConfig(joint_1_protection_level: int,
                         joint_2_protection_level: int,
                         joint_3_protection_level: int,
                         joint_4_protection_level: int,
                         joint_5_protection_level: int,
                         joint_6_protection_level: int)
```

Sets collision protection levels for each joint (CAN ID: 0x47A)

Parameters:

- `joint_X_protection_level`: Protection level for each joint (0-8)
  - 0: No collision detection
  - 1-8: Increasing detection thresholds



这里可以禁用碰撞检测，录制过程中断连可能是因为触发了碰撞保护。