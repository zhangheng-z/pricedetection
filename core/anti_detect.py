import random
import asyncio
from playwright.async_api import Page


class AntiDetect:
    """反检测：浏览器指纹随机化 + 真人行为模拟"""

    CHROME_VERSIONS = [
        "130.0.6723.92",
        "130.0.6723.70",
        "129.0.6668.90",
        "129.0.6668.60",
    ]

    VIEWPORTS = [
        {"width": 1366, "height": 768},
        {"width": 1440, "height": 900},
        {"width": 1536, "height": 864},
        {"width": 1920, "height": 1080},
        {"width": 1280, "height": 720},
    ]

    @staticmethod
    def get_random_viewport():
        return random.choice(AntiDetect.VIEWPORTS)

    @staticmethod
    def get_random_user_agent():
        version = random.choice(AntiDetect.CHROME_VERSIONS)
        return (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{version} Safari/537.36"
        )

    @staticmethod
    def get_browser_args(stealth_mode: bool = False):
        if not stealth_mode:
            return [
                "--no-first-run",
                "--disable-dev-shm-usage",
            ]

        return [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--disable-dev-shm-usage",
        ]

    @staticmethod
    async def random_delay(min_s: float = 0.5, max_s: float = 2.0):
        await asyncio.sleep(random.uniform(min_s, max_s))

    @staticmethod
    async def human_type(page: Page, selector: str, text: str):
        """模拟人类打字：不等速，偶尔删改"""
        await page.click(selector)
        await AntiDetect.random_delay(0.3, 0.8)
        for char in text:
            await page.keyboard.type(char, delay=random.randint(40, 250))
            if random.random() < 0.03 and len(text) > 3:
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.2, 0.5))
                await page.keyboard.type(char, delay=random.randint(30, 100))

    @staticmethod
    async def human_scroll(page: Page, times: int = 3):
        """模拟人类滚动浏览"""
        for _ in range(times):
            scroll_distance = random.randint(300, 700)
            await page.evaluate(
                f"window.scrollBy({{top: {scroll_distance}, behavior: 'smooth'}})"
            )
            await AntiDetect.random_delay(0.8, 2.5)
            if random.random() < 0.3:
                await page.evaluate(
                    f"window.scrollBy({{top: {-random.randint(50, 200)}, behavior: 'smooth'}})"
                )

    @staticmethod
    async def human_mouse_move(page: Page):
        start_x, start_y = random.randint(100, 500), random.randint(100, 500)
        end_x, end_y = random.randint(200, 800), random.randint(200, 600)
        steps = random.randint(8, 15)
        for i in range(steps):
            t = (i + 1) / steps
            x = start_x + (end_x - start_x) * t + random.randint(-5, 5)
            y = start_y + (end_y - start_y) * t + random.randint(-5, 5)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.01, 0.03))
