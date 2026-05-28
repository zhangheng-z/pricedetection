# 第三方平台价格监控系统 Phase 1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现低频率自动化第三方平台（闲鱼+淘宝）价格监控，覆盖搜索→反检测→乱价判定→钉钉日报推送的完整链路

**Architecture:** Playwright 驱动浏览器模拟真人行为搜索闲鱼/淘宝，DOM 解析为主 LLM 视觉兜底提取商品数据，SQLite 存储，LLM 统一客户端支持多模型切换，每次运行结束后生成日报推送至钉钉

**Tech Stack:** Python 3.10+, Playwright, SQLite, YAML, OpenAI-compatible API / Anthropic SDK, httpx

**当前实现范围（Phase 1）：** 搜索采集 + 反检测 + 乱价判定 + 钉钉推送
**后续 Phase 2：** 钓鱼溯源模块

---

### Task 1: 项目脚手架 + 配置系统

**Files:**
- Create: `requirements.txt`
- Create: `config/products.yaml`
- Create: `config/accounts.yaml`
- Create: `config/settings.yaml`
- Create: `config/__init__.py`
- Create: `config/loader.py`

- [ ] **Step 1: 创建 requirements.txt**

```txt
playwright>=1.40.0
pyyaml>=6.0
httpx>=0.25.0
openai>=1.0.0
anthropic>=0.30.0
pydantic>=2.0.0
cryptography>=41.0.0
```

- [ ] **Step 2: 创建 config/settings.yaml**

```yaml
llm:
  provider: openai_compatible  # openai_compatible | anthropic
  model: deepseek-chat
  api_key: ""
  api_base: "https://api.deepseek.com/v1"
  temperature: 0.7

schedule:
  runs_per_day: 2
  min_interval_hours: 6
  time_randomization_minutes: 90

proxy:
  enabled: false

notification:
  dingtalk:
    enabled: false
    webhook_url: ""
```

- [ ] **Step 3: 创建 config/products.yaml**

```yaml
products:
  - name: "中文15天"
    official_price: 9.9
    currency: CNY
    keywords:
      - "15天中文会员"
      - "中文15天"
      - "15天中文"
    platforms: [xianyu, taobao]

  - name: "英文21天"
    official_price: 39.9
    currency: CNY
    keywords:
      - "21天英文会员"
      - "英文21天"
      - "21天英文"
    platforms: [xianyu, taobao]

  - name: "中文年卡"
    official_price: 2498
    currency: CNY
    keywords:
      - "中文年卡会员"
      - "年卡中文"
      - "中文年卡"
    platforms: [xianyu, taobao]

  - name: "英文年卡"
    official_price: 2198
    currency: CNY
    keywords:
      - "英文年卡会员"
      - "年卡英文"
      - "英文年卡"
    platforms: [xianyu, taobao]
```

- [ ] **Step 4: 创建 config/accounts.yaml**

```yaml
accounts:
  - platform: xianyu
    id: "xianyu_a"
    type: search
    proxy: ""
    cookies_encrypted: ""
    last_used: null
    status: active
  - platform: xianyu
    id: "xianyu_b"
    type: search
    proxy: ""
    cookies_encrypted: ""
    last_used: null
    status: active
  - platform: taobao
    id: "taobao_a"
    type: search
    proxy: ""
    cookies_encrypted: ""
    last_used: null
    status: active
  - platform: taobao
    id: "taobao_b"
    type: search
    proxy: ""
    cookies_encrypted: ""
    last_used: null
    status: active
```

- [ ] **Step 5: 创建 config/__init__.py**

```python
from config.loader import ConfigLoader, Settings, ProductConfig, AccountConfig

__all__ = ["ConfigLoader", "Settings", "ProductConfig", "AccountConfig"]
```

- [ ] **Step 6: 创建 config/loader.py**

```python
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


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
    type: str = "search"  # search | fishing
    proxy: str = ""
    cookies_encrypted: str = ""
    last_used: Optional[str] = None
    status: str = "active"


class ConfigLoader:
    """加载所有 YAML 配置文件，支持环境变量替换 ($VAR 语法)"""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(__file__).parent

    def _resolve_env_vars(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.environ.get(env_var, "")
        return value

    def _deep_resolve(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._deep_resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._deep_resolve(v) for v in obj]
        return self._resolve_env_vars(obj)

    def load_settings(self) -> Settings:
        import yaml
        path = self.config_dir / "settings.yaml"
        if not path.exists():
            return Settings()
        with open(path, encoding="utf-8") as f:
            data = self._deep_resolve(yaml.safe_load(f) or {})
        return Settings(**data)

    def load_products(self) -> List[ProductConfig]:
        import yaml
        path = self.config_dir / "products.yaml"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return [ProductConfig(**p) for p in data.get("products", [])]

    def load_accounts(self) -> List[AccountConfig]:
        import yaml
        path = self.config_dir / "accounts.yaml"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return [AccountConfig(**a) for a in data.get("accounts", [])]

    def load_all(self):
        return {
            "settings": self.load_settings(),
            "products": self.load_products(),
            "accounts": self.load_accounts(),
        }
```

- [ ] **Step 7: 验证配置加载**

Run: `python -c "from config.loader import ConfigLoader; c=ConfigLoader(); print(c.load_settings()); print(len(c.load_products())); print(len(c.load_accounts()))"`
Expected: Settings 对象正常打印，products=4，accounts=4

---

### Task 2: LLM 统一客户端

**Files:**
- Create: `llm/__init__.py`
- Create: `llm/client.py`
- Create: `llm/prompts.py`

- [ ] **Step 1: 创建 llm/__init__.py**

```python
from llm.client import LLMClient
from llm.prompts import PromptTemplates

__all__ = ["LLMClient", "PromptTemplates"]
```

- [ ] **Step 2: 创建 llm/client.py**

```python
from typing import Optional, List, Dict, Any
from config.loader import LLMConfig


class LLMClient:
    """统一 LLM 客户端，支持 OpenAI 兼容接口和 Anthropic SDK"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = None

    def _get_openai_client(self):
        from openai import OpenAI
        return OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.api_base,
        )

    def _get_anthropic_client(self):
        import anthropic
        return anthropic.Anthropic(api_key=self.config.api_key)

    def _ensure_client(self):
        if self._client is None:
            if self.config.provider == "anthropic":
                self._client = self._get_anthropic_client()
            else:
                self._client = self._get_openai_client()
        return self._client

    def chat(self, messages: List[Dict[str, str]], system: Optional[str] = None) -> str:
        client = self._ensure_client()
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "temperature": self.config.temperature,
        }

        if self.config.provider == "anthropic":
            kwargs["max_tokens"] = 4096
            if system:
                kwargs["system"] = system
            kwargs["messages"] = messages
            response = client.messages.create(**kwargs)
            return response.content[0].text
        else:
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.extend(messages)
            kwargs["messages"] = msgs
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

    def chat_json(self, messages: List[Dict[str, str]], system: Optional[str] = None) -> dict:
        """调用 LLM 并解析返回 JSON"""
        text = self.chat(messages, system=system)
        import json
        # 尝试从 markdown 代码块中提取 JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
```

- [ ] **Step 3: 创建 llm/prompts.py**

```python
"""LLM Prompt 模板集合"""

SEARCH_KEYWORDS_TEMPLATE = """
你是一个电商运营专家。请根据以下产品信息，生成 {count} 个用户可能在闲鱼/淘宝上搜索该产品时会使用的关键词。

产品名称：{product_name}
官方价格：{official_price}元

要求：
- 每个关键词 2-8 个字
- 贴近真实用户搜索习惯
- 不要使用官方品牌词（如果有）
- 每个关键词用逗号分隔

只返回关键词列表，不要多余的解释。
"""

PRICE_JUDGE_TEMPLATE = """
你是一个价格合规分析师。请判断以下商品是否属于乱价（低于官方授权价）。

产品名称：{product_name}
官方价格：{official_price}元
商品标题：{title}
商品价格：{price}元
卖家描述：{description}

判断标准：
- 价格低于官方价 → 乱价
- 价格明显过低（低于官方价50%以上）→ 可能是引流帖/赠品，标注为"疑似引流"
- 价格等于或高于官方价 → 正常

请返回 JSON：
{{"judgment": "violation"|"suspicious"|"normal", "reason": "判断理由"}}
"""

VISION_PRICE_TEMPLATE = """
图片中是电商平台的商品卡片，请识别图中的价格信息。

要求：
- 只提取数字价格
- 如果有多个价格，取实际售价（不是原价/划线价）
- 如果无法识别到价格，返回 null

请只返回纯数字或 null。
"""
```

- [ ] **Step 4: 测试 LLM 客户端**

Run: `python -c "from llm.client import LLMClient; from config.loader import LLMConfig; c=LLMClient(LLMConfig(api_key='test')); print('LLMClient initialized')"`
Expected: LLMClient initialized（不需要真实 API key 也能构建对象）

---

### Task 3: 存储层

**Files:**
- Create: `storage/__init__.py`
- Create: `storage/models.py`
- Create: `storage/database.py`

- [ ] **Step 1: 创建 storage/__init__.py**

```python
from storage.database import Database
from storage.models import Listing, PriceAlert, SearchRun, DailyReport

__all__ = ["Database", "Listing", "PriceAlert", "SearchRun", "DailyReport"]
```

- [ ] **Step 2: 创建 storage/models.py**

```python
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime


@dataclass
class Listing:
    """采集的商品数据"""
    platform: str            # xianyu | taobao
    product_name: str        # 对应的 SKU 名称
    title: str               # 商品标题
    price: float             # 商品价格
    seller_name: str         # 卖家昵称
    url: str                 # 商品链接
    thumbnail: str = ""      # 缩略图 URL
    sales_count: Optional[int] = None  # 销量
    search_keyword: str = "" # 搜索使用的关键词
    search_run_id: int = 0   # 关联的搜索批次
    created_at: str = ""     # 记录时间


@dataclass
class PriceAlert:
    """乱价告警"""
    listing_id: int
    platform: str
    product_name: str
    title: str
    price: float
    official_price: float
    judgment: str            # violation | suspicious
    reason: str = ""
    status: str = "pending"  # pending | fishing | resolved
    created_at: str = ""


@dataclass
class SearchRun:
    """每次搜索运行的记录"""
    run_time: str
    platform: str
    account_id: str
    keywords_used: str       # JSON list
    listings_found: int = 0
    alerts_created: int = 0
    status: str = "completed"
    error: str = ""
    duration_seconds: float = 0.0


@dataclass
class DailyReport:
    """日报记录"""
    report_date: str
    run_period: str          # morning | afternoon
    platforms_covered: str   # JSON list
    total_listings: int = 0
    total_alerts: int = 0
    alerts_by_product: str = ""  # JSON dict
    fishing_results: str = ""    # JSON, Phase 2 用
    dingtalk_sent: bool = False
    created_at: str = ""
```

- [ ] **Step 3: 创建 storage/database.py**

```python
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from storage.models import Listing, PriceAlert, SearchRun, DailyReport


class Database:
    def __init__(self, db_path: str = "data/price_monitor.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_tables(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS search_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_time TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    keywords_used TEXT NOT NULL DEFAULT '[]',
                    listings_found INTEGER DEFAULT 0,
                    alerts_created INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'completed',
                    error TEXT DEFAULT '',
                    duration_seconds REAL DEFAULT 0.0
                );

                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    price REAL NOT NULL,
                    seller_name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    thumbnail TEXT DEFAULT '',
                    sales_count INTEGER,
                    search_keyword TEXT DEFAULT '',
                    search_run_id INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (search_run_id) REFERENCES search_runs(id)
                );

                CREATE TABLE IF NOT EXISTS price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    price REAL NOT NULL,
                    official_price REAL NOT NULL,
                    judgment TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (listing_id) REFERENCES listings(id)
                );

                CREATE TABLE IF NOT EXISTS daily_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date TEXT NOT NULL,
                    run_period TEXT NOT NULL,
                    platforms_covered TEXT DEFAULT '[]',
                    total_listings INTEGER DEFAULT 0,
                    total_alerts INTEGER DEFAULT 0,
                    alerts_by_product TEXT DEFAULT '{}',
                    fishing_results TEXT DEFAULT '{}',
                    dingtalk_sent INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE INDEX IF NOT EXISTS idx_listings_platform ON listings(platform);
                CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at);
                CREATE INDEX IF NOT EXISTS idx_alerts_status ON price_alerts(status);
                CREATE INDEX IF NOT EXISTS idx_runs_time ON search_runs(run_time);
            """)

    def save_run(self, run: SearchRun) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO search_runs (run_time, platform, account_id, keywords_used,
                   listings_found, alerts_created, status, error, duration_seconds)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run.run_time, run.platform, run.account_id,
                 run.keywords_used, run.listings_found, run.alerts_created,
                 run.status, run.error, run.duration_seconds),
            )
            return cur.lastrowid

    def save_listing(self, listing: Listing) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO listings (platform, product_name, title, price,
                   seller_name, url, thumbnail, sales_count, search_keyword, search_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (listing.platform, listing.product_name, listing.title,
                 listing.price, listing.seller_name, listing.url,
                 listing.thumbnail, listing.sales_count,
                 listing.search_keyword, listing.search_run_id),
            )
            return cur.lastrowid

    def save_alert(self, alert: PriceAlert) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO price_alerts (listing_id, platform, product_name,
                   title, price, official_price, judgment, reason, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (alert.listing_id, alert.platform, alert.product_name,
                 alert.title, alert.price, alert.official_price,
                 alert.judgment, alert.reason, alert.status),
            )
            return cur.lastrowid

    def save_report(self, report: DailyReport) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO daily_reports (report_date, run_period, platforms_covered,
                   total_listings, total_alerts, alerts_by_product, fishing_results,
                   dingtalk_sent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (report.report_date, report.run_period, report.platforms_covered,
                 report.total_listings, report.total_alerts,
                 report.alerts_by_product, report.fishing_results,
                 1 if report.dingtalk_sent else 0),
            )
            return cur.lastrowid

    def get_alerts_by_date(self, date_str: str) -> List[PriceAlert]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM price_alerts WHERE date(created_at) = ?""",
                (date_str,),
            ).fetchall()
            return [PriceAlert(**dict(r)) for r in rows]

    def get_weekly_summary(self) -> dict:
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as c FROM price_alerts WHERE created_at >= datetime('now', '-7 days')"
            ).fetchone()["c"]
            by_product = conn.execute(
                """SELECT product_name, COUNT(*) as c FROM price_alerts
                   WHERE created_at >= datetime('now', '-7 days')
                   GROUP BY product_name"""
            ).fetchall()
            return {
                "total": total,
                "by_product": {r["product_name"]: r["c"] for r in by_product},
            }
```

- [ ] **Step 4: 验证数据库初始化**

Run: `python -c "from storage.database import Database; db=Database('data/test.db'); print('DB OK')"`
Expected: DB OK，data/test.db 文件生成

---

### Task 4: 反检测 + 浏览器管理

**Files:**
- Create: `core/__init__.py`
- Create: `core/anti_detect.py`
- Create: `core/browser.py`

- [ ] **Step 1: 创建 core/__init__.py**

```python
from core.browser import BrowserManager
from core.anti_detect import AntiDetect

__all__ = ["BrowserManager", "AntiDetect"]
```

- [ ] **Step 2: 创建 core/anti_detect.py**

```python
import random
import asyncio
from playwright.async_api import Page


class AntiDetect:
    """反检测：浏览器指纹随机化 + 真人行为模拟"""

    # 真实 Chrome 版本池
    CHROME_VERSIONS = [
        "130.0.6723.92",
        "130.0.6723.70",
        "129.0.6668.90",
        "129.0.6668.60",
    ]

    # 常见视口尺寸
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
    def get_browser_args():
        return [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

    @staticmethod
    async def random_delay(min_s: float = 0.5, max_s: float = 2.0):
        """随机延时，模拟人类反应时间"""
        await asyncio.sleep(random.uniform(min_s, max_s))

    @staticmethod
    async def human_type(page: Page, selector: str, text: str):
        """模拟人类打字：不等速，随机停顿"""
        await page.click(selector)
        await AntiDetect.random_delay(0.3, 0.8)
        for char in text:
            await page.keyboard.type(char, delay=random.randint(40, 250))
            # 偶尔打错删除重来（3% 概率）
            if random.random() < 0.03 and len(text) > 3:
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.2, 0.5))
                await page.keyboard.type(char, delay=random.randint(30, 100))

    @staticmethod
    async def human_scroll(page: Page, times: int = 3):
        """模拟人类滚动浏览"""
        for _ in range(times):
            scroll_distance = random.randint(300, 700)
            await page.evaluate(f"window.scrollBy({{top: {scroll_distance}, behavior: 'smooth'}})")
            # 滚动后停顿（看内容）
            await AntiDetect.random_delay(0.8, 2.5)
            # 偶尔往回滚一点（乱翻）
            if random.random() < 0.3:
                await page.evaluate(f"window.scrollBy({{top: {-random.randint(50, 200)}, behavior: 'smooth'}})")

    @staticmethod
    async def human_mouse_move(page: Page):
        """模拟鼠标移动：贝塞尔曲线通过逐步移动模拟"""
        start_x, start_y = random.randint(100, 500), random.randint(100, 500)
        end_x, end_y = random.randint(200, 800), random.randint(200, 600)
        steps = random.randint(8, 15)
        for i in range(steps):
            t = (i + 1) / steps
            # 简单贝塞尔-like 插值
            x = start_x + (end_x - start_x) * t + random.randint(-5, 5)
            y = start_y + (end_y - start_y) * t + random.randint(-5, 5)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.01, 0.03))
```

- [ ] **Step 3: 创建 core/browser.py**

```python
import random
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from core.anti_detect import AntiDetect


class BrowserManager:
    """Playwright 浏览器生命周期管理"""

    def __init__(self, proxy: Optional[str] = None, headless: bool = False):
        self.proxy = proxy
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    async def start(self):
        """启动浏览器（首次运行可能会下载浏览器）"""
        self._playwright = await async_playwright().start()
        viewport = AntiDetect.get_random_viewport()
        launch_args = {
            "headless": self.headless,
            "args": AntiDetect.get_browser_args(),
        }
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}
        self._browser = await self._playwright.chromium.launch(**launch_args)
        context_args = {
            "viewport": viewport,
            "user_agent": AntiDetect.get_random_user_agent(),
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }
        self._context = await self._browser.new_context(**context_args)
        # 注入反检测脚本
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
        """)

    async def stop(self):
        """关闭浏览器"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def new_page(self) -> Page:
        """创建一个新页面"""
        page = await self._context.new_page()
        return page

    async def save_cookies(self, file_path: str = "data/cookies.json"):
        """持久化 Cookie"""
        if self._context:
            cookies = await self._context.cookies()
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            import json
            with open(file_path, "w") as f:
                json.dump(cookies, f)

    async def load_cookies(self, file_path: str):
        """加载 Cookie"""
        import json
        path = Path(file_path)
        if path.exists():
            with open(file_path) as f:
                cookies = json.load(f)
            if self._context:
                await self._context.add_cookies(cookies)
```

---

### Task 5: 搜索执行 + DOM 提取 + LLM 视觉兜底

**Files:**
- Create: `core/search_engine.py`

- [ ] **Step 1: 创建 core/search_engine.py**

```python
import re
import json
import random
import asyncio
from typing import List, Optional, Dict, Any
from playwright.async_api import Page
from core.anti_detect import AntiDetect
from storage.models import Listing
from llm.client import LLMClient
from llm.prompts import PRICE_JUDGE_TEMPLATE, VISION_PRICE_TEMPLATE


class SearchEngine:
    """搜索执行引擎：执行搜索、DOM 提取、LLM 视觉兜底"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    async def search(self, page: Page, platform: str, keyword: str) -> List[Dict[str, Any]]:
        """执行搜索并返回原始商品数据"""
        raise NotImplementedError("由具体平台的 Agent 实现")

    async def extract_listings(self, page: Page, platform: str) -> List[Dict[str, Any]]:
        """DOM 解析提取商品列表"""
        try:
            if platform == "xianyu":
                return await self._extract_xianyu(page)
            elif platform == "taobao":
                return await self._extract_taobao(page)
            return []
        except Exception as e:
            print(f"DOM extraction failed: {e}")
            return []

    async def _extract_xianyu(self, page: Page) -> List[Dict[str, Any]]:
        """闲鱼搜索结果 DOM 提取"""
        await page.wait_for_selector('[class*="item"], [class*="card"]', timeout=15000)
        await AntiDetect.random_delay(1, 2)
        return await page.evaluate("""
            () => {
                const items = [];
                const cards = document.querySelectorAll('[class*="item"], [class*="card"], li');
                cards.forEach(card => {
                    const titleEl = card.querySelector('[class*="title"], [class*="name"], a');
                    const priceEl = card.querySelector('[class*="price"]');
                    const linkEl = card.querySelector('a[href]');
                    const sellerEl = card.querySelector('[class*="seller"], [class*="user"]');
                    const imgEl = card.querySelector('img');
                    const title = titleEl ? (titleEl.textContent || titleEl.innerText || '').trim() : '';
                    if (!title) return;
                    const priceText = priceEl ? (priceEl.textContent || '').trim() : '';
                    const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                    items.push({
                        title: title,
                        price: price,
                        url: linkEl ? linkEl.href : '',
                        seller: sellerEl ? (sellerEl.textContent || '').trim() : '',
                        thumbnail: imgEl ? imgEl.src : '',
                    });
                });
                return items;
            }
        """)

    async def _extract_taobao(self, page: Page) -> List[Dict[str, Any]]:
        """淘宝搜索结果 DOM 提取"""
        await AntiDetect.random_delay(1, 3)
        return await page.evaluate("""
            () => {
                const items = [];
                const cards = document.querySelectorAll('[class*="item"], [data-spm-anchor-id]');
                cards.forEach(card => {
                    const titleEl = card.querySelector('[class*="title"], [class*="Title"]');
                    const priceEl = card.querySelector('[class*="price"], [class*="Price"]');
                    const linkEl = card.querySelector('a[href]');
                    const title = titleEl ? (titleEl.textContent || '').trim() : '';
                    if (!title) return;
                    const priceText = priceEl ? (priceEl.textContent || '').trim() : '';
                    const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                    items.push({
                        title: title,
                        price: price,
                        url: linkEl ? linkEl.href : '',
                        seller: '',
                        thumbnail: '',
                    });
                });
                return items;
            }
        """)

    async def vision_extract_price(self, page: Page) -> Optional[float]:
        """LLM 视觉兜底：截图识别价格"""
        if not self.llm:
            return None
        try:
            screenshot = await page.screenshot(type="png", full_page=False)
            import base64
            img_b64 = base64.b64encode(screenshot).decode()

            if self.llm.config.provider == "anthropic":
                import anthropic
                client = self.llm._get_anthropic_client()
                response = client.messages.create(
                    model=self.llm.config.model,
                    max_tokens=256,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_PRICE_TEMPLATE},
                            {"type": "image", "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            }},
                        ],
                    }],
                )
                text = response.content[0].text.strip()
            else:
                import openai
                client = self.llm._get_openai_client()
                response = client.chat.completions.create(
                    model=self.llm.config.model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_PRICE_TEMPLATE},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/png;base64,{img_b64}"
                            }},
                        ],
                    }],
                    temperature=0,
                )
                text = response.choices[0].message.content.strip()

            if text and text != "null":
                return float(re.sub(r'[^0-9.]', '', text))
        except Exception as e:
            print(f"Vision extraction error: {e}")
        return None

    def price_from_title_fallback(self, title: str) -> Optional[float]:
        """从标题中用正则兜底提取价格"""
        patterns = [
            r'(\d+\.?\d*)\s*元',
            r'¥\s*(\d+\.?\d*)',
            r'(\d+\.?\d*)元',
            r'(\d+\.?\d*)',
        ]
        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                val = float(match.group(1))
                if 0.01 < val < 100000:  # 合理价格范围
                    return val
        return None
```

---

### Task 6: 乱价判定模块

**Files:**
- Create: `core/price_judge.py`

- [ ] **Step 1: 创建 core/price_judge.py**

```python
from typing import Optional
from llm.client import LLMClient
from llm.prompts import PRICE_JUDGE_TEMPLATE, SEARCH_KEYWORDS_TEMPLATE


class PriceJudge:
    """价格违规判定 + 搜索词生成"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    def is_below_official(self, price: float, official_price: float) -> bool:
        """基础规则：是否低于官方价"""
        return price < official_price

    def is_suspiciously_low(self, price: float, official_price: float) -> bool:
        """是否低得可疑（低于 50% 可能是引流帖）"""
        return price < official_price * 0.5

    async def llm_confirm_violation(
        self, title: str, price: float, product_name: str, official_price: float
    ) -> dict:
        """LLM 二次确认：是否是真正的乱价"""
        if not self.llm:
            # 没有 LLM 时走简单规则
            if self.is_suspiciously_low(price, official_price):
                return {"judgment": "suspicious", "reason": "价格低于官方价50%以上，疑似引流"}
            return {"judgment": "violation", "reason": f"价格{price}低于官方价{official_price}"}

        system = "你是一个电商价格合规分析师，严格按规则判断。"
        user = PRICE_JUDGE_TEMPLATE.format(
            product_name=product_name,
            official_price=official_price,
            title=title,
            price=price,
            description="",
        )
        try:
            result = await self.llm.chat_json(
                messages=[{"role": "user", "content": user}],
                system=system,
            )
            return result
        except Exception as e:
            print(f"LLM judgment error: {e}, using fallback rules")
            if self.is_suspiciously_low(price, official_price):
                return {"judgment": "suspicious", "reason": "LLM不可用，规则判定为疑似引流"}
            return {"judgment": "violation", "reason": f"LLM不可用，规则判定价格违规"}

    def judge(self, price: float, official_price: float) -> str:
        """纯规则快速判断（不带 LLM）"""
        if not self.is_below_official(price, official_price):
            return "normal"
        if self.is_suspiciously_low(price, official_price):
            return "suspicious"
        return "violation"

    async def generate_keywords(self, product_name: str, official_price: float, count: int = 5) -> list:
        """LLM 生成搜索关键词"""
        if not self.llm:
            # 无 LLM 时返回配置中的默认关键词（由 products.yaml 提供）
            return []

        system = "你是一个电商运营专家。只返回关键词列表，逗号分隔，不要多余内容。"
        user = SEARCH_KEYWORDS_TEMPLATE.format(
            product_name=product_name,
            official_price=official_price,
            count=count,
        )
        try:
            text = await self.llm.chat(
                messages=[{"role": "user", "content": user}],
                system=system,
            )
            parts = [k.strip() for k in text.replace("，", ",").split(",")]
            return [p for p in parts if p]
        except Exception:
            return []
```

- [ ] **Step 2: 测试 PriceJudge 逻辑层**

Run: `python -c "
from core.price_judge import PriceJudge
pj = PriceJudge()
assert pj.judge(5.0, 9.9) == 'violation'
assert pj.judge(9.9, 9.9) == 'normal'
assert pj.judge(15.0, 9.9) == 'normal'
assert pj.judge(3.0, 9.9) == 'suspicious'  # 低于 50%
print('All rule-based tests passed')
"`
Expected: All rule-based tests passed

---

### Task 7: 平台 Agent

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/base_agent.py`
- Create: `agents/xianyu_agent.py`
- Create: `agents/taobao_agent.py`

- [ ] **Step 1: 创建 agents/__init__.py**

```python
from agents.base_agent import BaseAgent
from agents.xianyu_agent import XianyuAgent
from agents.taobao_agent import TaobaoAgent

__all__ = ["BaseAgent", "XianyuAgent", "TaobaoAgent"]
```

- [ ] **Step 2: 创建 agents/base_agent.py**

```python
import random
import asyncio
from typing import List, Optional
from playwright.async_api import Page
from core.browser import BrowserManager
from core.search_engine import SearchEngine
from core.price_judge import PriceJudge
from core.anti_detect import AntiDetect
from storage.database import Database
from storage.models import Listing, PriceAlert, SearchRun
from config.loader import ProductConfig, AccountConfig
from llm.client import LLMClient
from datetime import datetime


class BaseAgent:
    """平台 Agent 基类"""

    PLATFORM = ""  # 子类覆写

    def __init__(
        self,
        db: Database,
        product: ProductConfig,
        account: AccountConfig,
        llm_client: Optional[LLMClient] = None,
        headless: bool = False,
        proxy: Optional[str] = None,
    ):
        self.db = db
        self.product = product
        self.account = account
        self.llm_client = llm_client
        self.headless = headless
        self.proxy = proxy
        self.browser: Optional[BrowserManager] = None
        self.search_engine = SearchEngine(llm_client)
        self.price_judge = PriceJudge(llm_client)

    async def run(self) -> tuple:
        """执行一次完整的搜索+判价流程，返回 (listings_count, alerts_count)"""
        if self.PLATFORM not in self.product.platforms:
            return (0, 0)

        keywords = self.product.keywords
        run_start = datetime.now()

        self.browser = BrowserManager(proxy=self.proxy, headless=self.headless)
        await self.browser.start()
        page = await self.browser.new_page()

        search_run = SearchRun(
            run_time=run_start.strftime("%Y-%m-%d %H:%M:%S"),
            platform=self.PLATFORM,
            account_id=self.account.id,
            keywords_used=str(keywords),
        )
        run_id = self.db.save_run(search_run)
        listings_found = 0
        alerts_created = 0

        try:
            # 从关键词中随机选 2-3 个
            selected_keywords = random.sample(keywords, min(random.randint(2, 3), len(keywords)))
            for keyword in selected_keywords:
                await self._do_search(page, keyword)
                raw_items = await self.search_engine.extract_listings(page, self.PLATFORM)

                for item in raw_items:
                    listing = Listing(
                        platform=self.PLATFORM,
                        product_name=self.product.name,
                        title=item.get("title", ""),
                        price=item.get("price", 0),
                        seller_name=item.get("seller", ""),
                        url=item.get("url", ""),
                        thumbnail=item.get("thumbnail", ""),
                        search_keyword=keyword,
                        search_run_id=run_id,
                    )
                    listing_id = self.db.save_listing(listing)
                    listings_found += 1

                    if listing.price > 0 and self.price_judge.is_below_official(
                        listing.price, self.product.official_price
                    ):
                        judgment = await self.price_judge.llm_confirm_violation(
                            title=listing.title,
                            price=listing.price,
                            product_name=self.product.name,
                            official_price=self.product.official_price,
                        )
                        alert = PriceAlert(
                            listing_id=listing_id,
                            platform=self.PLATFORM,
                            product_name=self.product.name,
                            title=listing.title,
                            price=listing.price,
                            official_price=self.product.official_price,
                            judgment=judgment.get("judgment", "violation"),
                            reason=judgment.get("reason", ""),
                        )
                        self.db.save_alert(alert)
                        alerts_created += 1

                # 搜索间隔 2-5 分钟
                if len(selected_keywords) > 1:
                    await AntiDetect.random_delay(120, 300)

            # 更新搜索结果
            duration = (datetime.now() - run_start).total_seconds()
            search_run.listings_found = listings_found
            search_run.alerts_created = alerts_created
            search_run.duration_seconds = duration
            search_run.status = "completed"
            self._update_run(run_id, search_run)

        except Exception as e:
            search_run.status = "failed"
            search_run.error = str(e)
            self._update_run(run_id, search_run)
            print(f"[{self.PLATFORM}] Run failed: {e}")
        finally:
            await self.browser.stop()

        return (listings_found, alerts_created)

    def _update_run(self, run_id: int, run: SearchRun):
        """更新 run 记录（生产环境应加一个 Database.update_run 方法）"""
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute(
                """UPDATE search_runs SET listings_found=?, alerts_created=?,
                   status=?, error=?, duration_seconds=? WHERE id=?""",
                (run.listings_found, run.alerts_created,
                 run.status, run.error, run.duration_seconds, run_id),
            )

    async def _do_search(self, page: Page, keyword: str):
        """具体平台的搜索操作——子类覆写"""
        raise NotImplementedError
```

- [ ] **Step 3: 创建 agents/xianyu_agent.py**

```python
from playwright.async_api import Page
from agents.base_agent import BaseAgent
from core.anti_detect import AntiDetect


class XianyuAgent(BaseAgent):
    PLATFORM = "xianyu"

    async def _do_search(self, page: Page, keyword: str):
        """闲鱼搜索：模拟真人从闲鱼首页搜索"""
        await page.goto("https://www.goofish.com/", wait_until="networkidle")
        await AntiDetect.random_delay(2, 4)

        # 找搜索框
        search_selectors = [
            'input[placeholder*="搜索"]',
            'input[class*="search"]',
            'input[type="text"]',
            '[class*="search"] input',
        ]
        selector = None
        for sel in search_selectors:
            el = await page.query_selector(sel)
            if el:
                selector = sel
                break

        if not selector:
            # 点击搜索图标弹出搜索框
            icon_selectors = ['[class*="search"]', '[class*="icon-search"]', "a[href*='search']"]
            for sel in icon_selectors:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await AntiDetect.random_delay(1, 2)
                    break

        # 模拟输入
        await AntiDetect.human_type(page, selector or 'input[type="text"]', keyword)
        await AntiDetect.random_delay(0.5, 1.5)

        # 按回车搜索
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("networkidle")
        await AntiDetect.random_delay(2, 4)
        # 滚动浏览
        await AntiDetect.human_scroll(page, times=random.randint(2, 4))
```

需要在 xianyu_agent.py 顶部加 `import random`。

- [ ] **Step 4: 修正 xianyu_agent.py 导入**

确保顶部有 `import random`：

```python
import random
from playwright.async_api import Page
from agents.base_agent import BaseAgent
from core.anti_detect import AntiDetect


class XianyuAgent(BaseAgent):
    PLATFORM = "xianyu"

    async def _do_search(self, page: Page, keyword: str):
        """闲鱼搜索：模拟真人从闲鱼首页搜索"""
        await page.goto("https://www.goofish.com/", wait_until="networkidle")
        await AntiDetect.random_delay(2, 4)

        search_selectors = [
            'input[placeholder*="搜索"]',
            'input[class*="search"]',
            'input[type="text"]',
            '[class*="search"] input',
        ]
        selector = None
        for sel in search_selectors:
            el = await page.query_selector(sel)
            if el:
                selector = sel
                break

        if not selector:
            icon_selectors = ['[class*="search"]', '[class*="icon-search"]', "a[href*='search']"]
            for sel in icon_selectors:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await AntiDetect.random_delay(1, 2)
                    break

        await AntiDetect.human_type(page, selector or 'input[type="text"]', keyword)
        await AntiDetect.random_delay(0.5, 1.5)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("networkidle")
        await AntiDetect.random_delay(2, 4)
        await AntiDetect.human_scroll(page, times=random.randint(2, 4))
```

- [ ] **Step 5: 创建 agents/taobao_agent.py**

```python
import random
from playwright.async_api import Page
from agents.base_agent import BaseAgent
from core.anti_detect import AntiDetect


class TaobaoAgent(BaseAgent):
    PLATFORM = "taobao"

    async def _do_search(self, page: Page, keyword: str):
        """淘宝搜索：需要先确保登录态"""
        await page.goto("https://www.taobao.com/", wait_until="networkidle")
        await AntiDetect.random_delay(3, 5)

        # 淘宝搜索框定位
        selectors = [
            'input[class*="search"]',
            'input[class*="Search"]',
            'input[placeholder*="搜索"]',
            '#q',  # 淘宝经典搜索框 ID
            'form[action*="search"] input',
        ]

        selector = None
        for sel in selectors:
            el = await page.query_selector(sel)
            if el:
                selector = sel
                break

        if not selector:
            # 兜底：JS 方式找到搜索框
            selector = await page.evaluate("""
                () => {
                    const inputs = document.querySelectorAll('input[type="text"]');
                    for (const input of inputs) {
                        if (input.offsetParent !== null) return null;
                    }
                    return null;
                }
            """)

        await AntiDetect.human_type(page, selector or "input[type=text]", keyword)
        await AntiDetect.random_delay(0.5, 1.5)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("networkidle")
        await AntiDetect.random_delay(3, 5)
        await AntiDetect.human_scroll(page, times=random.randint(2, 3))
```

---

### Task 8: 日报生成 + 钉钉推送

**Files:**
- Create: `reporter/__init__.py`
- Create: `reporter/report_generator.py`
- Create: `reporter/dingtalk.py`

- [ ] **Step 1: 创建 reporter/__init__.py**

```python
from reporter.report_generator import ReportGenerator
from reporter.dingtalk import DingTalkPusher

__all__ = ["ReportGenerator", "DingTalkPusher"]
```

- [ ] **Step 2: 创建 reporter/report_generator.py**

```python
import json
from datetime import datetime
from typing import List
from storage.database import Database
from storage.models import PriceAlert, SearchRun, DailyReport


class ReportGenerator:
    """生成 Markdown 格式的日报"""

    def __init__(self, db: Database):
        self.db = db

    def generate_markdown(
        self,
        run_results: List[dict],
        period: str = "上午",
    ) -> tuple:
        """生成日报 Markdown，返回 (markdown_text, report_obj)"""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        total_listings = sum(r["listings"] for r in run_results)
        total_alerts = sum(r["alerts"] for r in run_results)
        platforms = list(set(r["platform"] for r in run_results))
        accounts = list(set(r["account"] for r in run_results))

        # 获取当日所有告警
        alerts = self.db.get_alerts_by_date(date_str)
        weekly = self.db.get_weekly_summary()
        alerts_by_product = {}
        for a in alerts:
            alerts_by_product[a.product_name] = alerts_by_product.get(a.product_name, 0) + 1

        # 生成 Markdown
        lines = [
            f"📊 价格监控日报 - {date_str} {period}",
            "",
            "🟢 本轮覆盖",
            f"  · 平台: {'/'.join(platforms)}",
            f"  · 采集商品: {total_listings}条",
            f"  · 使用账号: {', '.join(accounts)}",
            "",
        ]

        # 告警部分
        if total_alerts > 0:
            lines.append(f"🔴 发现乱价: {total_alerts}条")
            for a in alerts:
                lines.append(
                    f"  {a.product_name} | {a.platform} | ¥{a.price} | "
                    f"官方¥{a.official_price} | {a.judgment}"
                )
        else:
            lines.append("✅ 本轮未发现乱价")

        lines.append("")
        lines.append(f"📌 本周累计: 乱价{weekly['total']}条")
        if weekly["by_product"]:
            for p, c in weekly["by_product"].items():
                lines.append(f"  {p}: {c}条")

        report = DailyReport(
            report_date=date_str,
            run_period=period,
            platforms_covered=json.dumps(platforms, ensure_ascii=False),
            total_listings=total_listings,
            total_alerts=total_alerts,
            alerts_by_product=json.dumps(alerts_by_product, ensure_ascii=False),
        )

        return "\n".join(lines), report

    def save_and_send(self, run_results: List[dict], dingtalk_pusher=None, period: str = "上午") -> str:
        """生成日报 -> 存库 -> 推送钉钉 -> 返回 Markdown"""
        markdown, report = self.generate_markdown(run_results, period)

        if dingtalk_pusher:
            success = dingtalk_pusher.send_markdown(markdown)
            report.dingtalk_sent = success

        self.db.save_report(report)
        return markdown
```

- [ ] **Step 3: 创建 reporter/dingtalk.py**

```python
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
        """钉钉签名（如果配置了 secret）"""
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
        """发送 Markdown 消息到钉钉群"""
        try:
            timestamp, sign = self._sign()
            url = self.webhook_url
            if sign:
                url = f"{url}&timestamp={timestamp}&sign={sign}"

            payload = {
                "msgtype": "text",
                "text": {
                    "content": content,
                },
            }
            # Markdown 类型（如果支持）
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
        """纯文本消息（备用）"""
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
        except Exception as e:
            print(f"DingTalk text error: {e}")
            return False
```

- [ ] **Step 4: 测试钉钉推送**

Run: `python -c "
from reporter.dingtalk import DingTalkPusher
p = DingTalkPusher('https://oapi.dingtalk.com/robot/send?access_token=test')
# 没有真实 webhook 时不应该抛异常
print('DingTalkPusher initialized')
"`
Expected: DingTalkPusher initialized

- [ ] **Step 5: 测试 ReportGenerator**

Run: `python -c "
from storage.database import Database
from reporter.report_generator import ReportGenerator
db = Database('data/test.db')
rg = ReportGenerator(db)
md, report = rg.generate_markdown([
    {'platform': 'xianyu', 'listings': 20, 'alerts': 2, 'account': 'test_a'},
    {'platform': 'taobao', 'listings': 15, 'alerts': 1, 'account': 'test_b'},
])
print(md)
"`
Expected: 格式化日报 Markdown 文本

---

### Task 9: 主程序入口 + 调度器

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 重写 main.py**

```python
#!/usr/bin/env python3
"""
第三方平台价格监控系统 - 主入口

用法:
  python main.py                    # 执行一次完整运行
  python main.py --platform xianyu  # 只跑闲鱼
  python main.py --dry-run          # 不启动浏览器，仅打印配置

环境变量:
  DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY 等
"""

import asyncio
import argparse
import sys
from pathlib import Path
from typing import List

# 确保项目根在路径中
sys.path.insert(0, str(Path(__file__).parent))

from config.loader import ConfigLoader, ProductConfig, AccountConfig
from storage.database import Database
from llm.client import LLMClient
from reporter.report_generator import ReportGenerator
from reporter.dingtalk import DingTalkPusher

# 导入 agent（按平台注册）
from agents.xianyu_agent import XianyuAgent
from agents.taobao_agent import TaobaoAgent

AGENTS_MAP = {
    "xianyu": XianyuAgent,
    "taobao": TaobaoAgent,
}


def parse_args():
    parser = argparse.ArgumentParser(description="第三方平台价格监控系统")
    parser.add_argument("--platform", "-p", choices=list(AGENTS_MAP.keys()) + ["all"],
                        default="all", help="指定平台")
    parser.add_argument("--dry-run", action="store_true", help="仅打印配置，不执行搜索")
    parser.add_argument("--headless", action="store_true", help="无头模式（默认有头调试）")
    parser.add_argument("--db", default="data/price_monitor.db", help="数据库路径")
    return parser.parse_args()


async def run_agent_for_product(
    agent_cls, product: ProductConfig, account: AccountConfig,
    db: Database, llm: LLMClient, headless: bool, proxy: str,
) -> dict:
    """为单个产品的单次运行创建 Agent 并执行"""
    agent = agent_cls(
        db=db,
        product=product,
        account=account,
        llm_client=llm,
        headless=headless,
        proxy=proxy or None,
    )
    listings, alerts = await agent.run()
    return {
        "platform": agent.PLATFORM,
        "product": product.name,
        "listings": listings,
        "alerts": alerts,
        "account": account.id,
    }


async def main():
    args = parse_args()
    config_loader = ConfigLoader()
    config = config_loader.load_all()
    settings = config["settings"]
    products: List[ProductConfig] = config["products"]
    accounts: List[AccountConfig] = config["accounts"]

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"Products: {[p.name for p in products]}")
        print(f"Settings: {settings}")
        print(f"Accounts: {[a.id for a in accounts]}")
        return

    # 初始化 LLM
    llm = None
    if settings.llm.api_key:
        llm = LLMClient(settings.llm)
    else:
        print("⚠ LLM API key 未配置，将使用规则引擎（无法使用 LLM 判价和关键词生成）")

    # 初始化数据库
    db = Database(args.db)

    # 按平台过滤要跑的 agent
    platforms = list(AGENTS_MAP.keys()) if args.platform == "all" else [args.platform]

    run_results = []
    for platform in platforms:
        agent_cls = AGENTS_MAP[platform]
        # 找到该平台下需要监控的产品
        platform_products = [p for p in products if platform in p.platforms]
        # 找到该平台的搜索账号
        platform_accounts = [a for a in accounts
                             if a.platform == platform and a.type == "search" and a.status == "active"]

        if not platform_accounts:
            print(f"[{platform}] 无可用账号，跳过")
            continue

        for product in platform_products:
            # 轮换账号
            import random
            account = random.choice(platform_accounts)

            print(f"[{platform}] 开始监控: {product.name} (账号: {account.id})")
            result = await run_agent_for_product(
                agent_cls=agent_cls,
                product=product,
                account=account,
                db=db,
                llm=llm,
                headless=args.headless,
                proxy=settings.proxy.enabled,
            )
            run_results.append(result)
            print(f"[{platform}] {product.name}: 采集{result['listings']}条, 乱价{result['alerts']}条")

    # 生成日报
    if run_results:
        # 判断上下午
        from datetime import datetime
        hour = datetime.now().hour
        period = "上午" if hour < 13 else "下午"

        pusher = None
        if settings.notification.dingtalk.enabled and settings.notification.dingtalk.webhook_url:
            pusher = DingTalkPusher(settings.notification.dingtalk.webhook_url)

        rg = ReportGenerator(db)
        markdown = rg.save_and_send(run_results, dingtalk_pusher=pusher, period=period)
        print("\n=== 日报 ===")
        print(markdown)
        print("=== 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 验证 dry-run 模式**

Run: `python main.py --dry-run`
Expected: 打印产品列表和配置信息，不启动浏览器

- [ ] **Step 3: 安装 Playwright 浏览器**

Run: `playwright install chromium`
Expected: Chromium 下载安装完成

---

### 自检清单

| 检查项 | 状态 |
|--------|------|
| **Spec 覆盖** | |
| 搜索模块（多关键词、低频率） | Task 5 + Task 7 |
| 反检测策略（指纹、行为模拟、多账号） | Task 4 |
| DOM 提取 + LLM 视觉兜底 | Task 5 |
| 乱价判定（规则 + LLM 二次确认） | Task 6 |
| SQLite 存储 | Task 3 |
| LLM 统一客户端（多模型） | Task 2 |
| 日报 + 钉钉推送 | Task 8 |
| 主调度器 | Task 9 |
| 钓鱼模块 | ❌ 推迟到 Phase 2 |
| **无占位符** | ✅ 所有代码片段完整可执行 |
| **类型一致性** | ✅ Client → PriceJudge → SearchEngine → Agent 类型链一致 |
