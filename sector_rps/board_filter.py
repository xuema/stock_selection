#!/usr/bin/env python3
"""板块名黑名单过滤：东财 BK 与通达信 88xxxx 两套脚本共用。"""

from pathlib import Path

PATTERNS_FILE = Path(__file__).parent / "exclude_patterns.txt"


def load_patterns(path=PATTERNS_FILE):
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def split_boards(boards, patterns=None):
    """boards: [{"code","name"}, ...] → (保留, 剔除)"""
    patterns = load_patterns() if patterns is None else patterns
    kept, dropped = [], []
    for b in boards:
        (dropped if any(p in b["name"] for p in patterns) else kept).append(b)
    return kept, dropped
