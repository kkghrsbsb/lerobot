# Piper ACT 模型推理（策略部署）指南

## 说明范围

说明如何将训练好的 ACT 模型部署到 Piper 机械臂上运行推理，解释为什么使用 `lerobot-record` 而非单独的推理脚本，以及关键参数含义。

---

## 一、为什么用 lerobot-record 做推理

lerobot 框架没有独立的"推理脚本"。`lerobot-record` 本身支持三种模式：

| 模式 | 参数 | 用途 |
|------|------|------|
| 纯遥操作 | `--teleop.type=...` | 人控制主臂，从臂跟随，录制数据 |
| 策略推理 | `--policy.path=...` | 模型输出 action，机械臂执行，同时录制 |
| 混合 | 两者都给 | 人和模型共同控制 |

策略推理模式下，`lerobot-record` 每帧执行：

```
读观测 → 模型推理 action → robot.send_action() → 录制到数据集
```

录制评估数据集是有意设计——方便事后回看模型表现、对比不同 checkpoint、统计成功率。

---

## 二、运行命令

```shell
lerobot-record \
    --robot.type=piper_follower \
    --policy.path=outputs/train/act_piper_00/checkpoints/last/pretrained_model \
    --dataset.repo_id=xinger/eval_piper_00 \
    --dataset.single_task="Place Bobby inside the mooncake" \
    --dataset.num_episodes=5 \
    --dataset.episode_time_s=60 \
    --dataset.fps=30 \
    --dataset.push_to_hub=false \
    --policy.device=cuda
```

---

## 三、关键参数解释

### `--policy.path`

训练输出的 checkpoint 路径。目录下包含 `config.json`（策略配置）和 `model.safetensors`（权重）。`lerobot-record` 会自动加载模型、创建预处理/后处理 pipeline、推断输入输出维度。

查看可用 checkpoint：
```shell
ls outputs/train/act_piper_00/checkpoints/
# 005000/  010000/  ...  last -> 050000
```

`last` 是软链接指向最新的 checkpoint。也可以指定中间的 checkpoint 来对比效果。

### `--dataset.repo_id`

评估数据集的 ID。**命名规则：使用策略推理时必须以 `eval_` 开头**，否则框架会报错。这是 lerobot 的硬性约定，用于区分训练数据集和评估数据集。

### `--policy.device=cuda`

模型推理设备。`cuda` 利用 GPU 加速推理，保证实时性。`cpu` 也能跑但可能达不到目标帧率。

### `--dataset.push_to_hub=false`

本地评估不需要上传 Hub。

### 其他参数

`robot.type`、`fps`、`episode_time_s`、`num_episodes`、`single_task` 含义与数据采集时相同，不再赘述。

---

## 四、注意事项

- **安全**：首次运行策略推理时，模型可能输出不合理的 action，导致机械臂剧烈运动。手放在急停附近，准备随时断电。
- **残留目录**：如果上次运行被 Ctrl+C 中断，再次运行前需删除残留数据集目录：
  ```shell
  rm -rf ~/.cache/huggingface/lerobot/xinger/eval_piper_00
  ```
- **回看评估结果**：
  ```shell
  lerobot-dataset-viz --repo-id xinger/eval_piper_00 --episode-index 0
  ```
