# -*- coding: utf-8 -*-
"""《驿 · 十二夜》—— 所有可调数值集中在这里。

改数值不改逻辑。任何平衡调整都应该只改这个文件。
"""

# ────────────────────────── 局长度 ──────────────────────────
TOTAL_NIGHTS = 12

# ────────────────────────── 开局 ──────────────────────────
START_FAITH = 50          # 信
START_GOLD = 200          # 金
START_OIL = 100           # 油
MAX_FAITH = 100
MAX_OIL = 160

START_RIDERS = [
    {"name": "老陈", "speed": 1.15, "stamina": 100.0},
    {"name": "小满", "speed": 1.25, "stamina": 100.0},
]
START_HORSES = [
    {"name": "乌蹄", "speed": 1.10, "condition": 100.0},
    {"name": "灰耳", "speed": 1.20, "condition": 100.0},
]

# ────────────────────────── 路线 ──────────────────────────
ROUTES = {
    "north": {
        "name": "北口",
        "distance": 3,
        "desc": "最快的路，也是最不讲道理的路。",
        "repair_cost": 220,
    },
    "ford": {
        "name": "河渡",
        "distance": 4,
        "desc": "涨水就没法走。",
        "repair_cost": 240,
    },
    "mine": {
        "name": "旧矿道",
        "distance": 5,
        "desc": "又长又黑，但天气拿它没办法。",
        "repair_cost": 260,
    },
}

# ────────────────────────── 天气 ──────────────────────────
# 每条路线在各天气下的速度系数
WEATHER = {
    "clear": {
        "name": "晴",
        "route_factor": {"north": 1.00, "ford": 1.00, "mine": 1.00},
        "risk": 0.10,
        "desc": "星子亮得能看清山口。",
    },
    "cloud": {
        "name": "阴",
        "route_factor": {"north": 0.95, "ford": 1.00, "mine": 1.00},
        "risk": 0.12,
        "desc": "云压着山脊走。",
    },
    "rain": {
        "name": "雨",
        "route_factor": {"north": 0.85, "ford": 0.60, "mine": 1.00},
        "risk": 0.18,
        "desc": "雨点子打在窗纸上。",
    },
    "snow": {
        "name": "雪",
        "route_factor": {"north": 0.50, "ford": 0.85, "mine": 1.00},
        "risk": 0.20,
        "desc": "雪落下来没有声音。",
    },
    "storm": {
        "name": "暴雪",
        "route_factor": {"north": 0.30, "ford": 0.70, "mine": 1.00},
        "risk": 0.30,
        "desc": "什么都看不见了。",
    },
}

# 天气倾向随夜幕推进（第 0 夜 → 第 11 夜）
# 每一夜从这一组里抽；顺序对应 WEATHER 的键
WEATHER_SCHEDULE = [
    # (夜晚索引, 权重表)  索引越大越靠后；取第一个 <= 当前夜的
    (0,  {"clear": 45, "cloud": 30, "rain": 15, "snow": 8,  "storm": 2}),
    (3,  {"clear": 35, "cloud": 30, "rain": 18, "snow": 12, "storm": 5}),
    (6,  {"clear": 25, "cloud": 28, "rain": 18, "snow": 19, "storm": 10}),
    (9,  {"clear": 18, "cloud": 24, "rain": 16, "snow": 24, "storm": 18}),
    (11, {"clear": 12, "cloud": 20, "rain": 14, "snow": 26, "storm": 28}),
]

FORECAST_ACCURACY = 0.70   # 预报准确率——整个游戏的信息核心

# ────────────────────────── 行进 ──────────────────────────
# 行进时间 = ceil(距离 / (骑手脚力 * 马脚力 * 天气系数 * 灯系数 * BASE_TRAVEL))
# BASE_TRAVEL=2.0 时：慢组合北口要 2 夜，快组合 1 夜——这给了排班真正的取舍
BASE_TRAVEL = 2.00
OIL_LIGHT_FACTOR = 0.65    # 没油没灯时的速度系数
NO_LIGHT_OIL_THRESHOLD = 1

# 每条路线在「最顺利情况」下要跑几夜。信件期限由它推导，不写死。
ROUTE_BASE_NIGHTS = {"north": 1, "ford": 2, "mine": 2}

STAMINA_LOW = 30.0
STAMINA_PENALTY = 0.75
HORSE_LOW = 40.0
HORSE_PENALTY = 0.80

STAMINA_COST_MIN = 24.0
STAMINA_COST_MAX = 40.0
HORSE_COST_MIN = 14.0
HORSE_COST_MAX = 28.0

REST_STAMINA_GAIN = 35.0
FEED_CONDITION_GAIN = 40.0

# 马每夜自然恢复多少。
#
# 0 会让「马永远不会自己好」变得很反直觉：玩家第 6 夜左右会突然发现
# 所有马都在 10 以下，而且不知道该怎么补救——打满一局才体会到这个问题。
#
# 实测（tools/ai_optimal 的 Human 策略，300 局）：
#   0 → S 37.3% 达标 71.7%
#   2 → S 38.7% 达标 72.3%
#   3 → S 40.0% 达标 71.3%
# 也就是说它几乎不影响难度，纯粹是「别让玩家走进死胡同回不来」的保险。
# 取 2.0：能自救，但恢复速度远低于喂料（+40）。
HORSE_NATURAL_RECOVERY = 2.0

# ────────────────────────── 事件 ──────────────────────────
# 每趟出行按天气 risk 掷一次；数值是相对权重
EVENTS = {
    "tailwind": {"name": "顺风", "weight": 8,  "desc": "风在背后推着走"},
    "lost":     {"name": "迷路", "weight": 10, "desc": "雾里绕了半宿"},
    "rockfall": {"name": "落石", "weight": 6,  "desc": "路塌了，只能回头"},
    "robbery":  {"name": "遇劫", "weight": 5,  "desc": "信没了"},
    "calm":     {"name": "无事", "weight": 71, "desc": ""},
}
# 雪天北口落石翻倍；暴雪遇劫翻倍
ROCKFALL_CONDITION = {"route": "north", "weather": "snow", "mult": 2.0}
ROBBERY_CONDITION = {"weather": "storm", "mult": 2.0}

# ────────────────────────── 信件 ──────────────────────────
DISPATCH_KINDS = {
    "normal": {
        "name": "寻常",
        "weight": 55,
        "slack": 1,            # 期限 = 路线基准夜数 + slack
        "reward": (18, 34),
        "penalty": (3, 6),
    },
    "urgent": {
        "name": "加急",
        "weight": 32,
        "slack": 0,            # 紧凑，但偶尔放一点
        "slack_mix": [0, 0, 1],
        "reward": (40, 70),
        "penalty": (7, 11),
    },
    "express": {
        "name": "八百里",
        "weight": 13,
        "slack": 0,            # 最紧，且占用最强骑手
        "reward": (95, 150),
        "penalty": (14, 20),
    },
}

DISPATCHES_PER_NIGHT = (3, 5)      # 含两端
EXPRESS_STARTS_NIGHT = 5           # 第几夜起出现八百里

# 送达一封加多少「信」（再乘下面的种类倍数）。
#
# 这个值决定整个游戏的难度曲线：
#   2.0 → 只读预报认真打，达标率 41%，S 率 12%。太狠了：
#         每个决定都做对也只有四成能守住，S 基本是运气。
#   2.8 → 达标率 66%，S 率 35%。认真打三分之一的局能拿 S。
#   3.2 → 达标率 73%，S 率 45%。偏松。
# 采用 2.8。改这个值之后一定要重跑 tools/ai_optimal.py 看曲线。
FAITH_PER_DELIVER = 2.8
FAITH_DELIVER_MULT = {"normal": 1.0, "urgent": 1.6, "express": 2.4}

# ────────────────────────── 商店 ──────────────────────────
PRICES = {
    "hire_rider": 130,
    "buy_horse": 155,
    "feed": 40,
    "oil": 30,
}

HIRE_SPEED_RANGE = (1.10, 1.45)
BUY_HORSE_SPEED_RANGE = (1.05, 1.35)
OIL_REFILL_AMOUNT = 40

# ────────────────────────── 胜负 ──────────────────────────
SURVIVE_FAITH = 60         # 12 夜后达到这个数才算「守住」
# 从高到低匹配，第一个 <= 当前信的档位生效。
# 必须包含 0 档，否则极低分会兜底成最高的「其他」标签。
RATING_THRESHOLDS = [
    (80, "S"),
    (70, "A"),
    (60, "B"),
    (40, "C"),
    (20, "D"),
    (0,  "E"),
]

# ────────────────────────── 派系／结局阈值 ──────────────────────────
# 用来选结局文本
ENDING_GOOD = 70
ENDING_OK = 50
ENDING_BAD = 0
