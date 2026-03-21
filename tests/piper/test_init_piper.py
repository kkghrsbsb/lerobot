# 回零点测试
from lerobot.motors.piper.piper import PiperMotorsBus, PiperMotorsBusConfig

def main():
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
    bus.connect(enable=True)
    bus.apply_calibration()
    bus.safe_shutdown()

if __name__ == "__main__":
    main()