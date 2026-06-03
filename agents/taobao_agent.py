import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from playwright.async_api import Page
from agents.base_agent import BaseAgent
from core.anti_detect import AntiDetect


class TaobaoAgent(BaseAgent):
    PLATFORM = "taobao"

    def _format_price_text(self, price: Optional[float]) -> str:
        if price is None:
            return ""
        return f"{float(price):g}"

    def _should_skip_ignored_list_price(self, list_price: float) -> bool:
        return False

    def _should_open_detail_by_list_price(self, list_price: float, official_price: float) -> bool:
        if list_price <= 0:
            return True
        if self.price_judge.is_below_official(list_price, official_price):
            return True
        return list_price <= official_price + 50

    async def _do_search(self, page: Page, keyword: str):
        self._last_search_keyword = keyword
        search_url = self._build_taobao_search_url(keyword)
        print(f"[{self.PLATFORM}] goto search URL: {search_url}", flush=True)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        if not await self._ensure_taobao_search_results(page, keyword):
            debug_path = await self._save_sort_debug_snapshot(page)
            raise RuntimeError(f"[{self.PLATFORM}] did not reach search results page, debug saved: {debug_path}")
        await self._wait_if_verification(page, "before taobao price sort")
        await self._anti_risk_delay("search_delay_seconds", "after search")
        await self._wait_if_verification(page, "after search delay before taobao price sort")
        sorted_ok = await self._click_price_asc_sort(page)
        print(f"[{self.PLATFORM}] price ascending sort: {'clicked' if sorted_ok else 'not found'}", flush=True)
        await self._anti_risk_delay("sort_delay_seconds", "after sort")
        await AntiDetect.human_scroll(page, times=random.randint(2, 3))

    def _build_taobao_search_url(self, keyword: str) -> str:
        params = {
            "commend": "all",
            "ie": "utf8",
            "initiative_id": "tbindexz_20170306",
            "page": "1",
            "q": keyword,
            "search_type": "item",
            "sourceId": "tb.index",
            "tab": "all",
        }
        return "https://s.taobao.com/search?" + urlencode(params)

    async def _click_price_asc_sort(self, page: Page) -> bool:
        if await self._is_price_asc_sort_selected(page):
            return True

        if await self._is_taobao_low_to_high_menu_open(page) and await self._click_taobao_low_to_high_option(page):
            return True

        for _ in range(3):
            if await self._click_taobao_next_price_tab(page):
                if await self._click_taobao_low_to_high_option(page):
                    return True
            await AntiDetect.random_delay(0.3, 0.6)

        if await self._click_taobao_low_to_high_menu(page):
            return True

        for click_price in (
            self._click_taobao_price_by_sort_bar_position,
            self._click_taobao_price_sort_button,
            self._click_taobao_price_dropdown,
        ):
            if await click_price(page):
                await AntiDetect.random_delay(0.3, 0.6)
                if await self._click_taobao_low_to_high_option(page):
                    return True
                if await self._press_taobao_low_to_high_option(page):
                    return True

        if await self._is_price_asc_sort_selected(page):
            return True

        debug_path = await self._save_sort_debug_snapshot(page)
        print(f"[{self.PLATFORM}] price ascending sort failed, debug saved: {debug_path}", flush=True)
        return False

    async def _click_taobao_next_price_tab(self, page: Page) -> bool:
        try:
            target = await page.evaluate(
                """
                () => {
                    const norm = (text) => (text || '').replace(/\\s+/g, '').trim();
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' &&
                            style.display !== 'none' &&
                            Number(style.opacity || 1) > 0;
                    };
                    const inner = Array.from(document.querySelectorAll('.next-tabs-tab-inner'))
                        .find((el) => visible(el) && norm(el.innerText || el.textContent || '') === '价格');
                    if (!inner) return null;
                    const clickable = inner.closest([
                        '.next-tabs-tab',
                        '[role="tab"]',
                        'li',
                        'button',
                        'a',
                        '[role="button"]',
                        '[tabindex]'
                    ].join(',')) || inner;
                    if (!visible(clickable)) return null;
                    clickable.scrollIntoView({block: 'center', inline: 'center'});
                    const rect = clickable.getBoundingClientRect();
                    const innerRect = inner.getBoundingClientRect();
                    for (const el of [clickable, inner]) {
                        for (const type of ['pointerenter', 'mouseenter', 'mouseover', 'mousemove']) {
                            el.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
                        }
                    }
                    return {
                        points: [
                            {x: innerRect.left + innerRect.width / 2, y: innerRect.top + innerRect.height / 2, label: 'inner-center'},
                            {x: rect.right - Math.min(14, Math.max(6, rect.width / 5)), y: rect.top + rect.height / 2, label: 'tab-right'},
                            {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, label: 'tab-center'}
                        ]
                    };
                }
                """
            )
            if not target:
                return False
            for point in target.get("points", []):
                await page.mouse.move(point["x"], point["y"])
                await AntiDetect.random_delay(0.1, 0.2)
                await page.mouse.click(point["x"], point["y"])
                await AntiDetect.random_delay(0.3, 0.5)
                if await self._is_taobao_low_to_high_menu_open(page):
                    print(f"[{self.PLATFORM}] clicked taobao next price tab ({point['label']}): menu opened", flush=True)
                    return True
            print(f"[{self.PLATFORM}] clicked taobao next price tab: menu not open", flush=True)
            return False
        except Exception as exc:
            print(f"[{self.PLATFORM}] taobao next price tab click failed: {exc}", flush=True)
            return False

    async def _is_taobao_low_to_high_menu_open(self, page: Page) -> bool:
        try:
            return await page.evaluate(
                """
                () => {
                    const norm = (text) => (text || '').replace(/\\s+/g, '').trim();
                    const openedOverlay = Array.from(document.querySelectorAll('.next-overlay-wrapper.opened, .next-overlay-wrapper.v2.opened'))
                        .some((el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 &&
                                rect.height > 0 &&
                                style.visibility !== 'hidden' &&
                                style.display !== 'none' &&
                                norm(el.innerText || el.textContent || '').includes('从低到高');
                        });
                    if (openedOverlay) return true;

                    const visibleElement = (el) => {
                        for (let cur = el; cur; cur = cur.parentElement) {
                            const rect = cur.getBoundingClientRect();
                            const style = window.getComputedStyle(cur);
                            if (rect.width <= 0 || rect.height <= 0) return false;
                            if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity || 1) <= 0) return false;
                        }
                        return true;
                    };
                    const visibleRect = (rect) =>
                        rect.width > 0 &&
                        rect.height > 0 &&
                        rect.bottom >= 0 &&
                        rect.right >= 0 &&
                        rect.top <= (window.innerHeight || document.documentElement.clientHeight || 0) &&
                        rect.left <= (window.innerWidth || document.documentElement.clientWidth || 0);
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) {
                        const node = walker.currentNode;
                        if (norm(node.textContent || '') !== '从低到高') continue;
                        if (!visibleElement(node.parentElement)) continue;
                        const range = document.createRange();
                        range.selectNodeContents(node);
                        const rects = Array.from(range.getClientRects()).filter(visibleRect);
                        range.detach();
                        if (rects.some((rect) => rect.top >= 80 && rect.top <= 500)) return true;
                    }
                    return false;
                }
                """
            )
        except Exception:
            return False

    async def _click_taobao_low_to_high_menu(self, page: Page) -> bool:
        if await self._click_taobao_visible_text_node(
            page,
            ["\u4ef7\u683c"],
            top_range=(120, 380),
            left_range=(0, 700),
        ):
            await AntiDetect.random_delay(0.3, 0.6)
            if await self._is_taobao_low_to_high_menu_open(page) and await self._click_taobao_visible_text_node(
                page,
                ["\u4ece\u4f4e\u5230\u9ad8"],
                top_range=(80, 420),
            ):
                await self._wait_after_sort_click(page)
                return True

        if await self._is_taobao_low_to_high_menu_open(page) and await self._click_taobao_visible_text_node(
            page,
            ["\u4ece\u4f4e\u5230\u9ad8"],
            top_range=(80, 420),
        ):
            await self._wait_after_sort_click(page)
            return True

        if await self._is_taobao_low_to_high_menu_open(page) and await self._click_visible_taobao_text(page, ["\u4ece\u4f4e\u5230\u9ad8"]):
            await self._wait_after_sort_click(page)
            return True

        if not await self._click_visible_taobao_text(
            page,
            ["\u4ef7\u683c", "\u4ef7\u683c^", "\u4ef7\u683c\u2303"],
        ):
            return False

        await AntiDetect.random_delay(0.3, 0.6)
        if await self._is_taobao_low_to_high_menu_open(page) and await self._click_visible_taobao_text(page, ["\u4ece\u4f4e\u5230\u9ad8"]):
            await self._wait_after_sort_click(page)
            return True
        return False

    async def _click_taobao_visible_text_node(
        self,
        page: Page,
        labels: list,
        top_range: tuple = (0, 9999),
        left_range: tuple = (0, 9999),
    ) -> bool:
        try:
            target = await page.evaluate(
                """
                ({labels, topRange, leftRange}) => {
                    const norm = (text) => (text || '').replace(/\\s+/g, '').trim();
                    const wanted = labels.map(norm);
                    const visibleRect = (rect) =>
                        rect.width > 0 &&
                        rect.height > 0 &&
                        rect.bottom >= 0 &&
                        rect.right >= 0 &&
                        rect.top <= (window.innerHeight || document.documentElement.clientHeight || 0) &&
                        rect.left <= (window.innerWidth || document.documentElement.clientWidth || 0);
                    const visibleElement = (el) => {
                        if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
                        for (let cur = el; cur; cur = cur.parentElement) {
                            const rect = cur.getBoundingClientRect();
                            const style = window.getComputedStyle(cur);
                            if (rect.width <= 0 || rect.height <= 0) return false;
                            if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity || 1) <= 0) {
                                return false;
                            }
                        }
                        return true;
                    };
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        {
                            acceptNode(node) {
                                const text = norm(node.textContent || '');
                                if (!wanted.includes(text)) return NodeFilter.FILTER_REJECT;
                                const parent = node.parentElement;
                                if (!visibleElement(parent)) return NodeFilter.FILTER_REJECT;
                                return NodeFilter.FILTER_ACCEPT;
                            }
                        }
                    );
                    const candidates = [];
                    while (walker.nextNode()) {
                        const node = walker.currentNode;
                        const range = document.createRange();
                        range.selectNodeContents(node);
                        const rects = Array.from(range.getClientRects()).filter(visibleRect);
                        range.detach();
                        for (const rect of rects) {
                            if (rect.top < topRange[0] || rect.top > topRange[1]) continue;
                            if (rect.left < leftRange[0] || rect.left > leftRange[1]) continue;
                            const parent = node.parentElement;
                            const clickable = parent.closest('button, a, [role="button"], li, [tabindex]') || parent;
                            const clickRect = clickable.getBoundingClientRect();
                            const useRect = visibleRect(clickRect) ? clickRect : rect;
                            const x = useRect.left + useRect.width / 2;
                            const y = useRect.top + useRect.height / 2;
                            const hit = document.elementFromPoint(x, y);
                            if (hit && clickable !== hit && !clickable.contains(hit) && !hit.contains(parent)) continue;
                            candidates.push({
                                x,
                                y,
                                top: rect.top,
                                left: rect.left,
                                text: norm(node.textContent || ''),
                            });
                        }
                    }
                    candidates.sort((a, b) => a.top - b.top || a.left - b.left);
                    return candidates[0] || null;
                }
                """,
                {
                    "labels": labels,
                    "topRange": list(top_range),
                    "leftRange": list(left_range),
                },
            )
            if not target:
                return False
            await page.mouse.move(target["x"], target["y"])
            await page.mouse.click(target["x"], target["y"])
            print(f"[{self.PLATFORM}] clicked sort text node: {target['text']}", flush=True)
            return True
        except Exception as exc:
            print(f"[{self.PLATFORM}] sort text node click failed: {exc}", flush=True)
            return False

    async def _click_visible_taobao_text(self, page: Page, labels: list) -> bool:
        try:
            target = await page.evaluate(
                """
                (labels) => {
                    const norm = (text) => (text || '').replace(/\\s+/g, '');
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' &&
                            style.display !== 'none' &&
                            Number(style.opacity || 1) > 0;
                    };
                    const exact = labels.map(norm);
                    const selector = 'button, a, div, span, li, [role="button"], [tabindex]';
                    const candidates = Array.from(document.querySelectorAll(selector))
                        .filter(visible)
                        .map((el) => {
                            const text = norm(el.innerText || el.textContent || '');
                            if (!exact.includes(text)) return null;
                            const clickable = el.closest('button, a, [role="button"], li, [tabindex]') || el;
                            if (!visible(clickable)) return null;
                            const rect = clickable.getBoundingClientRect();
                            return {
                                x: rect.left + rect.width / 2,
                                y: rect.top + rect.height / 2,
                                top: rect.top,
                                left: rect.left,
                                text,
                            };
                        })
                        .filter(Boolean)
                        .sort((a, b) => a.top - b.top || a.left - b.left);
                    return candidates[0] || null;
                }
                """,
                labels,
            )
            if not target:
                return False
            await page.mouse.move(target["x"], target["y"])
            await page.mouse.click(target["x"], target["y"])
            print(f"[{self.PLATFORM}] clicked visible sort text: {target['text']}", flush=True)
            return True
        except Exception as exc:
            print(f"[{self.PLATFORM}] visible sort text click failed: {exc}", flush=True)
            return False

    async def _click_taobao_price_by_sort_bar_position(self, page: Page) -> bool:
        try:
            target = await page.evaluate(
                """
                () => {
                    const norm = (text) => (text || '').replace(/\\s+/g, '').trim();
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' &&
                            style.display !== 'none' &&
                            Number(style.opacity || 1) > 0;
                    };
                    const elements = Array.from(document.querySelectorAll('body *')).filter(visible);
                    const sortBar = elements
                        .map((el) => {
                            const text = norm(el.innerText || el.textContent || '');
                            const rect = el.getBoundingClientRect();
                            const hasSortTexts = text.includes('综合') && text.includes('销量') && text.includes('价格');
                            if (!hasSortTexts || rect.top < 120 || rect.top > 360 || rect.width < 180 || rect.height > 120) {
                                return null;
                            }
                            return {el, rect, text};
                        })
                        .filter(Boolean)
                        .sort((a, b) => (a.rect.height - b.rect.height) || (a.rect.width - b.rect.width))[0];
                    if (!sortBar) return null;

                    const children = Array.from(sortBar.el.querySelectorAll('*'))
                        .filter(visible)
                        .map((el) => {
                            const text = norm(el.innerText || el.textContent || '');
                            const rect = el.getBoundingClientRect();
                            return {el, text, rect};
                        })
                        .filter((item) => item.text === '价格' || item.text === '价格^' || item.text === '价格⌃')
                        .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
                    let target = children[0]?.el;

                    if (!target) {
                        const rect = sortBar.rect;
                        return {
                            x: rect.left + Math.min(Math.max(rect.width * 0.58, 170), rect.width - 30),
                            y: rect.top + rect.height / 2,
                        };
                    }

                    target = target.closest('button, a, [role="button"], li, [tabindex]') || target;
                    const rect = target.getBoundingClientRect();
                    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
                }
                """
            )
            if not target:
                return False
            await page.mouse.move(target["x"], target["y"])
            await page.mouse.click(target["x"], target["y"])
            print(f"[{self.PLATFORM}] clicked price sort by sort bar position", flush=True)
            return True
        except Exception as exc:
            print(f"[{self.PLATFORM}] price sort bar position click failed: {exc}", flush=True)
            return False

    async def _ensure_taobao_search_results(self, page: Page, keyword: str) -> bool:
        if await self._is_taobao_search_results_page(page):
            return True

        search_url = self._build_taobao_search_url(keyword)
        print(f"[{self.PLATFORM}] current page is not search results, goto search URL: {search_url}", flush=True)
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            print(f"[{self.PLATFORM}] search URL navigation failed: {exc}", flush=True)
            return False

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await AntiDetect.random_delay(1, 2)
        return await self._is_taobao_search_results_page(page)

    async def _is_taobao_search_results_page(self, page: Page) -> bool:
        try:
            return await page.evaluate(
                """
                () => {
                    const host = location.hostname || '';
                    const path = location.pathname || '';
                    if (!host.includes('s.taobao.com') || !path.includes('/search')) return false;

                    const norm = (text) => (text || '').replace(/\\s+/g, '').trim();
                    const bodyText = norm(document.body?.innerText || '');
                    if (!(bodyText.includes('综合') && bodyText.includes('销量') && bodyText.includes('价格'))) {
                        return false;
                    }

                    const hasSearchCards = Array.from(document.querySelectorAll('a[href*="item.taobao.com"], a[href*="detail.tmall.com"]'))
                        .some((el) => {
                            const rect = el.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0;
                        });
                    return hasSearchCards;
                }
                """
            )
        except Exception:
            return False

    async def _is_price_asc_sort_selected(self, page: Page) -> bool:
        if not await self._is_taobao_search_results_page(page):
            return False
        try:
            return await page.evaluate(
                """
                (labels) => {
                    const text = (document.body.innerText || '').replace(/\\s+/g, '');
                    const priceButton = Array.from(document.querySelectorAll('button, a, div, span'))
                        .find((el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility === 'hidden') return false;
                            const value = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
                            return value.includes(labels.price) && value.includes(labels.lowToHigh);
                        });
                    return Boolean(priceButton || text.includes(labels.price + labels.lowToHigh));
                }
                """,
                {"price": "\u4ef7\u683c", "lowToHigh": "\u4ece\u4f4e\u5230\u9ad8"},
            )
        except Exception:
            return False

    async def _click_taobao_price_sort_button(self, page: Page) -> bool:
        try:
            target = await page.evaluate(
                """
                () => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const norm = (text) => (text || '').replace(/\\s+/g, '');
                    const candidates = Array.from(document.querySelectorAll('button, a, div, span, li, [role="button"]'))
                        .filter(visible)
                        .map((el) => {
                            const text = norm(el.innerText || el.textContent || '');
                            const label = norm([
                                el.getAttribute('aria-label') || '',
                                el.getAttribute('title') || '',
                            ].join(' '));
                            const combined = `${text}${label}`;
                            if (!combined.includes('价格')) return null;
                            const clickable = el.closest('button, a, [role="button"], li, [tabindex]') || el;
                            if (!visible(clickable)) return null;
                            const rect = clickable.getBoundingClientRect();
                            let score = 0;
                            if (/价格(从低到高|由低到高|升序|低价优先)/.test(combined)) score += 160;
                            if (/升序|up|asc/i.test(combined)) score += 80;
                            if (/降序|从高到低|由高到低|down|desc/i.test(combined)) score -= 120;
                            if (rect.top >= 60 && rect.top < 220) score += 30;
                            if (rect.left >= 80 && rect.left < 520) score += 20;
                            if (text.length > 16) score -= 40;
                            return {target: clickable, score};
                        })
                        .filter(Boolean)
                        .filter((item) => item.score > 0)
                        .sort((a, b) => b.score - a.score);
                    const target = candidates[0]?.target;
                    if (!target) return null;
                    target.scrollIntoView({block: 'center', inline: 'center'});
                    const rect = target.getBoundingClientRect();
                    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
                }
                """
            )
            if not target:
                return False
            await page.mouse.move(target["x"], target["y"])
            await page.mouse.click(target["x"], target["y"])
            return True
        except Exception:
            return False

    async def _click_taobao_price_dropdown(self, page: Page) -> bool:
        try:
            target = await page.evaluate(
                """
                (priceText) => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const clickable = (el) => el.closest('button, a, [role="button"], li, [tabindex]') || el;
                    const candidates = Array.from(document.querySelectorAll('button, a, div, span, li, [role="button"]'))
                        .filter(visible)
                        .map((el) => {
                            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
                            const target = clickable(el);
                            if (!visible(target)) return null;
                            const rect = el.getBoundingClientRect();
                            const targetRect = target.getBoundingClientRect();
                            let score = 0;
                            if (text === priceText || text === `${priceText}^` || text === `${priceText}⌃`) score += 120;
                            if (text.startsWith(priceText)) score += 70;
                            if (text.includes(priceText)) score += 40;
                            if (/(综合|销量|区间|天猫|淘宝|店铺|企业购)/.test(text)) score -= 40;
                            if (targetRect.top >= 60 && targetRect.top < 180) score += 40;
                            if (rect.left > 100 && rect.left < 420) score += 20;
                            if (targetRect.width >= 60 && targetRect.width <= 140) score += 20;
                            if (text.length > 12) score -= 50;
                            return {el: target, score};
                        })
                        .filter(Boolean)
                        .filter((item) => item.score > 0)
                        .sort((a, b) => b.score - a.score);
                    const target = candidates[0]?.el;
                    if (!target) return null;
                    target.scrollIntoView({block: 'center', inline: 'center'});
                    const rect = target.getBoundingClientRect();
                    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
                }
                """,
                "\u4ef7\u683c",
            )
            if target:
                await page.mouse.move(target["x"], target["y"])
                await page.mouse.click(target["x"], target["y"])
                return True
        except Exception:
            pass

        try:
            locator = page.get_by_text("\u4ef7\u683c", exact=False).first
            if await locator.count() == 0:
                return False
            await locator.click(timeout=3000)
            return True
        except Exception:
            return False

    async def _click_taobao_low_to_high_option(self, page: Page) -> bool:
        if not await self._is_taobao_low_to_high_menu_open(page):
            return False

        if await self._click_taobao_low_to_high_menu_item(page):
            await self._wait_after_sort_click(page)
            return True

        if await self._click_taobao_visible_text_node(
            page,
            ["\u4ece\u4f4e\u5230\u9ad8"],
            top_range=(80, 500),
        ):
            await self._wait_after_sort_click(page)
            return True

        labels = [
            "\u4ece\u4f4e\u5230\u9ad8",
            "\u4ef7\u683c\u4ece\u4f4e\u5230\u9ad8",
            "\u4f4e\u4ef7\u4f18\u5148",
            "\u4ef7\u683c\u5347\u5e8f",
        ]
        try:
            clicked = await page.evaluate(
                """
                (labels) => {
                    const norm = (text) => (text || '').replace(/\\s+/g, '');
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const clickable = (el) => el.closest('button, a, [role="button"], li, [tabindex]') || el;
                    const candidates = Array.from(document.querySelectorAll('button, a, div, span, li, [role="button"]'))
                        .filter(visible)
                        .map((el) => {
                            const text = norm(el.innerText || el.textContent || '');
                            const matched = labels.some((label) => text.includes(norm(label)));
                            if (!matched) return null;
                            const target = clickable(el);
                            if (!visible(target)) return null;
                            const rect = target.getBoundingClientRect();
                            let score = 0;
                            if (text === norm(labels[0])) score += 140;
                            if (text.includes(norm(labels[0]))) score += 100;
                            if (rect.top >= 80 && rect.top < 260) score += 30;
                            if (rect.left >= 160 && rect.left < 330) score += 20;
                            score -= Math.max(0, text.length - 8) * 2;
                            return {target, score};
                        })
                        .filter(Boolean)
                        .sort((a, b) => b.score - a.score);
                    const target = candidates[0]?.target;
                    if (!target) return false;
                    target.scrollIntoView({block: 'center', inline: 'center'});
                    for (const type of ['mousedown', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
                    }
                    return true;
                }
                """,
                labels,
            )
            if clicked:
                await self._wait_after_sort_click(page)
                return True
        except Exception:
            pass
        for label in labels:
            try:
                locator = page.get_by_text(label, exact=False).first
                if await locator.count() == 0:
                    continue
                await locator.click(timeout=3000)
                await self._wait_after_sort_click(page)
                return True
            except Exception:
                continue
        return False

    async def _click_taobao_low_to_high_menu_item(self, page: Page) -> bool:
        try:
            target = await page.evaluate(
                """
                () => {
                    const norm = (text) => (text || '').replace(/\\s+/g, '').trim();
                    const visible = (el) => {
                        if (!el) return false;
                        for (let cur = el; cur; cur = cur.parentElement) {
                            const rect = cur.getBoundingClientRect();
                            const style = window.getComputedStyle(cur);
                            if (rect.width <= 0 || rect.height <= 0) return false;
                            if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity || 1) <= 0) return false;
                        }
                        return true;
                    };
                    const visibleRect = (rect) =>
                        rect.width > 0 &&
                        rect.height > 0 &&
                        rect.bottom >= 0 &&
                        rect.right >= 0 &&
                        rect.top <= (window.innerHeight || document.documentElement.clientHeight || 0) &&
                        rect.left <= (window.innerWidth || document.documentElement.clientWidth || 0);

                    const openedOverlays = Array.from(document.querySelectorAll('.next-overlay-wrapper.opened, .next-overlay-wrapper.v2.opened'))
                        .filter(visible)
                        .filter((el) => norm(el.innerText || el.textContent || '').includes('从低到高'));
                    for (const overlay of openedOverlays) {
                        const overlayCandidates = Array.from(overlay.querySelectorAll([
                            '.next-menu-item',
                            '[role="option"]',
                            '[role="menuitem"]',
                            'li',
                            'button',
                            'a',
                            '[tabindex]',
                            'div'
                        ].join(',')))
                            .filter(visible)
                            .map((el) => {
                                const text = norm(el.innerText || el.textContent || '');
                                if (text !== '从低到高') return null;
                                const rect = el.getBoundingClientRect();
                                if (!visibleRect(rect)) return null;
                                const cls = String(el.className || '');
                                let score = 100;
                                if (/next-menu-item/.test(cls)) score += 80;
                                if (el.getAttribute('role') === 'option' || el.getAttribute('role') === 'menuitem') score += 60;
                                if (el.tagName === 'LI') score += 40;
                                score -= Math.max(0, rect.width * rect.height - 12000) / 1000;
                                return {el, rect, score};
                            })
                            .filter(Boolean)
                            .sort((a, b) => b.score - a.score || a.rect.top - b.rect.top || a.rect.left - b.rect.left);
                        const overlayTarget = overlayCandidates[0]?.el;
                        if (overlayTarget) {
                            overlayTarget.scrollIntoView({block: 'center', inline: 'center'});
                            const rect = overlayTarget.getBoundingClientRect();
                            return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, source: 'opened-overlay'};
                        }

                        const walker = document.createTreeWalker(overlay, NodeFilter.SHOW_TEXT);
                        while (walker.nextNode()) {
                            const node = walker.currentNode;
                            if (norm(node.textContent || '') !== '从低到高') continue;
                            if (!visible(node.parentElement)) continue;
                            const item = node.parentElement.closest([
                                '.next-menu-item',
                                '[role="option"]',
                                '[role="menuitem"]',
                                'li',
                                'button',
                                'a',
                                '[tabindex]',
                                'div'
                            ].join(',')) || node.parentElement;
                            if (!visible(item)) continue;
                            const rect = item.getBoundingClientRect();
                            if (!visibleRect(rect)) continue;
                            return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, source: 'opened-overlay-text'};
                        }
                    }

                    const menuSelectors = [
                        '.next-menu-item',
                        '.next-overlay-wrapper [role="option"]',
                        '.next-overlay-wrapper [role="menuitem"]',
                        '.next-overlay-wrapper li',
                        '.next-overlay-wrapper div',
                        '[class*="menu"] [role="option"]',
                        '[class*="menu"] [role="menuitem"]',
                        '[class*="menu"] li',
                        '[class*="popup"] div',
                        '[class*="overlay"] div'
                    ].join(',');
                    const elementCandidates = Array.from(document.querySelectorAll(menuSelectors))
                        .filter(visible)
                        .map((el) => {
                            const text = norm(el.innerText || el.textContent || '');
                            if (text !== '从低到高' && !/^从低到高$/.test(text)) return null;
                            const rect = el.getBoundingClientRect();
                            if (!visibleRect(rect) || rect.top < 80 || rect.top > 520) return null;
                            return {el, rect, score: text === '从低到高' ? 100 : 50};
                        })
                        .filter(Boolean);

                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    const textCandidates = [];
                    while (walker.nextNode()) {
                        const node = walker.currentNode;
                        if (norm(node.textContent || '') !== '从低到高') continue;
                        if (!visible(node.parentElement)) continue;
                        const range = document.createRange();
                        range.selectNodeContents(node);
                        const rects = Array.from(range.getClientRects()).filter(visibleRect);
                        range.detach();
                        for (const rect of rects) {
                            if (rect.top < 80 || rect.top > 520) continue;
                            const parent = node.parentElement;
                            const el = parent.closest([
                                '.next-menu-item',
                                '[role="option"]',
                                '[role="menuitem"]',
                                'li',
                                'button',
                                'a',
                                '[role="button"]',
                                '[tabindex]'
                            ].join(',')) || parent;
                            if (!visible(el)) continue;
                            textCandidates.push({el, rect: el.getBoundingClientRect(), score: 120});
                        }
                    }

                    const candidates = elementCandidates.concat(textCandidates)
                        .sort((a, b) => b.score - a.score || a.rect.top - b.rect.top || a.rect.left - b.rect.left);
                    const target = candidates[0]?.el;
                    if (!target) return null;
                    target.scrollIntoView({block: 'center', inline: 'center'});
                    const rect = target.getBoundingClientRect();
                    for (const type of ['pointerover', 'mouseover', 'mouseenter', 'mousemove', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
                    }
                    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, source: 'fallback'};
                }
                """
            )
            if not target:
                return False
            await page.mouse.move(target["x"], target["y"])
            await page.mouse.click(target["x"], target["y"])
            print(f"[{self.PLATFORM}] clicked low-to-high menu item ({target.get('source', '')})", flush=True)
            return True
        except Exception as exc:
            print(f"[{self.PLATFORM}] low-to-high menu item click failed: {exc}", flush=True)
            return False

    async def _press_taobao_low_to_high_option(self, page: Page) -> bool:
        try:
            await page.keyboard.press("ArrowDown")
            await AntiDetect.random_delay(0.2, 0.4)
            await page.keyboard.press("Enter")
            await self._wait_after_sort_click(page)
            return await self._is_price_asc_sort_selected(page)
        except Exception:
            return False

    async def _wait_after_sort_click(self, page: Page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await AntiDetect.random_delay(1, 2)

    async def _save_sort_debug_snapshot(self, page: Page) -> Path:
        output_dir = Path("data/debug")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = output_dir / f"{timestamp}_{self.PLATFORM}_sort"
        try:
            await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        except Exception:
            pass
        try:
            base.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
        except Exception:
            pass
        return base.with_suffix(".png")

    async def _goto_next_results_page(self, page: Page) -> bool:
        try:
            current_state = await page.evaluate(
                """
                () => ({
                    firstUrl: Array.from(document.querySelectorAll('a[href*="item"]'))
                        .map((el) => el.href || '')
                        .find(Boolean) || '',
                    pageText: Array.from(document.querySelectorAll('body *'))
                        .map((el) => (el.textContent || '').trim())
                        .find((text) => /^\\d+\\s*\\/\\s*\\d+$/.test(text)) || '',
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
                    const buttons = Array.from(document.querySelectorAll('button, a, span, div'))
                        .filter(visible);
                    const target = buttons.find((el) => {
                        const text = (el.textContent || '').replace(/\\s+/g, '');
                        const label = [
                            el.getAttribute('aria-label') || '',
                            el.getAttribute('title') || '',
                            el.className || '',
                        ].join(' ');
                        return text === '>' || /下一页|next|arrow.*right|right.*arrow/i.test(label);
                    });
                    if (!target) return null;
                    target.scrollIntoView({block: 'center', inline: 'center'});
                    const rect = target.getBoundingClientRect();
                    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
                }
                """
            )
            if not target:
                return False
            await page.mouse.move(target["x"], target["y"])
            await page.mouse.click(target["x"], target["y"])
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await AntiDetect.random_delay(1, 2)
            next_state = await page.evaluate(
                """
                () => ({
                    firstUrl: Array.from(document.querySelectorAll('a[href*="item"]'))
                        .map((el) => el.href || '')
                        .find(Boolean) || '',
                    pageText: Array.from(document.querySelectorAll('body *'))
                        .map((el) => (el.textContent || '').trim())
                        .find((text) => /^\\d+\\s*\\/\\s*\\d+$/.test(text)) || '',
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
                    next_state.get("pageText")
                    and next_state.get("pageText") != current_state.get("pageText")
                )
            )
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
            await AntiDetect.random_delay(2, 3)
            await self._wait_for_verification_appearance(detail_page, "after detail open")
            offer = await self._select_matching_order_offer(detail_page, keyword)
            if offer is None:
                debug_path = await self._save_order_debug_snapshot(detail_page)
                print(f"[{self.PLATFORM}] matching detail spec/price not found, debug saved: {debug_path}", flush=True)
            return offer
        except Exception as exc:
            print(f"[{self.PLATFORM}] failed to fetch detail price: {exc}", flush=True)
            return None
        finally:
            await detail_page.close()

    async def _select_matching_order_offer(self, page: Page, keyword: str) -> Optional[Dict[str, Any]]:
        intent = self._search_intent(keyword)
        spec_state = await self._collect_taobao_detail_options(page, intent)
        options = spec_state.get("options", [])
        candidates = spec_state.get("candidates", [])
        detail_text = spec_state.get("detail_text", "")

        delist_candidate = next(
            (
                candidate
                for candidate in options
                if "7d" in candidate.get("kinds", []) and not candidate.get("sold_out")
            ),
            None,
        )
        if delist_candidate:
            price = await self._resolve_taobao_detail_price(page, delist_candidate)
            return {
                "price": float(price or 0),
                "spec_text": delist_candidate.get("text", ""),
                "spec_capture_mode": "detail_options_detected",
                "spec_capture_info": self._format_spec_capture_info(options, price),
                "force_decision": "DELIST",
            }

        en_15d_delist_candidate = next(
            (
                candidate
                for candidate in options
                if "15d" in candidate.get("kinds", [])
                and not candidate.get("sold_out")
                and self._looks_like_english_detail_text(
                    " ".join([candidate.get("text", ""), detail_text])
                )
            ),
            None,
        )
        if en_15d_delist_candidate:
            price = await self._resolve_taobao_detail_price(page, en_15d_delist_candidate)
            spec_text = " ".join([en_15d_delist_candidate.get("text", ""), detail_text]).strip()
            return {
                "price": float(price or 0),
                "spec_text": spec_text,
                "spec_capture_mode": "detail_options_detected",
                "spec_capture_info": self._format_spec_capture_info(options, price),
                "force_decision": "DELIST",
            }

        if candidates:
            offers = []
            exact_candidates = [candidate for candidate in candidates if candidate.get("intent_match")]
            for candidate in (exact_candidates or candidates)[:6]:
                if candidate.get("sold_out"):
                    continue
                price = await self._resolve_taobao_detail_price(page, candidate)
                if price is None:
                    continue
                offers.append({
                    "price": float(price),
                    "spec_text": candidate.get("text", ""),
                    "spec_capture_mode": "detail_options_detected",
                    "spec_capture_info": self._format_spec_capture_info(options, price),
                })
            if offers:
                return min(offers, key=lambda offer: offer["price"])

        price = await self._extract_taobao_detail_price(page)
        detail_item_text = await self._extract_taobao_detail_item_text(page)
        if price is not None and self._looks_like_cn_7d_delist_detail(detail_item_text, price):
            return {
                "price": float(price),
                "spec_text": detail_item_text,
                "spec_capture_mode": "detail_text_only",
                "spec_capture_info": self._format_spec_capture_info([], price),
                "force_decision": "DELIST",
            }
        return {
            "price": float(price),
            "spec_text": detail_item_text,
            "spec_capture_mode": "detail_text_only",
            "spec_capture_info": self._format_spec_capture_info([], price),
        } if price is not None else None

    async def _resolve_taobao_detail_price(self, page: Page, candidate: Dict[str, Any]) -> Optional[float]:
        clicked = await self._click_taobao_option(page, candidate)
        if clicked:
            await AntiDetect.random_delay(0.7, 1.2)
        if candidate.get("option_price") is not None:
            return float(candidate["option_price"])
        return await self._extract_taobao_detail_price(page)

    async def _click_taobao_option(self, page: Page, candidate: Dict[str, Any]) -> bool:
        token = str(candidate.get("token", "")).strip()
        if not token:
            return False
        try:
            locator = page.locator(f'[data-price-monitor-taobao-sku-token="{token}"]').first
            if await locator.count() == 0:
                return False
            await locator.scroll_into_view_if_needed(timeout=3000)
            await locator.click(timeout=5000)
            return True
        except Exception:
            return False

    async def _collect_taobao_detail_options(self, page: Page, intent: Dict[str, str]) -> Dict[str, Any]:
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
                    const match = clean(text).match(/(?:¥|￥)\s*(\d+(?:\.\d+)?)/);
                    if (!match) return null;
                    const price = Number.parseFloat(match[1]);
                    return Number.isFinite(price) ? price : null;
                };
                const dayPattern = (days) => new RegExp(`${days}(?:天|日|day|days)`, 'i');
                const yearPattern = /(?:年卡|年会员|一年卡|两年卡|1年卡|2年卡|一年|两年|1年|2年|12个月|365天)/i;
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
                            return /(?:年卡|年会员|一年卡|1年卡|一年|1年|12个月|365天)/i.test(value);
                        }
                        if (intent.year_count === '2') {
                            return /(?:年卡|年会员|两年卡|2年卡|两年|2年)/i.test(value);
                        }
                        return yearPattern.test(value);
                    }
                    return hasSpecToken(value);
                };
                const isSoldOut = (el, text) => {
                    const classText = `${el.className || ''} ${el.getAttribute('aria-disabled') || ''} ${el.getAttribute('disabled') || ''}`.toLowerCase();
                    return Boolean(
                        el.hasAttribute('disabled') ||
                        el.getAttribute('disabled') === 'true' ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        /disabled|soldout|sold-out|empty|invalid|forbid/.test(classText) ||
                        /(?:无库存|售罄|已售罄|暂时缺货|不可选)/.test(text)
                    );
                };
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
                const rejectedShellText = (value) => /(?:商品规格|数量|库存|客服|进店|加入购物车|领券购买|搜索|收藏|切换大图模式)/.test(value);
                const scoreSpec = (text, el) => {
                    const value = norm(text);
                    let score = 0;
                    if (el.matches('button, [role="button"], li, label')) score += 30;
                    if (parsePrice(text) !== null) score += 10;
                    if (specMatches(value)) score += 60;
                    if (/selected|active|current|选中/.test((el.className || '') + ' ' + (el.getAttribute('aria-selected') || ''))) score += 5;
                    score -= Math.max(0, value.length - 28) / 4;
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
                const options = [];
                const candidates = [];

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
                    const looksClickable = clickEl.matches('button, [role="button"], li, label') ||
                        /sku|spec|prop|option|item/i.test(clickEl.className || '');
                    const hasSpec = hasSpecToken(key);
                    const kinds = specKinds(key);
                    const looksLikeContainer = kinds.length > 1;
                    const soldOut = isSoldOut(clickEl, text || rawText);

                    if (looksClickable && hasSpec && !looksLikeContainer && !optionSeen.has(key)) {
                        optionSeen.add(key);
                        options.push({
                            text: text || rawText,
                            option_price: parsePrice(text || rawText),
                            kinds,
                            intent_match: specMatches(key),
                            sold_out: soldOut,
                        });
                    }

                    if (!key || seen.has(key)) return;
                    if (rejectedShellText(key) && !hasSpec) return;
                    if (!looksClickable || !hasSpec || looksLikeContainer) return;
                    seen.add(key);
                    const token = `price-monitor-taobao-sku-${candidates.length}`;
                    clickEl.setAttribute('data-price-monitor-taobao-sku-token', token);
                    candidates.push({
                        token,
                        text: text || rawText,
                        option_price: parsePrice(text || rawText),
                        score: scoreSpec(text || rawText, clickEl),
                        kinds,
                        intent_match: specMatches(key),
                        sold_out: soldOut,
                    });
                });

                candidates.sort((a, b) => b.score - a.score);
                return {
                    has_options: options.length >= 1,
                    options,
                    candidates,
                    detail_text: clean(document.body.innerText || ''),
                };
            }
            """,
            intent,
        )

    async def _extract_taobao_detail_price(self, page: Page) -> Optional[float]:
        value = await page.evaluate(
            r"""
            () => {
                const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                const toPrice = (text) => {
                    const match = clean(text).match(/(?:¥|￥)\s*(\d+(?:\.\d+)?)/);
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
                    const contextEl = el.closest('section, div, form, main') || el;
                    const context = clean(contextEl.textContent || '');
                    let score = 0;
                    if (/(?:平台加补后|券后|到手|补后|优惠后|加补后|礼金补贴后|限时补贴)/.test(context)) score += 160;
                    if (/(?:平台礼金|平台优惠券|优惠券|券满|满\\d+(?:\\.\\d+)?减\\d+(?:\\.\\d+)?|补贴)/.test(context)) score += 50;
                    if (/(?:商品规格|数量|有货)/.test(document.body.innerText || '')) score += 20;
                    if (/(?:优惠前|划线价|原价|市场价)/.test(context)) score -= 160;
                    if (/(?:评价|销量|已售|人付款)/.test(context)) score -= 20;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    score += Math.min(Number.parseFloat(style.fontSize) || 0, 48);
                    score -= rect.top / 2000;
                    candidates.push({price, score, text, context: context.slice(0, 120)});
                }
                candidates.sort((a, b) => b.score - a.score);
                return candidates.length ? candidates[0].price : null;
            }
            """
        )
        return float(value) if value else None

    async def _extract_taobao_detail_item_text(self, page: Page) -> str:
        value = await page.evaluate(
            r"""
            () => {
                const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                const text = clean(document.body.innerText || '');
                const specIndex = text.indexOf('商品规格');
                if (specIndex >= 0) return text.slice(specIndex, specIndex + 500);
                return text.slice(0, 800);
            }
            """
        )
        return str(value or "")

    def _format_spec_capture_info(self, options: list, price: Optional[float]) -> str:
        parts = []
        for option in options or []:
            text = str(option.get("text", "")).strip()
            if not text:
                continue
            item = text
            if option.get("option_price") is not None:
                item = f"{item}: {self._format_price_text(option.get('option_price'))}"
            if option.get("sold_out"):
                item = f"{item} 已售罄"
            parts.append(item)
        if price is not None:
            parts.append(f"detail_price:{self._format_price_text(price)}")
        return "；".join(parts)

    def _looks_like_cn_7d_delist_detail(self, text: str, price: float) -> bool:
        normalized = (text or "").lower().replace(" ", "")
        return (
            abs(float(price) - 3.9) < 0.01
            and "适趣" in normalized
            and "中文" in normalized
            and any(token in normalized for token in ("7天", "7日", "7day", "7days"))
        )

    def _looks_like_english_detail_text(self, text: str) -> bool:
        normalized = (text or "").lower().replace(" ", "")
        return (
            "适趣" in normalized
            and any(token in normalized for token in ("英语", "英文", "english"))
        )

    async def _save_order_debug_snapshot(self, page: Page) -> Path:
        output_dir = Path("data/debug")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = output_dir / f"{timestamp}_{self.PLATFORM}_detail"
        await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        base.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
        return base.with_suffix(".png")
