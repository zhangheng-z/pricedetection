import random
from playwright.async_api import Page
from agents.base_agent import BaseAgent
from core.anti_detect import AntiDetect


class TaobaoAgent(BaseAgent):
    PLATFORM = "taobao"

    async def _do_search(self, page: Page, keyword: str):
        await page.goto("https://www.taobao.com/", wait_until="networkidle")
        await AntiDetect.random_delay(3, 5)

        selectors = [
            'input[class*="search"]',
            'input[class*="Search"]',
            'input[placeholder*="搜索"]',
            '#q',
            'form[action*="search"] input',
        ]
        selector = None
        for sel in selectors:
            el = await page.query_selector(sel)
            if el:
                selector = sel
                break

        await AntiDetect.human_type(page, selector or "input[type=text]", keyword)
        await AntiDetect.random_delay(0.5, 1.5)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("networkidle")
        await self._anti_risk_delay("search_delay_seconds", "after search")
        sorted_ok = await self._click_price_asc_sort(page)
        print(f"[{self.PLATFORM}] price ascending sort: {'clicked' if sorted_ok else 'not found'}", flush=True)
        await self._anti_risk_delay("sort_delay_seconds", "after sort")
        await AntiDetect.human_scroll(page, times=random.randint(2, 3))
