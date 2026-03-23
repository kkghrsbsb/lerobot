"""
单臂纯观测数据采集脚本。

机械臂的运动由外部独立脚本通过 CAN 控制（示教、回放等），
本脚本只做"纯观察者"：每帧执行 robot.get_observation() 读取关节状态和相机图像，
将数据记录到 lerobot 格式的数据集中。

action 字段使用 echo action 策略：action[t] = state[t]（当前观测的关节状态即为 action）。

用法示例:

```shell
piper-observe \
    --robot.type=piper_follower \
    --dataset.repo_id=<my_username>/<my_dataset_name> \
    --dataset.num_episodes=5 \
    --dataset.single_task="Pick up the cube" \
    --dataset.fps=30 \
    --display_data=true
```
"""

import logging
import time
from dataclasses import asdict, dataclass
from pprint import pformat

from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig  # noqa: F401
from lerobot.configs import parser
from lerobot.datasets.feature_utils import build_dataset_frame, combine_feature_dicts, hw_to_dataset_features
from lerobot.datasets.image_writer import safe_stop_image_writer
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.pipeline_features import aggregate_pipeline_dataset_features, create_initial_features
from lerobot.datasets.video_utils import VideoEncodingManager
from lerobot.processor import make_default_robot_observation_processor
from lerobot.robots import (  # noqa: F401
    Robot,
    RobotConfig,
    make_robot_from_config,
    piper_follower,
)
from lerobot.scripts.lerobot_record import DatasetRecordConfig
from lerobot.utils.constants import ACTION, OBS_STR
from lerobot.utils.control_utils import (
    init_keyboard_listener,
    is_headless,
    sanity_check_dataset_name,
    sanity_check_dataset_robot_compatibility,
)
from lerobot.utils.robot_utils import precise_sleep
from lerobot.utils.utils import init_logging, log_say
from lerobot.utils.visualization_utils import init_rerun, log_rerun_data


@dataclass
class ObserveConfig:
    robot: RobotConfig
    dataset: DatasetRecordConfig
    # Display all cameras on screen
    display_data: bool = False
    display_ip: str | None = None
    display_port: int | None = None
    display_compressed_images: bool = False
    play_sounds: bool = True
    resume: bool = False


@safe_stop_image_writer
def observe_loop(
    robot: Robot,
    events: dict,
    fps: int,
    dataset: LeRobotDataset | None = None,
    control_time_s: float | None = None,
    single_task: str | None = None,
    display_data: bool = False,
    display_compressed_images: bool = False,
):
    """纯观测采集循环。

    每帧：
    1. robot.get_observation() 读取关节 + 相机
    2. echo action: action = 当前关节状态
    3. 组装 frame 写入 dataset
    """
    if dataset is not None and dataset.fps != fps:
        raise ValueError(f"The dataset fps should be equal to requested fps ({dataset.fps} != {fps}).")

    robot_observation_processor = make_default_robot_observation_processor()

    timestamp = 0
    start_episode_t = time.perf_counter()

    while timestamp < control_time_s:
        start_loop_t = time.perf_counter()

        if events["exit_early"]:
            events["exit_early"] = False
            break

        # 1. 读取观测
        obs = robot.get_observation()
        obs_processed = robot_observation_processor(obs)

        # 2. Echo action: 用当前关节状态作为 action
        #    只取 action_features 中声明的 key（关节+夹爪），排除相机
        action_values = {
            k: v for k, v in obs_processed.items()
            if k in robot.action_features
        }

        # 3. 构建 dataset frame 并存储
        if dataset is not None:
            observation_frame = build_dataset_frame(dataset.features, obs_processed, prefix=OBS_STR)
            action_frame = build_dataset_frame(dataset.features, action_values, prefix=ACTION)
            frame = {**observation_frame, **action_frame, "task": single_task}
            dataset.add_frame(frame)

        # 4. 可视化
        if display_data:
            log_rerun_data(
                observation=obs_processed,
                action=action_values,
                compress_images=display_compressed_images,
            )

        # 5. 帧率控制
        dt_s = time.perf_counter() - start_loop_t
        sleep_time_s = 1 / fps - dt_s
        if sleep_time_s < 0:
            logging.warning(
                f"Observe loop is running slower ({1 / dt_s:.1f} Hz) than the target FPS ({fps} Hz)."
            )
        precise_sleep(max(sleep_time_s, 0.0))
        timestamp = time.perf_counter() - start_episode_t


@parser.wrap()
def observe(cfg: ObserveConfig) -> LeRobotDataset:
    init_logging()
    logging.info(pformat(asdict(cfg)))

    if cfg.display_data:
        init_rerun(session_name="observing", ip=cfg.display_ip, port=cfg.display_port)
    display_compressed_images = (
        True
        if (cfg.display_data and cfg.display_ip is not None and cfg.display_port is not None)
        else cfg.display_compressed_images
    )

    robot = make_robot_from_config(cfg.robot)

    # Feature 构建：action 来自 robot.action_features（echo action 用），
    # observation 来自 robot.observation_features
    robot_observation_processor = make_default_robot_observation_processor()

    dataset_features = combine_feature_dicts(
        # action features: 直接从 robot.action_features 转换，不需要经过 pipeline
        hw_to_dataset_features(robot.action_features, ACTION, use_video=cfg.dataset.video),
        # observation features: 经过 observation processor pipeline
        aggregate_pipeline_dataset_features(
            pipeline=robot_observation_processor,
            initial_features=create_initial_features(observation=robot.observation_features),
            use_videos=cfg.dataset.video,
        ),
    )

    dataset = None
    listener = None

    try:
        if cfg.resume:
            dataset = LeRobotDataset(
                cfg.dataset.repo_id,
                root=cfg.dataset.root,
                batch_encoding_size=cfg.dataset.video_encoding_batch_size,
                vcodec=cfg.dataset.vcodec,
                streaming_encoding=cfg.dataset.streaming_encoding,
                encoder_queue_maxsize=cfg.dataset.encoder_queue_maxsize,
                encoder_threads=cfg.dataset.encoder_threads,
            )
            if hasattr(robot, "cameras") and len(robot.cameras) > 0:
                dataset.start_image_writer(
                    num_processes=cfg.dataset.num_image_writer_processes,
                    num_threads=cfg.dataset.num_image_writer_threads_per_camera * len(robot.cameras),
                )
            sanity_check_dataset_robot_compatibility(dataset, robot, cfg.dataset.fps, dataset_features)
        else:
            sanity_check_dataset_name(cfg.dataset.repo_id, policy=None)
            dataset = LeRobotDataset.create(
                cfg.dataset.repo_id,
                cfg.dataset.fps,
                root=cfg.dataset.root,
                robot_type=robot.name,
                features=dataset_features,
                use_videos=cfg.dataset.video,
                image_writer_processes=cfg.dataset.num_image_writer_processes,
                image_writer_threads=cfg.dataset.num_image_writer_threads_per_camera * len(robot.cameras),
                batch_encoding_size=cfg.dataset.video_encoding_batch_size,
                vcodec=cfg.dataset.vcodec,
                streaming_encoding=cfg.dataset.streaming_encoding,
                encoder_queue_maxsize=cfg.dataset.encoder_queue_maxsize,
                encoder_threads=cfg.dataset.encoder_threads,
            )

        robot.connect()
        listener, events = init_keyboard_listener()

        if not cfg.dataset.streaming_encoding:
            logging.info(
                "Streaming encoding is disabled. Consider enabling it: "
                "--dataset.streaming_encoding=true --dataset.encoder_threads=2"
            )

        with VideoEncodingManager(dataset):
            recorded_episodes = 0
            while recorded_episodes < cfg.dataset.num_episodes and not events["stop_recording"]:
                log_say(f"Recording episode {dataset.num_episodes}", cfg.play_sounds)
                observe_loop(
                    robot=robot,
                    events=events,
                    fps=cfg.dataset.fps,
                    dataset=dataset,
                    control_time_s=cfg.dataset.episode_time_s,
                    single_task=cfg.dataset.single_task,
                    display_data=cfg.display_data,
                    display_compressed_images=display_compressed_images,
                )

                # Episode 间隔：等待用户手动 reset 环境
                # 最后一个 episode 不需要 reset
                if not events["stop_recording"] and (
                    (recorded_episodes < cfg.dataset.num_episodes - 1) or events["rerecord_episode"]
                ):
                    log_say("Reset the environment", cfg.play_sounds)
                    # 不录制，只等待用户按键（exit_early）确认 reset 完成
                    reset_start = time.perf_counter()
                    while (
                        time.perf_counter() - reset_start < cfg.dataset.reset_time_s
                        and not events["exit_early"]
                        and not events["stop_recording"]
                    ):
                        precise_sleep(0.1)
                    events["exit_early"] = False

                if events["rerecord_episode"]:
                    log_say("Re-record episode", cfg.play_sounds)
                    events["rerecord_episode"] = False
                    events["exit_early"] = False
                    dataset.clear_episode_buffer()
                    continue

                dataset.save_episode()
                recorded_episodes += 1
    finally:
        log_say("Stop recording", cfg.play_sounds, blocking=True)

        if dataset:
            dataset.finalize()

        if robot.is_connected:
            robot.disconnect()

        if not is_headless() and listener:
            listener.stop()

        if cfg.dataset.push_to_hub:
            dataset.push_to_hub(tags=cfg.dataset.tags, private=cfg.dataset.private)

        log_say("Exiting", cfg.play_sounds)

    return dataset


def main():
    observe()


if __name__ == "__main__":
    main()
