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
