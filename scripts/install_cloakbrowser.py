import os

os.environ["CLOAKBROWSER_BINARY_PATH"] = r"E:\java learning\cloakbrowser-windows-x64\chrome.exe"

from cloakbrowser import ensure_binary

path = ensure_binary()
print(f"CloakBrowser binary ready: {path}")