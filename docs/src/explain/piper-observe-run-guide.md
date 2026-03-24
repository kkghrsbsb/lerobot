# piper-observe 运行命令与操作指南

## 说明范围

本文档面向实际操作者，说明 `piper-observe` 脚本的完整运行命令、参数含义、采集过程中的键盘操作，以及常见问题处理。

---

## 一、前置条件

1. **硬件连接**：Piper 机械臂通过 USB-CAN 适配器连接到主机，电源已开启
2. **CAN 端口**：已通过 udev 规则自动激活，或手动执行过：
   ```shell
   sudo ./piper-generate-udev-rule -i can0 -b 1000000
   ```
3. **环境**：在项目根目录下，虚拟环境已激活（`source .venv/bin/activate.fish` 或 `uv run`）
4. **相机**：USB 相机已连接，设备索引与 `config_piper_follower.py` 中配置一致（当前配置为 `index_or_path=2` 和 `index_or_path=4`）

---

## 二、完整运行命令

### 最小必填参数

```shell
piper-observe \
    --robot.type=piper_follower \
    --dataset.repo_id=xinger/my_dataset \
    --dataset.single_task="Pick up the cube"
```

### 完整参数（含默认值）

```shell
piper-observe \
    --robot.type=piper_follower \
    --dataset.repo_id=xinger/my_dataset \
    --dataset.single_task="Pick up the cube" \
    --dataset.fps=30 \
    --dataset.num_episodes=5 \
    --dataset.episode_time_s=60 \
    --dataset.reset_time_s=60 \
    --dataset.video=true \
    --dataset.push_to_hub=false \
    --display_data=false \
    --play_sounds=true \
    --resume=false
```

---

## 三、参数说明

### 必填参数

| 参数 | 说明 |
|------|------|
| `--robot.type` | 机器人类型，固定为 `piper_follower` |
| `--dataset.repo_id` | 数据集 ID，格式 `{用户名}/{数据集名}`，决定本地存储路径 |
| `--dataset.single_task` | 任务描述字符串，写入每一帧的 `task` 字段。为 None 时会报错 |

### 采集控制参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dataset.fps` | 30 | 采集帧率（Hz），与相机 fps 匹配效果最好 |
| `--dataset.num_episodes` | 50 | 总共采集多少个 episode |
| `--dataset.episode_time_s` | 60 | 每个 episode 采集时长（秒） |
| `--dataset.reset_time_s` | 60 | episode 间等待 reset 的最大时间（秒） |

### 存储与编码参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dataset.video` | true | 是否将图像编码为视频（false 则存 PNG） |
| `--dataset.vcodec` | `libsvtav1` | 视频编码器，可选 `h264`、`hevc`、`libsvtav1`、`auto` |
| `--dataset.streaming_encoding` | false | 实时编码（true 时 save_episode 几乎瞬间完成） |
| `--dataset.push_to_hub` | true | 采集结束后是否上传 HuggingFace Hub。**本地测试务必设为 false** |
| `--dataset.private` | false | 上传时是否设为私有仓库 |
| `--dataset.root` | None | 数据集本地存储根目录，None 则使用 `$HF_LEROBOT_HOME/{repo_id}` |

### 显示与调试参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--display_data` | false | 是否通过 rerun 可视化相机和关节数据 |
| `--display_ip` | None | rerun 远程连接 IP |
| `--display_port` | None | rerun 远程连接端口 |
| `--play_sounds` | true | 是否播放语音提示（episode 开始、reset、结束等） |
| `--resume` | false | 是否恢复上次未完成的采集（续录） |

---

## 四、采集过程与键盘操作

### 整体流程

```
启动 → connect（使能 + 回零位） → [episode 循环] → disconnect（安全关闭）
                                        │
                          ┌─────────────┼─────────────┐
                          ▼             ▼             ▼
                      录制 episode   等待 reset   保存 episode
                     (episode_time_s) (按键确认)   (save_episode)
```

### 键盘按键

采集启动后，脚本会监听键盘事件。以下按键在采集过程中有效：

| 按键 | 作用 | 使用时机 |
|------|------|---------|
| **右箭头 →** | `exit_early`：提前结束当前阶段 | 录制中：提前结束当前 episode；reset 等待中：确认 reset 完成，开始下一个 episode |
| **Escape** | `stop_recording`：停止整个采集 | 任何时候：停止录制并进入清理流程 |
| **Backspace** | `rerecord_episode`：重录当前 episode | 当前 episode 数据不满意时，清空当前 episode 缓冲区重录 |

### 典型操作序列

1. **启动脚本**：机械臂自动使能并回零位
2. **外部控制开始**：在另一个终端运行外部 CAN 控制脚本，让机械臂开始运动
3. **录制中**：脚本自动读取关节和相机数据，无需操作
4. **episode 结束**：到达 `episode_time_s` 后自动结束，或按 **→** 提前结束
5. **reset 阶段**：
   - 语音提示 "Reset the environment"
   - 手动将物体/环境复位
   - 按 **→** 确认 reset 完成，进入下一个 episode
   - 如果不按键，等待 `reset_time_s` 秒后自动进入下一个 episode
6. **重录**：如果当前 episode 操作失误，按 **Backspace** 丢弃并重录
7. **结束**：录完所有 episode 后自动结束，或按 **Escape** 提前终止
8. **关闭**：机械臂自动回安全位并失能

---

## 五、数据集输出

采集完成后，数据集存储在 `$HF_LEROBOT_HOME/{repo_id}` 目录下（默认 `~/.cache/huggingface/lerobot/{repo_id}`）。

### 每帧数据结构

| 字段 | dtype | shape | 说明 |
|------|-------|-------|------|
| `observation.state` | float32 | (7,) | 关节 1-6 + 夹爪位置，rad |
| `observation.images.cam2` | video | (480, 640, 3) | 相机 2 图像 |
| `observation.images.cam4` | video | (480, 640, 3) | 相机 4 图像 |
| `action` | float32 | (7,) | echo action，值与 `observation.state` 相同 |
| `task` | string | — | 任务描述 |

### echo action 说明

由于本脚本无 teleop 控制，action 使用 echo 策略：`action[t] = state[t]`。详见 [piper_observe.py 脚本说明](piper-observe-script.md) 中的第五节。

---

## 六、常见问题

### CAN 端口未找到

```
ValueError: No ports found. Make sure the Piper is connected and turned on.
```

检查 USB-CAN 适配器是否连接，机械臂电源是否开启。运行 `ip link show` 确认 `can0` 是否存在。

### 相机打开失败

```
RuntimeError: Could not open camera ...
```

运行 `ls /dev/video*` 确认相机设备索引，修改 `config_piper_follower.py` 中的 `index_or_path` 使其匹配。

### 帧率不足警告

```
WARNING: Observe loop is running slower (15.2 Hz) than the target FPS (30 Hz)
```

相机或 CAN 读取拖慢了循环。可以降低 `--dataset.fps`，或减少相机数量/分辨率。

### 续录已有数据集

```shell
piper-observe \
    --robot.type=piper_follower \
    --dataset.repo_id=xinger/my_dataset \
    --dataset.single_task="Pick up the cube" \
    --resume=true
```

`--resume=true` 会加载已有数据集并在其基础上追加新 episode。
