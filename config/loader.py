import os
import re
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import yaml


class LLMConfig(BaseModel):
    provider: str = "openai_compatible"
    model: str = "deepseek-chat"
    api_key: str = ""
    api_base: str = "https://api.deepseek.com/v1"
    temperature: float = 0.7


class ScheduleConfig(BaseModel):
    runs_per_day: int = 2
    min_interval_hours: int = 6
    time_randomization_minutes: int = 90


class AntiRiskConfig(BaseModel):
    enabled: bool = True
    stop_on_verification: bool = True
    browser_backend: str = "cloakbrowser"
    cloak_stealth_args: bool = True
    cloak_humanize: bool = True
    cloak_human_preset: str = "careful"
    cloak_binary_path: str = ""
    cloak_start_timeout_seconds: int = 120
    stealth_mode: bool = False
    randomize_user_agent: bool = False
    randomize_viewport: bool = False
    search_delay_seconds: List[int] = [5, 10]
    sort_delay_seconds: List[int] = [5, 10]
    page_turn_delay_seconds: List[int] = [10, 30]
    detail_click_delay_seconds: List[int] = [15, 45]
    buy_click_delay_seconds: List[int] = [3, 8]
    per_item_delay_seconds: List[int] = [3, 8]
    post_detail_cooldown_seconds: List[int] = [20, 60]
    max_pages_per_keyword: int = 5
    max_detail_clicks_per_keyword: int = 5
    max_detail_clicks_per_run: int = 8
    verification_poll_seconds: int = 8
    headless_verification_min_visible_seconds: int = 45
    headless_verification_clear_settle_seconds: int = 5
    open_detail_in_new_page: bool = False


class ProxyConfig(BaseModel):
    enabled: bool = False


class DingTalkConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""


class NotificationConfig(BaseModel):
    dingtalk: DingTalkConfig = DingTalkConfig()


class Settings(BaseModel):
    llm: LLMConfig = LLMConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    anti_risk: AntiRiskConfig = AntiRiskConfig()
    proxy: ProxyConfig = ProxyConfig()
    notification: NotificationConfig = NotificationConfig()


class ProductConfig(BaseModel):
    name: str
    official_price: float
    currency: str = "CNY"
    keywords: List[str]
    platforms: List[str]


class AccountConfig(BaseModel):
    platform: str
    id: str
    type: str = "search"
    proxy: str = ""
    browser_channel: str = "msedge"
    user_data_dir: str = ""
    storage_state: str = ""
    cookies_encrypted: str = ""
    last_used: Optional[str] = None
    status: str = "active"


class ConfigLoader:
    """加载所有 YAML 配置文件，支持环境变量替换 ($VAR 语法)"""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(__file__).parent
        self.project_dir = self.config_dir.parent
        self._load_dotenv()

    def _load_dotenv(self):
        env_path = self.project_dir / ".env"
        if not env_path.exists():
            return

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

    def _resolve_env_vars(self, value: Any) -> Any:
        if isinstance(value, str):
            def _replace(match: re.Match) -> str:
                return os.environ.get(match.group(1), "")
            return re.sub(r'\$\{(\w+)\}', _replace, value)
        return value

    def _deep_resolve(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._deep_resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._deep_resolve(v) for v in obj]
        return self._resolve_env_vars(obj)

    def load_settings(self) -> Settings:
        path = self.config_dir / "settings.yaml"
        if not path.exists():
            return Settings()
        with open(path, encoding="utf-8") as f:
            data = self._deep_resolve(yaml.safe_load(f) or {})
        return Settings(**data)

    def load_products(self) -> List[ProductConfig]:
        path = self.config_dir / "products.yaml"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = self._deep_resolve(yaml.safe_load(f) or {})
        return [ProductConfig(**p) for p in data.get("products", [])]

    def load_accounts(self) -> List[AccountConfig]:
        path = self.config_dir / "accounts.yaml"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = self._deep_resolve(yaml.safe_load(f) or {})
        return [AccountConfig(**a) for a in data.get("accounts", [])]

    def load_all(self):
        return {
            "settings": self.load_settings(),
            "products": self.load_products(),
            "accounts": self.load_accounts(),
        }
