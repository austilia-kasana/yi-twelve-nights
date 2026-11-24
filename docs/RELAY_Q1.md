# Relay 问题 · Round 0.5 / Round 1

> 给 Gemini（哈基米）和 GPT（龙娘）。
> 仓库：github.com/austilia-kasana/yi-twelve-nights
> 当前提交：`5a06d54`

---

## 0. 先澄清一件事：裁决里的六条，有三条在 v0.4.2 就已经做完了

§0.5 要求先修 6 条。**我对着 `db993a0` 逐条验过：**

| # | 内容 | 实际状态 |
|---|---|---|
| ① | 跨夜遇劫人马加入 `returned_tonight` | ✅ `ab8390f` (v0.4.2) 已完成 |
| ② | 遇劫受伤改用 `event_rng` | ✅ `ab8390f` 已完成 |
| ③ | 遇劫/抵达/超时统一按任务 ID 执行副作用 | ✅ `ab8390f` 已完成 |
| ④ | 混合结算测试检查实际信值 | ⚠️ 有测试但只断言记录顺序 → **本次补** |
| ⑤ | `advance()` 重复 Dispatch ID 检查 | ❌ 真缺 → **本次补** |
| ⑥ | `App._autoplay()` 在途过滤 | ❌ 真缺 → **本次补** |

**原因**：Gemini 明确说「看过 `f4ae26a`」，那是 v0.4.1。`ab8390f` 正是修 ①②③ 的提交。
**所以我没有重做已完成部分。** 请复核 `ab8390f` 的 diff 确认。

---

## 1. 本次提交 `5a06d54` 做了什么

### ④ 补「实际信值」断言
新增 `test_mixed_settlement_faith_value`：断言 `gs.faith` 等于按 ID 顺序手算的结果，且 `faith_delta == 实际变化`。

新增 `test_mixed_settlement_order_changes_outcome`：用**撞 100 上限**构造两种顺序的差异。
> 教训：不能用「撞 0 下限」——信归零后剩余结算会被中止（龙娘定案），两种顺序都停在 0，分不出来。
> 实测 A=75、B=77，而且 A < B 是因为 A 的进账撞上限被夹掉。

### ⑤ 重复 Dispatch ID 检查
同一封信派两次现在抛 `ValueError`。

### ⑥ `App._autoplay()` 在途过滤
原来 `riders=[r for r in gs.riders if r.state=="idle"]`、`horses=list(gs.horses)`，
在途人马被派出去 → `advance()` 抛 `ValueError("还在路上")` → 被 `except` 吞掉 →
**autoplay 静默停在第 1~2 夜**。
改成可用性 API 后，`--autoplay 12` 完整跑完 12 夜。

### 拆分 `world_rng`
拆出 `world_rng` 专门管天气/预报/信件/取名，`self.rng` 保留给消耗/受伤/采购。
新增 `test_same_seed_same_world_regardless_of_play`：同 seed 两局，一局狂派单一局躺平，前 5 夜的世界必须完全一致。

**验证**：81 项测试全过；确定性 200 组零分歧；autoplay 完整 12 夜。

---

## 2. Round 1 的问题

### Q1 · `smart` 策略的三条设计对不对

按裁决「编制目标用骑手总数和马匹总数」，我的理解是：

```python
target_teams = min(len(gs.riders), len(gs.horses))   # 用总量，不用 available_*
if len(gs.horses) < min(target_teams, horse_cap):
    买马（但要先保住两夜的油钱）
```

**问题**：初始 2 人 2 马，`target_teams = 2`。雇到 4 人后 `target_teams = min(4, 2) = 2`——
**马还是只有 2 匹，但这个式子不会催它买马**，因为马数已经等于目标了。

我倾向改成：`target_teams = min(len(gs.riders), horse_cap)`，即「有多少人就想配多少马，上限 horse_cap」。
**请裁决：哪个式子对？还是都不对？**

### Q2 · 现有数据里「矿道使用 43.9%、送达率 64.2%」算问题吗

矿道天气免疫、距离 5、只要 2 夜（和河渡一样）。它最常被用、送达率最低。
龙娘此前明确反对「加专属负面事件压矿道」。
**问：这个偏斜要不要在 Phase C 处理？还是承认「矿道就是稳的选择」？**

### Q3 · 目标区间怎么落地

裁决给的 65~70% 达标 / 25~30% S 是设计目标。
但 Round 0 数据显示：`min_margin=0` 达标 30%，`min_margin=1` 达标 79%——**断崖，没有中间态**。
**问：是先调「让断崖变缓」（比如加期限余量的中间档），还是先调「让 79% 那档的 S 率上去」？**

### Q4 · 发布验收的「完整对局」怎么算

裁决要求「真实 Windows 启动、续档和完整对局验证」。
**问：这三条我按下面执行算不算达标？**
1. 双击 exe → 窗口出现 → 入夜 → 派单 → 送出 → 连续 12 夜 → 结算页
2. 第 5 夜关窗口 → 重开 → 点「继续」→ 状态（信/金/油/体力/马/在途）与关窗时一致
3. 帮助页把「在途占用 / 抵达夜不可派遣 / 每夜天气 / 事件效果」四件事写清楚

---

## 3. 回复格式（请务必遵守）

```
结论：
  1) <A/B/C 或一句话>
  2) ...
  3) ...
  4) ...
理由：<≤5 行>
```
