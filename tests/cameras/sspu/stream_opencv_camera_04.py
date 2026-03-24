#!/usr/bin/env python
"""
实时展示 OpenCV 摄像头视频流
按 q 退出，按 s 保存截图
"""

import time
import cv2
import os

from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
from lerobot.cameras.configs import ColorMode, Cv2Rotation

# ── 配置 ──────────────────────────────────────────────────────────────────────
CAMERA_INDEX = 4
FPS          = 30
WIDTH        = 640
HEIGHT       = 480
WINDOW_NAME  = f"Camera /dev/video{CAMERA_INDEX}  |  q=退出  s=截图"

# ─────────────────────────────────────────────────────────────────────────────

output_dir = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(output_dir, exist_ok=True)

def main():
    config = OpenCVCameraConfig(
        index_or_path=CAMERA_INDEX,
        fps=FPS,
        width=WIDTH,
        height=HEIGHT,
        color_mode=ColorMode.RGB,
        rotation=Cv2Rotation.NO_ROTATION,
    )

    print(f"连接摄像头 /dev/video{CAMERA_INDEX} ...")
    with OpenCVCamera(config) as cam:
        print("已连接，按 q 退出，按 s 保存截图\n")

        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, WIDTH, HEIGHT)

        frame_count = 0
        fps_display = 0.0
        t_fps = time.perf_counter()
        screenshot_count = 0

        while True:
            # 读取最新帧（RGB）
            try:
                frame_rgb = cam.async_read(timeout_ms=200)
            except TimeoutError:
                print("[WARN] 读帧超时，跳过")
                continue

            frame_count += 1

            # 计算实时 FPS（每 30 帧更新一次）
            if frame_count % 30 == 0:
                elapsed = time.perf_counter() - t_fps
                fps_display = 30 / elapsed
                t_fps = time.perf_counter()

            # RGB → BGR（OpenCV 显示用 BGR）
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            # 叠加 HUD 信息
            h, w = frame_bgr.shape[:2]
            overlay = frame_bgr.copy()

            # 半透明顶栏背景
            cv2.rectangle(overlay, (0, 0), (w, 36), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.45, frame_bgr, 0.55, 0, frame_bgr)

            cv2.putText(
                frame_bgr,
                f"FPS: {fps_display:.1f}   {w}x{h}   frame #{frame_count}",
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (0, 255, 120), 1, cv2.LINE_AA,
            )

            cv2.imshow(WINDOW_NAME, frame_bgr)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("退出")
                break
            elif key == ord('s'):
                filename = os.path.join(output_dir, f"screenshot_{screenshot_count:03d}.png")
                cv2.imwrite(filename, cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))
                screenshot_count += 1
                print(f"截图已保存: {filename}")

        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()