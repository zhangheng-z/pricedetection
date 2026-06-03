#!/usr/bin/env python3
"""
第三方平台价格监控系统 - CLI 入口
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.monitor_service import MonitorService, RunOptions


def parse_args():
    parser = argparse.ArgumentParser(description="第三方平台价格监控系统")
    parser.add_argument("--platform", "-p", choices=["xianyu", "taobao", "all"],
                        default="all", help="指定平台")
    parser.add_argument("--dry-run", action="store_true", help="仅打印配置，不执行搜索")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--debug-fast", action="store_true", help="调试模式，缩短关键步骤等待时间")
    parser.add_argument("--db", default="data/price_monitor.db", help="数据库路径")
    return parser.parse_args()


async def main():
    args = parse_args()
    service = MonitorService()
    summary = await service.run(
        RunOptions(
            platform=args.platform,
            dry_run=args.dry_run,
            headless=args.headless,
            debug_fast=args.debug_fast,
            db_path=args.db,
        )
    )

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"Products: {summary.products}")
        print(f"Settings provider: {summary.provider} / {summary.model}")
        print(f"Accounts: {summary.accounts}")
        print(f"DingTalk: {'enabled' if summary.dingtalk_enabled else 'disabled'}")


if __name__ == "__main__":
    asyncio.run(main())
