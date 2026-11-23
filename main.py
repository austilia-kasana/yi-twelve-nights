#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《驿 · 十二夜》入口。

直接运行：
    python main.py
    python main.py --seed 42
    python main.py --assets-check
"""

from __future__ import annotations

import os
import sys

# 让 src 布局在开发时可直接跑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from relay.ui.app import main as app_main
    return app_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main() or 0)
