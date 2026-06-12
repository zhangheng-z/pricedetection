import random
import sqlite3
import asyncio
import re
from types import SimpleNamespace
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime
from pathlib import Path
from playwright.async_api import Page
from core.browser import BrowserManager
from core.search_engine import SearchEngine
from core.price_judge import PriceJudge
from core.anti_detect import AntiDetect
from storage.database import Database
from storage.models import Listing, PriceAlert, SearchRun
from config.loader import ProductConfig, AccountConfig
from llm.client import LLMClient
from reporter.excel_exporter import save_listing_table


class BaseAgent:
    """平台 Agent 基类"""

    PLATFORM = ""
    VERIFICATION_TEXT_MARKERS = (
        "\u8bf7\u62d6\u52a8\u4e0b\u65b9\u6ed1\u5757\u5b8c\u6210\u9a8c\u8bc1",
        "\u8bf7\u62d6\u52a8\u4e0b\u65b9\u6ed1\u5757",
        "\u901a\u8fc7\u9a8c\u8bc1\u4ee5\u786e\u4fdd\u6b63\u5e38\u8bbf\u95ee",
        "\u8bf7\u6309\u4f4f\u6ed1\u5757\uff0c\u62d6\u52a8\u5230\u6700\u53f3\u8fb9",
        "\u8bf7\u6309\u4f4f\u6ed1\u5757\u62d6\u52a8\u5230\u6700\u53f3\u8fb9",
    )

    def __init__(
        self,
        db: Database,
        product: ProductConfig,
        account: AccountConfig,
        llm_client: Optional[LLMClient] = None,
        headless: bool = False,
        proxy: Optional[str] = None,
        keyword_delay_range: Tuple[int, int] = (120, 300),
        anti_risk: Optional[Any] = None,
    ):
        self.db = db
        self.product = product
        self.account = account
        self.llm_client = llm_client
        self.headless = headless
        self.proxy = proxy
        self.keyword_delay_range = keyword_delay_range
        self.anti_risk = anti_risk or SimpleNamespace(
            enabled=True,
            search_delay_seconds=[5, 10],
            sort_delay_seconds=[5, 10],
            page_turn_delay_seconds=[10, 30],
            detail_click_delay_seconds=[15, 45],
            buy_click_delay_seconds=[3, 8],
            per_item_delay_seconds=[3, 8],
            post_detail_cooldown_seconds=[20, 60],
            max_pages_per_keyword=5,
            max_detail_clicks_per_keyword=5,
            max_detail_clicks_per_run=8,
            verification_poll_seconds=8,
            open_detail_in_new_page=False,
            browser_backend="cloakbrowser",
            cloak_stealth_args=True,
            cloak_humanize=True,
            cloak_human_preset="careful",
            cloak_binary_path="",
            cloak_start_timeout_seconds=120,
            stealth_mode=False,
            randomize_user_agent=False,
            randomize_viewport=False,
        )
        self.browser: Optional[BrowserManager] = None
        self.search_engine = SearchEngine(llm_client)
        self.price_judge = PriceJudge(llm_client)
        self.collected_listings: List[Listing] = []
        self.raw_listings: List[dict] = []
        self.last_results_path: Optional[Path] = None
        self.last_raw_results_path: Optional[Path] = None
        self.seen_urls = set()
        self.raw_items_seen = 0
        self.title_filtered_count = 0
        self.detail_clicks_by_keyword: Dict[str, int] = {}
        self.detail_clicks_total = 0
        self.verification_clear_count = 0

    async def run(self) -> Tuple[int, int]:
        """执行一次完整的搜索+判价流程，返回 (listings_count, alerts_count)"""
        if self.PLATFORM not in self.product.platforms:
            return (0, 0)

        keywords = self.product.keywords
        run_start = datetime.now()

        self.browser = BrowserManager(
            proxy=self.proxy,
            headless=self.headless,
            storage_state=self.account.storage_state or None,
            user_data_dir=self.account.user_data_dir or None,
            browser_channel=self.account.browser_channel or "msedge",
            browser_backend=getattr(self.anti_risk, "browser_backend", "cloakbrowser"),
            cloak_stealth_args=bool(getattr(self.anti_risk, "cloak_stealth_args", True)),
            cloak_humanize=bool(getattr(self.anti_risk, "cloak_humanize", True)),
            cloak_human_preset=getattr(self.anti_risk, "cloak_human_preset", "careful"),
            cloak_binary_path=getattr(self.anti_risk, "cloak_binary_path", "") or None,
            cloak_start_timeout_seconds=int(getattr(self.anti_risk, "cloak_start_timeout_seconds", 120)),
            stealth_mode=bool(getattr(self.anti_risk, "stealth_mode", False)),
            randomize_user_agent=bool(getattr(self.anti_risk, "randomize_user_agent", False)),
            randomize_viewport=bool(getattr(self.anti_risk, "randomize_viewport", False)),
        )
        await self.browser.start()
        if not self.account.storage_state and self.account.cookies_encrypted:
            await self.browser.load_cookie_header(
                self.account.cookies_encrypted,
                self._cookie_url(),
            )
        page = await self.browser.new_page()

        search_run = SearchRun(
            run_time=run_start.strftime("%Y-%m-%d %H:%M:%S"),
            platform=self.PLATFORM,
            account_id=self.account.id,
            keywords_used=str(keywords),
        )
        run_id = self.db.save_run(search_run)
        listings_found = 0
        alerts_created = 0

        try:
            selected_keywords = self._select_keywords(keywords)
            print(f"[{self.PLATFORM}] selected keywords: {selected_keywords}", flush=True)
            for keyword_index, keyword in enumerate(selected_keywords, start=1):
                print(
                    f"[{self.PLATFORM}] searching keyword {keyword_index}/{len(selected_keywords)}: {keyword}",
                    flush=True,
                )
                await self._do_search(page, keyword)
                await self._wait_if_verification(page, "after search")
                page_index = 1
                configured_max_pages = self._anti_risk_int("max_pages_per_keyword", 50)
                max_pages = configured_max_pages if configured_max_pages > 0 else 9999
                actual_total_pages = await self._get_total_results_pages(page)
                if actual_total_pages > 0:
                    max_pages = min(max_pages, actual_total_pages)
                    print(f"[{self.PLATFORM}] total results pages: {actual_total_pages}, scan pages: {max_pages}", flush=True)
                while page_index <= max_pages:
                    await self._wait_if_verification(page, f"before extracting page {page_index}")
                    print(f"[{self.PLATFORM}] extracting listings page {page_index}...", flush=True)
                    raw_items = await asyncio.wait_for(
                        self.search_engine.extract_listings(page, self.PLATFORM),
                        timeout=60,
                    )
                    print(f"[{self.PLATFORM}] extracted {len(raw_items)} listings on page {page_index}", flush=True)
                    if not raw_items:
                        break

                    found_delta, alert_delta = await self._process_raw_items(raw_items, keyword, run_id, page)
                    listings_found += found_delta
                    alerts_created += alert_delta

                    if not await self._goto_next_results_page(page):
                        break
                    await self._wait_if_verification(page, "after next page")
                    page_index += 1
                if page_index > max_pages:
                    print(f"[{self.PLATFORM}] stopped at max page limit: {max_pages}", flush=True)

            duration = (datetime.now() - run_start).total_seconds()
            self._save_results_file()
            self._save_raw_results_file()
            self._update_run(run_id, listings_found, alerts_created, duration, "completed", "")

        except Exception as e:
            self._save_results_file()
            self._save_raw_results_file()
            self._update_run(run_id, listings_found, alerts_created, 0, "failed", str(e))
            print(f"[{self.PLATFORM}] Run failed: {e}")
        finally:
            await self.browser.stop()

        return (listings_found, alerts_created)

    def _update_run(self, run_id: int, listings: int, alerts: int, duration: float, status: str, error: str):
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute(
                """UPDATE search_runs SET listings_found=?, alerts_created=?,
                   status=?, error=?, duration_seconds=? WHERE id=?""",
                (listings, alerts, status, error, duration, run_id),
            )

    async def _do_search(self, page: Page, keyword: str):
        raise NotImplementedError

    async def _process_raw_items(
        self,
        raw_items: List[Dict[str, Any]],
        keyword: str,
        run_id: int,
        page: Page,
    ) -> Tuple[int, int]:
        listings_found = 0
        alerts_created = 0

        for item in raw_items:
            await self._wait_if_verification(page, "while processing listings")
            self.raw_items_seen += 1
            title = item.get("title", "").strip()
            url = item.get("url", "").strip()
            list_price = float(item.get("price") or 0)
            self.raw_listings.append({
                "title": title,
                "price": list_price,
                "url": url,
            })
            if not self._title_matches_search(title, keyword):
                self.title_filtered_count += 1
                continue

            if self._should_skip_ignored_list_price(list_price):
                print(
                    f"[{self.PLATFORM}] skip detail: ignored list price {list_price}",
                    flush=True,
                )
                continue

            if not self._should_open_detail_by_list_price(list_price, self.product.official_price):
                print(
                    f"[{self.PLATFORM}] skip detail: list price {list_price} within tolerance of official {self.product.official_price}",
                    flush=True,
                )
                continue

            await self._anti_risk_delay("per_item_delay_seconds", "between low-price candidates")

            dedupe_key = url or f"{title}|{list_price}"
            if dedupe_key in self.seen_urls:
                continue
            self.seen_urls.add(dedupe_key)

            if url and self.db.listing_exists_by_url(url):
                print(
                    f"[{self.PLATFORM}] skip detail: already checked url {url}",
                    flush=True,
                )
                continue

            if not self._can_open_detail(keyword):
                print(
                    f"[{self.PLATFORM}] detail click limit reached for keyword: {keyword}",
                    flush=True,
                )
                continue
            if not self._can_open_detail_for_run():
                print(
                    f"[{self.PLATFORM}] detail click limit reached for run",
                    flush=True,
                )
                break
            self.detail_clicks_by_keyword[keyword] = self.detail_clicks_by_keyword.get(keyword, 0) + 1
            self.detail_clicks_total += 1
            await self._anti_risk_delay("detail_click_delay_seconds", "before detail")
            verification_marker = self.verification_clear_count
            order_offer = await self._fetch_order_offer(page, url, title, keyword)
            await self._anti_risk_delay("post_detail_cooldown_seconds", "after detail")
            if order_offer is None and self.verification_clear_count > verification_marker:
                print(
                    f"[{self.PLATFORM}] verification cleared while checking current item; "
                    f"rechecking to avoid omission: {title[:40]}",
                    flush=True,
                )
                await self._anti_risk_delay("detail_click_delay_seconds", "before omission recheck")
                order_offer = await self._fetch_order_offer(page, url, title, keyword)
                await self._anti_risk_delay("post_detail_cooldown_seconds", "after omission recheck")
            if order_offer is None:
                continue
            final_price = order_offer["price"]
            print(
                f"[{self.PLATFORM}] order price resolved: {order_offer['price']} "
                f"(spec={order_offer.get('spec_text', '')[:40]}, list price={list_price})",
                flush=True,
            )

            listing = Listing(
                platform=self.PLATFORM,
                product_name=self.product.name,
                title=title,
                price=final_price,
                seller_name=item.get("seller", ""),
                url=url,
                thumbnail=item.get("thumbnail", ""),
                search_keyword=keyword,
                search_run_id=run_id,
                spec_capture_mode=order_offer.get("spec_capture_mode", ""),
                spec_capture_info=order_offer.get("spec_capture_info", ""),
            )
            listing_id = self.db.save_listing(listing)
            listing.id = listing_id
            listings_found += 1

            analysis = self.price_judge.analyze_listing(
                title=listing.title,
                price=listing.price,
                product_name=self.product.name,
                official_price=self.product.official_price,
                spec_text=order_offer.get("spec_text", ""),
            )
            if order_offer.get("force_decision") == "DELIST":
                analysis["decision"] = "DELIST"
                analysis["risk_level"] = "HIGH"
                analysis["price_judgement_type"] = "DELIST_REQUIRED"
                analysis["reason"] = "\u53ef\u552e\u89c4\u683c\u547d\u4e2d\u9002\u8da3AI\u4e2d\u65877\u5929\uff0c\u9700\u4e0b\u67b6"
            decision = str(analysis.get("decision", "UNKNOWN"))

            if decision in {"VIOLATION", "SUSPECTED", "REVIEW", "DELIST"}:
                print(
                    f"[{self.PLATFORM}] price alert candidate: {decision} "
                    f"(price={listing.price}, official={self.product.official_price})",
                    flush=True,
                )
                setattr(listing, "judgment", decision)
                setattr(listing, "spec_capture_mode", order_offer.get("spec_capture_mode", ""))
                setattr(listing, "spec_capture_info", order_offer.get("spec_capture_info", ""))
                alert = PriceAlert(
                    listing_id=listing_id,
                    platform=self.PLATFORM,
                    product_name=self.product.name,
                    title=listing.title,
                    price=listing.price,
                    official_price=self.product.official_price,
                    judgment=decision,
                    reason=self.price_judge.format_analysis_reason(analysis),
                    spec_capture_mode=order_offer.get("spec_capture_mode", ""),
                    spec_capture_info=order_offer.get("spec_capture_info", ""),
                )
                self.db.save_alert(alert)
                self.collected_listings.append(listing)
                alerts_created += 1

        return listings_found, alerts_created

    def _select_keywords(self, keywords: List[str]) -> List[str]:
        return [random.choice(keywords)]

    def _should_skip_ignored_list_price(self, list_price: float) -> bool:
        return list_price in {9.9, 39.9, 2498.0, 2198.0}

    def _should_open_detail_by_list_price(self, list_price: float, official_price: float) -> bool:
        return self.price_judge.is_below_official(list_price, official_price)

    async def _goto_next_results_page(self, page: Page) -> bool:
        return False

    async def _get_total_results_pages(self, page: Page) -> int:
        return 0

    async def _fetch_order_offer(
        self,
        source_page: Page,
        url: str,
        title: str,
        keyword: str,
    ) -> Optional[Dict[str, Any]]:
        return None

    async def _click_buy_now(self, page: Page) -> bool:
        return False

    def _can_open_detail(self, keyword: str) -> bool:
        max_clicks = self._anti_risk_int("max_detail_clicks_per_keyword", 0)
        if max_clicks <= 0:
            return True
        return self.detail_clicks_by_keyword.get(keyword, 0) < max_clicks

    def _can_open_detail_for_run(self) -> bool:
        max_clicks = self._anti_risk_int("max_detail_clicks_per_run", 0)
        if max_clicks <= 0:
            return True
        return self.detail_clicks_total < max_clicks

    def _anti_risk_int(self, name: str, default: int) -> int:
        value = getattr(self.anti_risk, name, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _anti_risk_range(self, name: str, default: Tuple[float, float]) -> Tuple[float, float]:
        value = getattr(self.anti_risk, name, default)
        if not value or len(value) < 2:
            return default
        try:
            low = float(value[0])
            high = float(value[1])
        except (TypeError, ValueError):
            return default
        if high < low:
            low, high = high, low
        return (low, high)

    async def _anti_risk_delay(self, name: str, label: str = ""):
        if not getattr(self.anti_risk, "enabled", True):
            return
        low, high = self._anti_risk_range(name, (0, 0))
        if high <= 0:
            return
        seconds = random.uniform(low, high)
        if label:
            print(f"[{self.PLATFORM}] anti-risk delay {label}: {seconds:.1f}s", flush=True)
        await asyncio.sleep(seconds)

    def _mark_verification_cleared(self) -> None:
        self.verification_clear_count += 1

    async def _select_matching_order_offer(self, page: Page, keyword: str) -> Optional[Dict[str, Any]]:
        return None

    async def _collect_matching_order_specs(self, page: Page, intent: Dict[str, str]) -> Dict[str, Any]:
        return {"has_options": False, "options": [], "candidates": []}

    async def _extract_order_price(self, page: Page) -> Optional[float]:
        return None

    async def _save_order_debug_snapshot(self, page: Page) -> Path:
        output_dir = Path("data/debug")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = output_dir / f"{timestamp}_{self.PLATFORM}_order"
        await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        base.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
        return base.with_suffix(".png")

    async def _wait_if_verification(self, page: Page, label: str = "") -> bool:
        if not getattr(self.anti_risk, "stop_on_verification", True):
            return False

        if not await self._is_verification_page(page):
            return False

        if self.headless:
            if await self._resolve_headless_verification(page, label):
                self._mark_verification_cleared()
                return True
            raise RuntimeError(
                f"[{self.PLATFORM}] headless verification was not cleared. "
                "Keep the visible helper browser open and finish the slider before continuing."
            )

        try:
            await page.bring_to_front()
        except Exception:
            pass

        where = f" {label}" if label else ""
        print(
            f"[{self.PLATFORM}] verification detected{where}. "
            "Automation is paused. 请在打开的浏览器中手动拖动滑块完成验证，完成后程序会自动继续。",
            flush=True,
        )
        wait_seconds = 0
        while await self._is_verification_page(page):
            await asyncio.sleep(5)
            wait_seconds += 5
            if wait_seconds % 30 == 0:
                print(
                    f"[{self.PLATFORM}] still waiting for manual slider verification ({wait_seconds}s).",
                    flush=True,
                )

        print(f"[{self.PLATFORM}] verification cleared; resuming.", flush=True)
        self._mark_verification_cleared()
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await AntiDetect.random_delay(1, 2)
        return True

    async def _resolve_headless_verification(self, page: Page, label: str = "") -> bool:
        url = page.url
        if not url or url == "about:blank":
            return False

        where = f" {label}" if label else ""
        print(
            f"[{self.PLATFORM}] verification detected{where} in headless mode. "
            "Opening a visible browser for manual slider verification.",
            flush=True,
        )

        state_path = await self._save_temporary_storage_state(page)
        helper = BrowserManager(
            proxy=self.proxy,
            headless=False,
            storage_state=str(state_path) if state_path else (self.account.storage_state or None),
            user_data_dir=None,
            browser_channel=self.account.browser_channel or "msedge",
            browser_backend=getattr(self.anti_risk, "browser_backend", "cloakbrowser"),
            cloak_stealth_args=bool(getattr(self.anti_risk, "cloak_stealth_args", True)),
            cloak_humanize=bool(getattr(self.anti_risk, "cloak_humanize", True)),
            cloak_human_preset=getattr(self.anti_risk, "cloak_human_preset", "careful"),
            cloak_binary_path=getattr(self.anti_risk, "cloak_binary_path", "") or None,
            cloak_start_timeout_seconds=int(getattr(self.anti_risk, "cloak_start_timeout_seconds", 120)),
            stealth_mode=bool(getattr(self.anti_risk, "stealth_mode", False)),
            randomize_user_agent=bool(getattr(self.anti_risk, "randomize_user_agent", False)),
            randomize_viewport=bool(getattr(self.anti_risk, "randomize_viewport", False)),
        )

        try:
            await helper.start()
            helper_page = await helper.new_page()
            await helper_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await helper_page.bring_to_front()
            except Exception:
                pass
            print(
                f"[{self.PLATFORM}] visible verification browser opened. "
                "Please finish the slider there; the headless task will resume automatically.",
                flush=True,
            )
            return await self._wait_for_headless_verification_clear(page, helper_page, state_path)
        except Exception as exc:
            print(f"[{self.PLATFORM}] failed to open visible verification browser: {exc}", flush=True)
            return False
        finally:
            try:
                await helper.stop()
            except Exception:
                pass

    async def _save_temporary_storage_state(self, page: Page) -> Optional[Path]:
        try:
            output_dir = Path("data/debug")
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = output_dir / f"{timestamp}_{self.PLATFORM}_headless_verification_state.json"
            await page.context.storage_state(path=str(path))
            return path
        except Exception as exc:
            print(f"[{self.PLATFORM}] failed to save temporary browser state: {exc}", flush=True)
            return None

    async def _wait_for_headless_verification_clear(
        self,
        page: Page,
        helper_page: Page,
        state_path: Optional[Path],
    ) -> bool:
        wait_seconds = 0
        loop = asyncio.get_running_loop()
        opened_at = loop.time()
        min_visible_seconds = max(0, self._anti_risk_int("headless_verification_min_visible_seconds", 45))
        clear_settle_seconds = max(0, self._anti_risk_int("headless_verification_clear_settle_seconds", 5))
        helper_verification_seen = False
        while True:
            helper_closed = helper_page.is_closed()
            if not helper_closed:
                try:
                    helper_has_verification = await self._is_verification_page(helper_page)
                    if helper_has_verification:
                        helper_verification_seen = True
                        helper_manual_cleared = False
                        print(
                            f"[{self.PLATFORM}] waiting for manual slider verification in visible browser.",
                            flush=True,
                        )
                        while await self._is_verification_page(helper_page):
                            if await self._is_manual_verification_cleared(helper_page):
                                helper_manual_cleared = True
                                print(
                                    f"[{self.PLATFORM}] visible verification appears cleared; syncing state.",
                                    flush=True,
                                )
                                break
                            await asyncio.sleep(5)
                            wait_seconds += 5
                            if wait_seconds % 30 == 0:
                                print(
                                    f"[{self.PLATFORM}] still waiting for visible slider verification ({wait_seconds}s).",
                                    flush=True,
                                )
                        if clear_settle_seconds:
                            await asyncio.sleep(clear_settle_seconds)
                            wait_seconds += clear_settle_seconds
                            if (
                                not helper_manual_cleared
                                and await self._is_verification_page(helper_page)
                            ):
                                continue
                except Exception:
                    helper_closed = True

            visible_elapsed = loop.time() - opened_at
            if not helper_closed and visible_elapsed < min_visible_seconds:
                await asyncio.sleep(min(2, min_visible_seconds - visible_elapsed))
                wait_seconds += min(2, max(0, min_visible_seconds - visible_elapsed))
                continue

            if not helper_closed:
                await self._sync_helper_state_to_headless(helper_page, page, state_path)

            try:
                await page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass

            if not await self._is_verification_page(page):
                if helper_verification_seen and clear_settle_seconds:
                    await asyncio.sleep(clear_settle_seconds)
                    if not helper_closed:
                        await self._sync_helper_state_to_headless(helper_page, page, state_path)
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                    if await self._is_verification_page(page):
                        continue
                print(f"[{self.PLATFORM}] headless verification cleared; resuming.", flush=True)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                await AntiDetect.random_delay(1, 2)
                return True

            if helper_closed:
                print(
                    f"[{self.PLATFORM}] visible verification browser was closed, "
                    "but the headless page is still under verification.",
                    flush=True,
                )
                return False

            await asyncio.sleep(5)
            wait_seconds += 5
            if wait_seconds % 30 == 0:
                print(
                    f"[{self.PLATFORM}] headless page still waits for verification ({wait_seconds}s).",
                    flush=True,
                )

    async def _sync_helper_state_to_headless(
        self,
        helper_page: Page,
        headless_page: Page,
        state_path: Optional[Path],
    ) -> None:
        try:
            if state_path:
                await helper_page.context.storage_state(path=str(state_path))
                if self.account.storage_state:
                    await helper_page.context.storage_state(path=self.account.storage_state)
            cookies = await helper_page.context.cookies()
            if cookies:
                await headless_page.context.add_cookies(cookies)
        except Exception as exc:
            print(f"[{self.PLATFORM}] failed to sync verification browser state: {exc}", flush=True)

    async def _is_manual_verification_cleared(self, page: Page) -> bool:
        return False

    async def _wait_for_verification_appearance(
        self,
        page: Page,
        label: str = "",
        timeout_seconds: Optional[int] = None,
    ) -> bool:
        if not getattr(self.anti_risk, "stop_on_verification", True):
            return False

        if timeout_seconds is None:
            timeout_seconds = self._anti_risk_int("verification_poll_seconds", 8)
        if timeout_seconds <= 0:
            return await self._wait_if_verification(page, label)

        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            if await self._wait_if_verification(page, label):
                return True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(1, remaining))

    async def _is_verification_page(self, page: Page) -> bool:
        try:
            title = (await page.title()).lower()
            body_texts = [title]
            for frame in page.frames:
                try:
                    if frame != page.main_frame:
                        frame_element = await frame.frame_element()
                        if not await frame_element.is_visible(timeout=1000):
                            continue
                    frame_text = await frame.evaluate(
                        """
                        () => {
                            const visible = (el) => {
                                const rect = el.getBoundingClientRect();
                                const style = window.getComputedStyle(el);
                                return rect.width > 0 && rect.height > 0 &&
                                    style.visibility !== 'hidden' &&
                                    style.display !== 'none' &&
                                    Number(style.opacity || 1) > 0;
                            };
                            const texts = [];
                            const visit = (root) => {
                                if (!root) return;
                                for (const el of Array.from(root.querySelectorAll('*'))) {
                                    if (!visible(el)) continue;
                                    const ownText = Array.from(el.childNodes)
                                        .filter((node) => node.nodeType === Node.TEXT_NODE)
                                        .map((node) => node.textContent || '')
                                        .join(' ');
                                    const attrs = [
                                        el.getAttribute('aria-label') || '',
                                        el.getAttribute('title') || '',
                                        el.getAttribute('placeholder') || '',
                                        el.getAttribute('alt') || ''
                                    ].join(' ');
                                    if (ownText || attrs) texts.push(`${ownText} ${attrs}`);
                                    if (el.shadowRoot) visit(el.shadowRoot);
                                }
                            };
                            if (document.body) {
                                texts.push(document.body.innerText || '');
                                visit(document.body);
                            }
                            return texts.join('\\n').slice(0, 12000);
                        }
                        """
                    )
                    if frame_text:
                        body_texts.append(str(frame_text))
                except Exception:
                    continue

            text = "\n".join(body_texts).lower()
            normalized_text = re.sub(r"[\s,，。:：;；>]+", "", text)
            normalized_text = re.sub(r"[\s,.:;>\u3002\uff0c\uff1a\uff1b]+", "", text)
            if any(marker in text or marker in normalized_text for marker in self.VERIFICATION_TEXT_MARKERS):
                return True

            for frame in page.frames:
                try:
                    if await frame.evaluate(self._verification_structure_script()):
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def _verification_structure_script(self) -> str:
        return """
        () => {
            const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
            if (!viewportWidth || !viewportHeight) return false;

            const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== 'hidden' &&
                    style.display !== 'none' &&
                    Number(style.opacity || 1) > 0;
            };
            const rectOf = (el) => el.getBoundingClientRect();
            const elements = Array.from(document.querySelectorAll('body *')).filter(visible);

            const hasBlockingOverlay = elements.some((el) => {
                const rect = rectOf(el);
                const style = window.getComputedStyle(el);
                const coversViewport =
                    rect.width >= viewportWidth * 0.75 &&
                    rect.height >= viewportHeight * 0.75 &&
                    rect.left <= viewportWidth * 0.15 &&
                    rect.top <= viewportHeight * 0.15;
                const fixedLike = style.position === 'fixed' || style.position === 'sticky';
                const bg = style.backgroundColor || '';
                const hasDimBg = /rgba\\([^,]+,[^,]+,[^,]+,\\s*(0\\.[2-9]|1)/.test(bg);
                return coversViewport && (fixedLike || hasDimBg);
            });
            if (!hasBlockingOverlay) return false;

            const hasCenteredDialog = elements.some((el) => {
                const rect = rectOf(el);
                const style = window.getComputedStyle(el);
                const centerX = rect.left + rect.width / 2;
                const centerY = rect.top + rect.height / 2;
                const centered =
                    Math.abs(centerX - viewportWidth / 2) < viewportWidth * 0.22 &&
                    Math.abs(centerY - viewportHeight / 2) < viewportHeight * 0.28;
                const dialogSized =
                    rect.width >= 280 && rect.width <= viewportWidth * 0.8 &&
                    rect.height >= 180 && rect.height <= viewportHeight * 0.8;
                const bg = style.backgroundColor || '';
                const whiteLike =
                    /rgb\\(\\s*2[3-5]\\d\\s*,\\s*2[3-5]\\d\\s*,\\s*2[3-5]\\d\\s*\\)/.test(bg) ||
                    /rgba\\(\\s*2[3-5]\\d\\s*,\\s*2[3-5]\\d\\s*,\\s*2[3-5]\\d\\s*,\\s*(0\\.[8-9]|1)/.test(bg);
                const rounded = Number.parseFloat(style.borderRadius || '0') >= 8;
                return centered && dialogSized && (whiteLike || rounded);
            });
            if (!hasCenteredDialog) return false;

            const sliderTracks = elements.filter((el) => {
                const rect = rectOf(el);
                const style = window.getComputedStyle(el);
                const radius = Number.parseFloat(style.borderRadius || '0') || 0;
                const horizontalTrack =
                    rect.width >= 180 && rect.width <= 600 &&
                    rect.height >= 24 && rect.height <= 80 &&
                    rect.width / Math.max(rect.height, 1) >= 4;
                const rounded = radius >= Math.min(rect.height / 3, 12);
                return horizontalTrack && rounded;
            });

            return sliderTracks.some((track) => {
                const trackRect = rectOf(track);
                return elements.some((el) => {
                    if (el === track) return false;
                    const rect = rectOf(el);
                    const nearLeft = rect.left >= trackRect.left - 8 && rect.left <= trackRect.left + trackRect.width * 0.25;
                    const verticallyInside =
                        rect.top >= trackRect.top - 12 &&
                        rect.bottom <= trackRect.bottom + 12;
                    const handleSized =
                        rect.width >= 24 && rect.width <= 80 &&
                        rect.height >= 24 && rect.height <= 80;
                    return nearLeft && verticallyInside && handleSized;
                });
            });
        }
        """

    def _title_matches_search(self, title: str, keyword: str) -> bool:
        normalized_title = self._normalize_title(title)
        intent = self._search_intent(keyword)

        if not normalized_title:
            return False

        if "适趣" not in normalized_title:
            return False

        if intent["language"] == "cn" and "中文" not in normalized_title:
            return False

        if intent["language"] == "en" and not any(
            token in normalized_title for token in ("英文", "英语", "english")
        ):
            return False

        if intent["spec"] == "7d" and not self._has_duration(normalized_title, 7):
            return False
        if intent["spec"] == "15d" and not self._has_duration(normalized_title, 15):
            return False
        if intent["spec"] == "21d" and not self._has_duration(normalized_title, 21):
            return False
        if intent["spec"] == "year" and not self._has_year_card(normalized_title):
            return False

        return True

    def _title_matches_product(self, title: str) -> bool:
        return any(self._title_matches_search(title, keyword) for keyword in self.product.keywords)

    def _search_intent(self, keyword: str) -> Dict[str, str]:
        normalized = self._normalize_title(f"{keyword}{self.product.name}")
        language = ""
        if "中文" in normalized:
            language = "cn"
        elif any(token in normalized for token in ("英文", "英语", "english")):
            language = "en"

        spec = ""
        year_count = ""
        if self._has_duration(normalized, 7):
            spec = "7d"
        elif self._has_duration(normalized, 15):
            spec = "15d"
        elif self._has_duration(normalized, 21):
            spec = "21d"
        elif self._has_year_card(normalized):
            spec = "year"
            if any(token in normalized for token in ("两年", "2年", "两年卡", "2年卡")):
                year_count = "2"
            elif any(token in normalized for token in ("一年", "1年", "一年卡", "1年卡")):
                year_count = "1"

        return {
            "language": language,
            "spec": spec,
            "year_count": year_count,
        }

    def _normalize_title(self, text: str) -> str:
        return re.sub(r"\s+", "", (text or "").lower())

    def _has_duration(self, title: str, days: int) -> bool:
        return any(token in title for token in (f"{days}天", f"{days}日", f"{days}day", f"{days}days"))

    def _has_year_card(self, title: str) -> bool:
        return any(
            token in title
            for token in ("年卡", "年会员", "一年卡", "两年卡", "1年卡", "2年卡", "一年", "两年", "1年", "2年", "12个月", "365天")
        )

    def _looks_like_low_price_trial_listing(self, title: str) -> bool:
        trial_duration = self._has_duration(title, 7) or self._has_duration(title, 15) or self._has_duration(title, 21)
        trial_price = bool(re.search(r"(?:7|15|21)天(?:会员|阅读卡|体验卡)?[^\d]{0,8}(?:9\.9|3\.9|5\.9|6\.9)", title))
        year_price = bool(re.search(r"(?:年卡|年会员|一年|1年|2年)[^\d]{0,8}\d{3,4}", title))
        return trial_duration and (trial_price or year_price)

    async def _click_price_asc_sort(self, page: Page) -> bool:
        """Click a low-price-first sorter when the platform exposes one."""
        direct_labels = [
            "价格从低到高",
            "价格由低到高",
            "价格最低",
            "低价优先",
            "价格升序",
        ]
        for label in direct_labels:
            if await self._click_text(page, label):
                return True

        if await self._click_text(page, "价格"):
            await AntiDetect.random_delay(0.8, 1.5)
            for label in direct_labels:
                if await self._click_text(page, label):
                    return True
            return True

        clicked = await page.evaluate(
            """
            (labels) => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const nodes = Array.from(document.querySelectorAll('button, div, span, a, li'));
                const target = nodes.find((el) => {
                    if (!visible(el)) return false;
                    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
                    return labels.some((label) => text.includes(label.replace(/\\s+/g, '')));
                });
                if (!target) return false;
                target.scrollIntoView({block: 'center', inline: 'center'});
                target.click();
                return true;
            }
            """,
            direct_labels,
        )
        if clicked:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await AntiDetect.random_delay(1, 2)
            return True

        return False

    async def _click_text(self, page: Page, text: str) -> bool:
        try:
            locator = page.get_by_text(text, exact=False).first
            if await locator.count() == 0:
                return False
            await locator.click(timeout=3000)
            await page.wait_for_load_state("networkidle", timeout=10000)
            await AntiDetect.random_delay(1, 2)
            return True
        except Exception:
            return False

    def _save_results_file(self):
        output_dir = Path("data/search_results")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        product_slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", self.product.name).strip("_")
        path = output_dir / f"{timestamp}_{self.PLATFORM}_{product_slug}_{self.account.id}.xlsx"

        deduped = {}
        for listing in self.collected_listings:
            key = listing.url or f"{listing.title}|{listing.price}"
            if key not in deduped:
                deduped[key] = listing

        rows = [
            {
                "title": listing.title,
                "price": listing.price,
                "url": listing.url,
                "judgment": getattr(listing, "judgment", ""),
                "spec_capture_mode": getattr(listing, "spec_capture_mode", ""),
                "spec_capture_info": getattr(listing, "spec_capture_info", ""),
            }
            for listing in deduped.values()
        ]
        save_listing_table(rows, path)

        self.last_results_path = path
        print(
            f"[{self.PLATFORM}] results saved: {path} "
            f"(raw={self.raw_items_seen}, matched={len(rows)}, filtered_by_title={self.title_filtered_count})",
            flush=True,
        )

    def _save_raw_results_file(self):
        if not self.raw_listings:
            return

        output_dir = Path("data/search_results")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        product_slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", self.product.name).strip("_")
        path = output_dir / f"{timestamp}_{self.PLATFORM}_{product_slug}_{self.account.id}_raw.xlsx"

        deduped = {}
        for item in self.raw_listings:
            key = item.get("url") or f"{item.get('title')}|{item.get('price')}"
            if key not in deduped:
                deduped[key] = item

        save_listing_table(deduped.values(), path)
        self.last_raw_results_path = path
        print(f"[{self.PLATFORM}] raw results saved: {path}", flush=True)

    def _cookie_url(self) -> str:
        platform_urls = {
            "xianyu": "https://www.goofish.com/",
            "taobao": "https://www.taobao.com/",
        }
        return platform_urls.get(self.PLATFORM, "https://www.taobao.com/")
