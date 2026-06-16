"""Interactive tester for fishing prompt templates.

Run examples:
  python scripts/fishing_prompt_chat_tester.py --price lt1000
  python scripts/fishing_prompt_chat_tester.py --price gt1000 --db data/price_monitor.db
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PRODUCT_TYPES = {
    "gray_account": "灰产账号型",
    "personal_transfer": "个人闲置转让型",
    "channel_resale": "渠道贩卖型",
    "short_term_low_price": "短期低价型",
    "uncertain": "不确定",
}


def load_prompt_templates():
    prompts_path = PROJECT_ROOT / "llm" / "prompts.py"
    spec = importlib.util.spec_from_file_location("fishing_prompt_templates", prompts_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载提示词文件: {prompts_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PromptTemplates

TAGS = {
    "gray_account": "灰产账号型，不需要拍单",
    "manual_payment_required": "渠道贩卖型，需要人工付款",
    "need_ask_change_account": "需要追问是否换号",
    "need_manual_review": "需要人工复核",
    "suspicious_low_price_no_change": "低价但不用换号，需谨慎复核",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="钓鱼提示词聊天测试工具")
    parser.add_argument("--db", default="data/price_monitor.db", help="SQLite 数据库路径")
    parser.add_argument(
        "--price",
        choices=["all", "lt1000", "gt1000"],
        default="all",
        help="随机商品价格区间：all 全部，lt1000 小于1000，gt1000 大于等于1000",
    )
    parser.add_argument("--show-prompt", action="store_true", help="打印每次发送给 LLM 的完整提示词")
    parser.add_argument("--retries", type=int, default=3, help="LLM 429/上游饱和时的重试次数")
    parser.add_argument("--retry-delay", type=float, default=3.0, help="LLM 重试间隔秒数")
    return parser.parse_args()


def connect_db(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"数据库不存在: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def price_where(price_filter: str, alias: str) -> str:
    if price_filter == "lt1000":
        return f"AND {alias}.price < 1000"
    if price_filter == "gt1000":
        return f"AND {alias}.price >= 1000"
    return ""


def random_alert(conn: sqlite3.Connection, price_filter: str) -> dict[str, Any]:
    alert_where = price_where(price_filter, "a")
    listing_where = price_where(price_filter, "l")
    rows = conn.execute(
        f"""
        SELECT *
        FROM (
            SELECT
                a.id AS alert_id,
                a.product_name,
                a.title,
                a.price,
                a.official_price,
                a.reason,
                a.judgment,
                a.status,
                a.product_type,
                l.seller_name,
                l.url
            FROM price_alerts a
            JOIN listings l ON l.id = a.listing_id
            WHERE a.platform = 'xianyu'
              {alert_where}
            UNION ALL
            SELECT
                0 AS alert_id,
                l.product_name,
                l.title,
                l.price,
                0 AS official_price,
                '' AS reason,
                '' AS judgment,
                '' AS status,
                '' AS product_type,
                l.seller_name,
                l.url
            FROM listings l
            WHERE l.platform = 'xianyu'
              {listing_where}
        )
        ORDER BY RANDOM()
        LIMIT 1
        """
    ).fetchall()
    if not rows:
        raise ValueError(f"没有找到符合价格区间 {price_filter} 的商品")
    return dict(rows[0])


def load_llm():
    try:
        from config.loader import ConfigLoader
        from llm.client import LLMClient
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "缺少项目依赖，请使用项目虚拟环境运行，例如 "
            r".\venv\Scripts\python.exe scripts\fishing_prompt_chat_tester.py"
        ) from exc

    settings = ConfigLoader().load_settings()
    if not settings.llm.api_key:
        raise ValueError("未配置 LLM API Key，请检查 config/settings.yaml 或 .env")
    return LLMClient(settings.llm)


def is_transient_llm_error(exc: Exception) -> bool:
    text = str(exc)
    return (
        "429" in text
        or "upstream_error" in text
        or "上游负载已饱和" in text
        or "bad_response_status_code" in text
    )


def chat_json_with_retry(
    llm: Any,
    messages: list[dict[str, str]],
    retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    attempts = max(1, retries + 1)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return llm.chat_json(messages=messages)
        except Exception as exc:
            last_exc = exc
            if not is_transient_llm_error(exc) or attempt >= attempts:
                break
            print(f"LLM 临时失败，第 {attempt}/{attempts - 1} 次重试前等待 {retry_delay:g} 秒: {exc}")
            time.sleep(retry_delay)

    if is_transient_llm_error(last_exc or Exception()):
        if hasattr(llm, "_vectorengine_use_fallback"):
            print("主模型仍然繁忙，切换到 fallback 模型 gpt-5.4-mini 再试一次。")
            llm._vectorengine_use_fallback = True
            return llm.chat_json(messages=messages)
    raise last_exc or RuntimeError("LLM 调用失败")


def print_product(alert: dict[str, Any]) -> None:
    print("\n=== 随机商品 ===")
    print(f"商品: {alert.get('product_name') or '-'}")
    print(f"标题: {alert.get('title') or '-'}")
    print(f"页面价: {alert.get('price')}")
    print(f"官方价: {alert.get('official_price')}")
    print(f"判断: {alert.get('judgment') or '-'}")
    print(f"乱价类型: {alert.get('product_type') or '-'}")
    print(f"原因: {alert.get('reason') or '-'}")
    print(f"链接: {alert.get('url') or '-'}")


def format_price(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def call_initial(
    llm: Any,
    alert: dict[str, Any],
    show_prompt: bool,
    retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    prompt_templates = load_prompt_templates()
    prompt = prompt_templates.FISHING_INITIAL_CHAT.format(
        product_name=alert.get("product_name", ""),
        listing_price=format_price(alert.get("price")),
        title=alert.get("title", ""),
        reason=alert.get("reason", ""),
    )
    if show_prompt:
        print("\n--- INITIAL PROMPT ---")
        print(prompt)
    payload = chat_json_with_retry(
        llm,
        messages=[{"role": "user", "content": prompt}],
        retries=retries,
        retry_delay=retry_delay,
    )
    if not isinstance(payload, dict):
        raise ValueError("首句提示词返回值不是 JSON object")
    return payload


def call_chat(
    llm: Any,
    alert: dict[str, Any],
    last_buyer_question: str,
    seller_reply: str,
    conversation_history: list[dict[str, str]],
    show_prompt: bool,
    retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    prompt_templates = load_prompt_templates()
    prompt = prompt_templates.FISHING_CHAT.format(
        title=alert.get("title", ""),
        listing_price=format_price(alert.get("price")),
        question=last_buyer_question,
        seller_reply=seller_reply,
        conversation_history=format_conversation_history(conversation_history),
    )
    if show_prompt:
        print("\n--- CHAT PROMPT ---")
        print(prompt)
    payload = chat_json_with_retry(
        llm,
        messages=[{"role": "user", "content": prompt}],
        retries=retries,
        retry_delay=retry_delay,
    )
    if not isinstance(payload, dict):
        raise ValueError("聊天提示词返回值不是 JSON object")
    return payload


def print_json(title: str, payload: dict[str, Any]) -> None:
    print(f"\n=== {title} JSON ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def format_conversation_history(conversation_history: list[dict[str, str]]) -> str:
    lines = []
    for message in conversation_history:
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        sender = "买家" if message.get("sender") == "buyer" else "卖家"
        lines.append(f"{sender}：{content}")
    return "\n".join(lines) if lines else "无"


def run_chat(
    conn: sqlite3.Connection,
    llm: Any,
    price_filter: str,
    show_prompt: bool,
    retries: int,
    retry_delay: float,
) -> bool:
    alert = random_alert(conn, price_filter)
    print_product(alert)

    initial = call_initial(llm, alert, show_prompt, retries, retry_delay)
    print_json("首句判断", initial)

    product_type = str(initial.get("product_type", "")).strip()
    if product_type:
        print(f"商品类型: {PRODUCT_TYPES.get(product_type, product_type)}")

    buyer_message = str(initial.get("message", "")).strip()
    if not buyer_message:
        print("\nLLM 没有生成首句，通常表示该类型不需要继续对话。")
        return True

    print(f"\n买家LLM: {buyer_message}")
    last_buyer_question = buyer_message
    conversation_history = [{"sender": "buyer", "content": buyer_message}]

    while True:
        seller_reply = input("\n你作为商家回复（/new 换商品，/quit 退出）: ").strip()
        if seller_reply.lower() in {"/quit", "quit", "q"}:
            return False
        if seller_reply.lower() in {"/new", "new", "n"}:
            return True
        if not seller_reply:
            continue

        conversation_history.append({"sender": "seller", "content": seller_reply})
        payload = call_chat(
            llm,
            alert,
            last_buyer_question,
            seller_reply,
            conversation_history,
            show_prompt,
            retries,
            retry_delay,
        )
        print_json("对话判断", payload)

        tag = str(payload.get("tag", "")).strip()
        if tag:
            print(f"标签: {TAGS.get(tag, tag)}")
        follow_up = str(payload.get("follow_up_message", "")).strip()
        if follow_up:
            print(f"\n买家LLM: {follow_up}")
            last_buyer_question = follow_up
            conversation_history.append({"sender": "buyer", "content": follow_up})
        else:
            print("\nLLM 未给出下一句，本轮可视为判定结束。")


def main() -> int:
    args = parse_args()
    random.seed()
    try:
        conn = connect_db(args.db)
        llm = load_llm()
        llm.configure_usage_storage(args.db)
        print("提示词聊天测试已启动。你扮演商家，LLM 扮演买家。")
        print("命令：/new 换一个随机商品，/quit 退出。")
        while run_chat(conn, llm, args.price, args.show_prompt, args.retries, args.retry_delay):
            continue
        return 0
    except KeyboardInterrupt:
        print("\n已退出。")
        return 0
    except Exception as exc:
        print(f"\n测试失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
