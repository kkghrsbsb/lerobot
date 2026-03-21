from piper_control import piper_init, piper_interface
from lerobot.motors.piper.piper import PiperMotorsBus, PiperMotorsBusConfig


if __name__ == '__main__':
    bus = PiperMotorsBus(
        PiperMotorsBusConfig(
            motors={
                "joint_1": (1, "agilex_piper"),
                "joint_2": (2, "agilex_piper"),
                "joint_3": (3, "agilex_piper"),
                "joint_4": (4, "agilex_piper"),
                "joint_5": (5, "agilex_piper"),
                "joint_6": (6, "agilex_piper"),
                "gripper": (7, "agilex_piper"),
            },
        )
    )
    input("WARNING: the robot will be disabled. Press Enter to continue...")
    piper_init.disable_arm(bus.robot)