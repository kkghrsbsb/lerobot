# piper移植lerobot开发记录

### 一、为何需要移植？

在lerobot官方硬件上跑通后，下一步需要把lerobot移植到自己的硬件上跑：一方面，lerobot本身的硬件比较廉价，性能达不到要求；另一方面，能够移植才能满足后续自定义任务的需要。

### 二、移植需要解决的主要问题

本文使用的硬件平台为[松灵piper机械臂](https://zhida.zhihu.com/search?content_id=262149308&content_type=Article&match_order=1&q=松灵piper机械臂&zhida_source=entity)。lerobot项目直接支持的是[Feetech](https://zhida.zhihu.com/search?content_id=262149308&content_type=Article&match_order=1&q=Feetech&zhida_source=entity)和Dynamixel两类舵机，其他硬件（例如piper使用的是某未知型号的电机）需要自行实现接口。官网上给了硬件移植的文档：[https://huggingface.co/docs/lerobot/integrate_hardware](https://link.zhihu.com/?target=https%3A//huggingface.co/docs/lerobot/integrate_hardware)，但是写得比较简练，看完后也是云里雾里。

直观上，移植需要让lerobot与硬件无关的组件能够像与先前基于Feetech的机械臂交互一样与用户自己的机械臂交互。由于我们难以修改lerobot项目各组件之间的交互方式，也即难以修改接口，所以目标就变成了在保持接口不变的情况下，重新定义内部实现，也就是保持外在，改变内在。

### 三、接口分析与理解

根据先前lerobot的开发经验，核心的程序为[record.py](https://zhida.zhihu.com/search?content_id=262149308&content_type=Article&match_order=1&q=record.py&zhida_source=entity)，本文主要从record的代码理解接口。

（1）主函数：

```python
 def main():
     record()
```

（2)record()函数:

```python
 robot = make_robot_from_config(cfg.robot)
 teleop = make_teleoperator_from_config(cfg.teleop) if cfg.teleop is not None else None
```

从上述代码可知控制的robot（实际的follower）以及控制的teleop（采集数据时的master以及验证时的policy）是通过make_xx_from_config实例化的。

```python
             record_loop(
                 robot=robot,
                 events=events,
                 fps=cfg.dataset.fps,
                 teleop=teleop,
                 policy=policy,
                 dataset=dataset,
                 control_time_s=cfg.dataset.episode_time_s,
                 single_task=cfg.dataset.single_task,
                 display_data=cfg.display_data,
             )
```

除开加载config、初始化机械臂、视频编码等代码，record()的核心是record_loop()函数。

（3）record_loop()函数：

```python
         if policy is not None or dataset is not None:
             observation_frame = build_dataset_frame(dataset.features, observation, prefix="observation")
 
         if policy is not None:
             action_values = predict_action(
                 observation_frame,
                 policy,
                 get_safe_torch_device(policy.config.device),
                 policy.config.use_amp,
                 task=single_task,
                 robot_type=robot.robot_type,
             )
             action = {key: action_values[i].item() for i, key in enumerate(robot.action_features)}
         elif policy is None and isinstance(teleop, Teleoperator):
             action = teleop.get_action()
```

上面的代码为record_loop的核心内容：如果有policy则执行policy给出的action，没有policy则通过teleop获取action。

（4）record.py的其他代码：

其他主要是各种库和config参数的加载。只要不改变接口，不改变程序之间交互的逻辑，这些代码都是不需要改变的。并且record.py是通过封装函数实例化robot和teleop的，所以record.py并不需要什么改动。事实上，直到最后record.py，包括teleoperate.py需要修改的只有在导入包的时候加上piper相关我们自己实现的包。

（5）对于接口的总结和理解：

后续的工作集中在robot和teleop的实例化，robot和teleop需要实现connect、get_action、send_action等接口函数。

## 四、编写piper_follower

我们可以利用vscode的跳转功能找到需要实现的代码应该在的文件夹，比如follower的实现都在robots目录下。我们在robots目录下创建piper_follower目录，由于目标是保持接口与原先一致，所以我们可以复制一份so101_follower的实现到piper_follower中。

我们先修改简短的init和config文件，全都改名为piper开头。

之后进入piper_follower.py，我们已经认定要保留全部的接口，但是实现得是piper相关的驱动，所以可以大刀阔斧把所有原先so101相关的东西都删改一下。这一步需要对piper的驱动比较熟悉，最好有使用[piper_sdk](https://zhida.zhihu.com/search?content_id=262149308&content_type=Article&match_order=1&q=piper_sdk&zhida_source=entity)的经验后再来删改，这样就能知道哪些piper支持、哪些piper不支持、哪些piper不需要、哪些piper额外需要。

根据先前的经验，例如calibrated这种函数对于piper没有意义，piper可以不依赖lerobot离线标定好。但这些函数不需要删除，只需要实现为空就行：

```python
     @property
     def is_calibrated(self) -> bool:
         return self.bus.is_calibrated
 
     def calibrate(self) -> None:
         return
 
     def configure(self) -> None:
         return
 
     def setup_motors(self) -> None:
         return
```

对于def _motors_ft这类函数，是后续数据采集、模型训练、验证的必要内容。ft结尾的函数记录了数据类型，teleop传输、robot接收、dataset采集、policy生成的数据都要保持类型一致。这个可以照抄原本的代码，只要保持接口一致。

这里相机相关的东西不需要关注，需要关注的是机械臂指令传输相关的内容。

```python
     @property
     def _motors_ft(self) -> dict[str, type]:
         return {f"{motor}.pos": float for motor in self.bus.motors}
```

这里发现其实预设的交互逻辑的基础就是定义各个motor的代号，比如joint_1、joint_2。

同时我们发现在实例化过程中，如connect的实现，也并不直接与底层交互，lerobot项目采用的策略是再封装一层，也即实现了feetech舵机的底层驱动motorbus，因此出于方便我们也需要创建piper的motorbus。阅读feetech的代码实现，会发现feetech的motorbus实现非常底层，需要考虑通讯细节的问题，但是piper_sdk封装度很高，并且我们实际上也无从知晓piper的电机类型，所以我们可以对照着feetechmotorsbus的实现以及piper_follower所要求的motorbus相关的函数直接利用piper_sdk编写piper的motorbus。

我们编写了piper的驱动代码（对标feetchmotorsbus）。由于piper_sdk封装度很高，所以我们不需要考虑修改或者继承基类motorsbus，直接使用sdk实现piper驱动就行。

（1）connect函数

事实上我们在piper驱动类初始化的时候就可以会创建piper实例并连接，所以connect函数我们使能机械臂:

```python
     def connect(self):
         while (not self.piper.EnablePiper()):
             time.sleep(0.01)
         self._is_enable = True
```

（2）read函数

read函数中我们读取机械臂各个关节的角度：

```python
     def read(self):
         joint_msg = self.piper.GetArmJointMsgs()
         joint_state = joint_msg.joint_state
 
         gripper_msg = self.piper.GetArmGripperMsgs()
         gripper_state = gripper_msg.gripper_state
 
         return {
             "joint_1": joint_state.joint_1,
             "joint_2": joint_state.joint_2,
             "joint_3": joint_state.joint_3,
             "joint_4": joint_state.joint_4,
             "joint_5": joint_state.joint_5,
             "joint_6": joint_state.joint_6,
             "gripper": gripper_state.grippers_angle
         }
```

（3）write函数

write函数写入各个关节的目标角度并控制机械臂：

```python
     def write(self, target_joint:list):
         """
             Joint control
             - target joint: in radians
                 joint_1 (float): 关节1角度 -92000 ~ 92000 / 57324.840764
                 joint_2 (float): 关节2角度 -2400 ~ 120000 / 57324.840764
                 joint_3 (float): 关节3角度 3000 ~ -110000 / 57324.840764
                 joint_4 (float): 关节4角度 -90000 ~ 90000 / 57324.840764
                 joint_5 (float): 关节5角度 80000 ~ -80000 / 57324.840764
                 joint_6 (float): 关节6角度 -90000 ~ 90000 / 57324.840764
                 gripper_range: 夹爪角度 0~0.08
         """
         joint_0 = round(target_joint[0]*self.factor)
         joint_1 = round(target_joint[1]*self.factor)
         joint_2 = round(target_joint[2]*self.factor)
         joint_3 = round(target_joint[3]*self.factor)
         joint_4 = round(target_joint[4]*self.factor)
         joint_5 = round(target_joint[5]*self.factor)
         gripper_range = round(target_joint[6]*1000*1000)
 
         self.piper.MotionCtrl_2(0x01, 0x01, 100, 0x00)
         self.piper.JointCtrl(joint_0, joint_1, joint_2, joint_3, joint_4, joint_5)
         self.piper.GripperCtrl(abs(gripper_range), 1000, 0x01, 0)  # 单位 0.001°
 
```

（4）初始化函数

```python
 @dataclass
 class PIPERMotorsBusConfig:
     can_name: str
     motors: dict[str, tuple[int, str]]
 
 class PIPERMotorsBus():
     def __init__(
         self,
         config: PIPERMotorsBusConfig
     ):
         self.piper = C_PiperInterface_V2(config.can_name)
         self.piper.ConnectPort()
         self.motors = config.motors
         self.safe_disable_position = [0.0, 0.0, 0.0, 0.0, 0.52, 0.0, 0.0]
         self.factor = 57295.7795  # 1000*180/3.1415926
         self._is_enable = False
```

相应的在piper_follower中

（1）get_observation函数：

```python
     def get_observation(self) -> dict[str, Any]:
         if not self.is_connected:
             raise DeviceNotConnectedError("Piper is not connected.")
 
         # Read arm position
         obs_dict = self.bus.read()
         obs_dict = {f"{motor}.pos": val for motor, val in obs_dict.items()}
 
         # Capture images from cameras
         for cam_key, cam in self.cameras.items():
             obs_dict[cam_key] = cam.async_read()
 
         return obs_dict
```

（2）send_action函数：

```python
     def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
         if not self.is_connected:
             raise DeviceNotConnectedError("Piper is not connected.")
 
         target_joints = [action[f"{motor}.pos"] for motor in self.bus.motors]
 
         self.bus.write(target_joints)
         return action
```

piper_follower还包含了camera相关的实现，这些都不需要改动，也不要删除。

（3）初始化函数：

```python
 class PIPERFollower(Robot):
     """
     PIPER using piper sdk
     """
 
     config_class = PIPERFollowerConfig
     name = "piper_follower"
 
     def __init__(self, config: PIPERFollowerConfig):
         super().__init__(config)
         self.config = config
         bus_config = PIPERMotorsBus(
             can_name="can_follower",
             motors={
                 "joint_1": (1, "agilex_piper"),
                 "joint_2": (2, "agilex_piper"),
                 "joint_3": (3, "agilex_piper"),
                 "joint_4": (4, "agilex_piper"),
                 "joint_5": (5, "agilex_piper"),
                 "joint_6": (6, "agilex_piper"),
                 "gripper": (7, "agilex_piper"),
             }
         )
         self.bus = PIPERMotorsBus(config=bus_config)
         self.cameras = make_cameras_from_configs(config.cameras)
```

## 五、编写[piper_leader](https://zhida.zhihu.com/search?content_id=262149308&content_type=Article&match_order=1&q=piper_leader&zhida_source=entity)

leader的编写时可以仿照so101_leader，需要特别实现的是get_action函数：

```python
     def get_action(self) -> dict[str, float]:
         action_raw = self.bus.read()  # 原始单位 0.001°
         joint_factor = 57295.7795  # 度转弧度比例因子（可调）
         action = {
             f"{motor}.pos": val / joint_factor if motor != "gripper" else val / 1_000_000
             for motor, val in action_raw.items()
         }
 
         return action
```

## 六、调试与修改

上述已经基本完成了piper移植lerobot的代码工作，但运行record.py时会出现报错，本文调试过程中的报错主要有三个：

（1）没有在record中import piper_leader和piper_follower

（2）piper使用的是can连接，不需要port参数，需要在config文件中删除port项

（3）connect函数中误删了cam连接，需要补上，否则无法连接

除此之外，piper需要事先初始化can连接，详细参考piper_sdk的技术文档。同时piper时不时会出故障连不上，则需要进行断电、拔USB、单个机械臂初始化调试等操作使得piper连接恢复正常。

其余流程与lerobot原先流程一致，可以参考lerobot开发的博客。