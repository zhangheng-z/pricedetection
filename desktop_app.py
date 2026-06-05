import asyncio
import json
import sys
from pathlib import Path

from desktop import run_desktop_app
from scripts.save_login_state import main as run_login_helper


def _result_file_from_args() -> str:
    for index, arg in enumerate(sys.argv):
        if arg == "--result-file" and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return ""


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--login-helper":
        sys.argv.pop(1)
        try:
            asyncio.run(run_login_helper())
        except Exception as exc:
            result_file = _result_file_from_args()
            if result_file:
                Path(result_file).write_text(
                    json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
                    encoding="utf-8",
                )
            raise
        raise SystemExit(0)
    raise SystemExit(run_desktop_app())
