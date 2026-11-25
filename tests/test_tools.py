# -*- coding: utf-8 -*-
"""评测工具的「口径」不能漂——这里钉住它。

起因：v0.5.0 文档里的「500 局 达标 71.2% / S 27.2%」只有
`SmartStrategy(min_margin=1)` 复现得出来，而 `SmartStrategy` 的 docstring
写着「余量筛选 min_margin=1」、类上却没有这个字段（继承来的是 0）。
同一份代码于是有两套「官方难度」：文档 71.2%，`tools/sim_balance.py` 48%。

这类漂移不会让任何测试变红，只会让之后每个读文档的人算错。
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))


class TestStrategyCalibration(unittest.TestCase):
    def test_smart_filters_zero_margin(self):
        from ai import SmartStrategy
        # docstring 的三条设计之一：只接余量 >= 1 的信
        self.assertEqual(SmartStrategy().min_margin, 1)

    def test_base_does_not_filter(self):
        from ai import Strategy
        # 基准口径就是「什么都敢接」，不然两组数没法对比
        self.assertEqual(Strategy().min_margin, 0)

    def test_smart_can_be_overridden(self):
        # 显式传参还得能覆盖，否则想做「smart 但不筛余量」的对照实验就没路了
        from ai import SmartStrategy
        self.assertEqual(SmartStrategy(min_margin=0).min_margin, 0)

    def test_sim_balance_offers_both_yardsticks(self):
        # 谁跑过平衡模拟，就必须说清楚用的是哪种策略
        from sim_balance import STRATEGIES
        self.assertIn("base", STRATEGIES)
        self.assertIn("smart", STRATEGIES)


if __name__ == "__main__":
    unittest.main()
