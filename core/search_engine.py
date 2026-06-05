import re
import base64
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from playwright.async_api import Page

from core.anti_detect import AntiDetect
from llm.client import LLMClient
from llm.prompts import VISION_PRICE_TEMPLATE


class SearchEngine:
    """Search result extraction: DOM first, vision fallback where needed."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    async def search(self, page: Page, platform: str, keyword: str) -> List[Dict[str, Any]]:
        """Run platform search. Concrete agents implement this."""
        raise NotImplementedError("Implemented by platform agents")

    async def extract_listings(self, page: Page, platform: str) -> List[Dict[str, Any]]:
        """Extract raw listing data from the current search results page."""
        try:
            if platform == "xianyu":
                items = await self._extract_xianyu(page)
            elif platform == "taobao":
                items = await self._extract_taobao(page)
            else:
                items = []

            if not items:
                await self._save_debug_snapshot(page, platform)
            return items
        except Exception as exc:
            print(f"DOM extraction error ({platform}): {exc}")
            await self._save_debug_snapshot(page, platform)
            return []

    async def _extract_xianyu(self, page: Page) -> List[Dict[str, Any]]:
        """Extract Goofish/Xianyu PC search result cards."""
        card_selector = (
            'a[class*="feeds-item-wrap"], '
            '[class*="feeds-list-container"] a[href*="/item?id="]'
        )
        await page.wait_for_selector(card_selector, state="attached", timeout=15000)
        await AntiDetect.random_delay(1, 2)

        return await page.evaluate(
            """
            () => {
                const normalizeUrl = (raw) => {
                    if (!raw) return '';
                    let url = String(raw).trim();
                    if (!url || url === '#' || url.startsWith('javascript:')) return '';
                    if (url.startsWith('//')) url = location.protocol + url;
                    if (url.startsWith('/')) url = location.origin + url;
                    try { return new URL(url, location.href).href; } catch (e) { return ''; }
                };

                const clean = (text) => (text || '').replace(/\\s+/g, ' ').trim();

                const parsePrice = (card) => {
                    const priceWrap = card.querySelector('[class*="price-wrap"]');
                    if (!priceWrap) return 0;

                    const number = clean(priceWrap.querySelector('[class*="number"]')?.textContent || '');
                    const decimal = clean(priceWrap.querySelector('[class*="decimal"]')?.textContent || '');
                    const joined = `${number}${decimal}`.replace(/[^0-9.]/g, '');
                    const price = parseFloat(joined);
                    return Number.isNaN(price) ? 0 : price;
                };

                const getTitle = (card) => {
                    const titleBox = card.querySelector('[class*="row1-wrap-title"]');
                    const attrTitle = clean(titleBox?.getAttribute('title') || '');
                    if (attrTitle) return attrTitle;

                    const mainTitle = clean(card.querySelector('[class*="main-title"]')?.textContent || '');
                    if (mainTitle) return mainTitle;

                    return clean(card.getAttribute('title') || '');
                };

                const getSeller = (card) => {
                    const seller = card.querySelector('[class*="seller-text"]');
                    return clean(seller?.getAttribute('title') || seller?.textContent || '');
                };

                const cards = Array.from(document.querySelectorAll(
                    'a[class*="feeds-item-wrap"], [class*="feeds-list-container"] a[href*="/item?id="]'
                ));
                const seen = new Set();
                const items = [];

                cards.forEach((card) => {
                    const title = getTitle(card);
                    const url = normalizeUrl(card.getAttribute('href'));
                    const key = url || title;
                    if (!title || seen.has(key)) return;
                    seen.add(key);

                    const img = card.querySelector('img[class*="feeds-image"], img');
                    items.push({
                        title,
                        price: parsePrice(card),
                        url,
                        seller: getSeller(card),
                        thumbnail: img ? normalizeUrl(img.getAttribute('src')) : '',
                    });
                });

                return items;
            }
            """
        )

    async def _extract_taobao(self, page: Page) -> List[Dict[str, Any]]:
        """Extract Taobao search result cards with broad selectors."""
        await AntiDetect.random_delay(1, 3)
        return await page.evaluate(
            """
            () => {
                const items = [];
                const normalizeUrl = (raw) => {
                    if (!raw) return '';
                    let url = String(raw).trim();
                    if (!url || url === '#' || url.startsWith('javascript:')) return '';
                    if (url.startsWith('//')) url = location.protocol + url;
                    if (url.startsWith('/')) url = location.origin + url;
                    try { return new URL(url, location.href).href; } catch (e) { return ''; }
                };
                const findUrl = (card) => {
                    const link = card.querySelector('a[href]');
                    const href = normalizeUrl(link && link.getAttribute('href'));
                    if (href) return href;

                    const html = card.outerHTML || '';
                    const urlMatch = html.match(/https?:\/\/[^"'<>\s]*(?:item|taobao)[^"'<>\s]*/i);
                    if (urlMatch) return normalizeUrl(urlMatch[0].replace(/&amp;/g, '&'));

                    const idMatch = html.match(/(?:itemId|item_id|id)["'=: ]+(\d{8,})/i);
                    if (idMatch) return 'https://item.taobao.com/item.htm?id=' + idMatch[1];
                    return '';
                };
                const clean = (text) => (text || '').replace(/\\s+/g, ' ').trim();
                const parsePrice = (card) => {
                    const texts = Array.from(card.querySelectorAll('*'))
                        .map((el) => clean(el.textContent || ''))
                        .filter(Boolean);
                    const scored = [];
                    for (const text of texts) {
                        const match = text.match(/[\\u00a5\\uffe5]\\s*(\\d+(?:\\.\\d+)?)/);
                        if (!match) continue;
                        const price = Number.parseFloat(match[1]);
                        if (!Number.isFinite(price) || price <= 0) continue;
                        let score = 0;
                        if (/(?:优惠后|券后|到手|平台加补后|补后)/.test(text)) score += 80;
                        if (/(?:优惠券|平台礼金|券满|补贴)/.test(text)) score += 20;
                        if (/(?:优惠前|划线价|原价|市场价)/.test(text)) score -= 80;
                        score -= Math.max(0, text.length - 80) / 8;
                        scored.push({price, score});
                    }
                    scored.sort((a, b) => b.score - a.score);
                    if (scored.length) return scored[0].price;

                    const fallback = clean(card.textContent || '').match(/[\\u00a5\\uffe5]\\s*(\\d+(?:\\.\\d+)?)/);
                    return fallback ? Number.parseFloat(fallback[1]) || 0 : 0;
                };
                const getTitle = (card) => {
                    const titleEl = card.querySelector('[class*="title"], [class*="Title"], [title]');
                    const attrTitle = clean(titleEl?.getAttribute('title') || '');
                    if (attrTitle) return attrTitle;
                    const text = clean(titleEl?.textContent || '');
                    if (text) return text;
                    return clean(card.textContent || '').slice(0, 120);
                };
                const getSeller = (card) => {
                    const seller = card.querySelector('[class*="shop"], [class*="Shop"], [class*="seller"], [class*="Seller"]');
                    return clean(seller?.textContent || '');
                };

                const cardForLink = (link) => {
                    let current = link;
                    let best = link;
                    for (let depth = 0; current && depth < 7; depth += 1) {
                        const text = clean(current.textContent || '');
                        if (/[\\u00a5\\uffe5]\\s*\\d/.test(text) && text.length < 1600) best = current;
                        current = current.parentElement;
                    }
                    return best;
                };
                const links = Array.from(document.querySelectorAll('a[href*="item"], a[href*="detail"]'));
                const cards = links
                    .map(cardForLink)
                    .concat(Array.from(document.querySelectorAll('[data-spm-anchor-id]')));
                const seen = new Set();
                cards.forEach(card => {
                    const url = findUrl(card);
                    const title = getTitle(card);
                    if (!title) return;
                    const key = url || title;
                    if (seen.has(key)) return;
                    seen.add(key);

                    const img = card.querySelector('img');
                    items.push({
                        title,
                        price: parsePrice(card),
                        url,
                        seller: getSeller(card),
                        thumbnail: img ? normalizeUrl(img.getAttribute('src')) : '',
                    });
                });
                return items;
            }
            """
        )

    async def _save_debug_snapshot(self, page: Page, platform: str) -> None:
        try:
            output_dir = Path("data/debug")
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base = output_dir / f"{timestamp}_{platform}"
            await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
            base.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
            print(f"[{platform}] no DOM items extracted, debug snapshot saved: {base}.png/.html", flush=True)
        except Exception as exc:
            print(f"[{platform}] failed to save debug snapshot: {exc}", flush=True)

    async def vision_extract_price(self, page: Page) -> Optional[float]:
        """Use a vision-capable LLM to read a price from the viewport."""
        if not self.llm:
            return None

        try:
            screenshot = await page.screenshot(type="png", full_page=False)
            img_b64 = base64.b64encode(screenshot).decode()

            if self.llm.config.provider == "anthropic":
                client = self.llm._get_anthropic_client()
                response = client.messages.create(
                    model=self.llm.config.model,
                    max_tokens=256,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": VISION_PRICE_TEMPLATE},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": img_b64,
                                    },
                                },
                            ],
                        }
                    ],
                )
                self.llm.record_usage(response)
                text = response.content[0].text.strip()
            else:
                client = self.llm._get_openai_client()
                response = client.chat.completions.create(
                    model=self.llm.config.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": VISION_PRICE_TEMPLATE},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                                },
                            ],
                        }
                    ],
                    temperature=0,
                )
                self.llm.record_usage(response)
                text = response.choices[0].message.content.strip()

            if text and text != "null":
                return float(re.sub(r"[^0-9.]", "", text))
        except Exception as exc:
            print(f"Vision extraction error: {exc}")
        return None

    def price_from_title_fallback(self, title: str) -> Optional[float]:
        """Fallback price extraction from a title string."""
        patterns = [
            r"(\\d+\\.?\\d*)\\s*\\u5143",
            r"[\\u00a5\\uffe5]\\s*(\\d+\\.?\\d*)",
            r"(\\d+\\.?\\d*)\\s*CNY",
            r"(\\d+\\.?\\d*)\\s*RMB",
        ]
        for pattern in patterns:
            match = re.search(pattern, title, flags=re.IGNORECASE)
            if not match:
                continue
            value = float(match.group(1))
            if 0.01 < value < 100000:
                return value
        return None
