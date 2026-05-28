import json
import hashlib
import hmac
import base64
import time
from typing import Optional
import httpx


class DingTalkPusher:
    """钉钉机器人消息推送"""

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        self.webhook_url = webhook_url
        self.secret = secret

    def _sign(self) -> tuple:
        timestamp = str(round(time.time() * 1000))
        if not self.secret:
            return timestamp, ""
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")
        return timestamp, sign

    def send_markdown(self, content: str) -> bool:
        try:
            timestamp, sign = self._sign()
            url = self.webhook_url
            if sign:
                url = f"{url}&timestamp={timestamp}&sign={sign}"

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "价格监控日报",
                    "text": content,
                },
            }

            resp = httpx.post(url, json=payload, timeout=10)
            result = resp.json()
            if result.get("errcode") != 0:
                print(f"DingTalk send error: {result}")
                return False
            return True
        except Exception as e:
            print(f"DingTalk exception: {e}")
            return False

    def send_text(self, text: str) -> bool:
        try:
            timestamp, sign = self._sign()
            url = self.webhook_url
            if sign:
                url = f"{url}&timestamp={timestamp}&sign={sign}"

            payload = {
                "msgtype": "text",
                "text": {"content": text},
            }
            resp = httpx.post(url, json=payload, timeout=10)
            return resp.json().get("errcode") == 0
        except Exception:
            return False
