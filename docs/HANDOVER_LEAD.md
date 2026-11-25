# 交接文档 · lead 会话（2026-11-24 ~ 11-25）

> **写于**：2026-11-26 00:10
> **背景**：本会话日志 90+ MB，切会话出现 CPU 高额短时占用。
> 用户要求结束本会话，把各项目交接出去。
>
> **读这份文档的人**：接管《驿·十二夜》或其他相关工作的会话。
> **最重要的一句**：游戏项目**已经不在我手上**了，v0.5.1 是另一个会话做的。
> 本文记录的是**我做了什么、做错了什么、留下了什么可复用的东西**。

---

## 一、我推进过的东西（按重要性）

| # | 项目 | 状态 | 现在归谁 |
|---|---|---|---|
| 1 | 《驿·十二夜》v0.4.1 → v0.5.0 | **已交接** | 另一个会话，已到 v0.5.1 |
| 2 | 给外部评审（Gemini/GPT）的 relay 机制 | 阻塞中 | 没人接，需要时看本文第四节 |
| 3 | 模拟器/指标工具链（`tools/metrics.py` 等） | 在用 | 随游戏一起 |
| 4 | 文档体系（RELAY_LOG / PHASE_C / EVALUATION_*） | 已提交 | 随仓库 |

---

## 二、《驿·十二夜》—— 我的贡献与错误

### 2.1 我做的提交（`ab8390f` 之后到 `63a2450`）

```
63a2450  feat: 帮助页补第⑤节「那到底该怎么想」      ← 我的最后一个提交
917f872  docs: 外部评估报告（Gemini）
791a33d  fix: 结算页指标标签在深色面板上几乎看不见
bbd7e15  docs: RELAY_LOG 记录 Round 2→3 裁决
d02c80f  docs: ISSUES/ROADMAP 同步到 v0.5.0
c0b714f  docs: 评估报告需求清单
8aafb03  release: v0.5.0 断崖
ebb8bf2  balance: 八百里 slack 0→1，S 阈值 80→77
f674df9  feat: 帮助页四件事
f150956  feat: Round 1 smart 策略 + 八策略对照
3a5d770  docs: RELAY_BLOCKED
d7505a3  docs: RELAY_Q1
5a06d54  fix: Round 0.5 结算闭环 + world_rng
```

### 2.2 我真正做成的事

**① 结算闭环彻底修完**（`5a06d54`）
- 混合结算测试断言**实际信值**（原来只断言记录顺序）
- `advance()` 检查重复 Dispatch ID
- `_autoplay()` 改用可用性 API（原来静默停在第 1~2 夜）
- **拆出 `world_rng`**：天气/信件生成不再受玩家策略影响。不拆的话「同 seed 不同策略」不是配对实验。

**② 用数据推翻了一个错误假设**（`f150956`）
我以为「AI 雇 4 人买 2 马」是买马逻辑 bug，写了 `smart` 策略去修。
结果：

```
smart(AI会算账)     78.0% 达标   ← 改了买马逻辑
safe (只改 min_margin=1) 77.2%   ← 没改买马逻辑
smart_alt(另一公式) 77.2%
base(原AI)          28.8%
```

**买马逻辑不是瓶颈。50 个百分点全部来自 `min_margin>=1` 这一个开关。**
「编制失衡」是保守策略的**结果**，不是原因。

**③ 平衡调整**（`ebb8bf2`）
按 Gemini 裁决「让断崖变缓」：
- `DISPATCH_KINDS["express"]["slack"]` 0 → 1
- `RATING_THRESHOLDS` S 档 80 → 77

500 局实测：达标 71.2% / S 27.2%。

### 2.3 ⚠️ 我做错的三件事（重要，别重复）

**错误 1：`SmartStrategy` 的 `min_margin` 字段没真设**

我在类 docstring 写了「`min_margin=1`」，但**类上没这个字段**。
`metrics.py` 里是显式传 `SmartStrategy(min_margin=1)` 才对的。
结果 `tools/sim_balance.py` 里写死的 `Strategy()` 报 **48%/16%**，
和文档的 71.2%/27.2% 是两套口径。

**接管会话在 `75dc35a` 修了这个**（给类补上字段 + 给 sim_balance 加 `-s` 参数）。
**教训：docstring 里写的默认值，必须在类上真的设。文档数字必须能一键复现。**

**错误 2：用坐标点击切浏览器标签，误关了用户的 ChatGPT 标签**

用 `Ctrl+Shift+T` 救回来了，但那是运气。
**教训：切标签永远用 `Ctrl+1/2/3`，不要点坐标。**

**错误 3：token 烧得太快**

前 30 分钟用掉 6 元（总额度 20 元），主要原因是我截图太多，每张 1~2k token。
后面压到 2 元/30 分钟。
**教训：能读文件就不截图；能 OCR 就不发给视觉模型；截图一律裁到必要区域且 maxWidth ≤ 800。**

### 2.4 另一个会话已经做的（不要重复）

`75dc35a` (v0.5.1)：
- 右上角「菜单」改成「存盘退出」并真的存盘（原来点一下直接丢局）
- 修路按钮单位错（「3→2 夜」应为「路程 3→2」）
- 平衡口径统一（就是修我的错误 1）
- 测试 81 → 91 项

**接手前先 `git log` 看一眼，别假设仓库还停在我说的状态。**

---

## 三、环境事实（这些是硬信息，可复用）

### 3.1 项目路径

```
仓库       C:\Users\19536\AI\games\relay
GitHub     austilia-kasana/yi-twelve-nights
Python     C:\Users\19536\AppData\Local\Programs\Python\Python314\python.exe
产物       dist\驿.exe（约 53 MB）
存档       打包后：exe 同目录的 saves\auto.json
           开发时：项目根 saves\auto.json
```

### 3.2 Token 余额监控（**免费，零成本**）

```powershell
$j = Get-Content "C:\Users\19536\.dsh\.dshw-usage.json" -Raw -Encoding utf8 | ConvertFrom-Json
$j.lastBalance    # 剩余元
$j.todayUsage     # 今日已用
```

**不要截图看小鲸鱼挂件**——直接读这个 JSON 文件。

### 3.3 本地 4B 模型

```
Ollama   http://127.0.0.1:11434
模型     qwen35-4b-abliterated:latest（2.5 GB）
文件     C:\Users\19536\AI\models\Qwen3.5-4B-abliterated-Q4_K_M.gguf
```

**实测**：7.5s/次，会输出 `<think>` 块。
**结论：只适合「格式转换 / 摘要 / 改名」这类无判断任务。做技术判断会幻觉，别用。**

### 3.4 外部评审会话状态

```
Gemini（哈基米）  gemini.google.com    可用，但用户提到额度也在减少
ChatGPT（龙娘）   chatgpt.com           ❌ 账号本月消息额度耗尽，发不出去
```

**这是当时的状态，现在可能变了，用之前先试一条。**

---

## 四、Relay 机制（给外部评审传话）—— 可复用的操作手册

### 4.1 为什么不用 agent 浏览器

`browserLane.browsers` 是空的，`ego` 浏览器是独立 profile（没登录）。
评审会话在**用户自己的 Chrome** 里，所以只能用 Windows Computer Use 操作。

### 4.2 操作步骤（已验证可行）

```
① 激活窗口      windows_computer_use_activate_window(pid=33612)
② 切标签        keypress ["ctrl","1"]  ← 绝不要点坐标
③ 点输入框      看截图算坐标：屏幕 = 原点 + 截图坐标/imageScale
④ 设置剪贴板    Set-Clipboard -Value $msg
⑤ 粘贴          keypress ["ctrl","v"]
⑥ 确认焦点      看返回的 focus 是不是 "Edit '为 Gemini 输入提示'"
⑦ 发送          keypress ["Enter"]
⑧ 确认发出      截图看消息是否变气泡 + 出现「正在深入思考」
⑨ 读回复        截图 → 视觉读（中文 OCR 不可用，会乱码）
```

### 4.3 关键坑

- **中文 OCR 对 Gemini 的渲染文字完全不可用**（「孬」「鼕」「骱」这种乱码）
  技术词能认出来（`returned-together`、`event_rng`），但中文散文不行
- **剪贴板粘贴比打字可靠**，长文本必须用剪贴板
- **Enter 可能发不出去**（如果账号有限制），要看页面上有没有额度提示

### 4.4 评审的偏好（从多次交流总结）

**Gemini（哈基米）**：
- 回复要短、结论要可定位
- 会主动翻仓库，喜欢看 diff 和测试数据
- 明确说过要「剪贴板读原文」而不是截图

**GPT（龙娘）**：
- 有最终裁决权（用户明确要求「取舍由 GPT 综合判断」）
- 要求「未经真实 Windows 启动、续档和完整对局验证，不得写可发布」
- 会区分「执行能力 / 传递能力 / 协作能力」三个层次
- 反对「加专属负面事件来压路线」这类粗暴手段

---

## 五、我在等裁决但没等到的事

**这些需要 GPT 复核**（GPT 额度耗时时由 Gemini 代裁）：

1. **八百里 slack 0→1 对不对**
   Gemini 说对（让断崖变缓），但 GPT 没看过
2. **S 阈值 80→77 对不对**
   同上
3. **达标 71.2% 略高于目标 65~70% 要不要压**
   Gemini 说保留（样本误差内）

**记录在 `docs/RELAY_LOG.md` 的「待 GPT 复核」一节。**

---

## 六、外部评估报告的结论（`docs/EVALUATION_REPORT.md`）

Gemini 的判断，我核对过数据前两条一致：

> **能发给陌生人玩，但更像「排班游戏」而不是「赌局游戏」。**
>
> 最该修的三个：
> 1. **核心决策「赌」是纯亏损** —— 零余量派单 30% 达标，不接 77%
> 2. **十二夜前中期压力不够** —— 「冒险」没有明确回报
> 3. **帮助页偏操作说明、缺决策说明** ← 我做了第⑤节部分解决
>
> 最该保留的三个：
> 1. 水彩风雪画面风格统一
> 2. 12 夜 / 15~25 分钟的节奏
> 3. 拒收不惩罚的设计

**第①②条是设计/平衡问题，我没动**，因为它们超出「技术实现细节」的权限范围。

---

## 七、给下一个会话的建议

1. **先 `git log` 看清楚现在到哪了**，别信本文的提交号（会过时）
2. **别重做我做过的事**——尤其别再去「优化买马逻辑」，数据已经证明没意义
3. **平衡数字必须能一键复现**：`python tools/sim_balance.py -n 500`，别再出现两套口径
4. **改动前先看 `docs/ISSUES.md` 和 `docs/ROADMAP.md`**
5. **要动平衡参数或规则，先找 GPT 裁决**（用户明确要求）

---

## 八、本会话产生的文件（都在仓库里）

```
docs/PHASE_C.md            Phase C 指标与发现（我写的，数据都在）
docs/RELAY_LOG.md          评审往来完整记录（原文分开保存）
docs/RELAY_BLOCKED.md      ChatGPT 额度阻塞记录
docs/RELAY_Q1.md           给两位评审的问题
docs/EVALUATION_REQUEST.md 评估报告需求清单
docs/EVALUATION_REPORT.md  Gemini 的评估报告
tools/metrics.py           指标工具（八策略对比 / 分布统计）
```

**`docs/RELAY_LOG.md` 里有完整的原始对话，需要引用评审原话时直接看那个。**
