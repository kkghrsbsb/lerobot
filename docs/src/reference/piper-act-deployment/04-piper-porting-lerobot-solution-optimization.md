# piper移植lerobot方案优化

## 一、引言

在《[piper移植lerobot开发记录](https://zhuanlan.zhihu.com/p/1942596287334711514)》一文在[piper机械臂](https://zhida.zhihu.com/search?content_id=262478999&content_type=Article&match_order=1&q=piper机械臂&zhida_source=entity)上复现了lerobot，同时在《[piper sdk接口函数整理](https://zhuanlan.zhihu.com/p/1943706175024637040)》一文中对此前遇到的问题进行了分析整理，并列举了[piper_sdk](https://zhida.zhihu.com/search?content_id=262478999&content_type=Article&match_order=1&q=piper_sdk&zhida_source=entity)中对于解决眼下问题可能有效的接口函数。本文在进一步详细阅读了piper sdk开发文档的基础上，对现有的移植实现方案进行了优化，并经过实际测试验证解决了存在的三个主要问题（直接引自《[piper sdk接口函数整理](https://zhuanlan.zhihu.com/p/1943706175024637040)》一文）：

（1）启动piper有时候会出现端口连不上的的问题，发送指令会报错。现在的解决方式是断开两个机械臂的USB连接和电源，然后只连接一个机械臂的电源和USB，并按照机械臂单个调试的流程启动一个机械臂关节运动控制的demo，运行正常后再接上所有的线，开始跑lerobot。

（2）lerobot record过程中在夹爪不小心碰到桌面后会出现从臂停滞，主臂无法正常控制从臂（会出现非常长的控制间隔），只能中断采集。并且由于lerobot最新的包不支持本地resume（表面上支持，实际上每次都会尝试连接[huggingface](https://zhida.zhihu.com/search?content_id=262272320&content_type=Article&match_order=1&q=huggingface&zhida_source=entity)云端数据集，然后由于网络连接问题卡住不动），中断采集意味着需要重新来过，非常不方便，甚至可以说使得正常数据采集完全无法进行。在piper移植lerobot的过程中，我们选择了简单的演示任务来避免从臂碰撞卡死，但是这个并非长久之计。

（3）推理阶段似乎对于初始位置有一道高墙。第一次训练出来后发现机械臂没有动静，后续检查了代码、输出debug信息也没有找到问题，最后在绝望中胡乱尝试突然能够正常推理控制。推测原因是初始位置policy并没有学习到，因为采集过程中每次的初始位置我们摆放地很随意，所以可能对于从零点位置出发的机械臂，policy不能正常控制。

## 二、piper初始连接问题

经过实际尝试发现，这个问题出在piper的can连接激活上。

由于lerobot的主从控制通讯逻辑是读取主臂关节角度然后再作为目标关节角度由lerobot的中间程序写入从臂并进行控制，这和piper官方的主从控制逻辑不太一样，后者是通过一个can口通过离线设置主从臂后直接由主臂通过同一条can线控制从臂。按照lerobot的通讯逻辑，主臂和从臂需要分别连接一个can口，这意味着需要同时激活多个can口（原先由于共用一个can线通讯，只需要激活一个）。

问题出在运行piper官方所述的bash [can_muti_activate.sh](https://zhida.zhihu.com/search?content_id=262478999&content_type=Article&match_order=1&q=can_muti_activate.sh&zhida_source=entity)后，会出现报错，并且前置的can口设置无法生效：

```text
 USB_PORTS["3-1.4:1.0"]="can_left:1000000"
 USB_PORTS["3-1.1:1.0"]="can_right:1000000"
```

首先会报错说再终端直接赋值是不对的，然后即便使用正确方式赋值，在运行bash can_muti_activate.sh时也会发现无法生效。因此在先前的试验中，实际使用的是单个can口激活的指令，也就是分别激活从臂和主臂的can口。这种解决方法本身比较草率，可能就是导致初始化连接经常出错，而需要繁琐并且并不合理的流程（断电、断开can口等）初始化的原因。

在这次方案优化的过程中，本文直接复制了一份can_muti_activate.sh，并直接编辑了其中有关USB_PORTS的变量定义。之后再运行bash my_muti_activate.sh（自定义）即可正常初始化piper连接，并且经过多次试验，通过该shell激活的piper可以稳定连接，不会出现连接传输上的报错。

## 三、在数据采集过程中从臂断连问题

在发现断连问题时直觉就是可能触发了机械臂的碰撞保护。

在前面接口函数整理的过程中发现了一个碰撞保护相关的配置函数，这个非常关键：

```python
  def CrashProtectionConfig(joint_1_protection_level: int,
                          joint_2_protection_level: int,
                          joint_3_protection_level: int,
                          joint_4_protection_level: int,
                          joint_5_protection_level: int,
                          joint_6_protection_level: int)
```

所以本文在piper机械臂connect函数中加入了这个配置，并且直接将所有关节的值设置为0，也就是没有碰撞检测。

这样修改后发现数据采集过程中不再出现断连问题，即使故意引导从臂磕碰桌面多次也不会触发断连。

## 四、推理部署问题

先前分析认为可能是由于数据采集过程中机械臂的初始位置比较随意，导致训练获得的policy不能很好地理解初始状态，因此在初始位置卡住（不执行任何动作）。

本文首先删除了原先piper实现中在disconnect函数中回到初始位置地代码，这样就可以利用[teleporate](https://zhida.zhihu.com/search?content_id=262478999&content_type=Article&match_order=1&q=teleporate&zhida_source=entity)程序使用主臂控制从臂从任意初始状态开始推理。但是通过调换不同初始位置，policy依旧无法正常推理。甚至在整个优化过程中，使用原先地policy模型都没能再现正常推理过程（此前曾由于未知原因成果生成有效推理控制）。但所幸曾经成果运行过推理，所以姑且可以认为piper移植代码是没有问题的，因此问题大概率出在数据采集上。原先的数据采集任务是引导机械臂末端去指一下目标（一个玩具刀模型），推测可能玩具的外观特征比较特殊，不适合样本比较少的验证试验，此外也有可能是任务过于简单，导致policy在训练过程中尝试学到的东西过少。一种合理的猜测是模型并没有认识到指认玩具是任务目标，而是把回到初始位置视为了终极任务目标。

对此本文重新采用了在lerobot原生机械臂上的数据采集任务方案，也就是抓取黄色橡皮泥到盒子中。这个数据采集任务方案原先由于从臂断连问题被放弃。

本文还是采集了30组数据进行训练，最终获得的policy虽然效果非常糟糕，但是通过试验观测可以认为能够正常进行推理控制。效果糟糕的主要原因可能在于数据量还不够充足。效果可以查看视频：

【piper移植lerobot效果展示】 [piper移植lerobot效果展示_哔哩哔哩_bilibili](https://link.zhihu.com/?target=https%3A//www.bilibili.com/video/BV1qYaGzcE6p/%3Fshare_source%3Dcopy_web%26vd_source%3D2efcafa638cf97e688594939fbdc9783)

ps试验中发现光线可能对于推理效果影响很大，录制视频时候的效果比第一次跑通的时候效果好很多。原因可能是视频录制时间和数据采集的时间段相同都在下午，存在窗户透过来的自然光照，而第一次模型推理部署的时候在晚间（下午采集数据晚上完成训练）。下一步的目标是想办法提高数据集质量和规模，这个问题可以在后续继续研究。