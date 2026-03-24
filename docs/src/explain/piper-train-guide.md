# piper-observe 数据集本地训练指南

## 说明范围

说明如何使用 `piper-observe` 采集的本地数据集，通过 `lerobot-train` 训练 ACT 策略模型。涵盖命令、参数、数据集要求、训练流程和常见问题。

---

## 一、前置条件

1. **数据集已采集**：通过 `piper-observe` 完成至少一轮数据采集，数据集存储在本地
2. **GPU 环境**：推荐 NVIDIA GPU（CUDA），CPU 也可训练但极慢
3. **依赖已安装**：lerobot 虚拟环境已激活

确认数据集路径（默认）：

```shell
ls ~/.cache/huggingface/lerobot/xinger/piper_dataset_00
# 应包含: data/  info.json  stats.json  tasks.json  videos/（如有）
```

---

## 二、训练命令

### 最小命令

```shell
lerobot-train \
    --dataset.repo_id=xinger/piper_dataset_00 \
    --policy.type=act \
    --output_dir=outputs/train/act_piper_00
```

`repo_id` 会自动匹配 `~/.cache/huggingface/lerobot/{repo_id}` 下的本地数据集。

### 推荐完整命令

```shell
lerobot-train \
    --dataset.repo_id=xinger/piper_dataset_00 \
    --policy.type=act \
    --output_dir=outputs/train/act_piper_00 \
    --batch_size=8 \
    --steps=100000 \
    --num_workers=4 \
    --save_freq=10000 \
    --log_freq=100 \
    --eval_freq=0 \
    --seed=42 \
    --policy.device=cuda \
    --policy.push_to_hub=false \
    --wandb.enable=false
```

### 使用特定 episode 子集训练

```shell
lerobot-train \
    --dataset.repo_id=xinger/piper_dataset_00 \
    --dataset.episodes='[0,1,2,3,4]' \
    --policy.type=act \
    --output_dir=outputs/train/act_piper_00_subset
```

---

## 三、参数说明

### 数据集参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dataset.repo_id` | (必填) | 数据集 ID，自动在 `$HF_LEROBOT_HOME` 下查找 |
| `--dataset.root` | None | 显式指定本地路径（覆盖自动查找） |
| `--dataset.episodes` | None | 使用哪些 episode，None 表示全部 |
| `--dataset.use_imagenet_stats` | true | 图像使用 ImageNet 归一化统计量 |

### 策略参数（ACT）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--policy.type` | (必填) | 策略类型，使用 `act` |
| `--policy.device` | cuda | 训练设备，`cuda` 或 `cpu` |
| `--policy.push_to_hub` | true | 训练结束是否上传 Hub。**本地训练设 false** |
| `--policy.chunk_size` | 100 | action chunking 步数（预测未来多少步 action） |
| `--policy.n_action_steps` | 100 | 每次推理执行多少步 |
| `--policy.dim_model` | 512 | Transformer 隐藏层维度 |
| `--policy.n_heads` | 8 | 注意力头数 |
| `--policy.n_encoder_layers` | 4 | 编码器层数 |
| `--policy.n_decoder_layers` | 1 | 解码器层数 |
| `--policy.use_vae` | true | 是否使用 VAE |
| `--policy.vision_backbone` | resnet18 | 视觉骨干网络 |

> `input_features` 和 `output_features` 不需要手动指定，会从数据集元数据自动推断。

### 训练控制参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--batch_size` | 8 | 每步训练的 batch 大小 |
| `--steps` | 100000 | 总训练步数 |
| `--num_workers` | 4 | DataLoader 工作进程数 |
| `--seed` | 1000 | 随机种子 |
| `--use_policy_training_preset` | true | 使用策略内置的优化器/调度器预设 |

### 日志与保存参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--output_dir` | 自动生成 | 输出目录（checkpoint、日志） |
| `--log_freq` | 200 | 每多少步打印一次训练指标 |
| `--save_freq` | 20000 | 每多少步保存一次 checkpoint |
| `--save_checkpoint` | true | 是否保存 checkpoint |
| `--eval_freq` | 20000 | 评估频率。**实物训练设为 0（无仿真环境）** |
| `--wandb.enable` | false | 是否启用 Weights & Biases 日志 |
| `--resume` | false | 是否从上次 checkpoint 恢复训练 |

---

## 四、训练流程

```
lerobot-train
    │
    ├── 1. 加载数据集 (make_dataset)
    │       └── 读取 info.json → 推断 features → 计算 stats
    │
    ├── 2. 创建策略 (make_policy)
    │       └── ACT: ResNet18 视觉编码 + Transformer encoder/decoder + VAE
    │       └── 自动从数据集 features 推断 input/output 维度
    │
    ├── 3. 创建优化器 (make_optimizer_and_scheduler)
    │       └── ACT 预设: AdamW, lr=1e-5, weight_decay=1e-4
    │
    ├── 4. 训练循环 (steps 次)
    │       ├── 采样 batch
    │       ├── 预处理（归一化）
    │       ├── forward + backward
    │       ├── 梯度裁剪 + optimizer.step()
    │       ├── 定期日志 (log_freq)
    │       └── 定期保存 checkpoint (save_freq)
    │
    └── 5. 训练结束
            └── 保存最终 checkpoint
```

---

## 五、输出目录结构

```
outputs/train/act_piper_00/
├── train_config.json                    ← 完整训练配置（可用于恢复）
├── checkpoints/
│   ├── 010000/                          ← step 10000 的 checkpoint
│   │   ├── config.json                  ← 策略配置
│   │   ├── model.safetensors            ← 模型权重
│   │   ├── preprocessor/               ← 归一化参数
│   │   ├── postprocessor/
│   │   └── train_state/                 ← 优化器状态（用于恢复训练）
│   ├── 020000/
│   └── last -> 020000                   ← 指向最新 checkpoint 的软链接
└── eval/                                ← 评估结果（仿真训练才有）
```

---

## 六、恢复中断的训练

```shell
lerobot-train \
    --config_path=outputs/train/act_piper_00/train_config.json \
    --resume=true
```

会从最后保存的 checkpoint 恢复优化器状态和训练步数，继续训练。

---

## 七、数据集与 ACT 的兼容性

### 数据集 features 要求

ACT 需要以下字段（`piper-observe` 采集的数据集已满足）：

| 字段 | 要求 | piper-observe 输出 |
|------|------|-------------------|
| `observation.images.*` | 至少一个图像 key | `observation.images.cam2`, `observation.images.cam4` |
| `observation.state` | 可选，本体感觉状态 | (7,) float32，关节 + 夹爪 |
| `action` | 必须，训练目标 | (7,) float32，echo action |

### echo action 与 ACT 训练

echo action 下 `action[t] = state[t]`，ACT 的 action chunking 使其非平凡：

- ACT 预测 `action[t:t+chunk_size]`，即未来 chunk_size 步的轨迹
- 训练目标：给定当前观测，预测接下来的关节位置序列
- 如果轨迹是运动中的，这是有意义的预测任务

### 建议的初始训练参数

小数据集（< 30 episodes）首次训练建议：

```shell
lerobot-train \
    --dataset.repo_id=xinger/piper_dataset_00 \
    --policy.type=act \
    --output_dir=outputs/train/act_piper_00 \
    --batch_size=8 \
    --steps=50000 \
    --save_freq=5000 \
    --log_freq=100 \
    --eval_freq=0 \
    --policy.device=cuda \
    --policy.push_to_hub=false \
    --wandb.enable=false
```

---

## 八、常见问题

### CUDA 内存不足

```
torch.cuda.OutOfMemoryError: CUDA out of memory
```

降低 `--batch_size`（如 4 或 2），或降低图像分辨率。

### 找不到数据集

```
FileNotFoundError: ...
```

确认数据集路径存在。可以显式指定：
```shell
--dataset.root=~/.cache/huggingface/lerobot/xinger/piper_dataset_00
```

### 训练 loss 不下降

- 检查数据集是否有足够的运动多样性（echo action 下静止不动的 episode 无训练价值）
- 增加 `--steps`
- 检查 `--dataset.episodes` 是否遗漏了有效 episode

### eval_freq 报错

实物训练没有仿真环境，必须设 `--eval_freq=0`，否则会尝试创建 gym 环境而报错。
