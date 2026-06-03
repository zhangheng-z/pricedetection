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

    async def _is_verification_page(self, page: Page) -> bool:
        if await super()._is_verification_page(page):
            return True

        for frame in page.frames:
            try:
                if await frame.evaluate(self._xianyu_verification_structure_script()):
                    return True
            except Exception:
                continue
        return False

    def _xianyu_verification_structure_script(self) -> str:
        return r"""
        () => {
            const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
            if (!viewportWidth || !viewportHeight || !document.body) return false;

            const text = (document.body.innerText || '').replace(/\s+/g, '');
            const textMarkers = [
                '\u8bf7\u62d6\u52a8\u4e0b\u65b9\u6ed1\u5757\u5b8c\u6210\u9a8c\u8bc1',
                '\u901a\u8fc7\u9a8c\u8bc1\u4ee5\u786e\u4fdd\u6b63\u5e38\u8bbf\u95ee',
                '\u8bf7\u6309\u4f4f\u6ed1\u5757',
                '\u62d6\u52a8\u5230\u6700\u53f3\u8fb9'
            ];
            if (textMarkers.some((marker) => text.includes(marker))) return true;

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

            const dialogs = elements.filter((el) => {
                const rect = rectOf(el);
                const style = window.getComputedStyle(el);
                const centerX = rect.left + rect.width / 2;
                const centerY = rect.top + rect.height / 2;
                const centered =
                    Math.abs(centerX - viewportWidth / 2) < viewportWidth * 0.18 &&
                    Math.abs(centerY - viewportHeight / 2) < viewportHeight * 0.22;
                const dialogSized =
                    rect.width >= 300 && rect.width <= Math.min(620, viewportWidth * 0.75) &&
                    rect.height >= 200 && rect.height <= Math.min(520, viewportHeight * 0.75);
                const bg = style.backgroundColor || '';
                const whiteLike =
                    /rgb\(\s*2[3-5]\d\s*,\s*2[3-5]\d\s*,\s*2[3-5]\d\s*\)/.test(bg) ||
                    /rgba\(\s*2[3-5]\d\s*,\s*2[3-5]\d\s*,\s*2[3-5]\d\s*,\s*(0\.[8-9]|1)/.test(bg);
                const rounded = Number.parseFloat(style.borderRadius || '0') >= 8;
                return centered && dialogSized && (whiteLike || rounded);
            });
            if (!dialogs.length) return false;

            return dialogs.some((dialog) => {
                const dialogRect = rectOf(dialog);
                const insideDialog = (el) => {
                    const rect = rectOf(el);
                    return rect.left >= dialogRect.left - 4 &&
                        rect.right <= dialogRect.right + 4 &&
                        rect.top >= dialogRect.top - 4 &&
                        rect.bottom <= dialogRect.bottom + 4;
                };
                const dialogElements = elements.filter((el) => el !== dialog && insideDialog(el));
                const tracks = dialogElements.filter((el) => {
                    const rect = rectOf(el);
                    const style = window.getComputedStyle(el);
                    const horizontalTrack =
                        rect.width >= 180 &&
                        rect.width <= Math.min(420, dialogRect.width * 0.9) &&
                        rect.height >= 24 &&
                        rect.height <= 70 &&
                        rect.width / Math.max(rect.height, 1) >= 4;
                    const rounded = Number.parseFloat(style.borderRadius || '0') >= 10;
                    return horizontalTrack && rounded;
                });

                return tracks.some((track) => {
                    const trackRect = rectOf(track);
                    return dialogElements.some((el) => {
                        if (el === track) return false;
                        const rect = rectOf(el);
                        const handleSized =
                            rect.width >= 24 && rect.width <= 80 &&
                            rect.height >= 24 && rect.height <= 80;
                        const nearTrackStart =
                            rect.left >= trackRect.left - 12 &&
                            rect.left <= trackRect.left + trackRect.width * 0.25;
                        const verticallyAligned =
                            rect.top >= trackRect.top - 16 &&
                            rect.bottom <= trackRect.bottom + 16;
                        return handleSized && nearTrackStart && verticallyAligned;
                    });
                });
            });
        }
        """

    async def _is_manual_verification_cleared(self, page: Page) -> bool:
        try:
            return await page.evaluate(
                r"""
                () => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' &&
                            style.display !== 'none' &&
                            Number(style.opacity || 1) > 0;
                    };
                    const buyLabels = [
                        '\u7acb\u5373\u8d2d\u4e70',
                        '\u9a6c\u4e0a\u8d2d\u4e70',
                        '\u7acb\u5373\u4e0b\u5355'
                    ];
                    const hasBuyAction = Array.from(document.querySelectorAll('button, [role="button"], div, span, a'))
                        .some((el) => {
                            if (!visible(el)) return false;
                            const text = (el.innerText || el.textContent || '').replace(/\s+/g, '');
                            return buyLabels.some((label) => text.includes(label));
                        });
                    if (hasBuyAction) return true;

                    const bodyText = (document.body?.innerText || '').replace(/\s+/g, '');
                    const normalPageText = [
                        '\u5546\u54c1\u8be6\u60c5',
                        '\u5b9d\u8d1d\u8be6\u60c5',
                        '\u6211\u60f3\u8981',
                        '\u52a0\u5165\u8d2d\u7269\u8f66',
                        '\u786e\u8ba4\u8ba2\u5355',
                        '\u63d0\u4ea4\u8ba2\u5355'
                    ];
                    if (normalPageText.some((marker) => bodyText.includes(marker))) {
                        return true;
                    }

                    const verificationText = [
                        '\u8bf7\u62d6\u52a8\u4e0b\u65b9\u6ed1\u5757\u5b8c\u6210\u9a8c\u8bc1',
                        '\u901a\u8fc7\u9a8c\u8bc1\u4ee5\u786e\u4fdd\u6b63\u5e38\u8bbf\u95ee',
                        '\u8bf7\u6309\u4f4f\u6ed1\u5757',
                        '\u62d6\u52a8\u5230\u6700\u53f3\u8fb9'
                    ];
                    return !verificationText.some((marker) => bodyText.includes(marker));
                }
                """
            )
        except Exception:
            return False

    def _format_price_text(self, price: Optional[float]) -> str:
        if price is None:
            return ""
        return f"{float(price):g}"

    def _format_spec_capture_info(self, mode: str, spec_text: str, price: Optional[float], options: list) -> str:
        if mode == "order_text_only":
            parts = []
            if spec_text:
                parts.append(str(spec_text).strip())
            if price is not None:
                parts.append(f"价格:{self._format_price_text(price)}")
            return " | ".join(parts)

        if mode == "options_detected":
            items = []
            for option in options or []:
                text = str(option.get("text", "")).strip()
                option_price = option.get("option_price")
                if not text:
                    continue
                item = text
                if option_price is not None:
                    item = f"{item}: {self._format_price_text(option_price)}"
                if option.get("sold_out"):
                    item = f"{item} 已售罄"
                items.append(item)
            return "；".join(items)

        return ""

    async def _click_xianyu_option(self, page: Page, candidate: Dict[str, Any]) -> bool:
        token = str(candidate.get("token", "")).strip()
        if not token:
            return False

        try:
            locator = page.locator(f'[data-price-monitor-sku-token="{token}"]').first
            if await locator.count() == 0:
                return False
            await locator.scroll_into_view_if_needed(timeout=3000)
            try:
                await locator.hover(timeout=2000)
            except Exception:
                pass
            await locator.click(timeout=5000)
            await self._wait_for_verification_appearance(page, "after option click", timeout_seconds=3)
            return True
        except Exception:
            return False

    async def _probe_xianyu_option_state(self, page: Page, candidate: Dict[str, Any]) -> Dict[str, Any]:
        before_sold_out_count = await page.evaluate(
            r"""
            () => {
                const text = (document.body.innerText || '').replace(/\s+/g, ' ').trim();
                const matches = text.match(/该时长暂无库存|暂无库存|已售罄|售罄/g);
                return matches ? matches.length : 0;
            }
            """
        )
        clicked = await self._click_xianyu_option(page, candidate)
        if not clicked:
            return {"clicked": False, "sold_out": False, "price": None}

        await AntiDetect.random_delay(0.7, 1.2)
        after_sold_out_count = await page.evaluate(
            r"""
            () => {
                const text = (document.body.innerText || '').replace(/\s+/g, ' ').trim();
                const matches = text.match(/该时长暂无库存|暂无库存|已售罄|售罄/g);
                return matches ? matches.length : 0;
            }
            """
        )
        sold_out = after_sold_out_count > before_sold_out_count
        price = None if sold_out else await self._extract_xianyu_order_price(page)
        return {"clicked": True, "sold_out": sold_out, "price": price}

    async def _resolve_xianyu_option_prices(self, page: Page, spec_state: Dict[str, Any]) -> Dict[str, Any]:
        options = [dict(option) for option in spec_state.get("options", [])]
        candidates = [dict(candidate) for candidate in spec_state.get("candidates", [])]
        if not options or not candidates:
            return spec_state

        price_by_text = {}
        sold_out_by_text = {}
        for candidate in candidates:
            text = str(candidate.get("text", "")).strip()
            if not text:
                continue
            if candidate.get("option_price") is not None and candidate.get("sold_out") is not True:
                price_by_text[text] = candidate.get("option_price")
            if candidate.get("sold_out") is True:
                sold_out_by_text[text] = True
            if candidate.get("option_price") is not None and candidate.get("sold_out") is not None:
                continue

            try:
                probe = await self._probe_xianyu_option_state(page, candidate)
                if not probe.get("clicked"):
                    continue
                candidate["sold_out"] = bool(probe.get("sold_out"))
                sold_out_by_text[text] = bool(probe.get("sold_out"))
                resolved_price = probe.get("price")
                if resolved_price is None:
                    continue
                candidate["option_price"] = float(resolved_price)
                price_by_text[text] = float(resolved_price)
            except Exception:
                continue

        for option in options:
            text = str(option.get("text", "")).strip()
            if text in sold_out_by_text:
                option["sold_out"] = sold_out_by_text[text]
            if option.get("option_price") is None and text in price_by_text:
                option["option_price"] = price_by_text[text]

        for candidate in candidates:
            text = str(candidate.get("text", "")).strip()
            if text in sold_out_by_text:
                candidate["sold_out"] = sold_out_by_text[text]
            if candidate.get("option_price") is None and text in price_by_text:
                candidate["option_price"] = price_by_text[text]

        spec_state["options"] = options
        spec_state["candidates"] = candidates
        return spec_state

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
                    activePage: Array.from(document.querySelectorAll('[class*="pagination-page-box"]'))
                        .find((el) => /active/.test(el.className || ''))?.textContent?.trim() || '',
                    tinyPage: Array.from(document.querySelectorAll('[class*="search-page-tiny-page"]'))
                        .find((el) => (el.textContent || '').includes('/'))?.textContent?.trim() || '',
                    url: location.href,
                })
                """
            )
            await self._anti_risk_delay("page_turn_delay_seconds", "before next page")

            target = await page.evaluate(
                """
                () => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const tinyButton = Array.from(document.querySelectorAll('button'))
                        .find((el) => visible(el) && !el.disabled && el.querySelector('[class*="search-page-tiny-arrow-right"]'));
                    if (tinyButton) {
                        tinyButton.scrollIntoView({block: 'center', inline: 'center'});
                        const rect = tinyButton.getBoundingClientRect();
                        return {
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2,
                            label: 'tiny-next',
                        };
                    }

                    window.scrollTo(0, document.body.scrollHeight);
                    const container = Array.from(document.querySelectorAll('[class*="pagination"]'))
                        .filter(visible)
                        .pop();
                    if (!container) return null;

                    const pageBoxes = Array.from(container.querySelectorAll('[class*="pagination-page-box"]'))
                        .filter((el) => visible(el) && /^\\d+$/.test((el.textContent || '').trim()));
                    const activeIndex = pageBoxes.findIndex((el) => /active/.test(el.className || ''));
                    if (activeIndex >= 0 && activeIndex + 1 < pageBoxes.length) {
                        const nextPage = pageBoxes[activeIndex + 1];
                        nextPage.scrollIntoView({block: 'center', inline: 'center'});
                        const rect = nextPage.getBoundingClientRect();
                        return {
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2,
                            label: (nextPage.textContent || '').trim(),
                        };
                    }

                    const button = Array.from(container.querySelectorAll('button'))
                        .find((el) => visible(el) && !el.disabled && el.querySelector('[class*="arrow-right"]'));
                    if (!button) return null;
                    button.scrollIntoView({block: 'center', inline: 'center'});
                    const rect = button.getBoundingClientRect();
                    return {
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                        label: 'next',
                    };
                }
                """
            )
            if not target:
                return False
            await page.mouse.move(target["x"], target["y"])
            await page.mouse.click(target["x"], target["y"])

            try:
                await page.wait_for_function(
                    """
                    (state) => {
                        const firstUrl = document.querySelector('a[class*="feeds-item-wrap"]')?.href || '';
                        const activePage = Array.from(document.querySelectorAll('[class*="pagination-page-box"]'))
                            .find((el) => /active/.test(el.className || ''))?.textContent?.trim() || '';
                        const tinyPage = Array.from(document.querySelectorAll('[class*="search-page-tiny-page"]'))
                            .find((el) => (el.textContent || '').includes('/'))?.textContent?.trim() || '';
                        return location.href !== state.url ||
                            (firstUrl && firstUrl !== state.firstUrl) ||
                            (activePage && activePage !== state.activePage) ||
                            (tinyPage && tinyPage !== state.tinyPage);
                    }
                    """,
                    current_state,
                    timeout=15000,
                )
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await self._anti_risk_delay("page_turn_delay_seconds", "after next page")
            await AntiDetect.human_scroll(page, times=random.randint(1, 2))

            next_state = await page.evaluate(
                """
                () => ({
                    firstUrl: document.querySelector('a[class*="feeds-item-wrap"]')?.href || '',
                    activePage: Array.from(document.querySelectorAll('[class*="pagination-page-box"]'))
                        .find((el) => /active/.test(el.className || ''))?.textContent?.trim() || '',
                    tinyPage: Array.from(document.querySelectorAll('[class*="search-page-tiny-page"]'))
                        .find((el) => (el.textContent || '').includes('/'))?.textContent?.trim() || '',
                    url: location.href,
                })
                """
            )
            return bool(
                next_state.get("url") != current_state.get("url")
                or (
                    next_state.get("firstUrl")
                    and next_state.get("firstUrl") != current_state.get("firstUrl")
                )
                or (
                    next_state.get("activePage")
                    and next_state.get("activePage") != current_state.get("activePage")
                )
                or (
                    next_state.get("tinyPage")
                    and next_state.get("tinyPage") != current_state.get("tinyPage")
                )
            )
        except Exception:
            return False

    async def _get_total_results_pages(self, page: Page) -> int:
        try:
            value = await page.evaluate(
                """
                () => {
                    const tinyText = Array.from(document.querySelectorAll('[class*="search-page-tiny-page"]'))
                        .map((el) => (el.textContent || '').trim())
                        .find((text) => /^\\d+\\s*\\/\\s*\\d+$/.test(text));
                    if (tinyText) {
                        const match = tinyText.match(/\\/\\s*(\\d+)/);
                        if (match) return Number.parseInt(match[1], 10) || 0;
                    }

                    const pageNumbers = Array.from(document.querySelectorAll('[class*="pagination-page-box"]'))
                        .map((el) => Number.parseInt((el.textContent || '').trim(), 10))
                        .filter((value) => Number.isFinite(value) && value > 0);
                    return pageNumbers.length ? Math.max(...pageNumbers) : 0;
                }
                """
            )
            return int(value or 0)
        except Exception:
            return 0

    async def _ensure_price_asc_sort(self, page: Page) -> bool:
        if await self._is_price_asc_sort_selected(page):
            return True
        sorted_ok = await self._click_price_asc_sort(page)
        if sorted_ok:
            print(f"[{self.PLATFORM}] price ascending sort restored", flush=True)
        return sorted_ok

    async def _is_price_asc_sort_selected(self, page: Page) -> bool:
        try:
            return await page.evaluate(
                """
                () => Array.from(document.querySelectorAll('[class*="search-select-container"]'))
                    .some((el) => (el.innerText || el.textContent || '').replace(/\\s+/g, '').includes('\u4ef7\u683c\u4ece\u4f4e\u5230\u9ad8'))
                """
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

        detail_page = await source_page.context.new_page()
        try:
            await detail_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await detail_page.bring_to_front()
            except Exception:
                pass
            await AntiDetect.random_delay(1, 2)
            await self._wait_for_verification_appearance(detail_page, "after detail open")

            if not await self._click_buy_now(detail_page):
                if await self._wait_for_verification_appearance(
                    detail_page,
                    "before buy retry",
                    timeout_seconds=3,
                ):
                    if not await self._click_buy_now(detail_page):
                        print(f"[{self.PLATFORM}] buy button not found: {title[:40]}", flush=True)
                        return None
                else:
                    print(f"[{self.PLATFORM}] buy button not found: {title[:40]}", flush=True)
                    return None

            await AntiDetect.random_delay(1.5, 3)
            try:
                await detail_page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass
            await self._wait_for_verification_appearance(detail_page, "after buy click", timeout_seconds=5)

            await self._wait_if_verification(detail_page, "before order spec extraction")
            offer = await self._select_matching_order_offer(detail_page, keyword)
            await self._wait_if_verification(detail_page, "after order spec extraction")
            if offer is None:
                debug_path = await self._save_order_debug_snapshot(detail_page)
                print(f"[{self.PLATFORM}] matching order spec/price not found, debug saved: {debug_path}", flush=True)
            return offer
        except Exception as exc:
            print(f"[{self.PLATFORM}] failed to fetch order price: {exc}", flush=True)
            return None
        finally:
            await detail_page.close()

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
        if spec_state.get("has_options"):
            spec_state = await self._resolve_xianyu_option_prices(page, spec_state)
        candidates = spec_state.get("candidates", [])

        delist_candidate = next(
            (
                candidate
                for candidate in spec_state.get("options", [])
                if "7d" in candidate.get("kinds", []) and not candidate.get("sold_out")
            ),
            None,
        )
        if delist_candidate:
            price = delist_candidate.get("option_price")
            if price is None:
                price = await self._extract_xianyu_order_price(page)
            return {
                "price": float(price or 0),
                "spec_text": delist_candidate.get("text", ""),
                "spec_capture_mode": "options_detected",
                "spec_capture_info": self._format_spec_capture_info(
                    "options_detected",
                    delist_candidate.get("text", ""),
                    price,
                    spec_state.get("options", []),
                ),
                "force_decision": "DELIST",
            }

        en_15d_delist_candidate = next(
            (
                candidate
                for candidate in spec_state.get("options", [])
                if "15d" in candidate.get("kinds", [])
                and not candidate.get("sold_out")
                and self._looks_like_english_order_text(
                    " ".join([candidate.get("text", ""), spec_state.get("order_text", "")])
                )
            ),
            None,
        )
        if en_15d_delist_candidate:
            price = en_15d_delist_candidate.get("option_price")
            if price is None:
                price = await self._extract_xianyu_order_price(page)
            spec_text = " ".join([en_15d_delist_candidate.get("text", ""), spec_state.get("order_text", "")]).strip()
            return {
                "price": float(price or 0),
                "spec_text": spec_text,
                "spec_capture_mode": "options_detected",
                "spec_capture_info": self._format_spec_capture_info(
                    "options_detected",
                    spec_text,
                    price,
                    spec_state.get("options", []),
                ),
                "force_decision": "DELIST",
            }

        if not spec_state.get("has_options"):
            price = await self._extract_xianyu_order_price(page)
            order_text = await self._extract_xianyu_order_item_text(page)
            if price is not None and self._looks_like_cn_7d_delist_order(order_text, price):
                return {
                    "price": price,
                    "spec_text": order_text,
                    "spec_capture_mode": "order_text_only",
                    "spec_capture_info": self._format_spec_capture_info("order_text_only", order_text, price, []),
                    "force_decision": "DELIST",
                }
            return {
                "price": price,
                "spec_text": order_text,
                "spec_capture_mode": "order_text_only",
                "spec_capture_info": self._format_spec_capture_info("order_text_only", order_text, price, []),
            } if price is not None else None

        if not candidates:
            return None

        offers = []
        exact_candidates = [candidate for candidate in candidates if candidate.get("intent_match")]
        for candidate in (exact_candidates or candidates)[:6]:
            try:
                clicked = await self._click_xianyu_option(page, candidate)
                if not clicked:
                    continue
                await AntiDetect.random_delay(0.7, 1.2)

                option_price = candidate.get("option_price")
                price = option_price if option_price is not None else await self._extract_xianyu_order_price(page)
                if price is None:
                    continue
                offers.append({
                    "price": float(price),
                    "spec_text": candidate.get("text", ""),
                    "spec_capture_mode": "options_detected",
                    "spec_capture_info": self._format_spec_capture_info(
                        "options_detected",
                        candidate.get("text", ""),
                        price,
                        spec_state.get("options", []),
                    ),
                })
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
                const isSoldOut = (el, text) => {
                    const classText = `${el.className || ''} ${el.getAttribute('aria-disabled') || ''} ${el.getAttribute('disabled') || ''}`.toLowerCase();
                    return Boolean(
                        el.hasAttribute('disabled') ||
                        el.getAttribute('disabled') === 'true' ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        /disabled|soldout|sold-out|empty|invalid|forbid/.test(classText) ||
                        /(?:\u65e0\u5e93\u5b58|\u552e\u7f44|\u5df2\u552e\u7f44|\u6682\u65e0\u5e93\u5b58)/.test(text)
                    );
                };
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
                    const optionSoldOut = isSoldOut(clickEl, text || rawText);

                    if (optionLooksClickable && optionTextHasSpec && !optionLooksLikeContainer && !optionSeen.has(key)) {
                        optionSeen.add(key);
                        optionTexts.push({
                            text: text || rawText,
                            option_price: parsePrice(text || rawText),
                            kinds: optionSpecKinds,
                            intent_match: optionTextMatchesIntent,
                            sold_out: optionSoldOut,
                        });
                    }

                    if (!key || seen.has(key)) return;
                    if (rejectedShellText(key) && !hasSpecToken(key)) return;
                    if (!optionLooksClickable || !optionTextHasSpec || optionLooksLikeContainer) return;
                    seen.add(key);
                    const index = elements.length;
                    const token = `price-monitor-sku-${index}`;
                    clickEl.setAttribute('data-price-monitor-sku-token', token);
                    elements.push(clickEl);
                    candidates.push({
                        index,
                        token,
                        text: text || rawText,
                        option_price: parsePrice(text || rawText),
                        score: scoreSpec(text || rawText, clickEl),
                        kinds: optionSpecKinds,
                        intent_match: optionTextMatchesIntent,
                        sold_out: optionSoldOut,
                    });
                });

                candidates.sort((a, b) => b.score - a.score);
                window.__priceMonitorSkuCandidates = elements;
                const orderText = clean(document.body.innerText || '');
                return {has_options: optionTexts.length >= 2, options: optionTexts, candidates, order_text: orderText};
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

    async def _extract_xianyu_order_item_text(self, page: Page) -> str:
        value = await page.evaluate(
            r"""
            () => {
                const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                const lines = clean(document.body.innerText || '')
                    .split(/(?<=\S)\s+(?=\S)/)
                    .map(clean)
                    .filter(Boolean);
                const matched = lines.find((line) =>
                    /适趣/i.test(line) && /(?:7天|7日|7day|7days)/i.test(line)
                );
                if (matched) return matched;
                return lines.find((line) => /适趣/i.test(line)) || '';
            }
            """
        )
        return str(value or "")

    def _looks_like_cn_7d_delist_order(self, text: str, price: float) -> bool:
        normalized = (text or "").lower().replace(" ", "")
        return (
            abs(float(price) - 3.9) < 0.01
            and "适趣" in normalized
            and "中文" in normalized
            and any(token in normalized for token in ("7天", "7日", "7day", "7days"))
        )

    def _looks_like_english_order_text(self, text: str) -> bool:
        normalized = (text or "").lower().replace(" ", "")
        return (
            "适趣" in normalized
            and any(token in normalized for token in ("英语", "英文", "english"))
        )

    async def _save_order_debug_snapshot(self, page: Page) -> Path:
        output_dir = Path("data/debug")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = output_dir / f"{timestamp}_{self.PLATFORM}_order"
        await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        base.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
        return base.with_suffix(".png")
