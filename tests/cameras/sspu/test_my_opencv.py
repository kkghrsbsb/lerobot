#!/usr/bin/env python
"""
测试 OpenCV 摄像头流的脚本
摄像头: /dev/video2
"""

import time
import sys
import numpy as np

from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
from lerobot.cameras.configs import ColorMode, Cv2Rotation

# ── 配置 ──────────────────────────────────────────────────────────────────────
CAMERA_INDEX = 2          # /dev/video2
FPS          = 30
WIDTH        = 640
HEIGHT       = 480
# ─────────────────────────────────────────────────────────────────────────────


def make_config() -> OpenCVCameraConfig:
    return OpenCVCameraConfig(
        index_or_path=CAMERA_INDEX,
        fps=FPS,
        width=WIDTH,
        height=HEIGHT,
        color_mode=ColorMode.RGB,
        rotation=Cv2Rotation.NO_ROTATION,
    )


def separator(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


# ── Test 1: 基本连接 ───────────────────────────────────────────────────────────
def test_connect():
    separator("Test 1: 连接 / 断开")
    config = make_config()
    cam = OpenCVCamera(config)
    cam.connect()
    print(f"[OK] 摄像头已连接")
    print(f"     is_connected = {cam.is_connected}")
    print(f"     分辨率: {cam.width}x{cam.height}  FPS: {cam.fps}")
    cam.disconnect()
    print(f"[OK] 摄像头已断开  is_connected = {cam.is_connected}")


# ── Test 2: read() 同步阻塞读 ──────────────────────────────────────────────────
def test_read_sync(n_frames: int = 5):
    separator("Test 2: read() 同步阻塞读")
    config = make_config()
    with OpenCVCamera(config) as cam:
        for i in range(n_frames):
            t0 = time.perf_counter()
            frame = cam.read()
            elapsed = (time.perf_counter() - t0) * 1000
            assert frame is not None, "read() 返回 None"
            assert frame.shape == (HEIGHT, WIDTH, 3), f"shape 错误: {frame.shape}"
            print(f"  frame {i+1}/{n_frames}  shape={frame.shape}  耗时={elapsed:.1f}ms")
    print("[OK] read() 通过")


# ── Test 3: async_read() 异步读 ────────────────────────────────────────────────
def test_read_async(n_frames: int = 10, timeout_ms: int = 300):
    separator("Test 3: async_read() 异步读")
    config = make_config()
    with OpenCVCamera(config) as cam:
        success = 0
        for i in range(n_frames):
            try:
                t0 = time.perf_counter()
                frame = cam.async_read(timeout_ms=timeout_ms)
                elapsed = (time.perf_counter() - t0) * 1000
                assert frame.shape == (HEIGHT, WIDTH, 3), f"shape 错误: {frame.shape}"
                print(f"  frame {i+1}/{n_frames}  shape={frame.shape}  耗时={elapsed:.1f}ms")
                success += 1
            except TimeoutError as e:
                print(f"  frame {i+1}/{n_frames}  [TIMEOUT] {e}")
    print(f"[OK] async_read() 成功 {success}/{n_frames} 帧")


# ── Test 4: read_latest() 即时帧 ──────────────────────────────────────────────
def test_read_latest(n_frames: int = 10, max_age_ms: int = 1000):
    separator("Test 4: read_latest() 即时最新帧")
    config = make_config()
    with OpenCVCamera(config) as cam:
        try:
            prev = cam.read_latest(max_age_ms=max_age_ms)
            print(f"  初始帧  shape={prev.shape}")
            new_count = 0
            for i in range(n_frames):
                time.sleep(1.0 / FPS)           # 等一帧时间
                frame = cam.read_latest(max_age_ms=max_age_ms)
                is_new = not np.array_equal(prev, frame)
                new_count += int(is_new)
                print(f"  frame {i+1}/{n_frames}  shape={frame.shape}  新帧={is_new}")
                prev = frame
            print(f"[OK] read_latest() 共检测到 {new_count}/{n_frames} 个新帧")
        except TimeoutError as e:
            print(f"[FAIL] 帧太旧: {e}")


# ── Test 5: 帧率基准测试 ───────────────────────────────────────────────────────
def test_fps_benchmark(duration_s: float = 3.0):
    separator(f"Test 5: 帧率基准 ({duration_s}s)")
    config = make_config()
    with OpenCVCamera(config) as cam:
        count = 0
        t_start = time.perf_counter()
        while time.perf_counter() - t_start < duration_s:
            cam.read()
            count += 1
        elapsed = time.perf_counter() - t_start
        actual_fps = count / elapsed
        print(f"  读取帧数: {count}")
        print(f"  实际 FPS: {actual_fps:.2f}  (目标: {FPS})")
        fps_ok = actual_fps >= FPS * 0.8       # 允许 20% 误差
        status = "OK" if fps_ok else "WARN"
        print(f"[{status}] FPS 检测 {'通过' if fps_ok else '低于预期 (可能是硬件限制)'}")


# ── Test 6: 像素值合理性检查 ──────────────────────────────────────────────────
def test_frame_sanity():
    separator("Test 6: 帧像素值合理性检查")
    config = make_config()
    with OpenCVCamera(config) as cam:
        frame = cam.read()
        mean_val = frame.mean()
        min_val  = frame.min()
        max_val  = frame.max()
        print(f"  dtype={frame.dtype}  shape={frame.shape}")
        print(f"  像素值: min={min_val}  max={max_val}  mean={mean_val:.2f}")

        assert frame.dtype == np.uint8,       f"dtype 应为 uint8, 实为 {frame.dtype}"
        assert min_val >= 0,                  "像素最小值 < 0"
        assert max_val <= 255,                "像素最大值 > 255"
        assert mean_val > 5,                  f"画面疑似全黑 (mean={mean_val:.2f})"
        assert mean_val < 250,                f"画面疑似全白 (mean={mean_val:.2f})"
        print("[OK] 帧数据合理")


# ── 主入口 ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  OpenCV 摄像头流测试")
    print(f"  设备: /dev/video{CAMERA_INDEX}  {WIDTH}x{HEIGHT}@{FPS}fps")
    print("=" * 60)

    tests = [
        ("连接测试",        test_connect),
        ("同步读帧",        test_read_sync),
        ("异步读帧",        test_read_async),
        ("即时最新帧",      test_read_latest),
        ("帧率基准",        test_fps_benchmark),
        ("像素合理性",      test_frame_sanity),
    ]

    passed, failed = 0, 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"\n[FAIL] {name} 抛出异常: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    separator("测试结果汇总")
    print(f"  通过: {passed}  失败: {failed}  共: {len(tests)}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()