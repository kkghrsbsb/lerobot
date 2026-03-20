import time
from dataclasses import dataclass, field

from piper_control import piper_connect, piper_control, piper_init, piper_interface

# 用于 builtin_control_move
# 单次运动最大允许时长，超过时自动停止
MOVE_TIMEOUT_SECONDS = 12.0
# 到位判定阈值
MOVE_THRESHOLD = 0.01

# 关节初始位（回零位），6 关节，单位 rad
INIT_JOINT_POSITION = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 失能前的安全位，单位 rad
SAFE_DISABLE_POSITION = [0.0, 0.0, 0.0, 0.02, 0.5, 0.0]

# 夹爪初始位，单位与 piper_control 的 command_gripper() 一致
INIT_GRIPPER_POSITION = 0.0
# 夹爪夹持时允许施加的力 range: [0, 2]
GRIPPER_EFFORT_NOW = 0.5

# 内置位置控制器速度（范围 0-100），低值更安全
JOINT_SAFE_SPEED = 10


# 要以后插入 USB 自动读入 CAN 一劳永逸，请运行根目录下 piper-generate-udev-rule
# sudo ./piper-generate-udev-rule -i can0 -b 1000000
# from: https://github.com/Reimagine-Robotics/piper_control/blob/main/scripts/piper-generate-udev-rule
def connect_can():
    """连接到 Piper 的 CAN 接口并返回已激活的 CAN 端口名称列表。

    Returns:
        list[str]: 激活后的 CAN 端口列表（例如 ["can0"]）

    Raises:
        ValueError: 如果未发现任何已激活的 CAN 端口，则抛出异常提示用户检查连接
    """
    ports = piper_connect.find_ports()
    print(f"Piper ports: {ports}")

    piper_connect.activate(ports)
    ports = piper_connect.active_ports()

    if not ports:
        raise ValueError("No ports found. Make sure the Piper is connected and turned on.")

    return ports


@dataclass
class PiperMotorsBusConfig:
    motors: dict[str, tuple[int, str]]
    port: list[str] = field(default_factory=connect_can)


class PiperMotorsBus:
    """
    基于 piper_control 的 Piper 机械臂“电机总线”封装。
    """

    def __init__(self, config: PiperMotorsBusConfig) -> None:
        self.motors = config.motors
        self.robot = piper_interface.PiperInterface(can_port=config.port[0])
        self._is_connected = False
        # 借用接口，“已标定”被复用为"回零位"操作
        self._is_calibrated = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def is_calibrated(self) -> bool:
        return self._is_calibrated

    @property
    def motor_names(self) -> list[str]:
        return list(self.motors.keys())

    @property
    def motor_models(self) -> list[str]:
        return [model for _, model in self.motors.values()]

    @property
    def motor_indices(self) -> list[int]:
        return [idx for idx, _ in self.motors.values()]

    def probe_arm_enabled_state(
            self,
            settle_seconds=0.3,
            sample_count=5,
            sample_interval=0.05,
    ):
        """通过多次采样状态来探测机械臂是否已使能。"""

        # Allow status feedback to settle after reconnect, then sample multiple
        # times to avoid one-shot false negatives.
        time.sleep(settle_seconds)
        enabled_samples = []
        for _ in range(sample_count):
            enabled_samples.append(self.robot.is_arm_enabled())
            time.sleep(sample_interval)

        is_enabled = any(enabled_samples)
        if is_enabled:
            print(f"arm appears enabled (samples={enabled_samples}), skip reset_arm.")
        else:
            print(f"arm appears disabled (samples={enabled_samples}).")

        return is_enabled

    def probe_gripper_enabled_state(
            self,
            settle_seconds=0.3,
            sample_count=5,
            sample_interval=0.05,
    ):
        """通过多次采样状态来探测夹爪是否已使能。"""

        time.sleep(settle_seconds)
        enabled_samples = []
        for _ in range(sample_count):
            enabled_samples.append(self.robot.is_gripper_enabled())
            time.sleep(sample_interval)

        is_enabled = any(enabled_samples)
        if is_enabled:
            print(f"gripper appears enabled (samples={enabled_samples}), skip enable_gripper.")
        else:
            print(f"gripper appears disabled (samples={enabled_samples}).")

        return is_enabled

    def builtin_control_move(
            self,
            reach_position=None,
            safe_speed=JOINT_SAFE_SPEED,
            threshold=MOVE_THRESHOLD,
            timeout=MOVE_TIMEOUT_SECONDS,
    ):
        """"阻塞式移动，采用内置默认关节位控制器上下文安全移动到固定位置"""
        with piper_control.BuiltinJointPositionController(
                self.robot,
                rest_position=None,
        ) as controller:
            self.robot.set_arm_mode(speed=safe_speed)
            print(f"moving to position: {reach_position}")
            success = controller.move_to_position(
                reach_position,
                threshold=threshold,
                timeout=timeout,
            )
            print(f"reached target: {success}")

    def safe_shutdown(self):
        """运动到一个安全位置失能机械臂和夹爪"""
        self.builtin_control_move(reach_position=SAFE_DISABLE_POSITION)

        time.sleep(1)
        self.robot.disable_gripper()
        piper_init.disable_arm(self.robot)

    def connect(self, enable: bool) -> None:
        """使能或失能机械臂。

        Args:
            enable: True 为使能（启动控制器），False 为失能（停止控制器并断开）。
        """
        if enable:
            is_arm_enabled = self.probe_arm_enabled_state()
            if not is_arm_enabled:
                print("resetting arm")
                piper_init.reset_arm(
                    self.robot,
                    arm_controller=piper_interface.ArmController.POSITION_VELOCITY,
                    move_mode=piper_interface.MoveMode.JOINT,
                )
                is_arm_enabled = True

            is_gripper_enabled = self.probe_gripper_enabled_state()
            if not is_gripper_enabled:
                print("resetting gripper")
                piper_init.reset_gripper(self.robot)
                is_gripper_enabled = True

            print(f"arm enabled: {is_arm_enabled}")
            print(f"current joints: {self.robot.get_joint_positions()}")
            print(f"gripper enabled: {is_gripper_enabled}")
            print(f"current gripper state: {self.robot.get_gripper_state()}")

            self.robot.show_status()
            self._is_connected = True
        else:
            self.safe_shutdown()
            self._is_connected = False

    def set_calibration(self):
        return

    def revert_calibration(self):
        return

    def apply_calibration(self) -> None:
        """移动到初始位置"""
        self.builtin_control_move(reach_position=INIT_JOINT_POSITION)
        self._is_calibrated = True

    def apply_calibration_master(self) -> None:
        """master移动到初始位置"""
        self.builtin_control_move(reach_position=INIT_JOINT_POSITION)
        self._is_calibrated = True

    def read(self) -> dict[str, float]:
        """读取当前关节位置和夹爪状态。

        Returns:
            dict，键为 joint_1..joint_6 和 gripper，值为弧度（rad）。
            piper_control 已内部完成单位转换，返回值直接是 rad，无需额外换算。
        """
        joints = self.robot.get_joint_positions()
        gripper_pos, _ = self.robot.get_gripper_state()
        return {
            "joint_1": joints[0],
            "joint_2": joints[1],
            "joint_3": joints[2],
            "joint_4": joints[3],
            "joint_5": joints[4],
            "joint_6": joints[5],
            "gripper": gripper_pos,
        }

    def write(self, target_joints: list[float]) -> None:
        """发送关节位置指令。

        Args:
            target_joints: 长度为 7 的列表 [j1, j2, j3, j4, j5, j6, gripper]，单位 rad。
        """
        q = [float(x) for x in target_joints[:6]]

        gripper_pos = float(target_joints[6])

        self.robot.command_joint_positions(q)
        self.robot.command_gripper(position=gripper_pos, effort=GRIPPER_EFFORT_NOW)
