import asyncio
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from agents.base_agent import BaseAgent
from core.anti_detect import AntiDetect
from core.browser import BrowserManager


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

    def _infer_year_count_from_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", "", (text or "").lower())
        if any(token in normalized for token in ("两年", "2年")):
            return "2"
        if any(token in normalized for token in ("一年", "1年")):
            return "1"
        return ""

    def _infer_year_count_from_price(self, price: Optional[float]) -> str:
        if price is None:
            return ""
        if abs(float(price) - 2498.0) <= 0.5:
            return "2"
        if abs(float(price) - 1998.0) <= 0.5:
            return "1"
        return ""

    def _with_year_spec_hint(self, offer: Dict[str, Any], intent: Dict[str, str]) -> Dict[str, Any]:
        if intent.get("spec") != "year":
            return offer
        year_count = self._infer_year_count_from_text(str(offer.get("spec_text", "")))
        if not year_count:
            year_count = self._infer_year_count_from_price(offer.get("price"))
        if year_count:
            offer["year_count"] = year_count
            suffix = "两年" if year_count == "2" else "一年"
            spec_text = str(offer.get("spec_text", "")).strip()
            if suffix not in spec_text:
                offer["spec_text"] = f"{spec_text} {suffix}".strip()
        return offer

    def _build_fishing_browser(self, headless: bool) -> BrowserManager:
        return BrowserManager(
            proxy=self.proxy,
            headless=headless,
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

    async def _load_fishing_account_cookies(self) -> None:
        if self.browser and not self.account.storage_state and self.account.cookies_encrypted:
            await self.browser.load_cookie_header(self.account.cookies_encrypted, self._cookie_url())

    async def _open_fishing_detail_page(self, url: str) -> Page:
        if not self.browser:
            raise RuntimeError("Fishing browser is not started.")

        print(f"[{self.PLATFORM}] fishing opening new page", flush=True)
        page = await asyncio.wait_for(self.browser.new_page(), timeout=15)
        print(f"[{self.PLATFORM}] fishing goto listing: {url}", flush=True)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except PlaywrightTimeoutError:
            print(f"[{self.PLATFORM}] fishing goto timed out, continue with current page: {page.url}", flush=True)
        print(f"[{self.PLATFORM}] fishing detail page loaded: {page.url}", flush=True)
        return page

    async def start_chat_for_listing(self, url: str) -> Page:
        self.browser = self._build_fishing_browser(self.headless)
        print(f"[{self.PLATFORM}] fishing browser starting", flush=True)
        await self.browser.start()
        print(f"[{self.PLATFORM}] fishing browser started", flush=True)
        await self._load_fishing_account_cookies()

        page = await self._open_fishing_detail_page(url)
        await self._wait_for_verification_appearance(page, "after fishing detail open", timeout_seconds=3)
        page = await self._ensure_fishing_login(page, url)
        print(f"[{self.PLATFORM}] fishing clicking chat button", flush=True)
        if not await self._click_chat_button(page):
            await self._save_fishing_debug_snapshot(page, "chat_button_not_found")
            raise RuntimeError("未找到咸鱼商品详情页的聊一聊按钮")
        print(f"[{self.PLATFORM}] fishing chat button clicked", flush=True)
        await self._wait_for_fishing_page_stable(page, timeout=5000)
        await AntiDetect.random_delay(1, 2)
        await self._wait_for_verification_appearance(page, "after fishing chat open", timeout_seconds=3)
        page = await self._resolve_chat_page(page)
        if not await self._has_chat_input(page):
            if await self._is_login_required_page(page):
                page = await self._ensure_fishing_login(page, url)
                await self._wait_for_fishing_page_stable(page, timeout=5000)
                if not await self._has_chat_input(page):
                    if not await self._click_chat_button(page):
                        await self._save_fishing_debug_snapshot(page, "chat_button_not_found_after_login")
                        raise RuntimeError("Login finished, but chat button was not found.")
                    await self._wait_for_fishing_page_stable(page, timeout=5000)
                    await AntiDetect.random_delay(1, 2)
                    page = await self._resolve_chat_page(page)
            if await self._has_chat_input(page):
                print(f"[{self.PLATFORM}] fishing chat page ready: {page.url}", flush=True)
                return page
            await self._save_fishing_debug_snapshot(page, "chat_page_not_ready")
            await self._save_fishing_input_diagnostics(page, reason="chat_page_not_ready")
            raise RuntimeError("已点击聊天入口，但未检测到聊天输入框")
        print(f"[{self.PLATFORM}] fishing chat page ready: {page.url}", flush=True)
        return page

    async def _ensure_fishing_login(self, page: Page, url: str) -> Page:
        if not await self._is_login_required_page(page):
            return page

        if self.headless:
            print(
                f"[{self.PLATFORM}] login required in headless fishing mode. "
                "Switching to a visible browser for manual login.",
                flush=True,
            )
            page = await self._restart_fishing_browser_visible(url)
        else:
            print(
                f"[{self.PLATFORM}] login required. Please finish login in the visible browser.",
                flush=True,
            )
            try:
                await page.bring_to_front()
            except Exception:
                pass

        await self._wait_for_manual_fishing_login(page)
        await self._save_fishing_login_state(page)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except PlaywrightTimeoutError:
            print(f"[{self.PLATFORM}] fishing reload after login timed out: {page.url}", flush=True)
        await self._wait_for_fishing_page_stable(page, timeout=5000)
        await self._wait_for_verification_appearance(page, "after fishing login", timeout_seconds=3)
        return page

    async def _restart_fishing_browser_visible(self, url: str) -> Page:
        if self.browser:
            await self.browser.stop()
        self.headless = False
        self.browser = self._build_fishing_browser(False)
        print(f"[{self.PLATFORM}] fishing visible login browser starting", flush=True)
        await self.browser.start()
        print(f"[{self.PLATFORM}] fishing visible login browser started", flush=True)
        await self._load_fishing_account_cookies()
        page = await self._open_fishing_detail_page(url)
        try:
            await page.bring_to_front()
        except Exception:
            pass
        return page

    async def _wait_for_manual_fishing_login(self, page: Page) -> None:
        wait_seconds = 0
        while True:
            if page.is_closed():
                raise RuntimeError("Login browser was closed before login finished.")
            if not await self._is_login_required_page(page):
                break
            await asyncio.sleep(5)
            wait_seconds += 5
            if wait_seconds % 30 == 0:
                print(f"[{self.PLATFORM}] still waiting for manual login ({wait_seconds}s).", flush=True)

        print(f"[{self.PLATFORM}] login state detected; resuming fishing.", flush=True)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await AntiDetect.random_delay(1, 2)

    async def _save_fishing_login_state(self, page: Page) -> None:
        if not self.account.storage_state:
            return
        try:
            storage_state = Path(self.account.storage_state)
            storage_state.parent.mkdir(parents=True, exist_ok=True)
            await page.context.storage_state(path=str(storage_state))
            print(f"[{self.PLATFORM}] saved login state: {storage_state}", flush=True)
        except Exception as exc:
            print(f"[{self.PLATFORM}] failed to save login state: {exc}", flush=True)

    async def _is_login_required_page(self, page: Page) -> bool:
        try:
            current_url = (page.url or "").lower()
            if any(marker in current_url for marker in ("login.taobao.com", "passport", "/member/login")):
                return True
            return bool(
                await page.evaluate(
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
                        const text = (document.body?.innerText || '').replace(/\s+/g, '');
                        const strongMarkers = [
                            '\u5bc6\u7801\u767b\u5f55',
                            '\u77ed\u4fe1\u767b\u5f55',
                            '\u9a8c\u8bc1\u7801\u767b\u5f55',
                            '\u6dd8\u5b9d\u8d26\u53f7\u767b\u5f55',
                            '\u8bf7\u5148\u767b\u5f55',
                            '\u4eb2\uff0c\u8bf7\u767b\u5f55',
                            '\u767b\u5f55\u540e\u67e5\u770b'
                        ];
                        if (strongMarkers.some((marker) => text.includes(marker))) return true;

                        const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
                        const hasAccountInput = inputs.some((el) => {
                            const attrs = [
                                el.getAttribute('placeholder') || '',
                                el.getAttribute('aria-label') || '',
                                el.getAttribute('name') || ''
                            ].join('');
                            return /(\u624b\u673a|\u8d26\u53f7|\u5bc6\u7801|phone|mobile|login|password)/i.test(attrs);
                        });
                        if (!hasAccountInput) return false;

                        const buttons = Array.from(document.querySelectorAll('button, [role="button"], a, div, span'))
                            .filter(visible);
                        return buttons.some((el) => {
                            const label = (el.innerText || el.textContent || '').replace(/\s+/g, '');
                            return label === '\u767b\u5f55' || label.includes('\u767b\u5f55\u5e76\u540c\u610f');
                        });
                    }
                    """
                )
            )
        except Exception:
            return False

    async def fill_chat_message(self, page: Page, message: str) -> bool:
        await self._scroll_chat_messages_to_bottom(page)
        if await self._type_chat_message_with_keyboard(page, message):
            return True

        await self._wait_for_fishing_page_stable(page)
        filled = await self._fishing_evaluate(
            page,
            r"""
            (message) => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const dispatch = (el) => {
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: 'a'}));
                };
                const candidates = Array.from(document.querySelectorAll([
                    'textarea',
                    'input[type="text"]',
                    '[contenteditable="true"]',
                    '[role="textbox"]'
                ].join(','))).filter(visible);

                const scored = candidates.map((el) => {
                    const text = [
                        el.getAttribute('placeholder') || '',
                        el.getAttribute('aria-label') || '',
                        el.innerText || '',
                        el.textContent || ''
                    ].join(' ');
                    const rect = el.getBoundingClientRect();
                    let score = rect.top;
                    if (/请输入消息|消息|输入/.test(text)) score += 100000;
                    if (rect.top > window.innerHeight * 0.55) score += 50000;
                    return {el, score};
                }).sort((a, b) => b.score - a.score);

                const target = scored[0]?.el;
                if (!target) return false;
                target.scrollIntoView({block: 'center', inline: 'center'});
                target.focus();
                target.click();
                if (target.isContentEditable || target.getAttribute('contenteditable') === 'true') {
                    target.textContent = message;
                } else {
                    const setter = Object.getOwnPropertyDescriptor(target.__proto__, 'value')?.set;
                    if (setter) {
                        setter.call(target, message);
                    } else {
                        target.value = message;
                    }
                }
                dispatch(target);
                return true;
            }
            """,
            message,
        )
        if filled:
            await AntiDetect.random_delay(0.2, 0.5)
            if await self._chat_input_has_text(page, message):
                print(f"[{self.PLATFORM}] fishing input typed by dom set", flush=True)
                return True
            print(f"[{self.PLATFORM}] fishing dom set did not change textbox", flush=True)

        selectors = [
            "textarea",
            "[contenteditable='true']",
            "[role='textbox']",
            "input[type='text']",
            "[class*='input'] textarea",
            "[class*='Input'] textarea",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).last
                if await locator.count() == 0:
                    continue
                if not await locator.is_visible(timeout=2000):
                    continue
                await locator.click(timeout=3000)
                try:
                    await locator.fill(message, timeout=5000)
                except Exception:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await page.keyboard.type(message, delay=40)
                await AntiDetect.random_delay(0.2, 0.5)
                if await self._chat_input_has_text(page, message):
                    print(f"[{self.PLATFORM}] fishing input typed by fallback selector", flush=True)
                    return True
            except Exception:
                continue
        await self._save_fishing_debug_snapshot(page, "chat_input_not_found")
        await self._save_fishing_input_diagnostics(page)
        return False

    async def _type_chat_message_with_keyboard(self, page: Page, message: str) -> bool:
        await self._wait_for_fishing_page_stable(page)
        for context in [page, *page.frames]:
            locator_builders = [
                lambda ctx=context: ctx.get_by_placeholder("请输入消息", exact=False).last,
                lambda ctx=context: ctx.locator("textarea[placeholder*='消息']").last,
                lambda ctx=context: ctx.locator("input[placeholder*='消息']").last,
                lambda ctx=context: ctx.locator("[contenteditable='true']").last,
                lambda ctx=context: ctx.locator("[role='textbox']").last,
                lambda ctx=context: ctx.locator("textarea").last,
                lambda ctx=context: ctx.locator("input[type='text']").last,
            ]
            for build_locator in locator_builders:
                try:
                    locator = build_locator()
                    if await locator.count() == 0:
                        continue
                    if not await locator.is_visible(timeout=1200):
                        continue
                    await locator.scroll_into_view_if_needed(timeout=2000)
                    await locator.click(timeout=3000)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await page.keyboard.insert_text(message)
                    await AntiDetect.random_delay(0.2, 0.5)
                    if await self._chat_input_has_text(page, message):
                        print(f"[{self.PLATFORM}] fishing input typed by locator", flush=True)
                        return True
                    print(f"[{self.PLATFORM}] fishing locator focused but text not detected", flush=True)
                except Exception:
                    continue

        clicked = await self._fishing_evaluate(
            page,
            r"""
            () => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const candidates = Array.from(document.querySelectorAll([
                    'textarea',
                    'input[type="text"]',
                    '[contenteditable="true"]',
                    '[role="textbox"]'
                ].join(','))).filter(visible);
                const scored = candidates.map((el) => {
                    const rect = el.getBoundingClientRect();
                    const text = [
                        el.getAttribute('placeholder') || '',
                        el.getAttribute('aria-label') || ''
                    ].join(' ');
                    let score = rect.top;
                    if (/请输入消息|消息|输入/.test(text)) score += 100000;
                    if (rect.top > window.innerHeight * 0.55) score += 50000;
                    return {el, score};
                }).sort((a, b) => b.score - a.score);
                const target = scored[0]?.el;
                if (!target) return false;
                target.scrollIntoView({block: 'center', inline: 'center'});
                target.focus();
                target.click();
                return true;
            }
            """,
        )
        if not clicked:
            return await self._type_chat_message_by_coordinates(page, message)
        try:
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.insert_text(message)
            await AntiDetect.random_delay(0.2, 0.5)
            if await self._chat_input_has_text(page, message):
                print(f"[{self.PLATFORM}] fishing input typed by dom focus", flush=True)
                return True
            return await self._type_chat_message_by_coordinates(page, message)
        except Exception:
            return False

    async def _type_chat_message_by_coordinates(self, page: Page, message: str) -> bool:
        try:
            width, height = await self._page_inner_size(page)
            points = [
                (max(40, width * 0.06), max(120, height - 95)),
                (max(140, width * 0.16), max(120, height - 95)),
                (max(260, width * 0.28), max(120, height - 95)),
                (max(40, width * 0.06), max(120, height - 55)),
                (max(140, width * 0.16), max(120, height - 55)),
            ]
            for x, y in points:
                await page.mouse.click(x, y)
                await AntiDetect.random_delay(0.2, 0.4)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await page.keyboard.insert_text(message)
                await AntiDetect.random_delay(0.3, 0.6)
                if await self._chat_input_has_text(page, message):
                    print(f"[{self.PLATFORM}] fishing input typed by coordinates ({x:.0f},{y:.0f})", flush=True)
                    return True
            await self._save_fishing_debug_snapshot(page, "chat_input_text_not_detected")
            await self._save_fishing_input_diagnostics(page)
            print(f"[{self.PLATFORM}] fishing coordinate input did not change textbox", flush=True)
            return False
        except Exception:
            return False

    async def _page_inner_size(self, page: Page) -> tuple[int, int]:
        try:
            size = await self._fishing_evaluate(
                page,
                "() => ({width: window.innerWidth || 1366, height: window.innerHeight || 768})",
            )
            return (int(size.get("width") or 1366), int(size.get("height") or 768))
        except Exception:
            viewport = page.viewport_size or {"width": 1366, "height": 768}
            return (int(viewport.get("width") or 1366), int(viewport.get("height") or 768))

    async def _save_fishing_input_diagnostics(self, page: Page, reason: str = "input_diagnostics") -> None:
        try:
            diagnostics = []
            script = r"""
            () => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                return Array.from(document.querySelectorAll('*'))
                    .filter(visible)
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                        return {
                            tag: el.tagName,
                            role: el.getAttribute('role') || '',
                            placeholder: el.getAttribute('placeholder') || '',
                            aria: el.getAttribute('aria-label') || '',
                            contenteditable: el.getAttribute('contenteditable') || '',
                            className: String(el.className || '').slice(0, 160),
                            id: el.id || '',
                            text: text.slice(0, 120),
                            rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
                        };
                    })
                    .filter((item) =>
                        /输入|消息|发送|textarea|input|textbox|editable/i.test(
                            `${item.tag} ${item.role} ${item.placeholder} ${item.aria} ${item.contenteditable} ${item.className} ${item.text}`
                        )
                    )
                    .slice(-80);
            }
            """
            for index, frame in enumerate([page, *page.frames]):
                try:
                    diagnostics.append({"frame": index, "url": getattr(frame, "url", ""), "items": await frame.evaluate(script)})
                except Exception as exc:
                    diagnostics.append({"frame": index, "error": str(exc)})
            output_dir = Path("data/debug")
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = output_dir / f"{timestamp}_{self.PLATFORM}_fishing_{reason}.json"
            path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{self.PLATFORM}] fishing input diagnostics saved: {path}", flush=True)
        except Exception as exc:
            print(f"[{self.PLATFORM}] fishing input diagnostics failed: {exc}", flush=True)
            try:
                output_dir = Path("data/debug")
                output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = output_dir / f"{timestamp}_{self.PLATFORM}_fishing_{reason}_failed.json"
                path.write_text(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    async def _chat_input_has_text(self, page: Page, message: str) -> bool:
        try:
            script = r"""
            () => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                return Array.from(document.querySelectorAll([
                    'textarea',
                    'input[type="text"]',
                    '[contenteditable="true"]',
                    '[role="textbox"]'
                ].join(','))).filter(visible)
                    .map((el) => el.value || el.innerText || el.textContent || '')
                    .join('\n');
            }
            """
            values = []
            for context in [page, *page.frames]:
                try:
                    values.append(str(await context.evaluate(script) or ""))
                except Exception:
                    continue
            combined = "\n".join(values)
            return str(message).strip() in combined.strip()
        except Exception:
            return False

    async def send_chat_message(self, page: Page, message: str) -> bool:
        print(f"[{self.PLATFORM}] fishing input message: {message}", flush=True)
        await self._save_fishing_input_diagnostics(page, reason="pre_input")
        if not await self.fill_chat_message(page, message):
            print(f"[{self.PLATFORM}] fishing input failed", flush=True)
            return False

        before_messages = await self.read_chat_messages(
            page,
            save_diagnostics=False,
            scroll_to_top=False,
            verbose=False,
        )
        before_count = self._count_message_occurrences(before_messages, message)
        print(f"[{self.PLATFORM}] fishing clicking send", flush=True)
        await AntiDetect.random_delay(0.4, 0.8)
        send_labels = ["发送", "发 送"]
        for context in [page, *page.frames]:
            for label in send_labels:
                try:
                    locator = context.get_by_text(label, exact=True).last
                    if await locator.count() > 0 and await locator.is_visible(timeout=1000):
                        disabled = await locator.evaluate(
                            "(el) => el.disabled || el.getAttribute('aria-disabled') === 'true' || /disabled/.test(el.className || '')"
                        )
                        if disabled:
                            continue
                        await locator.click(timeout=3000)
                        await self._wait_for_fishing_page_stable(page, timeout=5000)
                        print(f"[{self.PLATFORM}] fishing send clicked by text", flush=True)
                        return await self._wait_for_sent_message(page, message, before_count)
                except Exception:
                    continue
        clicked = await self._fishing_evaluate(
            page,
            r"""
            () => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none' &&
                        Number(style.opacity || 1) > 0;
                };
                const nodes = Array.from(document.querySelectorAll('button, [role="button"], div, span'))
                    .filter(visible)
                    .filter((el) => (el.innerText || el.textContent || '').replace(/\s+/g, '') === '发送')
                    .filter((el) => {
                        const className = el.className || '';
                        return !el.disabled &&
                            el.getAttribute('aria-disabled') !== 'true' &&
                            !/disabled/.test(String(className));
                    });
                const bottomNodes = nodes
                    .map((el) => ({el, rect: el.getBoundingClientRect()}))
                    .sort((a, b) => (b.rect.top - a.rect.top) || (b.rect.left - a.rect.left));
                const target = bottomNodes[0]?.el;
                if (!target) return false;
                target.click();
                return true;
            }
            """
        )
        if clicked:
            await self._wait_for_fishing_page_stable(page, timeout=5000)
            print(f"[{self.PLATFORM}] fishing send clicked by dom", flush=True)
            return await self._wait_for_sent_message(page, message, before_count)
        if await self._click_send_by_coordinates(page):
            print(f"[{self.PLATFORM}] fishing send clicked by coordinates", flush=True)
            return await self._wait_for_sent_message(page, message, before_count)
        try:
            await page.keyboard.press("Enter")
            await self._wait_for_fishing_page_stable(page, timeout=5000)
            await AntiDetect.random_delay(0.5, 1.0)
            print(f"[{self.PLATFORM}] fishing send triggered by enter", flush=True)
            return await self._wait_for_sent_message(page, message, before_count)
        except Exception:
            await self._save_fishing_debug_snapshot(page, "chat_send_failed")
            return False

    async def _wait_for_sent_message(self, page: Page, message: str, before_count: int, timeout_seconds: int = 8) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            messages = await self.read_chat_messages(
                page,
                save_diagnostics=False,
                scroll_to_top=False,
                verbose=False,
            )
            current_count = self._count_message_occurrences(messages, message)
            input_empty = not await self._chat_input_has_text(page, message)
            if current_count > before_count or (current_count > 0 and input_empty):
                print(f"[{self.PLATFORM}] fishing send confirmed", flush=True)
                return True
            if asyncio.get_running_loop().time() >= deadline:
                print(f"[{self.PLATFORM}] fishing send not confirmed", flush=True)
                await self._save_fishing_debug_snapshot(page, "chat_send_not_confirmed")
                return False
            await asyncio.sleep(1)

    def _count_message_occurrences(self, messages: list[Dict[str, str]], message: str) -> int:
        target = str(message or "").strip()
        if not target:
            return 0
        return sum(
            1
            for item in messages
            if item.get("sender") == "buyer" and target in str(item.get("content", ""))
        )

    async def _click_send_by_coordinates(self, page: Page) -> bool:
        try:
            viewport = page.viewport_size or {"width": 1366, "height": 768}
            width = int(viewport.get("width") or 1366)
            height = int(viewport.get("height") or 768)
            await page.mouse.click(max(50, width - 70), max(80, height - 35))
            await self._wait_for_fishing_page_stable(page, timeout=5000)
            await AntiDetect.random_delay(0.5, 1.0)
            return True
        except Exception:
            return False

    async def _scroll_chat_messages_to_bottom(self, page: Page) -> None:
        script = r"""
            () => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const candidates = Array.from(document.querySelectorAll('div, section, main'))
                    .filter(visible)
                    .filter((el) => el.scrollHeight > el.clientHeight + 80)
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        const className = String(el.className || '');
                        const hasMessage = Boolean(el.querySelector(
                            '[class*="message-row"], [class*="MessageRow"], [class*="message-content"], [class*="bubble"]'
                        ));
                        let score = 0;
                        if (hasMessage) score += 120;
                        if (/message|msg|chat|im|conversation|list|body|content/i.test(className)) score += 80;
                        if (rect.top < window.innerHeight - 180) score += 30;
                        if (rect.width > window.innerWidth * 0.35) score += 20;
                        return {el, score, scrollHeight: el.scrollHeight};
                    })
                    .filter((item) => item.score >= 80)
                    .sort((a, b) => (b.score - a.score) || (b.scrollHeight - a.scrollHeight));
                const target = candidates[0]?.el || document.scrollingElement || document.documentElement;
                target.scrollTop = target.scrollHeight;
                window.scrollTo(0, document.body.scrollHeight);
                return {
                    found: Boolean(candidates[0]),
                    scrollTop: target.scrollTop,
                    scrollHeight: target.scrollHeight,
                    clientHeight: target.clientHeight
                };
            }
        """
        for context in [page, *page.frames]:
            try:
                await context.evaluate(script)
            except Exception:
                pass
        try:
            viewport = page.viewport_size or {"width": 1366, "height": 768}
            await page.mouse.move(int(viewport["width"] * 0.5), int(viewport["height"] * 0.45))
            await page.mouse.wheel(0, 1800)
        except Exception:
            pass
        await AntiDetect.random_delay(0.3, 0.6)

    async def _scroll_chat_messages_to_top(self, page: Page) -> None:
        script = r"""
            () => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const candidates = Array.from(document.querySelectorAll('div, section, main'))
                    .filter(visible)
                    .filter((el) => el.scrollHeight > el.clientHeight + 80)
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        const className = String(el.className || '');
                        const hasMessage = Boolean(el.querySelector(
                            '[class*="message-row"], [class*="MessageRow"], [class*="message-content"], [class*="bubble"]'
                        ));
                        let score = 0;
                        if (hasMessage) score += 120;
                        if (/message|msg|chat|im|conversation|list|body|content/i.test(className)) score += 80;
                        if (rect.top < window.innerHeight - 180) score += 30;
                        if (rect.width > window.innerWidth * 0.35) score += 20;
                        return {el, score, scrollHeight: el.scrollHeight, top: rect.top};
                    })
                    .filter((item) => item.score >= 80)
                    .sort((a, b) => (b.score - a.score) || (b.scrollHeight - a.scrollHeight));
                const target = candidates[0]?.el || document.scrollingElement || document.documentElement;
                target.scrollTop = 0;
                window.scrollTo(0, 0);
                return {
                    found: Boolean(candidates[0]),
                    className: String(target.className || '').slice(0, 120),
                    scrollTop: target.scrollTop,
                    scrollHeight: target.scrollHeight,
                    clientHeight: target.clientHeight
                };
            }
        """
        for context in [page, *page.frames]:
            try:
                await context.evaluate(script)
            except Exception:
                pass
        try:
            viewport = page.viewport_size or {"width": 1366, "height": 768}
            await page.mouse.move(int(viewport["width"] * 0.5), int(viewport["height"] * 0.45))
            for _ in range(5):
                await page.mouse.wheel(0, -1800)
                await AntiDetect.random_delay(0.15, 0.25)
        except Exception:
            pass
        await AntiDetect.random_delay(0.5, 0.8)

    async def read_chat_messages(
        self,
        page: Page,
        save_diagnostics: bool = False,
        scroll_to_top: bool = True,
        verbose: bool = True,
    ) -> list[Dict[str, str]]:
        await self._wait_for_fishing_page_stable(page)
        if scroll_to_top and verbose:
            print(f"[{self.PLATFORM}] fishing scrolling chat to top before reading", flush=True)
        if scroll_to_top:
            await self._scroll_chat_messages_to_top(page)
        script = r"""
            () => {
                const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const rejectText = /立即购买|闲鱼号|请输入消息|发送|活动价|含运费|商品详情|北京|表情|图片|剪刀|地址|手机壳/;
                const inputAreaTop = Math.max(0, window.innerHeight - 170);
                const candidates = Array.from(document.querySelectorAll('div, span, p, pre'))
                    .filter(visible)
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        const text = clean(el.innerText || el.textContent);
                        const className = String(el.className || '');
                        let score = 0;
                        if (/message|msg|bubble|chat|talk|im|content/i.test(className)) score += 80;
                        if (rect.top > 180 && rect.top < inputAreaTop) score += 60;
                        if (rect.width >= 20 && rect.width <= window.innerWidth * 0.75) score += 30;
                        if (text.length >= 1 && text.length <= 220) score += 30;
                        return {rect, text, className, score};
                    })
                    .filter((item) => item.text && item.score >= 80)
                    .filter((item) => item.rect.top > 160 && item.rect.top < inputAreaTop)
                    .filter((item) => !rejectText.test(item.text))
                    .filter((item) => !/^\d+(\.\d+)?$/.test(item.text));

                const seen = new Set();
                return candidates
                    .sort((a, b) => (a.rect.top - b.rect.top) || (a.rect.left - b.rect.left) || (b.score - a.score))
                    .filter((item) => {
                        const key = `${item.text}|${Math.round(item.rect.top / 6)}`;
                        if (seen.has(key)) return false;
                        seen.add(key);
                        return true;
                    })
                    .slice(-20)
                    .map((item) => ({
                        sender: item.rect.left > window.innerWidth * 0.45 ? 'buyer' : 'seller',
                        content: item.text,
                        score: item.score,
                        rect: {
                            x: item.rect.x,
                            y: item.rect.y,
                            width: item.rect.width,
                            height: item.rect.height
                        },
                        className: item.className.slice(0, 120),
                    }));
            }
        """
        all_messages = []
        diagnostics = []
        for index, context in enumerate([page, *page.frames]):
            try:
                messages = await context.evaluate(script)
                for message in messages or []:
                    item = dict(message)
                    item["frame"] = index
                    all_messages.append(item)
                diagnostics.append({"frame": index, "url": getattr(context, "url", ""), "messages": messages or []})
            except Exception as exc:
                diagnostics.append({"frame": index, "error": str(exc)})

        if save_diagnostics:
            await self._save_fishing_message_diagnostics(diagnostics)

        seen = set()
        result = []
        for message in sorted(all_messages, key=lambda item: (item.get("frame", 0), item.get("rect", {}).get("y", 0))):
            content = str(message.get("content", "")).strip()
            if not content or content in seen:
                continue
            seen.add(content)
            result.append({"sender": message.get("sender", ""), "content": content})
        return result[-20:]

    async def read_chat_messages(
        self,
        page: Page,
        save_diagnostics: bool = False,
        scroll_to_top: bool = True,
        verbose: bool = True,
    ) -> list[Dict[str, str]]:
        await self._wait_for_fishing_page_stable(page)
        if scroll_to_top and verbose:
            print(f"[{self.PLATFORM}] fishing scrolling chat to top before reading", flush=True)
        if scroll_to_top:
            await self._scroll_chat_messages_to_top(page)
        script = r"""
            () => {
                const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const inputAreaTop = Math.max(0, window.innerHeight - 170);
                const centerX = window.innerWidth / 2;
                const rejectWords = [
                    '\u7acb\u5373\u8d2d\u4e70', '\u95f2\u9c7c\u53f7',
                    '\u8bf7\u8f93\u5165\u6d88\u606f', '\u6309Enter\u952e\u53d1\u9001',
                    '\u70b9\u51fb\u53d1\u9001\u6309\u94ae\u53d1\u9001',
                    '\u6d3b\u52a8\u4ef7', '\u542b\u8fd0\u8d39', '\u5546\u54c1\u8be6\u60c5',
                    '\u5317\u4eac', '\u8868\u60c5', '\u56fe\u7247', '\u526a\u5200',
                    '\u5730\u5740', '\u53d1\u95f2\u7f6e', '\u53cd\u9988',
                    '\u5ba2\u670d', '\u56de\u9876\u90e8', 'APP',
                    '\u53d1\u9001', '\u53d1 \u9001', '\u5df2\u8bfb'
                ];
                const isNoise = (text) => {
                    if (!text || rejectWords.some((word) => text.includes(word))) return true;
                    if (/^\d+(\.\d+)?$/.test(text)) return true;
                    if (/^\d{1,2}:\d{2}$/.test(text)) return true;
                    if (/^[A-Za-z0-9_*.\-\s]{1,20}$/.test(text)) return true;
                    return false;
                };
                const makeItem = (el, row) => {
                    const rect = el.getBoundingClientRect();
                    const text = clean(el.innerText || el.textContent);
                    const className = String(el.className || row?.className || '');
                    return {
                        sender: (rect.left + rect.width / 2) > centerX ? 'buyer' : 'seller',
                        content: text,
                        score: 300,
                        rect: {
                            x: rect.x,
                            y: rect.y,
                            width: rect.width,
                            height: rect.height
                        },
                        className: className.slice(0, 120),
                    };
                };
                const validItem = (item) =>
                    item.content &&
                    item.rect.y > 40 &&
                    item.rect.y < inputAreaTop &&
                    item.rect.width >= 18 &&
                    item.rect.width <= window.innerWidth * 0.65 &&
                    item.content.length <= 260 &&
                    !isNoise(item.content);

                const messageRows = Array.from(document.querySelectorAll(
                    '[class*="message-row"], [class*="MessageRow"], [class*="msg-row"], [class*="bubble"]'
                )).filter(visible);
                const rowItems = messageRows.flatMap((row) => {
                    const bubbles = Array.from(row.querySelectorAll(
                        '[class*="message-content"], [class*="MessageContent"], [class*="bubble"]'
                    )).filter(visible);
                    const items = bubbles.length ? bubbles.map((bubble) => makeItem(bubble, row)) : [makeItem(row, row)];
                    return items.filter(validItem);
                });

                const globalItems = Array.from(document.querySelectorAll(
                    '[class*="message-content"], [class*="MessageContent"], [class*="bubble"]'
                )).filter(visible).map((el) => makeItem(el, null)).filter(validItem);
                const rightTextItems = Array.from(document.querySelectorAll('div, span, p, pre'))
                    .filter(visible)
                    .map((el) => makeItem(el, null))
                    .filter(validItem)
                    .filter((item) => (item.rect.x + item.rect.width / 2) > centerX)
                    .filter((item) => item.rect.width <= window.innerWidth * 0.35);
                const candidates = [...rowItems, ...globalItems, ...rightTextItems];

                const seen = new Set();
                return candidates
                    .sort((a, b) => (a.rect.y - b.rect.y) || (a.rect.x - b.rect.x) || (b.score - a.score))
                    .filter((item) => {
                        const key = `${item.content}|${Math.round(item.rect.y / 6)}`;
                        if (seen.has(key)) return false;
                        seen.add(key);
                        return true;
                    })
                    .slice(-20);
            }
        """
        all_messages = []
        diagnostics = []
        scan_rounds = 8 if scroll_to_top else 1
        for scan_index in range(scan_rounds):
            for index, context in enumerate([page, *page.frames]):
                try:
                    messages = await context.evaluate(script)
                    for message in messages or []:
                        item = dict(message)
                        item["frame"] = index
                        item["scan"] = scan_index
                        all_messages.append(item)
                    diagnostics.append({
                        "scan": scan_index,
                        "frame": index,
                        "url": getattr(context, "url", ""),
                        "messages": messages or [],
                    })
                except Exception as exc:
                    diagnostics.append({"scan": scan_index, "frame": index, "error": str(exc)})
            if scroll_to_top and scan_index < scan_rounds - 1:
                scroll_script = r"""
                    () => {
                        const visible = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0 &&
                                style.visibility !== 'hidden' && style.display !== 'none';
                        };
                        const candidates = Array.from(document.querySelectorAll('div, section, main'))
                            .filter(visible)
                            .filter((el) => el.scrollHeight > el.clientHeight + 80)
                            .map((el) => {
                                const rect = el.getBoundingClientRect();
                                const className = String(el.className || '');
                                const hasMessage = Boolean(el.querySelector(
                                    '[class*="message-row"], [class*="MessageRow"], [class*="message-content"], [class*="bubble"]'
                                ));
                                let score = 0;
                                if (hasMessage) score += 120;
                                if (/message|msg|chat|im|conversation|list|body|content/i.test(className)) score += 80;
                                if (rect.top < window.innerHeight - 180) score += 30;
                                if (rect.width > window.innerWidth * 0.35) score += 20;
                                return {el, score, scrollHeight: el.scrollHeight};
                            })
                            .filter((item) => item.score >= 80)
                            .sort((a, b) => (b.score - a.score) || (b.scrollHeight - a.scrollHeight));
                        const target = candidates[0]?.el || document.scrollingElement || document.documentElement;
                        const before = target.scrollTop;
                        target.scrollTop = Math.min(
                            target.scrollTop + Math.max(240, Math.floor(target.clientHeight * 0.75)),
                            target.scrollHeight
                        );
                        return {before, after: target.scrollTop, scrollHeight: target.scrollHeight};
                    }
                """
                for context in [page, *page.frames]:
                    try:
                        await context.evaluate(scroll_script)
                    except Exception:
                        pass
                try:
                    viewport = page.viewport_size or {"width": 1366, "height": 768}
                    await page.mouse.move(int(viewport["width"] * 0.5), int(viewport["height"] * 0.45))
                    await page.mouse.wheel(0, 650)
                    await AntiDetect.random_delay(0.2, 0.35)
                except Exception:
                    pass

        if save_diagnostics:
            await self._save_fishing_message_diagnostics(diagnostics)

        seen = set()
        result = []
        for message in sorted(
            all_messages,
            key=lambda item: (item.get("scan", 0), item.get("frame", 0), item.get("rect", {}).get("y", 0)),
        ):
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            key = (message.get("sender", ""), content)
            if key in seen:
                continue
            seen.add(key)
            result.append({"sender": message.get("sender", ""), "content": content})
        result = result[-80:]
        if verbose:
            print(f"[{self.PLATFORM}] fishing recognized chat messages: {len(result)}", flush=True)
            for index, message in enumerate(result, 1):
                print(
                    f"[{self.PLATFORM}] fishing chat message {index}: "
                    f"{message.get('sender', '')}: {message.get('content', '')}",
                    flush=True,
                )
        return result

    async def wait_for_seller_messages(
        self,
        page: Page,
        known_contents: set[str],
        timeout_seconds: int = 45,
    ) -> list[Dict[str, str]]:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            messages = await self.read_chat_messages(
                page,
                save_diagnostics=False,
                scroll_to_top=False,
                verbose=False,
            )
            new_seller_messages = [
                message for message in messages
                if message.get("sender") == "seller" and message.get("content") not in known_contents
            ]
            if new_seller_messages:
                return new_seller_messages
            if asyncio.get_running_loop().time() >= deadline:
                return []
            await asyncio.sleep(3)

    async def _save_fishing_message_diagnostics(self, diagnostics: list[dict]) -> None:
        try:
            output_dir = Path("data/debug")
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = output_dir / f"{timestamp}_{self.PLATFORM}_fishing_messages_poll.json"
            path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    async def close_fishing_browser(self) -> None:
        if self.browser:
            await self.browser.stop()
            self.browser = None

    async def _wait_for_fishing_page_stable(self, page: Page, timeout: int = 8000) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=min(timeout, 3000))
        except Exception:
            pass

    async def _fishing_evaluate(self, page: Page, script: str, arg: Any = None, retries: int = 3) -> Any:
        last_exc = None
        for attempt in range(retries):
            try:
                await self._wait_for_fishing_page_stable(page, timeout=5000)
                if arg is None:
                    return await page.evaluate(script)
                return await page.evaluate(script, arg)
            except PlaywrightError as exc:
                last_exc = exc
                text = str(exc)
                navigation_related = (
                    "Execution context was destroyed" in text
                    or "most likely because of a navigation" in text
                    or "Cannot find context with specified id" in text
                )
                if not navigation_related or attempt == retries - 1:
                    raise
                await asyncio.sleep(0.8 + attempt * 0.5)
        raise last_exc

    async def _click_chat_button(self, page: Page) -> bool:
        labels = ["聊一聊", "我想要", "联系卖家", "立即沟通", "去聊天"]
        for label in labels:
            selectors = [
                f"button:has-text('{label}')",
                f"[role='button']:has-text('{label}')",
                f"a:has-text('{label}')",
            ]
            for selector in selectors:
                try:
                    locator = page.locator(selector).last
                    if await locator.count() == 0:
                        continue
                    if not await locator.is_visible(timeout=2000):
                        continue
                    await locator.scroll_into_view_if_needed(timeout=3000)
                    await locator.click(timeout=5000)
                    return True
                except Exception:
                    continue

        clicked = await self._fishing_evaluate(
            page,
            r"""
            (labels) => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const nodes = Array.from(document.querySelectorAll('button, [role="button"], a, div, span'))
                    .filter(visible)
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        const text = (el.innerText || el.textContent || '').replace(/\s+/g, '');
                        const style = window.getComputedStyle(el);
                        let score = 0;
                        if (labels.some((label) => text === label)) score += 1000;
                        if (labels.some((label) => text.includes(label))) score += 300;
                        if (el.matches('button, [role="button"], a')) score += 200;
                        if (rect.width >= 50 && rect.width <= 260 && rect.height >= 28 && rect.height <= 90) score += 120;
                        if (rect.top > window.innerHeight * 0.45) score += 80;
                        if (rect.left > window.innerWidth * 0.45) score += 40;
                        if (/rgb\(\s*255\s*,/.test(style.backgroundColor || '')) score += 30;
                        score -= Math.max(0, text.length - 8) * 20;
                        return {el, rect, text, score};
                    });
                const candidates = nodes.filter(({text, rect}) => {
                    if (!text) return false;
                    if (text.includes('消息') && !labels.some((label) => text.includes(label))) return false;
                    if (text.length > 24) return false;
                    if (rect.left > window.innerWidth - 120 && text === '消息') return false;
                    return labels.some((label) => text.includes(label));
                });
                candidates.sort((a, b) => b.score - a.score);
                const target = candidates[0]?.el;
                if (!target) return false;
                target.scrollIntoView({block: 'center', inline: 'center'});
                target.click();
                return true;
            }
            """,
            labels,
        )
        return bool(clicked)

    async def _resolve_chat_page(self, page: Page) -> Page:
        deadline = asyncio.get_running_loop().time() + 12
        while asyncio.get_running_loop().time() < deadline:
            pages = list(page.context.pages)
            for candidate in reversed(pages):
                try:
                    if await self._has_chat_input(candidate):
                        return candidate
                except Exception:
                    continue
            await asyncio.sleep(0.5)
        return page

    async def _has_chat_input(self, page: Page) -> bool:
        script = r"""
        () => {
            const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== 'hidden' && style.display !== 'none';
            };
            return Array.from(document.querySelectorAll([
                'textarea',
                'input[type="text"]',
                '[contenteditable="true"]',
                '[role="textbox"]'
            ].join(','))).some((el) => {
                if (!visible(el)) return false;
                const text = [
                    el.getAttribute('placeholder') || '',
                    el.getAttribute('aria-label') || '',
                    el.innerText || '',
                    el.textContent || ''
                ].join(' ');
                const rect = el.getBoundingClientRect();
                return /请输入消息|消息|输入/.test(text) || rect.top > window.innerHeight * 0.55;
            });
        }
        """
        for context in [page, *page.frames]:
            try:
                if await context.evaluate(script):
                    return True
            except Exception:
                continue
        return False

    async def _save_fishing_debug_snapshot(self, page: Page, reason: str) -> Path:
        output_dir = Path("data/debug")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = output_dir / f"{timestamp}_{self.PLATFORM}_fishing_{reason}"
        await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        base.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
        return base.with_suffix(".png")

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
            detail_title = await self._extract_detail_title(detail_page, title)
            detail_price = await self._extract_detail_display_price(detail_page)

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
            else:
                offer["detail_title"] = detail_title
                offer["detail_price"] = detail_price
            return offer
        except Exception as exc:
            print(f"[{self.PLATFORM}] failed to fetch order price: {exc}", flush=True)
            return None
        finally:
            await detail_page.close()

    async def _extract_detail_title(self, page: Page, fallback: str = "") -> str:
        value = await page.evaluate(
            r"""
            () => {
                const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const candidates = [];
                document.querySelectorAll('span[class*="desc"], span[class*="Desc"]').forEach((el) => {
                    if (!visible(el)) return;
                    const text = clean(el.innerText || el.textContent || '');
                    if (!text) return;
                    candidates.push(text);
                });
                candidates.sort((a, b) => b.length - a.length);
                return candidates[0] || '';
            }
            """
        )
        return str(value or fallback or "").strip()

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
            return self._with_year_spec_hint({
                "price": price,
                "spec_text": order_text,
                "spec_capture_mode": "order_text_only",
                "spec_capture_info": self._format_spec_capture_info("order_text_only", order_text, price, []),
            }, intent) if price is not None else None

        if not candidates:
            return None

        offers = []
        exact_candidates = [candidate for candidate in candidates if candidate.get("intent_match")]
        candidate_pool = exact_candidates or candidates
        if intent.get("spec") == "year":
            candidate_pool = sorted(candidate_pool, key=self._year_option_sort_key)
        for candidate in candidate_pool[:6]:
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
        return self._with_year_spec_hint(offers[0], intent)

    def _year_option_sort_key(self, candidate: Dict[str, Any]) -> tuple:
        text = str(candidate.get("text", ""))
        year_count = self._infer_year_count_from_text(text)
        if year_count == "2":
            return (0, -float(candidate.get("score") or 0))
        if year_count == "1":
            return (1, -float(candidate.get("score") or 0))
        if "year" in candidate.get("kinds", []):
            return (2, -float(candidate.get("score") or 0))
        return (3, -float(candidate.get("score") or 0))

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
                const monthPattern = /(?:^|[^\u9001\u8d60])(?:\d+\u4e2a\u6708|[一二三四五六七八九十]+\u4e2a\u6708|\d+\u6708\u4f1a\u5458|[一二三四五六七八九十]+\u6708\u4f1a\u5458)/i;
                const quarterPattern = /(?:\u5b63\u5361|\u5b63\u4f1a\u5458|\u4e09\u4e2a\u6708|\u4e09\u6708\u4f1a\u5458|3\u4e2a\u6708|3\u6708\u4f1a\u5458)/i;
                const yearPattern = /(?:\u5e74\u5361|\u5e74\u4f1a\u5458|\u4e00\u5e74\u5361|\u4e24\u5e74\u5361|1\u5e74\u5361|2\u5e74\u5361|\u4e00\u5e74|\u4e24\u5e74|1\u5e74|2\u5e74|12\u4e2a\u6708|365\u5929)/i;
                const hasSpecToken = (value) => dayPattern(7).test(value) ||
                    dayPattern(15).test(value) || dayPattern(21).test(value) ||
                    monthPattern.test(value) || quarterPattern.test(value) || yearPattern.test(value);
                const specKinds = (value) => {
                    const kinds = [];
                    if (dayPattern(7).test(value)) kinds.push('7d');
                    if (dayPattern(15).test(value)) kinds.push('15d');
                    if (dayPattern(21).test(value)) kinds.push('21d');
                    if (monthPattern.test(value)) kinds.push('month');
                    if (quarterPattern.test(value)) kinds.push('quarter');
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
                const directSpecChildCount = (el) => Array.from(el.children || [])
                    .filter((child) => visible(child) && hasSpecToken(norm(child.innerText || child.textContent || '')))
                    .length;

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
                    const childSpecCount = directSpecChildCount(clickEl);
                    const textLooksLikeOption = hasSpecToken(key) && key.length <= 40 && !rejectedShellText(key);
                    const optionLooksClickable = clickEl.matches('button, [role="button"], li, label') ||
                        /sku|spec|prop|option|item/i.test(clickEl.className || '') ||
                        textLooksLikeOption;
                    const optionTextHasSpec = hasSpecToken(key);
                    const optionTextMatchesIntent = specMatches(key);
                    const optionSpecKinds = specKinds(key);
                    const optionLooksLikeContainer = optionSpecKinds.length > 1 || childSpecCount >= 2;
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
                const dayPattern = (days) => new RegExp(`${days}(?:天|日|day|days)`, 'i');
                const monthPattern = /(?:\d+个月|\d+月会员|三个月|三月会员)/i;
                const quarterPattern = /(?:季卡|季会员|三个月|三月会员|3个月|3月会员)/i;
                const yearPattern = /(?:年卡|年会员|一年卡|两年卡|1年卡|2年卡|一年|两年|1年|2年|12个月|365天)/i;
                const hasSpecToken = (value) => dayPattern(7).test(value) ||
                    dayPattern(15).test(value) || dayPattern(21).test(value) ||
                    monthPattern.test(value) || quarterPattern.test(value) || yearPattern.test(value);
                const specKinds = (value) => {
                    const kinds = [];
                    if (dayPattern(7).test(value)) kinds.push('7d');
                    if (dayPattern(15).test(value)) kinds.push('15d');
                    if (dayPattern(21).test(value)) kinds.push('21d');
                    if (monthPattern.test(value)) kinds.push('month');
                    if (quarterPattern.test(value)) kinds.push('quarter');
                    if (yearPattern.test(value)) kinds.push('year');
                    return kinds;
                };
                const yearCount = (value) => {
                    if (/(?:两年|2年)/.test(value)) return '2';
                    if (/(?:一年|1年)/.test(value)) return '1';
                    return '';
                };
                const specMatches = (value) => {
                    if (intent.spec === '7d') return dayPattern(7).test(value);
                    if (intent.spec === '15d') return dayPattern(15).test(value);
                    if (intent.spec === '21d') return dayPattern(21).test(value);
                    if (intent.spec === 'year') return yearPattern.test(value);
                    return hasSpecToken(value);
                };
                const isSoldOut = (el, text) => {
                    const classText = `${el.className || ''} ${el.getAttribute('aria-disabled') || ''} ${el.getAttribute('disabled') || ''}`.toLowerCase();
                    return Boolean(
                        el.hasAttribute('disabled') ||
                        el.getAttribute('disabled') === 'true' ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        /disabled|soldout|sold-out|empty|invalid|forbid/.test(classText) ||
                        /(?:无库存|售罄|已售罄|暂无库存)/.test(text)
                    );
                };
                const scoreSpec = (text) => {
                    const value = norm(text);
                    let score = 0;
                    if (specMatches(value)) score += 60;
                    if (intent.spec === 'year') {
                        if (yearCount(value) === '2') score += 100;
                        if (yearCount(value) === '1') score += 40;
                        if (yearPattern.test(value)) score += 20;
                    }
                    score -= Math.max(0, value.length - 24) / 4;
                    return score;
                };

                const optionSeen = new Set();
                const optionTexts = [];
                const candidates = [];
                const elements = [];
                document.querySelectorAll('span[class*="option"], span[class*="Option"]').forEach((el) => {
                    if (!visible(el)) return;
                    const text = clean(el.innerText || el.textContent || '');
                    const key = norm(text);
                    if (!key || optionSeen.has(key) || !hasSpecToken(key)) return;
                    optionSeen.add(key);
                    const token = `price-monitor-sku-${elements.length}`;
                    el.setAttribute('data-price-monitor-sku-token', token);
                    elements.push(el);
                    const option = {
                        index: elements.length - 1,
                        token,
                        text,
                        option_price: null,
                        score: scoreSpec(text),
                        kinds: specKinds(key),
                        intent_match: specMatches(key),
                        year_count: yearCount(key),
                        sold_out: isSoldOut(el, text),
                    };
                    optionTexts.push({...option});
                    candidates.push(option);
                });

                candidates.sort((a, b) => b.score - a.score);
                window.__priceMonitorSkuCandidates = elements;
                return {
                    has_options: optionTexts.length >= 2,
                    options: optionTexts,
                    candidates,
                    order_text: clean(document.body.innerText || ''),
                };
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
                    const match = clean(text).match(/[¥￥]\s*(\d+(?:\.\d+)?)/);
                    if (!match) return null;
                    const price = Number.parseFloat(match[1]);
                    return Number.isFinite(price) && price > 0 ? price : null;
                };
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const fromSelector = (selector) => {
                    const items = Array.from(document.querySelectorAll(selector))
                        .filter(visible)
                        .map((el) => toPrice(el.innerText || el.textContent || ''))
                        .filter((price) => price !== null);
                    return items.length ? items[0] : null;
                };
                const moneyPrice = fromSelector('[class*="money"], [class*="Money"]');
                if (moneyPrice !== null) return moneyPrice;
                const singlePrice = fromSelector('[class*="price"], [class*="Price"]');
                if (singlePrice !== null) return singlePrice;
                const candidates = [];
                for (const el of Array.from(document.querySelectorAll('body *'))) {
                    if (!visible(el)) continue;
                    const price = toPrice(el.innerText || el.textContent || '');
                    if (price === null) continue;
                    const context = clean((el.closest('section, div, form, main') || el).textContent || '');
                    let score = 0;
                    if (/(?:实付款|应付款|应付|合计|总计|订单金额|支付金额|需付款)/.test(context)) score += 100;
                    if (/(?:订单信息|购买数量|确认订单|提交订单)/.test(document.body.innerText || '')) score += 30;
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
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const name = Array.from(document.querySelectorAll('[class*="name"], [class*="Name"]'))
                    .filter(visible)
                    .map((el) => clean(el.innerText || el.textContent || ''))
                    .find(Boolean);
                if (name) return name;
                return clean(document.body.innerText || '');
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
