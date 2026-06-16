import asyncio
import io
import json
import math
import random
import subprocess
import sys
import uuid
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from agents.taobao_agent import TaobaoAgent
from agents.xianyu_agent import XianyuAgent
from config.loader import AccountConfig, ConfigLoader, ProductConfig, Settings
from core.price_judge import SKU_RULES
from llm.client import LLMClient
from reporter.dingtalk import DingTalkPusher
from reporter.excel_exporter import save_listing_table
from reporter.report_generator import ReportGenerator
from storage.database import Database

AGENTS_MAP = {
    "xianyu": XianyuAgent,
    "taobao": TaobaoAgent,
}

PLATFORM_URLS = {
    "xianyu": "https://www.goofish.com/",
    "taobao": "https://www.taobao.com/",
}


@dataclass
class RunOptions:
    platform: str = "all"
    dry_run: bool = False
    headless: bool = False
    debug_fast: bool = False
    db_path: str = "data/price_monitor.db"


@dataclass
class ProductRunResult:
    platform: str
    product: str
    listings: int
    alerts: int
    account: str
    results_file: str = ""
    raw_results_file: str = ""
    items: List[dict] = field(default_factory=list)


@dataclass
class LoginSession:
    account_id: str
    platform: str
    user_data_dir: str
    storage_state: str
    wait_file: str
    result_file: str
    process: subprocess.Popen


@dataclass
class RunSummary:
    options: RunOptions
    started_at: datetime
    finished_at: datetime
    products: List[str]
    accounts: List[str]
    provider: str
    model: str
    dingtalk_enabled: bool
    used_llm: bool
    run_results: List[ProductRunResult] = field(default_factory=list)
    deduped_results_file: str = ""
    review_results_file: str = ""
    report_markdown: str = ""
    report_file: str = ""

    @property
    def total_listings(self) -> int:
        return sum(result.listings for result in self.run_results)

    @property
    def total_alerts(self) -> int:
        return sum(result.alerts for result in self.run_results)


@dataclass
class ReviewAlertsResult:
    total_review_items: int
    updated_items: int
    review_results_file: str = ""


class _StdoutTee(io.TextIOBase):
    def __init__(self, original, callback: Optional[Callable[[str], None]] = None):
        self.original = original
        self.callback = callback
        self._buffer = ""

    def write(self, text: str) -> int:
        if self.original is not None:
            self.original.write(text)
        if self.callback:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line:
                    self.callback(line)
        return len(text)

    def flush(self) -> None:
        if self.original is not None:
            self.original.flush()
        if self.callback and self._buffer:
            self.callback(self._buffer)
            self._buffer = ""


class MonitorService:
    REVIEW_BATCH_SIZE = 10

    def __init__(
        self,
        config_loader: Optional[ConfigLoader] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.config_loader = config_loader or ConfigLoader()
        self.log_callback = log_callback
        self._login_session: Optional[LoginSession] = None

    def load_runtime_config(self) -> dict:
        config = self.config_loader.load_all()
        settings: Settings = config["settings"]
        products: List[ProductConfig] = config["products"]
        accounts: List[AccountConfig] = config["accounts"]
        return {
            "settings": settings,
            "products": products,
            "accounts": accounts,
            "platforms": list(AGENTS_MAP.keys()),
        }

    def load_config_documents(self) -> dict:
        config_dir = self.config_loader.config_dir
        return {
            "settings.yaml": (config_dir / "settings.yaml").read_text(encoding="utf-8"),
            "products.yaml": (config_dir / "products.yaml").read_text(encoding="utf-8"),
            "accounts.yaml": (config_dir / "accounts.yaml").read_text(encoding="utf-8"),
        }

    def save_config_document(self, filename: str, content: str) -> None:
        allowed_files = {"settings.yaml", "products.yaml", "accounts.yaml"}
        if filename not in allowed_files:
            raise ValueError(f"Unsupported config file: {filename}")

        yaml.safe_load(content or "")
        path = self.config_loader.config_dir / filename
        path.write_text(content, encoding="utf-8")
        self.load_runtime_config()

    def save_llm_config(self, llm_config: dict) -> None:
        path = self.config_loader.config_dir / "settings.yaml"
        raw_settings = ""
        if path.exists():
            raw_settings = path.read_text(encoding="utf-8")

        llm_block = yaml.safe_dump(
            {
                "llm": {
                    "provider": llm_config["provider"],
                    "model": llm_config["model"],
                    "api_key": llm_config["api_key"],
                    "api_base": llm_config["api_base"],
                    "temperature": float(llm_config["temperature"]),
                }
            },
            allow_unicode=True,
            sort_keys=False,
        )
        updated_settings = self._replace_top_level_yaml_block(raw_settings, "llm", llm_block)
        yaml.safe_load(updated_settings or "")
        path.write_text(updated_settings, encoding="utf-8")
        self.load_runtime_config()

    def review_database_alerts(self, db_path: str) -> ReviewAlertsResult:
        tee = _StdoutTee(sys.stdout, self.log_callback)
        with redirect_stdout(tee):
            try:
                result = self._review_database_alerts_internal(db_path)
                tee.flush()
                return result
            finally:
                tee.flush()

    def _review_database_alerts_internal(self, db_path: str) -> ReviewAlertsResult:
        settings: Settings = self.config_loader.load_settings()
        if not settings.llm.api_key:
            raise ValueError("LLM API key not configured.")

        LLMClient.configure_usage_storage(db_path)
        db = Database(db_path)
        alerts = db.list_review_alerts()
        if not alerts:
            print("No REVIEW alerts found.", flush=True)
            return ReviewAlertsResult(total_review_items=0, updated_items=0)

        run_results = self._review_alerts_to_run_results(alerts)
        llm = LLMClient(settings.llm)
        review_results_file, review_payload = self._save_review_results(run_results, llm)
        self._apply_review_results(run_results, review_payload, db)
        updated_items = self._count_review_decisions(review_payload)
        if review_results_file:
            print(f"Review results file: {review_results_file}", flush=True)
        print(
            f"Review alerts finished: total={len(alerts)}, updated={updated_items}",
            flush=True,
        )
        return ReviewAlertsResult(
            total_review_items=len(alerts),
            updated_items=updated_items,
            review_results_file=review_results_file,
        )

    def _review_alerts_to_run_results(self, alerts: List[dict]) -> List[ProductRunResult]:
        results_by_key: Dict[tuple[str, str], ProductRunResult] = {}
        for alert in alerts:
            platform = str(alert.get("platform") or "")
            product = str(alert.get("product_name") or "")
            key = (platform, product)
            result = results_by_key.get(key)
            if result is None:
                result = ProductRunResult(
                    platform=platform,
                    product=product,
                    listings=0,
                    alerts=0,
                    account="database",
                )
                results_by_key[key] = result
            result.items.append({
                "title": alert.get("title", ""),
                "price": alert.get("price", 0),
                "url": alert.get("url", ""),
                "judgment": alert.get("judgment", ""),
                "spec_capture_mode": alert.get("spec_capture_mode", ""),
                "spec_capture_info": alert.get("spec_capture_info", ""),
            })
            result.listings += 1
            result.alerts += 1
        return list(results_by_key.values())

    def _count_review_decisions(self, review_payload: Dict[str, Any]) -> int:
        count = 0
        for batch in review_payload.get("batches", []):
            count += sum(1 for result in batch.get("results", []) if isinstance(result, dict))
        return count

    def list_accounts(self) -> List[dict]:
        config = self.load_runtime_config()
        accounts: List[AccountConfig] = config["accounts"]
        result = []
        for account in accounts:
            storage_state = Path(account.storage_state or f"data/auth/{account.id}.json")
            saved_at = ""
            if storage_state.exists():
                saved_at = datetime.fromtimestamp(storage_state.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            result.append(
                {
                    "id": account.id,
                    "platform": account.platform,
                    "type": account.type,
                    "status": account.status,
                    "browser_channel": account.browser_channel or "msedge",
                    "user_data_dir": account.user_data_dir or f"data/browser_profiles/{account.id}",
                    "storage_state": str(storage_state),
                    "storage_state_exists": storage_state.exists(),
                    "saved_at": saved_at,
                }
            )
        return result

    async def open_login_browser(self, account_id: str) -> dict:
        account = self._get_account_by_id(account_id)
        if self._login_session and self._login_session.account_id != account_id:
            raise RuntimeError(
                f"Login session already active for {self._login_session.account_id}. "
                "Please finish and save it before opening another account."
            )
        if self._login_session and self._login_session.account_id == account_id:
            raise RuntimeError(f"Login session already active for {account_id}.")

        user_data_dir = Path(account.user_data_dir or f"data/browser_profiles/{account.id}")
        storage_state = Path(account.storage_state or f"data/auth/{account.id}.json")
        runtime_dir = self._runtime_dir()
        login_session_dir = runtime_dir / "data" / "login_sessions"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        storage_state.parent.mkdir(parents=True, exist_ok=True)
        login_session_dir.mkdir(parents=True, exist_ok=True)

        session_id = uuid.uuid4().hex
        wait_file = login_session_dir / f"{account.id}_{session_id}.signal"
        result_file = login_session_dir / f"{account.id}_{session_id}.result.json"
        if wait_file.exists():
            wait_file.unlink()
        if result_file.exists():
            result_file.unlink()

        command = [
            *self._login_helper_command(),
            "--platform",
            account.platform,
            "--account",
            account.id,
            "--wait-file",
            str(wait_file),
            "--result-file",
            str(result_file),
        ]
        process = subprocess.Popen(
            command,
            cwd=str(runtime_dir),
        )

        self._login_session = LoginSession(
            account_id=account.id,
            platform=account.platform,
            user_data_dir=str(user_data_dir),
            storage_state=str(storage_state),
            wait_file=str(wait_file),
            result_file=str(result_file),
            process=process,
        )

        return {
            "account_id": account.id,
            "platform": account.platform,
            "user_data_dir": str(user_data_dir),
            "storage_state": str(storage_state),
        }

    async def save_login_state(self, account_id: str) -> str:
        if not self._login_session:
            raise RuntimeError("No active login session. Please open the login window first.")
        if self._login_session.account_id != account_id:
            raise RuntimeError(
                f"Active login session belongs to {self._login_session.account_id}, not {account_id}."
            )

        session = self._login_session
        try:
            wait_file = Path(session.wait_file)
            wait_file.parent.mkdir(parents=True, exist_ok=True)
            wait_file.write_text("continue", encoding="utf-8")
            exit_code = await asyncio.to_thread(session.process.wait)

            result_path = Path(session.result_file)
            if result_path.exists():
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                if not payload.get("ok", False):
                    raise RuntimeError(payload.get("error", "Login state save failed."))
                return payload.get("storage_state", session.storage_state)

            if exit_code != 0:
                raise RuntimeError(f"Login helper exited with code {exit_code}")
            return session.storage_state
        finally:
            self._cleanup_login_session_files(session)
            self._login_session = None

    async def run(self, options: RunOptions) -> RunSummary:
        started_at = datetime.now()
        tee = _StdoutTee(sys.stdout, self.log_callback)
        with redirect_stdout(tee):
            summary = await self._run_internal(options, started_at)
            tee.flush()
            return summary

    async def _run_internal(self, options: RunOptions, started_at: datetime) -> RunSummary:
        config = self.load_runtime_config()
        settings: Settings = config["settings"]
        products: List[ProductConfig] = config["products"]
        accounts: List[AccountConfig] = config["accounts"]
        LLMClient.configure_usage_storage(options.db_path)

        if options.platform != "all" and options.platform not in AGENTS_MAP:
            raise ValueError(f"Unsupported platform: {options.platform}")

        if options.dry_run:
            return RunSummary(
                options=options,
                started_at=started_at,
                finished_at=datetime.now(),
                products=[product.name for product in products],
                accounts=[account.id for account in accounts],
                provider=settings.llm.provider,
                model=settings.llm.model,
                dingtalk_enabled=settings.notification.dingtalk.enabled,
                used_llm=bool(settings.llm.api_key),
            )

        llm = None
        if settings.llm.api_key:
            llm = LLMClient(settings.llm)
        else:
            print("LLM API key not configured, fallback to rule-based logic.")

        db = Database(options.db_path)
        platforms = list(AGENTS_MAP.keys()) if options.platform == "all" else [options.platform]
        keyword_delay_range = (3, 8) if options.debug_fast else (120, 300)
        requested_products = [product for product in products if any(platform in product.platforms for platform in platforms)]
        if not requested_products:
            raise ValueError(
                f"No enabled products configured for platform(s): {', '.join(platforms)}. "
                "Please update config/products.yaml."
            )

        run_results: List[ProductRunResult] = []
        for platform in platforms:
            agent_cls = AGENTS_MAP[platform]
            platform_products = [product for product in products if platform in product.platforms]
            if not platform_products:
                print(f"[{platform}] no enabled products configured, skipped")
                continue
            platform_accounts = [
                account for account in accounts
                if account.platform == platform and account.type == "search" and account.status == "active"
            ]

            if not platform_accounts:
                print(f"[{platform}] no active search account, skipped")
                continue

            for product in platform_products:
                account = random.choice(platform_accounts)
                print(f"[{platform}] start monitoring {product.name} (account: {account.id})", flush=True)
                result = await self._run_agent_for_product(
                    agent_cls=agent_cls,
                    product=product,
                    account=account,
                    db=db,
                    llm=llm,
                    headless=options.headless,
                    proxy=settings.proxy.enabled,
                    keyword_delay_range=keyword_delay_range,
                    anti_risk=settings.anti_risk,
                )
                run_results.append(result)
                print(
                    f"[{platform}] {product.name}: collected {result.listings}, alerts {result.alerts}",
                    flush=True,
                )
                if result.results_file:
                    print(f"[{platform}] results file: {result.results_file}", flush=True)
                if result.raw_results_file:
                    print(f"[{platform}] raw results file: {result.raw_results_file}", flush=True)

        deduped_results_file = ""
        review_results_file = ""
        report_markdown = ""
        report_file = ""
        if run_results:
            if llm:
                review_results_file, review_payload = self._save_review_results(run_results, llm)
                if review_results_file:
                    print(f"Review results file: {review_results_file}")
                self._apply_review_results(run_results, review_payload, db)
            deduped_results_file = self._save_deduped_run_results(run_results)
            if deduped_results_file:
                print(f"Deduped run results file: {deduped_results_file}")

            hour = datetime.now().hour
            period = "上午" if hour < 13 else "下午"

            pusher = None
            if settings.notification.dingtalk.enabled and settings.notification.dingtalk.webhook_url:
                pusher = DingTalkPusher(settings.notification.dingtalk.webhook_url)

            report_generator = ReportGenerator(db)
            report_markdown = report_generator.save_and_send(
                [self._result_to_dict(result) for result in run_results],
                dingtalk_pusher=pusher,
                period=period,
            )
            report_file = str(report_generator.last_report_path) if report_generator.last_report_path else ""
            print("\n=== 日报 ===")
            print(report_markdown)
            if report_file:
                print(f"Local report saved: {report_file}")
            print("=== 完成 ===")

        return RunSummary(
            options=options,
            started_at=started_at,
            finished_at=datetime.now(),
            products=[product.name for product in products],
            accounts=[account.id for account in accounts],
            provider=settings.llm.provider,
            model=settings.llm.model,
            dingtalk_enabled=settings.notification.dingtalk.enabled,
            used_llm=bool(settings.llm.api_key),
            run_results=run_results,
            deduped_results_file=deduped_results_file,
            review_results_file=review_results_file,
            report_markdown=report_markdown,
            report_file=report_file,
        )

    async def _run_agent_for_product(
        self,
        agent_cls,
        product: ProductConfig,
        account: AccountConfig,
        db: Database,
        llm: Optional[LLMClient],
        headless: bool,
        proxy: bool,
        keyword_delay_range: tuple = (120, 300),
        anti_risk=None,
    ) -> ProductRunResult:
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
        return ProductRunResult(
            platform=agent.PLATFORM,
            product=product.name,
            listings=listings,
            alerts=alerts,
            account=account.id,
            results_file=str(agent.last_results_path) if agent.last_results_path else "",
            raw_results_file=str(agent.last_raw_results_path) if agent.last_raw_results_path else "",
            items=[
                {
                    "title": item.title,
                    "price": item.price,
                    "url": item.url,
                    "judgment": getattr(item, "judgment", ""),
                    "spec_capture_mode": getattr(item, "spec_capture_mode", ""),
                    "spec_capture_info": getattr(item, "spec_capture_info", ""),
                }
                for item in agent.collected_listings
            ],
        )

    def _save_deduped_run_results(self, run_results: List[ProductRunResult]) -> str:
        items = []
        seen_urls = set()

        for result in run_results:
            for item in result.items:
                url = item.get("url", "")
                key = url or f"{item.get('title', '')}|{item.get('price', '')}"
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                items.append({
                    "title": item.get("title", ""),
                    "price": item.get("price", 0),
                    "url": url,
                    "judgment": item.get("judgment", ""),
                    "spec_capture_mode": item.get("spec_capture_mode", ""),
                    "spec_capture_info": item.get("spec_capture_info", ""),
                })

        items.sort(key=lambda row: (float(row.get("price") or 0) <= 0, float(row.get("price") or 0)))
        output_dir = Path("data/search_results")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"{timestamp}_all_deduped.xlsx"
        save_listing_table(items, path)

        return str(path)

    def _collect_review_items(self, run_results: List[ProductRunResult]) -> List[Dict[str, Any]]:
        items = []
        seen_keys = set()

        for result in run_results:
            for item in result.items:
                if str(item.get("judgment", "")).upper() != "REVIEW":
                    continue
                url = item.get("url", "")
                key = url or f"{item.get('title', '')}|{item.get('price', '')}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                items.append({
                    "product": result.product,
                    "title": item.get("title", ""),
                    "price": item.get("price", 0),
                    "url": url,
                    "spec_capture_mode": item.get("spec_capture_mode", ""),
                    "spec_capture_info": item.get("spec_capture_info", ""),
                })

        items.sort(key=lambda row: (float(row.get("price") or 0) <= 0, float(row.get("price") or 0)))
        for index, item in enumerate(items, start=1):
            item["row_no"] = index
        return items

    def _build_review_prompt(self, items: List[Dict[str, Any]]) -> str:
        sku_lines = []
        for sku_id, rule in SKU_RULES.items():
            sku_lines.append(
                f"- {sku_id}: version={rule['version']}, period={rule['period']}, official_price={rule['official_price']}"
            )

        payload = [
            {
                "row_no": item["row_no"],
                "product": item["product"],
                "title": item["title"],
                "list_price": item["price"],
                "url": item["url"],
                "spec_capture_mode": item["spec_capture_mode"],
                "spec_capture_info": item["spec_capture_info"],
            }
            for item in items
        ]

        return (
            "你是适趣AI商品SKU复核助手。请根据每条商品的完整标题、列表价格、规格采集模式和规格采集信息，"
            "判断商品究竟售卖的是哪一种SKU，并给出最终判定。\n\n"
            "已知SKU与官方价：\n"
            f"{chr(10).join(sku_lines)}\n\n"
            "判定要求：\n"
            "1. 先识别具体SKU，优先使用规格采集信息。\n"
            "2. 如果某个规格后面带“已售罄”，不要把它当作当前在售SKU，除非所有规格都已售罄且标题只明确指向该SKU。\n"
            "3. 如果能明确SKU且列表价格低于该SKU官方价，decision 返回 VIOLATION。\n"
            "4. 如果仍无法明确SKU，decision 返回 REVIEW。\n"
            "5. 如果能明确SKU且价格不低于该SKU官方价，decision 返回 NORMAL。\n"
            "6. 只返回 JSON 数组，不要加解释，不要加 Markdown 代码块。\n\n"
            "返回字段：row_no, url, sku, decision, reason, confidence。\n\n"
            f"待复核数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _save_review_results(self, run_results: List[ProductRunResult], llm: LLMClient) -> tuple[str, Dict[str, Any]]:
        review_items = self._collect_review_items(run_results)
        if not review_items:
            return ("", {})

        output_dir = Path("data/search_results")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"{timestamp}_review_llm.json"

        batches = []
        total_batches = math.ceil(len(review_items) / self.REVIEW_BATCH_SIZE)
        for batch_index in range(total_batches):
            start = batch_index * self.REVIEW_BATCH_SIZE
            batch_items = review_items[start:start + self.REVIEW_BATCH_SIZE]
            print(
                f"Running review LLM batch {batch_index + 1}/{total_batches} "
                f"({len(batch_items)} items)",
                flush=True,
            )
            prompt = self._build_review_prompt(batch_items)
            raw_result = llm.chat_json(messages=[{"role": "user", "content": prompt}])
            if not isinstance(raw_result, list):
                raise ValueError(f"Expected review LLM result list, got: {type(raw_result).__name__}")
            batches.append({
                "batch_no": batch_index + 1,
                "items": batch_items,
                "results": raw_result,
            })

        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": llm.config.model,
            "batch_size": self.REVIEW_BATCH_SIZE,
            "total_items": len(review_items),
            "batches": batches,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return (str(path), payload)

    def _apply_review_results(
        self,
        run_results: List[ProductRunResult],
        review_payload: Dict[str, Any],
        db: Database,
    ) -> None:
        if not review_payload:
            return

        decision_by_url: Dict[str, Dict[str, Any]] = {}
        decision_by_row_no: Dict[int, Dict[str, Any]] = {}
        for batch in review_payload.get("batches", []):
            for result in batch.get("results", []):
                if not isinstance(result, dict):
                    continue
                url = str(result.get("url", "")).strip()
                row_no = result.get("row_no")
                if url:
                    decision_by_url[url] = result
                if isinstance(row_no, int):
                    decision_by_row_no[row_no] = result

        review_items = self._collect_review_items(run_results)
        row_no_by_key = {
            (item.get("url") or f"{item.get('title', '')}|{item.get('price', '')}"): item["row_no"]
            for item in review_items
        }

        for result in run_results:
            for item in result.items:
                if str(item.get("judgment", "")).upper() != "REVIEW":
                    continue
                url = str(item.get("url", "")).strip()
                key = url or f"{item.get('title', '')}|{item.get('price', '')}"
                decision = decision_by_url.get(url) if url else None
                if not decision:
                    row_no = row_no_by_key.get(key)
                    if row_no is not None:
                        decision = decision_by_row_no.get(row_no)
                if not decision:
                    continue

                final_decision = str(decision.get("decision", item.get("judgment", ""))).upper()
                review_reason = str(decision.get("reason", ""))
                item["judgment"] = final_decision
                item["review_sku"] = decision.get("sku", "")
                item["review_reason"] = review_reason
                item["review_confidence"] = decision.get("confidence", "")

                if not url:
                    continue
                if final_decision == "NORMAL":
                    db.update_alert_judgment_by_url(url, "NORMAL", review_reason)
                    continue
                if final_decision in {"VIOLATION", "SUSPECTED", "DELIST", "REVIEW"}:
                    db.update_alert_judgment_by_url(url, final_decision, review_reason)

    def _result_to_dict(self, result: ProductRunResult) -> dict:
        return {
            "platform": result.platform,
            "product": result.product,
            "listings": result.listings,
            "alerts": result.alerts,
            "account": result.account,
            "results_file": result.results_file,
            "raw_results_file": result.raw_results_file,
            "items": result.items,
        }

    def _get_account_by_id(self, account_id: str) -> AccountConfig:
        accounts: List[AccountConfig] = self.load_runtime_config()["accounts"]
        for account in accounts:
            if account.id == account_id:
                return account
        raise ValueError(f"Account not found: {account_id}")

    def _has_usable_storage_state(self, path: Path) -> bool:
        return path.exists() and path.stat().st_size > 0

    def _replace_top_level_yaml_block(self, content: str, key: str, replacement: str) -> str:
        lines = content.splitlines()
        start = None
        for index, line in enumerate(lines):
            if line == f"{key}:":
                start = index
                break

        if start is None:
            prefix = content.rstrip()
            return f"{replacement}\n" if not prefix else f"{replacement}\n{prefix}\n"

        end = len(lines)
        for index in range(start + 1, len(lines)):
            line = lines[index]
            if line and not line.startswith((" ", "\t", "#")):
                end = index
                break

        replacement_lines = replacement.rstrip().splitlines()
        updated_lines = lines[:start] + replacement_lines + lines[end:]
        return "\n".join(updated_lines).rstrip() + "\n"

    def _runtime_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return self.config_loader.project_dir

    def _login_helper_command(self) -> List[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--login-helper"]

        python_path = self.config_loader.project_dir / "venv" / "Scripts" / "python.exe"
        script_path = self.config_loader.project_dir / "scripts" / "save_login_state.py"
        if not python_path.exists():
            raise FileNotFoundError(f"Python interpreter not found: {python_path}")
        if not script_path.exists():
            raise FileNotFoundError(f"Login script not found: {script_path}")
        return [str(python_path), str(script_path)]

    def _cleanup_login_session_files(self, session: LoginSession) -> None:
        for file_path in (session.wait_file, session.result_file):
            path = Path(file_path)
            if path.exists():
                path.unlink()
