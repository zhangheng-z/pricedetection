import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from agents.base_agent import BaseAgent
from core.anti_detect import AntiDetect


class XianyuAgent(BaseAgent):
    PLATFORM = "xianyu"

    async def _do_search(self, page: Page, keyword: str):
        print(f"[{self.PLATFORM}] opening home page", flush=True)
        await page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
        await AntiDetect.random_delay(2, 4)

        search_selectors = [
            "form input[type='text']",
            "input[class*='search-input']",
            "input[class*='search']",
            "input[type='text']",
            "[class*='search'] input",
        ]
        selector = None
        search_submitted = False
        for sel in search_selectors:
            try:
                locator = page.locator(sel).first
                if await locator.count() > 0 and await locator.is_visible(timeout=2000):
                    selector = sel
                    break
            except Exception:
                pass

        if selector:
            print(f"[{self.PLATFORM}] typing search keyword: {keyword}", flush=True)
            try:
                await page.click(selector, timeout=5000)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await AntiDetect.human_type(page, selector, keyword)
                await AntiDetect.random_delay(0.5, 1.5)
                await page.keyboard.press("Enter")
                search_submitted = True
            except Exception as exc:
                print(f"[{self.PLATFORM}] search input failed, fallback to search URL: {exc}", flush=True)
        else:
            icon_selectors = ["[class*='search']", "[class*='icon-search']", "a[href*='search']"]
            for sel in icon_selectors:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await AntiDetect.random_delay(1, 2)
                    break

        if not search_submitted:
            search_url = f"https://www.goofish.com/search?q={quote(keyword)}"
            print(f"[{self.PLATFORM}] goto search URL: {search_url}", flush=True)
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

        try:
            await page.wait_for_url("**/search**", timeout=10000)
        except Exception:
            if "/search" not in page.url:
                search_url = f"https://www.goofish.com/search?q={quote(keyword)}"
                print(f"[{self.PLATFORM}] search did not navigate, goto search URL: {search_url}", flush=True)
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector('a[class*="feeds-item-wrap"], [class*="feeds-list-container"]', timeout=20000)
        except Exception as exc:
            print(f"[{self.PLATFORM}] search results not visible yet: {exc}", flush=True)
        await self._anti_risk_delay("search_delay_seconds", "after search")

        sorted_ok = await self._click_price_asc_sort(page)
        print(f"[{self.PLATFORM}] price ascending sort: {'clicked' if sorted_ok else 'not found'}", flush=True)
        await self._anti_risk_delay("sort_delay_seconds", "after sort")
        await AntiDetect.human_scroll(page, times=random.randint(2, 4))

    async def _goto_next_results_page(self, page: Page) -> bool:
        try:
            current_state = await page.evaluate(
                """
                () => ({
                    firstUrl: document.querySelector('a[class*="feeds-item-wrap"]')?.href || '',
                    activePage: Array.from(document.querySelectorAll('[class*="pagination"] [class*="page-box"]'))
                        .find((el) => /active/.test(el.className || ''))?.textContent?.trim() || '',
                })
                """
            )
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self._anti_risk_delay("page_turn_delay_seconds", "before next page")

            clicked = await page.evaluate(
                """
                () => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const container = Array.from(document.querySelectorAll('[class*="pagination"]'))
                        .filter(visible)
                        .pop();
                    if (!container) return false;

                    const pageBoxes = Array.from(container.querySelectorAll('[class*="page-box"]'))
                        .filter((el) => visible(el) && /^\\d+$/.test((el.textContent || '').trim()));
                    const activeIndex = pageBoxes.findIndex((el) => /active/.test(el.className || ''));
                    if (activeIndex >= 0 && activeIndex + 1 < pageBoxes.length) {
                        const nextPage = pageBoxes[activeIndex + 1];
                        nextPage.scrollIntoView({block: 'center', inline: 'center'});
                        nextPage.click();
                        return true;
                    }

                    const button = Array.from(container.querySelectorAll('button'))
                        .find((el) => visible(el) && !el.disabled && el.querySelector('[class*="arrow-right"]'));
                    if (!button) return false;
                    button.scrollIntoView({block: 'center', inline: 'center'});
                    button.click();
                    return true;
                }
                """
            )
            if not clicked:
                return False

            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await self._anti_risk_delay("page_turn_delay_seconds", "after next page")
            await AntiDetect.human_scroll(page, times=random.randint(1, 2))

            next_state = await page.evaluate(
                """
                () => ({
                    firstUrl: document.querySelector('a[class*="feeds-item-wrap"]')?.href || '',
                    activePage: Array.from(document.querySelectorAll('[class*="pagination"] [class*="page-box"]'))
                        .find((el) => /active/.test(el.className || ''))?.textContent?.trim() || '',
                })
                """
            )
            return bool(
                next_state.get("firstUrl")
                and (
                    next_state.get("firstUrl") != current_state.get("firstUrl")
                    or next_state.get("activePage") != current_state.get("activePage")
                )
            )
        except Exception:
            return False

    async def _click_price_asc_sort(self, page: Page) -> bool:
        forced = await page.evaluate(
            """
            (label) => {
                const norm = (text) => (text || '').replace(/\\s+/g, '').trim();
                const items = Array.from(document.querySelectorAll('[class*="search-select-item"]'));
                const target = items.find((el) => norm(el.innerText || el.textContent) === label);
                if (!target) return false;
                target.click();
                target.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                target.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                target.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                return true;
            }
            """,
            "\u4ef7\u683c\u4ece\u4f4e\u5230\u9ad8",
        )
        if forced:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await AntiDetect.random_delay(1, 2)
            selected = await page.evaluate(
                """
                (label) => Array.from(document.querySelectorAll('[class*="search-select-container"]'))
                    .some((el) => (el.innerText || el.textContent || '').replace(/\\s+/g, '').includes(label))
                """,
                "\u4ef7\u683c\u4ece\u4f4e\u5230\u9ad8",
            )
            if selected:
                return True

        direct_labels = [
            "\u4ef7\u683c\u4ece\u4f4e\u5230\u9ad8",
            "\u4ef7\u683c\u7531\u4f4e\u5230\u9ad8",
            "\u4ef7\u683c\u6700\u4f4e",
            "\u4f4e\u4ef7\u4f18\u5148",
            "\u4ef7\u683c\u5347\u5e8f",
        ]
        for label in direct_labels:
            if await self._click_text(page, label):
                return True

        if await self._click_text(page, "\u4ef7\u683c"):
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
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
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

    async def _fetch_order_offer(
        self,
        source_page: Page,
        url: str,
        title: str,
        keyword: str,
    ) -> Optional[Dict[str, Any]]:
        if not url:
            return None

        use_new_page = bool(getattr(self.anti_risk, "open_detail_in_new_page", False))
        search_url = source_page.url
        detail_page = await source_page.context.new_page() if use_new_page else source_page
        try:
            await detail_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await AntiDetect.random_delay(1, 2)

            if not await self._click_buy_now(detail_page):
                print(f"[{self.PLATFORM}] buy button not found: {title[:40]}", flush=True)
                return None

            await AntiDetect.random_delay(1.5, 3)
            try:
                await detail_page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass

            offer = await self._select_matching_order_offer(detail_page, keyword)
            if offer is None:
                debug_path = await self._save_order_debug_snapshot(detail_page)
                print(f"[{self.PLATFORM}] matching order spec/price not found, debug saved: {debug_path}", flush=True)
            return offer
        except Exception as exc:
            print(f"[{self.PLATFORM}] failed to fetch order price: {exc}", flush=True)
            return None
        finally:
            if use_new_page:
                await detail_page.close()
            elif search_url and search_url != detail_page.url:
                try:
                    await detail_page.goto(search_url, wait_until="networkidle", timeout=30000)
                    await AntiDetect.random_delay(2, 4)
                except Exception:
                    pass

    async def _click_buy_now(self, page: Page) -> bool:
        labels = [
            "\u7acb\u5373\u8d2d\u4e70",
            "\u9a6c\u4e0a\u8d2d\u4e70",
            "\u7acb\u5373\u4e0b\u5355",
        ]
        selectors = []
        for label in labels:
            selectors.extend([
                f"text={label}",
                f"button:has-text('{label}')",
                f"[class*='buy']:has-text('{label}')",
            ])

        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    continue
                await self._anti_risk_delay("buy_click_delay_seconds", "before buy")
                await locator.click(timeout=5000)
                return True
            except Exception:
                continue
        return False

    async def _select_matching_order_offer(self, page: Page, keyword: str) -> Optional[Dict[str, Any]]:
        intent = self._search_intent(keyword)
        spec_state = await self._collect_xianyu_order_options(page, intent)
        candidates = spec_state.get("candidates", [])

        if not spec_state.get("has_options"):
            price = await self._extract_xianyu_order_price(page)
            return {"price": price, "spec_text": ""} if price is not None else None

        if not candidates:
            return None

        offers = []
        for candidate in candidates[:6]:
            try:
                clicked = await page.evaluate(
                    """
                    (index) => {
                        const el = window.__priceMonitorSkuCandidates?.[index];
                        if (!el) return false;
                        el.scrollIntoView({block: 'center', inline: 'center'});
                        el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                        el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                        el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                        el.click();
                        return true;
                    }
                    """,
                    candidate["index"],
                )
                if not clicked:
                    continue
                await AntiDetect.random_delay(0.7, 1.2)

                option_price = candidate.get("option_price")
                price = option_price if option_price is not None else await self._extract_xianyu_order_price(page)
                if price is None:
                    continue
                offers.append({"price": float(price), "spec_text": candidate.get("text", "")})
            except Exception:
                continue

        if not offers:
            return None
        return min(offers, key=lambda offer: offer["price"])

    async def _collect_xianyu_order_options(self, page: Page, intent: Dict[str, str]) -> Dict[str, Any]:
        return await page.evaluate(
            r"""
            (intent) => {
                const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                const norm = (text) => clean(text).toLowerCase().replace(/\s+/g, '');
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const parsePrice = (text) => {
                    const match = clean(text).match(/[\u00a5\uffe5]\s*(\d+(?:\.\d+)?)/);
                    if (!match) return null;
                    const price = Number.parseFloat(match[1]);
                    return Number.isFinite(price) ? price : null;
                };
                const dayPattern = (days) => new RegExp(`${days}(?:\u5929|\u65e5|day|days)`, 'i');
                const yearPattern = /(?:\u5e74\u5361|\u5e74\u4f1a\u5458|\u4e00\u5e74\u5361|\u4e24\u5e74\u5361|1\u5e74\u5361|2\u5e74\u5361|\u4e00\u5e74|\u4e24\u5e74|1\u5e74|2\u5e74|12\u4e2a\u6708|365\u5929)/i;
                const hasSpecToken = (value) => dayPattern(7).test(value) ||
                    dayPattern(15).test(value) || dayPattern(21).test(value) || yearPattern.test(value);
                const specKinds = (value) => {
                    const kinds = [];
                    if (dayPattern(7).test(value)) kinds.push('7d');
                    if (dayPattern(15).test(value)) kinds.push('15d');
                    if (dayPattern(21).test(value)) kinds.push('21d');
                    if (yearPattern.test(value)) kinds.push('year');
                    return kinds;
                };
                const specMatches = (value) => {
                    if (intent.spec === '7d') return dayPattern(7).test(value);
                    if (intent.spec === '15d') return dayPattern(15).test(value);
                    if (intent.spec === '21d') return dayPattern(21).test(value);
                    if (intent.spec === 'year') {
                        if (intent.year_count === '1') {
                            return /(?:\u5e74\u5361|\u5e74\u4f1a\u5458|\u4e00\u5e74\u5361|1\u5e74\u5361|\u4e00\u5e74|1\u5e74|12\u4e2a\u6708|365\u5929)/i.test(value);
                        }
                        if (intent.year_count === '2') {
                            return /(?:\u5e74\u5361|\u5e74\u4f1a\u5458|\u4e24\u5e74\u5361|2\u5e74\u5361|\u4e24\u5e74|2\u5e74)/i.test(value);
                        }
                        return yearPattern.test(value);
                    }
                    return hasSpecToken(value);
                };
                const rejectedShellText = (value) => /(?:\u63d0\u4ea4\u8ba2\u5355|\u786e\u8ba4\u8ba2\u5355|\u8ba2\u5355\u4fe1\u606f|\u8d2d\u4e70\u6570\u91cf|\u7acb\u5373\u8d2d\u4e70|\u9a6c\u4e0a\u8d2d\u4e70|\u5ba2\u670d|\u8fd4\u56de|\u5173\u95ed)/.test(value);
                const clickableFor = (el) => el.closest([
                    'button',
                    '[role="button"]',
                    'li',
                    'label',
                    '[class*="sku"]',
                    '[class*="Sku"]',
                    '[class*="spec"]',
                    '[class*="Spec"]',
                    '[class*="prop"]',
                    '[class*="Prop"]',
                    '[class*="item"]',
                    '[class*="Item"]',
                    '[class*="option"]',
                    '[class*="Option"]'
                ].join(','));
                const scoreSpec = (text, el) => {
                    const value = norm(text);
                    let score = 0;
                    if (el.matches('button, [role="button"], li, label')) score += 30;
                    if (parsePrice(text) !== null) score += 10;
                    if (specMatches(value)) score += 60;
                    if (intent.year_count === '1' && /(?:\u4e00\u5e74\u5361|1\u5e74\u5361|\u4e00\u5e74|1\u5e74)/.test(value)) score += 50;
                    if (intent.year_count === '2' && /(?:\u4e24\u5e74\u5361|2\u5e74\u5361|\u4e24\u5e74|2\u5e74)/.test(value)) score += 50;
                    if (/selected|active|current|\u9009\u4e2d/.test((el.className || '') + ' ' + (el.getAttribute('aria-selected') || ''))) score += 5;
                    score -= Math.max(0, value.length - 24) / 4;
                    return score;
                };

                const selector = [
                    'button',
                    '[role="button"]',
                    'li',
                    'label',
                    '[class*="sku"]',
                    '[class*="Sku"]',
                    '[class*="spec"]',
                    '[class*="Spec"]',
                    '[class*="prop"]',
                    '[class*="Prop"]',
                    '[class*="item"]',
                    '[class*="Item"]',
                    '[class*="option"]',
                    '[class*="Option"]',
                    '[title]',
                    '[aria-label]',
                    'span',
                    'div'
                ].join(',');
                const seen = new Set();
                const optionSeen = new Set();
                const optionTexts = [];
                const candidates = [];
                const elements = [];

                document.querySelectorAll(selector).forEach((el) => {
                    if (!visible(el)) return;
                    const rawText = clean([
                        el.innerText || el.textContent || '',
                        el.getAttribute('title') || '',
                        el.getAttribute('aria-label') || ''
                    ].join(' '));
                    const clickEl = clickableFor(el) || el;
                    if (!visible(clickEl)) return;
                    const clickText = clean(clickEl.innerText || clickEl.textContent || rawText);
                    const text = clickText.length <= 180 ? clickText : rawText;
                    const key = norm(text || rawText);
                    const optionLooksClickable = clickEl.matches('button, [role="button"], li, label') ||
                        /sku|spec|prop|option|item/i.test(clickEl.className || '');
                    const optionTextHasSpec = hasSpecToken(key);
                    const optionTextMatchesIntent = specMatches(key);
                    const optionSpecKinds = specKinds(key);
                    const optionLooksLikeContainer = optionSpecKinds.length > 1;

                    if (optionLooksClickable && optionTextHasSpec && !optionLooksLikeContainer && !optionSeen.has(key)) {
                        optionSeen.add(key);
                        optionTexts.push(text || rawText);
                    }

                    if (!key || seen.has(key)) return;
                    if (rejectedShellText(key) && !hasSpecToken(key)) return;
                    if (!optionLooksClickable || !optionTextHasSpec || optionLooksLikeContainer || !optionTextMatchesIntent) return;
                    seen.add(key);
                    const index = elements.length;
                    elements.push(clickEl);
                    candidates.push({
                        index,
                        text: text || rawText,
                        option_price: parsePrice(text || rawText),
                        score: scoreSpec(text || rawText, clickEl),
                    });
                });

                candidates.sort((a, b) => b.score - a.score);
                window.__priceMonitorSkuCandidates = elements;
                return {has_options: optionTexts.length >= 2, options: optionTexts, candidates};
            }
            """,
            intent,
        )

    async def _extract_xianyu_order_price(self, page: Page) -> Optional[float]:
        value = await page.evaluate(
            r"""
            () => {
                const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                const toPrice = (text) => {
                    const match = clean(text).match(/[\u00a5\uffe5]\s*(\d+(?:\.\d+)?)/);
                    if (!match) return null;
                    const price = Number.parseFloat(match[1]);
                    return Number.isFinite(price) ? price : null;
                };
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const candidates = [];
                for (const el of Array.from(document.querySelectorAll('body *'))) {
                    if (!visible(el)) continue;
                    const ownText = clean(Array.from(el.childNodes)
                        .filter((node) => node.nodeType === Node.TEXT_NODE)
                        .map((node) => node.textContent)
                        .join(' '));
                    const text = ownText || clean(el.textContent);
                    const price = toPrice(text);
                    if (price === null || price <= 0) continue;

                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const context = clean((el.closest('section, div, form, main') || el).textContent);
                    let score = 0;
                    if (/(?:\u5b9e\u4ed8\u6b3e|\u5e94\u4ed8\u6b3e|\u5e94\u4ed8|\u5408\u8ba1|\u603b\u8ba1|\u8ba2\u5355\u91d1\u989d|\u652f\u4ed8\u91d1\u989d|\u9700\u4ed8\u6b3e)/.test(context)) score += 100;
                    if (/(?:\u8ba2\u5355\u4fe1\u606f|\u8d2d\u4e70\u6570\u91cf|\u786e\u8ba4\u8ba2\u5355|\u63d0\u4ea4\u8ba2\u5355)/.test(document.body.innerText || '')) score += 30;
                    score += Math.min(Number.parseFloat(style.fontSize) || 0, 40);
                    score += rect.top / 1000;
                    score += rect.left / 10000;
                    candidates.push({price, score});
                }
                candidates.sort((a, b) => b.score - a.score);
                return candidates.length ? candidates[0].price : null;
            }
            """
        )
        return float(value) if value else None

    async def _save_order_debug_snapshot(self, page: Page) -> Path:
        output_dir = Path("data/debug")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = output_dir / f"{timestamp}_{self.PLATFORM}_order"
        await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        base.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
        return base.with_suffix(".png")
