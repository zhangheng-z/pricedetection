#!/usr/bin/env python3
"""
第三方平台价格监控系统 - 主入口

用法:
  python main.py                    # 执行一次完整运行
  python main.py --platform xianyu  # 只跑闲鱼
  python main.py --dry-run          # 不启动浏览器，仅打印配置

环境变量:
  DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY 等
"""

import asyncio
import argparse
import sys
import random
from pathlib import Path
from datetime import datetime
from typing import List

sys.path.insert(0, str(Path(__file__).parent))

from config.loader import ConfigLoader, ProductConfig, AccountConfig
from storage.database import Database
from llm.client import LLMClient
from reporter.report_generator import ReportGenerator
from reporter.dingtalk import DingTalkPusher
from reporter.excel_exporter import save_listing_table
from agents.xianyu_agent import XianyuAgent
from agents.taobao_agent import TaobaoAgent

AGENTS_MAP = {
    "xianyu": XianyuAgent,
    "taobao": TaobaoAgent,
}


def parse_args():
    parser = argparse.ArgumentParser(description="第三方平台价格监控系统")
    parser.add_argument("--platform", "-p", choices=list(AGENTS_MAP.keys()) + ["all"],
                        default="all", help="指定平台")
    parser.add_argument("--dry-run", action="store_true", help="仅打印配置，不执行搜索")
    parser.add_argument("--headless", action="store_true", help="无头模式（默认有头调试）")
    parser.add_argument("--debug-fast", action="store_true", help="调试模式：缩短关键词间等待时间")
    parser.add_argument("--db", default="data/price_monitor.db", help="数据库路径")
    return parser.parse_args()


async def run_agent_for_product(
    agent_cls, product: ProductConfig, account: AccountConfig,
    db: Database, llm: LLMClient, headless: bool, proxy: str,
    keyword_delay_range: tuple = (120, 300),
    anti_risk=None,
) -> dict:
    agent = agent_cls(
        db=db,
        product=product,
        account=account,
        llm_client=llm,
        headless=headless,
        proxy=proxy or None,
        keyword_delay_range=keyword_delay_range,
        anti_risk=anti_risk,
    )
    listings, alerts = await agent.run()
    return {
        "platform": agent.PLATFORM,
        "product": product.name,
        "listings": listings,
        "alerts": alerts,
        "account": account.id,
        "results_file": str(agent.last_results_path) if agent.last_results_path else "",
        "raw_results_file": str(agent.last_raw_results_path) if agent.last_raw_results_path else "",
        "items": [
            {"title": item.title, "price": item.price, "url": item.url}
            for item in agent.collected_listings
        ],
    }


def save_deduped_run_results(run_results: List[dict]) -> str:
    items = []
    seen_urls = set()

    for result in run_results:
        for item in result.get("items", []):
            url = item.get("url", "")
            key = url or f"{item.get('title', '')}|{item.get('price', '')}"
            if key in seen_urls:
                continue
            seen_urls.add(key)
            items.append({
                "title": item.get("title", ""),
                "price": item.get("price", 0),
                "url": url,
            })

    items.sort(key=lambda row: (float(row.get("price") or 0) <= 0, float(row.get("price") or 0)))
    output_dir = Path("data/search_results")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{timestamp}_all_deduped.xlsx"
    save_listing_table(items, path)

    return str(path)


async def main():
    args = parse_args()
    config_loader = ConfigLoader()
    config = config_loader.load_all()
    settings = config["settings"]
    products: List[ProductConfig] = config["products"]
    accounts: List[AccountConfig] = config["accounts"]

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"Products: {[p.name for p in products]}")
        print(f"Settings provider: {settings.llm.provider} / {settings.llm.model}")
        print(f"Accounts: {[a.id for a in accounts]}")
        print(f"DingTalk: {'enabled' if settings.notification.dingtalk.enabled else 'disabled'}")
        return

    llm = None
    if settings.llm.api_key:
        llm = LLMClient(settings.llm)
    else:
        print("⚠ LLM API key 未配置，将使用规则引擎（无法使用 LLM 判价和关键词生成）")

    db = Database(args.db)
    platforms = list(AGENTS_MAP.keys()) if args.platform == "all" else [args.platform]
    keyword_delay_range = (3, 8) if args.debug_fast else (120, 300)

    run_results = []
    for platform in platforms:
        agent_cls = AGENTS_MAP[platform]
        platform_products = [p for p in products if platform in p.platforms]
        platform_accounts = [
            a for a in accounts
            if a.platform == platform and a.type == "search" and a.status == "active"
        ]

        if not platform_accounts:
            print(f"[{platform}] 无可用账号，跳过")
            continue

        for product in platform_products:
            account = random.choice(platform_accounts)
            print(f"[{platform}] 开始监控: {product.name} (账号: {account.id})", flush=True)
            result = await run_agent_for_product(
                agent_cls=agent_cls,
                product=product,
                account=account,
                db=db,
                llm=llm,
                headless=args.headless,
                proxy=settings.proxy.enabled,
                keyword_delay_range=keyword_delay_range,
                anti_risk=settings.anti_risk,
            )
            run_results.append(result)
            print(f"[{platform}] {product.name}: 采集{result['listings']}条, 乱价{result['alerts']}条", flush=True)
            if result.get("results_file"):
                print(f"[{platform}] results file: {result['results_file']}", flush=True)
            if result.get("raw_results_file"):
                print(f"[{platform}] raw results file: {result['raw_results_file']}", flush=True)

    if run_results:
        deduped_results_file = save_deduped_run_results(run_results)
        if deduped_results_file:
            print(f"Deduped run results file: {deduped_results_file}")

        hour = datetime.now().hour
        period = "上午" if hour < 13 else "下午"

        pusher = None
        if settings.notification.dingtalk.enabled and settings.notification.dingtalk.webhook_url:
            pusher = DingTalkPusher(settings.notification.dingtalk.webhook_url)

        rg = ReportGenerator(db)
        markdown = rg.save_and_send(run_results, dingtalk_pusher=pusher, period=period)
        print("\n=== 日报 ===")
        print(markdown)
        if rg.last_report_path:
            print(f"Local report saved: {rg.last_report_path}")
        print("=== 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
