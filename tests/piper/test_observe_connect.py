"""
测试脚本 1：启动 robot.connect() 使能机械臂并 calibrate（回零位）。

运行后机械臂进入使能+零位状态，保持连接等待用户按 Enter 断开。
用于配合 test_can_coexist.py 验证 CAN 共存。

用法：
    .venv/bin/python tests/piper/test_observe_connect.py
"""

from lerobot.robots.piper_follower.piper_follower import PIPERFollower
from lerobot.robots.piper_follower.config_piper_follower import PIPERFollowerConfig


def main():
    config = PIPERFollowerConfig()
    robot = PIPERFollower(config)

    print("=" * 60)
    print("正在连接机械臂（connect + calibrate 回零位）...")
    print("=" * 60)

    robot.connect()

    print()
    print("=" * 60)
    print("机械臂已使能且在零位。")
    print(f"  is_connected: {robot.is_connected}")
    print(f"  is_calibrated: {robot.is_calibrated}")
    print()
    print("现在可以在另一个终端运行 test_can_coexist.py 来测试 CAN 共存。")
    print("按 Enter 断开并安全关闭机械臂...")
    print("=" * 60)

    try:
        input()
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C")

    print("正在断开...")
    robot.disconnect()
    print("已断开。")


if __name__ == "__main__":
    main()
