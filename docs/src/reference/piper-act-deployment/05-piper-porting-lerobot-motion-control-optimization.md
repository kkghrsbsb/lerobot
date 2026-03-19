# Piper移植lerobot运动控制优化

## 一、引言

目前已经成功将lerobot移植到了[piper](https://zhida.zhihu.com/search?content_id=262612706&content_type=Article&match_order=1&q=piper&zhida_source=entity)上，遥控、数据采集、训练、推理这些任务流程都能畅通地实施。眼下的目标是优化piper机械臂的运行效果，例如提高成功率、提高机械臂运动的稳定性。对此的主要措施可以从两方面开展，一个是提高[数据集](https://zhida.zhihu.com/search?content_id=262612706&content_type=Article&match_order=1&q=数据集&zhida_source=entity)的质量和规模，一个是对机械臂的运动控制进行进一步的优化。对于前者，暂时计划主要从减少光线干扰、在更加合理的位置部署摄像头（比如部署在臂上）、提高数据采集时示教动作的一致性这几个方面进行试验；对于后者，则将从代码层面直接对运动控制进行改善。

本文介绍通过改进代码来优化piper运动控制的方法，思路主要来源于b站视频：

【LeRobot中ACT算法介绍与调优【附源码】】 [LeRobot中ACT算法介绍与调优【附源码】_哔哩哔哩_bilibili](https://link.zhihu.com/?target=https%3A//www.bilibili.com/video/BV1WDYZzgEqj/%3Fshare_source%3Dcopy_web%26vd_source%3D2efcafa638cf97e688594939fbdc9783)

视频作者不仅提供了优化思路以及优化效果的展示，还提供了源码。

本文将对该视频中所介绍的思路、对应的代码实现进行分析和介绍，并将代码移植到piper上进行实际试验。

## 二、lerobot官方代码运动控制的缺陷

lerobot训练得到的机器人在推理验证中往往表现出较为剧烈的抖动。这是因为lerobot是模仿学习，任务示范人员在数据采集过程中无法避免由于无法熟练使用主臂而将不必要的抖动作为数据集的一部分录入，并且即便对于类似的抓取任务，示范人员也会存在动作策略上的差别，这在目前数据量少、网络结构还远未达到成熟的状况下都将导致运动控制的不稳定（其实还有非常多的原因）。

对于已经给定的网络模型，开发者能做的直接能做的就是提高数据采集质量，也就是给模型提供最优质的任务示范，这类似于学生不聪明只好老师高明一些了。除此之外，开发者还能做的就是对机器人进行强制编码，将一些机器人难以学习到的重要知识用代码强制传授给机器人。

在不破坏模型泛化能力的原则上，想要减少机械臂运动时的抖动，可以采取的策略有运动滤波和插值。两者也是机械运动控制的经典优化策略。

## 三、对ACT生成的动作序列进行插值与滤波

lerobot一般流程使用的模型是ACT，可以在policies目录下找到act相关代码。

lerobot工程移植了act的原始代码，并且实现了用于控制机器人的相关封装代码。

我们可以直接利用vscode的索引功能找到lerobot act相关代码中的select_action函数：

```python
     def select_action(self, batch: dict[str, Tensor]) -> Tensor:
         """Select a single action given environment observations.
 
         This method wraps `select_actions` in order to return one action at a time for execution in the
         environment. It works by managing the actions in a queue and only calling `select_actions` when the
         queue is empty.
         """
         self.eval()  # keeping the policy in eval mode as it could be set to train mode while queue is consumed
 
         if self.config.temporal_ensemble_coeff is not None:
             actions = self.predict_action_chunk(batch)
             action = self.temporal_ensembler.update(actions)
             return action
 
         # Action queue logic for n_action_steps > 1. When the action_queue is depleted, populate it by
         # querying the policy.
         if len(self._action_queue) == 0:
             actions = self.predict_action_chunk(batch)[:, : self.config.n_action_steps]
 
             # `self.model.forward` returns a (batch_size, n_action_steps, action_dim) tensor, but the queue
             # effectively has shape (n_action_steps, batch_size, *), hence the transpose.
             self._action_queue.extend(actions.transpose(0, 1))
         return self._action_queue.popleft()
```

这里做的事情就是如果动作队列空了，就用模型预测生成一连串新的动作。

这个逻辑生成的动作序列有一个无法避免的缺陷就是前后两次生成的动作簇（一连串的动作）首尾难以做到连续，这就是为何在推理运行过程中会出现机械臂跳变的现象（比抖动更加剧烈，类似惊厥）。

对此，可以使用线性插值生成一系列中间动作对这个原本的跳变过程进行平滑过渡。

随后对整个的动作序列进行均值滤波可以进一步缓解抖动现象。

ps写到这里突然想到在采集数据过程中如果更加缓慢地进行操作示范，最后运行效果会不会更加稳定。

基于上述思路对select_action函数进行修改：

```python
     def select_action(self, batch: dict[str, Tensor]) -> Tensor:
         """Select a single action given environment observations.
 
         This method wraps `select_actions` in order to return one action at a time for execution in the
         environment. It works by managing the actions in a queue and only calling `select_actions` when the
         queue is empty.
         """
         self.eval()  # keeping the policy in eval mode as it could be set to train mode while queue is consumed
 
         if self.config.temporal_ensemble_coeff is not None:
             actions = self.predict_action_chunk(batch)
             action = self.temporal_ensembler.update(actions)
             return action
 
         # vkrobot 模型预测，预测出n_action_steps序列长度后存入queue，随后根据序列中的action来控制机械臂
         if len(self._action_queue) == 1:
             self.last_action = self._action_queue[0].cpu().tolist()[0]
 
         # Action queue logic for n_action_steps > 1. When the action_queue is depleted, populate it by
         # querying the policy.
         if len(self._action_queue) == 0:
             actions = self.predict_action_chunk(batch)[:, : self.config.n_action_steps]
 
             # `self.model.forward` returns a (batch_size, n_action_steps, action_dim) tensor, but the queue
             # effectively has shape (n_action_steps, batch_size, *), hence the transpose.
             # vkrobot 跳边点线性插值
             self.begin_mutation_filter(actions)
             self._action_queue.extend(actions.transpose(0, 1))
             # vkrobot 均值滤波
             self.actions_mean_filtering()
         return self._action_queue.popleft()
```

这里主要修改的地方为：

```python
  if len(self._action_queue) == 1:
```

如果队列里只剩最后一个动作了，意味着这是上一次预测生成的动作簇的末尾，因此对该动作进行记录。这里补充说明：所谓的“动作”其实是一系列关节角度。

如此一来，当生成下一次预测时，就可以根据上一个动作进行线性插值来过渡，并对所有新生成的动作序列进行均值滤波：

```python
             self.begin_mutation_filter(actions)
             self._action_queue.extend(actions.transpose(0, 1))
             # vkrobot 均值滤波
             self.actions_mean_filtering()
```

插值以及滤波的函数需要额外自行实现，lerobot代码里没有。

## 四、在损失函数中加入[平滑损失](https://zhida.zhihu.com/search?content_id=262612706&content_type=Article&match_order=1&q=平滑损失&zhida_source=entity)

参考视频的作者还提出了一种减少抖动的方法，就是把平滑损失加入到总的损失中。

这个方法应该属于机器学习领域的常用的方法，这个方法思路非常巧妙，但是实际作用效果感觉有待商榷。

```python
         # # # 均值滤波loss vkrobot
         kernel_size = 11
         padding = kernel_size // 2
         x = actions_hat.transpose(1, 2)
         weight = torch.ones(6, 1, kernel_size, device=actions_hat.device) / kernel_size
         filterd_x = F.conv1d(x, weight, padding=padding, groups=6)
         filterd_tensor = filterd_x.transpose(1,2)
         mean_loss = torch.abs(actions_hat - filterd_tensor).mean()
         loss += mean_loss
         loss_dict["mean_loss"] = mean_loss.item()
```

## 五、其他

参考视频里还提到了修改模型推理参数来提高抓取成功率。

在piper尝试了该方法，设置为推理100步，执行其中的前50步，发现会让机器人陷入一种彷徨状态，止步不前。改成70步也容易陷入上述情况，这个参数修改可能要根据实际情况决定。

此外，参考视频还提到在采集数据时就引入均值滤波，这个方法应该是有效的，这里打算在之后专门针对数据采集优化的研究中再进行试验。

在引入插值与滤波后直接运行先前训练得到的模型，前后运行效果可以查看视频：

【Piper移植lerobot运动控制优化效果展示】 [Piper移植lerobot运动控制优化效果展示_哔哩哔哩_bilibili](https://link.zhihu.com/?target=https%3A//www.bilibili.com/video/BV1dyazzqEty/%3Fshare_source%3Dcopy_web%26vd_source%3D2efcafa638cf97e688594939fbdc9783)

总体而言，在推理过程中piper机械臂的运动变得更加平稳，抓取成功率也有一定的提高。