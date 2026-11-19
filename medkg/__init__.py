# -*- coding: utf-8 -*-
"""项目根引用：把项目根目录加入 sys.path，便于脚本直接 import medkg。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

__version__ = "1.0.0"