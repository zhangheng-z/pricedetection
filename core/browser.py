import random
import asyncio
import json
import platform
import os
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional
import cloakbrowser.config as cloak_config
from cloakbrowser import launch_context_async, launch_persistent_context_async
from cloakbrowser.download import get_binary_path
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from core.anti_detect import AntiDetect


def _patch_cloakbrowser_windows_platform():
    if platform.system() != "Windows" or platform.machine():
        return
    cloak_config.SUPPORTED_PLATFORMS[("Windows", "")] = "windows-x64"


class BrowserManager:
    """Playwright 浏览器生命周期管理"""

    def __init__(
        self,
        proxy: Optional[str] = None,
        headless: bool = False,
        storage_state: Optional[str] = None,
        user_data_dir: Optional[str] = None,
        browser_channel: str = "msedge",
        browser_backend: str = "cloakbrowser",
        cloak_stealth_args: bool = True,
        cloak_humanize: bool = True,
        cloak_human_preset: str = "careful",
        cloak_binary_path: Optional[str] = None,
        cloak_start_timeout_seconds: int = 120,
        stealth_mode: bool = False,
        randomize_user_agent: bool = False,
        randomize_viewport: bool = False,
    ):
        self.proxy = proxy
        self.headless = headless
        self.storage_state = storage_state
        self.user_data_dir = user_data_dir
        self.browser_channel = browser_channel or "msedge"
        self.browser_backend = (browser_backend or "cloakbrowser").lower()
        self.cloak_stealth_args = cloak_stealth_args
        self.cloak_humanize = cloak_humanize
        self.cloak_human_preset = cloak_human_preset or "careful"
        self.cloak_binary_path = cloak_binary_path
        self.cloak_start_timeout_seconds = cloak_start_timeout_seconds
        self.stealth_mode = stealth_mode
        self.randomize_user_agent = randomize_user_agent
        self.randomize_viewport = randomize_viewport
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    async def start(self):
        if self.browser_backend == "cloakbrowser":
            await self._start_cloakbrowser()
            return
        await self._start_playwright()

    async def _start_cloakbrowser(self):
        _patch_cloakbrowser_windows_platform()
        if self.cloak_binary_path:
            os.environ["CLOAKBROWSER_BINARY_PATH"] = self.cloak_binary_path
        else:
            binary_path = get_binary_path()
            if not binary_path.exists():
                raise RuntimeError(
                    "CloakBrowser binary is not installed. Run: "
                    ".\\venv\\Scripts\\python.exe scripts\\install_cloakbrowser.py"
                )
        viewport = AntiDetect.get_random_viewport() if self.randomize_viewport else {"width": 1366, "height": 768}
        launch_kwargs = {
            "headless": self.headless,
            "proxy": self.proxy,
            "args": ["--no-first-run"],
            "stealth_args": self.cloak_stealth_args,
            "locale": "zh-CN",
            "timezone": "Asia/Shanghai",
            "humanize": self.cloak_humanize,
            "human_preset": self.cloak_human_preset,
        }
        context_kwargs = {
            "viewport": viewport,
        }
        if self.randomize_user_agent:
            context_kwargs["user_agent"] = AntiDetect.get_random_user_agent()
        if self.storage_state and Path(self.storage_state).exists() and not self.user_data_dir:
            context_kwargs["storage_state"] = self.storage_state

        profile_label = self.user_data_dir or "temporary"
        print(f"[browser] launching CloakBrowser profile={profile_label}", flush=True)

        if self.user_data_dir:
            Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
            launch_coro = launch_persistent_context_async(
                self.user_data_dir,
                **launch_kwargs,
                **context_kwargs,
            )
        else:
            launch_coro = launch_context_async(
                **launch_kwargs,
                **context_kwargs,
            )
        try:
            self._context = await asyncio.wait_for(
                launch_coro,
                timeout=self.cloak_start_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"CloakBrowser launch timed out after {self.cloak_start_timeout_seconds}s. "
                "Check whether an old browser/profile process is still running, or set "
                "anti_risk.cloak_binary_path in config/settings.yaml."
            ) from exc
        await self._load_storage_state_into_context()
        print("[browser] CloakBrowser launched", flush=True)

    async def _start_playwright(self):
        self._playwright = await async_playwright().start()
        viewport = AntiDetect.get_random_viewport() if self.randomize_viewport else {"width": 1366, "height": 768}
        launch_args = {
            "headless": self.headless,
            "args": AntiDetect.get_browser_args(self.stealth_mode),
        }
        if self.browser_channel:
            launch_args["channel"] = self.browser_channel
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}

        context_args = {
            "viewport": viewport,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }
        if self.randomize_user_agent:
            context_args["user_agent"] = AntiDetect.get_random_user_agent()

        if self.user_data_dir:
            Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
            self._context = await self._playwright.chromium.launch_persistent_context(
                self.user_data_dir,
                **launch_args,
                **context_args,
            )
        else:
            try:
                self._browser = await self._playwright.chromium.launch(**launch_args)
            except PlaywrightError as exc:
                if "Executable doesn't exist" not in str(exc):
                    raise
                fallback_args = dict(launch_args)
                fallback_args.pop("channel", None)
                self._browser = await self._launch_installed_browser(fallback_args)

        if not self._context and self.storage_state and Path(self.storage_state).exists():
            context_args["storage_state"] = self.storage_state
        if not self._context:
            self._context = await self._browser.new_context(**context_args)

        if self.stealth_mode:
            await self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
            """)

        await self._load_storage_state_into_context()

    async def _launch_installed_browser(self, launch_args: dict) -> Browser:
        """Fallback to locally installed Edge/Chrome when Playwright browsers are missing."""
        errors = []
        for channel in ("msedge", "chrome"):
            try:
                return await self._playwright.chromium.launch(channel=channel, **launch_args)
            except PlaywrightError as exc:
                errors.append(f"{channel}: {exc}")
        raise RuntimeError(
            "Playwright Chromium is not installed and no local Edge/Chrome browser could be launched. "
            "Run: .\\venv\\Scripts\\playwright.exe install chromium\n"
            + "\n".join(errors)
        )

    async def stop(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _load_storage_state_into_context(self):
        """Merge saved cookies into persistent contexts that cannot be created from storage_state."""
        if not self._context or not self.storage_state:
            return
        path = Path(self.storage_state)
        if not path.exists():
            return
        try:
            raw_text = path.read_text(encoding="utf-8").strip()
            if not raw_text:
                print(f"[browser] skip empty storage_state file: {path}", flush=True)
                return
            data = json.loads(raw_text)
            cookies = data.get("cookies") or []
            if cookies:
                await self._context.add_cookies(cookies)
                print(f"[browser] loaded {len(cookies)} cookies from {path}", flush=True)
        except Exception as exc:
            print(f"[browser] failed to load storage_state {path}: {exc}", flush=True)

    async def new_page(self) -> Page:
        return await self._context.new_page()

    async def load_cookie_header(self, cookie_header: str, url: str):
        """Load a raw Cookie request header into the current browser context."""
        if not self._context or not cookie_header:
            return

        parsed = urlparse(url)
        domain = parsed.hostname or ""
        if not domain:
            return

        cookies = []
        for item in cookie_header.split(";"):
            if "=" not in item:
                continue
            name, value = item.split("=", 1)
            name = name.strip()
            value = value.strip()
            if not name:
                continue
            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
            })

        if cookies:
            await self._context.add_cookies(cookies)

    async def save_cookies(self, file_path: str = "data/cookies.json"):
        if self._context:
            cookies = await self._context.cookies()
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            import json
            with open(file_path, "w") as f:
                json.dump(cookies, f)

    async def load_cookies(self, file_path: str):
        import json
        path = Path(file_path)
        if path.exists():
            with open(file_path) as f:
                cookies = json.load(f)
            if self._context:
                await self._context.add_cookies(cookies)

    async def save_storage_state(self, file_path: str):
        if not self._context:
            raise RuntimeError("Browser context is not started.")
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(path))
