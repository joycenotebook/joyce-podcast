#!/usr/bin/env python3
"""标出企业追踪里超过 90 天的事实，方便下次改 companies.json。

不访问网络，不读密钥。默认退出 0，这样过期的历史数字不会把 CI 打红。
加 --strict 时，只要有过期或数字缺日期就退出 1。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.company_facts import fact_problems, load_companies  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="列出企业卡里过期或缺少日期的数字")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--as-of", default="", help="核对日 YYYY-MM-DD，默认今天")
    parser.add_argument("--strict", action="store_true", help="有过期或坏事实时退出 1")
    args = parser.parse_args(argv)
    today = date.fromisoformat(args.as_of) if args.as_of else date.today()
    bundle = load_companies(args.root, today=today)
    print(f"企业追踪新鲜度 · 核对日 {today.isoformat()} · 超过 {bundle['staleDays']} 天算过期")
    print(bundle["disclaimer"])
    print()
    stale_n = 0
    missing_n = 0
    problems: list[str] = []
    for co in bundle["list"]:
        cov = co["coverage"]
        problems.extend(fact_problems(co))
        stale_n += cov["staleCount"]
        missing_n += len(cov["missingDate"])
        flag = "有过期" if cov["staleCount"] else "日期都在窗口内"
        print(
            f"- {co['name']} · 未公开 {cov['undisclosedCount']} 项 · "
            f"过期 {cov['staleCount']} · {flag}"
        )
        for row in cov["stale"]:
            print(f"    过期 {row['asOf']}  {row['path']}  {row['value']}")
        for path in cov["missingDate"]:
            print(f"    缺日期  {path}")
    print()
    if problems:
        print(f"事实字段有问题 {len(problems)} 条：")
        for item in problems:
            print("   ", item)
    else:
        print("数字事实的单位、日期、来源和类型都在。")
    print(f"合计过期 {stale_n} · 缺日期 {missing_n} · 公司 {len(bundle['list'])} 家")
    if args.strict and (stale_n or missing_n or problems):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
