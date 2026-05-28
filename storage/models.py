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
    id: int = 0              # 数据库主键


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
    id: int = 0              # 数据库主键


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
    id: int = 0              # 数据库主键


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
    id: int = 0              # 数据库主键
