"""
测试脚本 2：检测机械臂是否已使能且在零位，然后执行外部控制命令。

前置条件：先在另一个终端运行 test_observe_connect.py，使机械臂进入使能+零位状态。

本脚本通过独立的 PiperInterface 连接同一个 CAN 总线，验证：
1. 能否读取到使能状态和零位关节角
2. 能否通过第二个 CAN 连接发送控制命令（CAN 共存）

用法：
    .venv/bin/python tests/piper/test_can_coexist.py
"""

import math
import time

from piper_control import piper_connect, piper_interface

# ── 阈值常量 ──────────────────────────────────────────────
ZERO_POSITION_THRESHOLD = 0.05  # rad，判定"在零位"的最大偏差


def check_arm_status(robot: piper_interface.PiperInterface) -> tuple[bool, bool]:
    """检测机械臂是否已使能且在零位。

    Returns:
        (is_enabled, is_at_zero): 使能状态, 是否在零位
    """
    # 多次采样判断使能状态
    time.sleep(0.3)
    enabled_samples = []
    for _ in range(5):
        enabled_samples.append(robot.is_arm_enabled())
        time.sleep(0.05)

    is_enabled = any(enabled_samples)
    print(f"  使能状态采样: {enabled_samples} → {'已使能' if is_enabled else '未使能'}")

    # 读取关节位置判断是否在零位
    joints = robot.get_joint_positions()
    print(f"  关节位置 (rad): {[f'{j:.4f}' for j in joints]}")

    max_deviation = max(abs(j) for j in joints)
    is_at_zero = max_deviation < ZERO_POSITION_THRESHOLD
    print(
        f"  最大偏差: {max_deviation:.4f} rad, 阈值: {ZERO_POSITION_THRESHOLD} → {'在零位' if is_at_zero else '不在零位'}")

    return is_enabled, is_at_zero


def external_control(robot: piper_interface.PiperInterface):
    """在这里写你的外部控制命令。

    这个函数通过独立的 PiperInterface 发送控制命令，
    用于验证是否能和 test_observe_connect.py 的连接共存。

    robot 是通过独立 CAN 连接创建的 PiperInterface 实例。
    可用的 API:
        robot.get_joint_positions()           → list[float], 6 关节, rad
        robot.get_gripper_state()             → (gripper_pos, gripper_effort)
        robot.command_joint_positions([...])   → 发送 6 关节目标位, rad
        robot.command_gripper(position, effort) → 夹爪指令
        robot.set_arm_mode(speed=10)          → 设置速度 (0-100)
    """
    # ── 在下方写你的控制命令 ────────────────────────────────

    # 示例：读取 5 次关节状态，每次间隔 0.5 秒
    print("\n  开始读取关节状态（验证只读 CAN 共存）...")
    for i in range(5):
        joints = robot.get_joint_positions()
        gripper_pos, gripper_effort = robot.get_gripper_state()
        print(f"    [{i + 1}/5] joints={[f'{j:.3f}' for j in joints]}, "
              f"gripper_pos={gripper_pos:.3f}")
        time.sleep(0.5)

    # ── 如需测试写入共存，取消下面的注释 ─────────────────────
    # WARNING: 确保周围安全！写入命令会让机械臂运动！

    print("\n  尝试发送关节命令（验证写入 CAN 共存）...")
    robot.set_arm_mode(speed=5)  # 低速
    # 小幅运动
    target = [0.2, 0.2, -0.2, 0.3, -0.2, 0.5]
    robot.command_joint_positions(target)
    time.sleep(4)
    print(f"current joints: {robot.get_joint_positions()}")
    time.sleep(1)
    # 回零位
    robot.command_joint_positions([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    time.sleep(4)
    print(f"current joints: {robot.get_joint_positions()}")
    time.sleep(1)
    print("  写入测试完成。")

    # ── 你的控制命令写在这里 ────────────────────────────────

    pass


def main():
    print("=" * 60)
    print("CAN 共存测试：通过独立连接检测+控制机械臂")
    print("=" * 60)

    # 发现并激活 CAN 端口
    ports = piper_connect.find_ports()
    print(f"发现端口: {ports}")
    piper_connect.activate(ports)
    active = piper_connect.active_ports()
    print(f"已激活端口: {active}")

    if not active:
        print("错误：未发现已激活的 CAN 端口")
        return

    # 创建独立的 PiperInterface（与 test_observe_connect.py 的连接共存）
    robot = piper_interface.PiperInterface(can_port=active[0])
    print(f"已创建独立 PiperInterface (port={active[0]})")

    print("\n── 检测机械臂状态 ──")
    is_enabled, is_at_zero = check_arm_status(robot)

    if not is_enabled:
        print("\n⚠ 机械臂未使能。请先在另一个终端运行 test_observe_connect.py。")
        return

    if not is_at_zero:
        print("\n⚠ 机械臂不在零位。可能 calibrate 尚未完成或有外部干扰。")

    print(f"\n✓ 机械臂状态正常: 使能={is_enabled}, 零位={is_at_zero}")
    print("\n── 执行外部控制命令 ──")
    external_control(robot)

    print("\n── 测试完成 ──")
    print("本脚本不负责失能机械臂。请在 test_observe_connect.py 中按 Enter 断开。")


if __name__ == "__main__":
    main()
