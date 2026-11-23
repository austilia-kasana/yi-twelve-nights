# 驿 · 十二夜

一个回合制资源调度游戏。你是山口驿站的驿丞。十二个夜晚，把北边的战报送过山。

单局 15–25 分钟。没有实时操作，没有战斗。核心是**判断信息、承担风险、做取舍**。

---

## 怎么开始

**方式一：双击 exe**

```
dist\驿.exe
```

不需要装 Python，不需要联网。

**方式二：从源码跑**

```bash
pip install pygame-ce numpy
python main.py
```

可选参数：

```bash
python main.py --seed 42        # 固定随机种子（复盘用）
python main.py --assets-check   # 只检查素材和字体
```

---

## 操作

| 操作 | 说明 |
|---|---|
| 点一封信 | 选中它 |
| 点一个骑手 | 派给他（再点一次取消） |
| 点一匹马 | 换马 |
| 「送出今夜」/ 空格 / 回车 | 推进一夜 |
| 「整备」 | 买马、雇人、喂料、添油 |
| 菜单 / Esc | 回标题（会丢掉这一局） |

---

## 玩什么

### 三条资源

- **信**（0–100）——唯一会输的东西。归零，驿就被撤了。
- **金**——买东西用。
- **油**——没油就没灯，夜里走得更慢。

### 三条路

| 路线 | 距离 | 特点 |
|---|---|---|
| 北口 | 3 | 最快。但下雪就废 |
| 河渡 | 4 | 下雨涨水，走不动 |
| 旧矿道 | 5 | 又长又黑，但天气拿它没办法 |

### 核心张力：天气预报只有七成准

黄昏时你能看到「今夜预报」。但三成的情况下它会错。

**预报说晴，你可能赌一把把最快的骑手派去北口。也可能保守一点，用远一点的路。**

这个赌，每一夜都要做一次。

### 骑手和马都是消耗品

骑手跑一趟扣体力，歇一晚回一点。马不会自己恢复，得花金喂。

**体力和状态低的会显著减速**——所以「谁配谁」是有讲究的。

### 胜负

十二夜之后：
- **信 ≥ 60** —— 守住
- **信 < 60** —— 撑过了，但驿已经名存实亡
- **信 = 0** —— 中途被撤

评价按最终信给 S / A / B / C。

---

## 目录结构

```
relay/
  main.py                 入口
  build.py                打包脚本
  relay/
    core/                 纯逻辑，不依赖 pygame
      balance.py          所有可调数值
      models.py           数据结构
      sim.py              GameState：模拟核心
    ui/
      theme.py            颜色 / 字体 / 排版
      art.py              素材加载（缺失自动替身）
      widgets.py          按钮 / 卡片 / 提示
      fx.py               雪、余烬、震屏
      scenes.py           标题 / 主界面 / 结算
      app.py              主循环
    audio/
      synth.py            numpy 合成音效
      player.py           播放与降级
    assets/
      art/                程序生成的美术（ComfyUI）
      sfx/                程序生成的音效（numpy）
  tools/
    comfy_client.py       ComfyUI API 封装
    gen_assets.py         全套美术生成
    sim_balance.py        批量平衡模拟
  tests/
    test_core.py          25 个单元测试
  docs/
    GDD.md                设计文档
    README.md             本文件
```

---

## 开发

### 跑测试

```bash
python -m unittest discover -s tests -v
```

### 平衡模拟

```bash
python tools/sim_balance.py -n 500
```

会用一个「还算聪明」的 AI 策略跑 500 局，输出通关率和终局分布。

### 重新生成美术

需要本机跑着 ComfyUI（默认 `127.0.0.1:8188`）：

```bash
python tools/gen_assets.py --list        # 看清单
python tools/gen_assets.py               # 出全部（跳过已有的）
python tools/gen_assets.py --only title  # 只出一张
python tools/gen_assets.py --force       # 全重出
```

模型：`RealVisXL_V4.0.safetensors`，采样器 `dpmpp_2m` / `karras`，cfg 6.0。
每张约 25–35 秒。

### 重新生成音效

```bash
python relay/audio/synth.py
```

纯 numpy 合成，不需要外部素材。

### 打包

```bash
python build.py            # 单文件 exe → dist/驿.exe
python build.py --clean    # 先清理
python build.py --console  # 保留控制台（调试）
```

---

## 设计说明

**为什么是回合制**：目标玩家要的是思考时间。实时操作会把「算余量」变成「拼手速」。

**为什么天气预报只有七成准**：这是整个游戏的信息核心。如果预报百分百准，最优解就唯一了；如果完全不预告，玩家就只能撞运气。七成刚刚好——够你算，但不保证。

**为什么拒收不罚**：玩家永远可以「少接一封」。这让「放弃」成为一个正当策略，而不是失败。

**为什么事件都有明确概率**：所有损失都必须可归因。如果一场暴雪纯随机地毁掉全局，玩家学不到任何东西。

**为什么没有战斗**：战争只作为信的背景存在。你只看到纸和雪。这比画一场战斗更省，也更扣主题。

---

## 已知限制

- 中文字体依赖系统。找不到 Microsoft YaHei / SimHei 时会退回 pygame 默认字体（中文会显示成方块）。`--assets-check` 能检测到。
- 美术是本地 ComfyUI 生成的，风格统一但细节不完全一致。
- 没有存档。一局 20 分钟，关掉就没了。
- 只有单一难度。

---

## 素材来源

- **美术**：本机 ComfyUI + RealVisXL_V4.0 生成，程序化提示词，无水印无版权素材。
- **音效**：numpy 合成，本仓库代码生成。
- **字体**：系统字体，不随包分发。
- **代码**：本项目全部自写。

---

## 版本

见 `CHANGELOG.md`。
