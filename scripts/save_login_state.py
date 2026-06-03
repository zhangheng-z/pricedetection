import argparse
import asyncio
import json
import platform
import os
import sys
from pathlib import Path

import cloakbrowser.config as cloak_config
from cloakbrowser import launch_persistent_context_async
from playwright.async_api import async_playwright

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from config.loader import ConfigLoader


PLATFORM_URLS = {
    "xianyu": "https://www.goofish.com/",
    "taobao": "https://www.taobao.com/",
}


def patch_cloakbrowser_windows_platform():
    if platform.system() != "Windows" or platform.machine():
        return
    cloak_config.SUPPORTED_PLATFORMS[("Windows", "")] = "windows-x64"


async def launch_cloak_context(args, user_data_dir: Path):
    patch_cloakbrowser_windows_platform()
    if args.binary_path:
        os.environ["CLOAKBROWSER_BINARY_PATH"] = args.binary_path
    user_data_dir.mkdir(parents=True, exist_ok=True)
    return await launch_persistent_context_async(
        str(user_data_dir),
        headless=args.headless,
        locale="zh-CN",
        timezone="Asia/Shanghai",
        viewport={"width": 1366, "height": 768},
        stealth_args=not args.no_stealth_args,
        humanize=not args.no_humanize,
        human_preset=args.human_preset,
        args=["--no-first-run"],
    )


async def launch_playwright_context(args, user_data_dir: Path):
    user_data_dir.mkdir(parents=True, exist_ok=True)
    launch_args = {
        "headless": args.headless,
        "channel": args.channel,
        "args": [
            "--disable-dev-shm-usage",
            "--no-first-run",
        ],
    }
    playwright = await async_playwright().start()
    context = await playwright.chromium.launch_persistent_context(
        str(user_data_dir),
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        viewport={"width": 1366, "height": 768},
        **launch_args,
    )
    original_close = context.close

    async def close_with_playwright():
        try:
            await original_close()
        finally:
            await playwright.stop()

    context.close = close_with_playwright
    return context


async def main():
    parser = argparse.ArgumentParser(description="Open a browser, log in manually, and save storage state.")
    parser.add_argument("--platform", default="xianyu",choices=PLATFORM_URLS.keys())
    parser.add_argument("--account", default="xianyu_a", help="Account id, e.g. xianyu_a")
    parser.add_argument("--output", default="", help="Output JSON path. Defaults to data/auth/{account}.json")
    parser.add_argument("--backend", default="cloakbrowser", choices=["cloakbrowser", "playwright"])
    parser.add_argument("--channel", default="msedge", choices=["msedge", "chrome"], help="Playwright fallback channel.")
    parser.add_argument(
        "--user-data-dir",
        default="",
        help="Persistent browser profile path. Defaults to data/browser_profiles/{account}",
    )
    parser.add_argument("--headless", action="store_true", help="Mostly for CI; manual login needs visible browser.")
    parser.add_argument("--no-stealth-args", action="store_true", help="CloakBrowser only: disable stealth args.")
    parser.add_argument("--no-humanize", action="store_true", help="CloakBrowser only: disable human behavior patching.")
    parser.add_argument("--human-preset", default="careful", choices=["default", "careful"])
    parser.add_argument("--binary-path", default="", help="CloakBrowser only: local chrome.exe/msedge.exe path.")
    parser.add_argument("--wait-file", default="", help="If set, wait until this file exists instead of waiting for Enter.")
    parser.add_argument("--result-file", default="", help="Optional JSON result file to write success/error details.")
    args = parser.parse_args()

    if args.backend == "cloakbrowser" and not args.binary_path:
        args.binary_path = ConfigLoader().load_settings().anti_risk.cloak_binary_path

    output = Path(args.output or f"data/auth/{args.account}.json")
    user_data_dir = Path(args.user_data_dir or f"data/browser_profiles/{args.account}")
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.backend == "cloakbrowser":
        context = await launch_cloak_context(args, user_data_dir)
    else:
        context = await launch_playwright_context(args, user_data_dir)

    try:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(PLATFORM_URLS[args.platform], wait_until="domcontentloaded")

        print()
        print(f"Browser opened with backend: {args.backend}")
        print("1. Log in manually in the opened browser.")
        print("2. Confirm the page shows your logged-in account.")
        if args.wait_file:
            wait_file = Path(args.wait_file)
            wait_file.parent.mkdir(parents=True, exist_ok=True)
            print(f"3. Return to the desktop app and click the confirm/save button.")
            print(f"Waiting for signal file: {wait_file}")
            while not wait_file.exists():
                await asyncio.sleep(0.5)
        else:
            print("3. Return to this terminal and press Enter.")
            input("Press Enter after login is complete...")

        state = await context.storage_state(path=str(output))
        print(f"Saved cookies: {len(state.get('cookies', []))}")
    finally:
        await context.close()

    print(f"Storage state saved: {output}")
    print(f"Persistent profile saved: {user_data_dir}")
    if args.result_file:
        Path(args.result_file).write_text(
            json.dumps(
                {
                    "ok": True,
                    "storage_state": str(output),
                    "user_data_dir": str(user_data_dir),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        argv = sys.argv[1:]
        result_file = ""
        for index, arg in enumerate(argv):
            if arg == "--result-file" and index + 1 < len(argv):
                result_file = argv[index + 1]
                break
        if result_file:
            Path(result_file).write_text(
                json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
                encoding="utf-8",
            )
        raise
