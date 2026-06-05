import os
import sys
from pathlib import Path


base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))

playwright_browsers = base_dir / "ms-playwright"
if playwright_browsers.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(playwright_browsers))

cloak_binary = base_dir / "cloakbrowser-windows-x64" / "chrome.exe"
if cloak_binary.exists():
    os.environ.setdefault("CLOAKBROWSER_BINARY_PATH", str(cloak_binary))
