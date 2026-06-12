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
                    spec_capture_mode TEXT DEFAULT '',
                    spec_capture_info TEXT DEFAULT '',
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
                    product_type TEXT DEFAULT '',
                    payment_status TEXT DEFAULT '',
                    spec_capture_mode TEXT DEFAULT '',
                    spec_capture_info TEXT DEFAULT '',
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

                CREATE TABLE IF NOT EXISTS fishing_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    listing_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    status TEXT DEFAULT 'created',
                    current_step TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    started_at TEXT DEFAULT (datetime('now', 'localtime')),
                    finished_at TEXT DEFAULT '',
                    FOREIGN KEY (alert_id) REFERENCES price_alerts(id),
                    FOREIGN KEY (listing_id) REFERENCES listings(id)
                );

                CREATE TABLE IF NOT EXISTS fishing_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER NOT NULL DEFAULT 0,
                    session_id INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    content TEXT NOT NULL,
                    raw_payload TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (listing_id) REFERENCES listings(id),
                    FOREIGN KEY (session_id) REFERENCES fishing_sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_listings_platform ON listings(platform);
                CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at);
                CREATE INDEX IF NOT EXISTS idx_alerts_status ON price_alerts(status);
                CREATE INDEX IF NOT EXISTS idx_runs_time ON search_runs(run_time);
                CREATE INDEX IF NOT EXISTS idx_fishing_sessions_alert ON fishing_sessions(alert_id);
                CREATE INDEX IF NOT EXISTS idx_fishing_messages_session ON fishing_messages(session_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_listings_url_unique
                    ON listings(url)
                    WHERE url != '';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_price_alerts_listing_unique
                    ON price_alerts(listing_id);
            """)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(fishing_messages)").fetchall()
            }
            if "listing_id" not in columns:
                conn.execute("DELETE FROM fishing_messages")
                conn.execute(
                    "ALTER TABLE fishing_messages ADD COLUMN listing_id INTEGER NOT NULL DEFAULT 0"
                )
            self._ensure_column(conn, "listings", "spec_capture_mode", "TEXT DEFAULT ''")
            self._ensure_column(conn, "listings", "spec_capture_info", "TEXT DEFAULT ''")
            self._ensure_column(conn, "price_alerts", "spec_capture_mode", "TEXT DEFAULT ''")
            self._ensure_column(conn, "price_alerts", "spec_capture_info", "TEXT DEFAULT ''")
            self._ensure_column(conn, "price_alerts", "product_type", "TEXT DEFAULT ''")
            self._ensure_column(conn, "price_alerts", "payment_status", "TEXT DEFAULT ''")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fishing_messages_listing ON fishing_messages(listing_id)"
            )

    def _ensure_column(self, conn, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
            try:
                cur = conn.execute(
                    """INSERT INTO listings (platform, product_name, title, price,
                       seller_name, url, thumbnail, sales_count, search_keyword, search_run_id,
                       spec_capture_mode, spec_capture_info)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (listing.platform, listing.product_name, listing.title,
                     listing.price, listing.seller_name, listing.url,
                     listing.thumbnail, listing.sales_count,
                     listing.search_keyword, listing.search_run_id,
                     listing.spec_capture_mode, listing.spec_capture_info),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                if not listing.url:
                    raise
                existing = conn.execute(
                    "SELECT id FROM listings WHERE url = ?",
                    (listing.url,),
                ).fetchone()
                if not existing:
                    raise
                conn.execute(
                    """
                    UPDATE listings
                    SET price = ?, seller_name = ?, thumbnail = ?, search_keyword = ?,
                        search_run_id = ?, spec_capture_mode = ?, spec_capture_info = ?
                    WHERE id = ?
                    """,
                    (
                        listing.price,
                        listing.seller_name,
                        listing.thumbnail,
                        listing.search_keyword,
                        listing.search_run_id,
                        listing.spec_capture_mode,
                        listing.spec_capture_info,
                        existing["id"],
                    ),
                )
                return int(existing["id"])

    def save_alert(self, alert: PriceAlert) -> int:
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM price_alerts WHERE listing_id = ?",
                (alert.listing_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE price_alerts
                       SET platform = ?, product_name = ?, title = ?, price = ?,
                           official_price = ?, judgment = ?, reason = ?, status = ?,
                           spec_capture_mode = ?, spec_capture_info = ?
                       WHERE id = ?""",
                    (alert.platform, alert.product_name, alert.title, alert.price,
                     alert.official_price, alert.judgment, alert.reason, alert.status,
                     alert.spec_capture_mode, alert.spec_capture_info,
                     existing["id"]),
                )
                return int(existing["id"])

            cur = conn.execute(
                """INSERT INTO price_alerts (listing_id, platform, product_name,
                   title, price, official_price, judgment, reason, status,
                   spec_capture_mode, spec_capture_info)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (alert.listing_id, alert.platform, alert.product_name,
                 alert.title, alert.price, alert.official_price,
                 alert.judgment, alert.reason, alert.status,
                 alert.spec_capture_mode, alert.spec_capture_info),
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

    def list_fishable_alerts(self) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.id AS alert_id,
                    a.listing_id,
                    a.platform,
                    a.product_name,
                    a.title,
                    a.price,
                    a.official_price,
                    a.judgment,
                    a.reason,
                    a.status,
                    a.product_type,
                    a.payment_status,
                    COALESCE(NULLIF(a.spec_capture_mode, ''), l.spec_capture_mode, '') AS spec_capture_mode,
                    COALESCE(NULLIF(a.spec_capture_info, ''), l.spec_capture_info, '') AS spec_capture_info,
                    a.created_at,
                    l.seller_name,
                    l.url,
                    l.thumbnail,
                    (
                        SELECT fs.id
                        FROM fishing_sessions fs
                        WHERE fs.alert_id = a.id
                        ORDER BY fs.id DESC
                        LIMIT 1
                    ) AS latest_session_id
                FROM price_alerts a
                JOIN listings l ON l.id = a.listing_id
                WHERE a.platform = 'xianyu'
                  AND a.status IN (
                      'pending',
                      'fishing',
                      'waiting_seller',
                      'seller_replied',
                      'manual_required',
                      'failed',
                      'evidence_collected',
                      'resolved'
                  )
                  AND a.judgment IN ('VIOLATION', 'SUSPECTED', 'DELIST', 'REVIEW')
                ORDER BY
                    CASE a.product_name
                        WHEN '适趣 AI 中文15天' THEN 1
                        WHEN '适趣 AI 中文年卡' THEN 2
                        WHEN '适趣 AI 英文21天' THEN 3
                        WHEN '适趣 AI 英文年卡' THEN 4
                        ELSE 99
                    END,
                    a.price ASC,
                    a.created_at DESC,
                    a.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def list_review_alerts(self) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.id AS alert_id,
                    a.listing_id,
                    a.platform,
                    a.product_name,
                    a.title,
                    a.price,
                    a.official_price,
                    a.judgment,
                    a.reason,
                    a.status,
                    a.product_type,
                    a.payment_status,
                    COALESCE(NULLIF(a.spec_capture_mode, ''), l.spec_capture_mode, '') AS spec_capture_mode,
                    COALESCE(NULLIF(a.spec_capture_info, ''), l.spec_capture_info, '') AS spec_capture_info,
                    a.created_at,
                    l.seller_name,
                    l.url,
                    l.thumbnail
                FROM price_alerts a
                JOIN listings l ON l.id = a.listing_id
                WHERE UPPER(a.judgment) = 'REVIEW'
                ORDER BY a.created_at DESC, a.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def listing_exists_by_url(self, url: str) -> bool:
        if not url:
            return False
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM listings WHERE url = ? LIMIT 1",
                (url,),
            ).fetchone()
            return row is not None

    def get_listing_by_url(self, url: str) -> Optional[dict]:
        if not url:
            return None
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM listings WHERE url = ? LIMIT 1",
                (url,),
            ).fetchone()
            return dict(row) if row else None

    def update_alert_judgment_by_url(self, url: str, judgment: str, reason: str = "") -> bool:
        if not url:
            return False
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE price_alerts
                SET judgment = ?, reason = ?, status = 'pending'
                WHERE listing_id IN (
                    SELECT id FROM listings WHERE url = ?
                )
                """,
                (judgment, reason, url),
            )
            return cur.rowcount > 0

    def delete_alert_by_url(self, url: str) -> bool:
        if not url:
            return False
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM listings WHERE url = ?",
                (url,),
            ).fetchall()
            deleted = False
            for row in rows:
                deleted = self._delete_listing_graph(conn, int(row["id"])) or deleted
            return deleted

    def clear_business_data(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(
                """
                DELETE FROM fishing_messages;
                DELETE FROM fishing_sessions;
                DELETE FROM price_alerts;
                DELETE FROM listings;
                DELETE FROM search_runs;
                DELETE FROM daily_reports;
                """
            )

    def get_fishing_alert(self, alert_id: int) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT
                    a.id AS alert_id,
                    a.listing_id,
                    a.platform,
                    a.product_name,
                    a.title,
                    a.price,
                    a.official_price,
                    a.judgment,
                    a.reason,
                    a.status,
                    a.product_type,
                    a.payment_status,
                    COALESCE(NULLIF(a.spec_capture_mode, ''), l.spec_capture_mode, '') AS spec_capture_mode,
                    COALESCE(NULLIF(a.spec_capture_info, ''), l.spec_capture_info, '') AS spec_capture_info,
                    l.seller_name,
                    l.url,
                    l.thumbnail
                FROM price_alerts a
                JOIN listings l ON l.id = a.listing_id
                WHERE a.id = ?
                """,
                (alert_id,),
            ).fetchone()
            return dict(row) if row else None

    def create_fishing_session(self, alert_id: int, listing_id: int, platform: str, account_id: str) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO fishing_sessions (alert_id, listing_id, platform, account_id, status, current_step)
                VALUES (?, ?, ?, ?, 'created', 'created')
                """,
                (alert_id, listing_id, platform, account_id),
            )
            return cur.lastrowid

    def save_fishing_message(
        self,
        listing_id: int,
        session_id: int,
        sender: str,
        content: str,
        raw_payload: str = "",
    ) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO fishing_messages (listing_id, session_id, sender, content, raw_payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (listing_id, session_id, sender, content, raw_payload),
            )
            return cur.lastrowid

    def list_fishing_messages(self, session_id: int) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, listing_id, session_id, sender, content, raw_payload, created_at
                FROM fishing_messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_fishing_messages_by_listing(self, listing_id: int) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, listing_id, session_id, sender, content, raw_payload, created_at
                FROM fishing_messages
                WHERE listing_id = ?
                ORDER BY id ASC
                """,
                (listing_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def replace_fishing_messages_for_listing(
        self,
        listing_id: int,
        session_id: int,
        messages: List[dict],
    ) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM fishing_messages WHERE listing_id = ?", (listing_id,))
            for message in messages:
                sender = str(message.get("sender", "")).strip()
                content = str(message.get("content", "")).strip()
                if not sender or not content:
                    continue
                conn.execute(
                    """
                    INSERT INTO fishing_messages (listing_id, session_id, sender, content, raw_payload)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (listing_id, session_id, sender, content, str(message.get("raw_payload", ""))),
                )

    def delete_alert(self, alert_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT listing_id FROM price_alerts WHERE id = ?",
                (alert_id,),
            ).fetchone()
            if not row:
                return False
            return self._delete_listing_graph(conn, int(row["listing_id"]))

    def _delete_listing_graph(self, conn, listing_id: int) -> bool:
        conn.execute("DELETE FROM fishing_messages WHERE listing_id = ?", (listing_id,))
        conn.execute("DELETE FROM fishing_sessions WHERE listing_id = ?", (listing_id,))
        alert_cur = conn.execute("DELETE FROM price_alerts WHERE listing_id = ?", (listing_id,))
        listing_cur = conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
        return alert_cur.rowcount > 0 or listing_cur.rowcount > 0

    def update_alert_status(self, alert_id: int, status: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE price_alerts
                SET status = ?,
                    payment_status = CASE
                        WHEN product_type = 'channel_resale' AND ? = 'resolved' THEN 'paid'
                        WHEN product_type = 'channel_resale' AND ? = 'manual_required' THEN 'unpaid'
                        ELSE payment_status
                    END
                WHERE id = ?
                """,
                (status, status, status, alert_id),
            )
            return cur.rowcount > 0

    def update_alert_status_and_reason(
        self,
        alert_id: int,
        status: str,
        reason: str,
        product_type: str = "",
        payment_status: str = "",
    ) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE price_alerts
                SET status = ?,
                    reason = ?,
                    product_type = CASE WHEN ? != '' THEN ? ELSE product_type END,
                    payment_status = CASE
                        WHEN ? != '' THEN ?
                        WHEN COALESCE(NULLIF(?, ''), product_type) = 'channel_resale'
                             AND ? = 'manual_required' THEN 'unpaid'
                        WHEN COALESCE(NULLIF(?, ''), product_type) = 'channel_resale'
                             AND ? = 'resolved' THEN 'paid'
                        ELSE payment_status
                    END
                WHERE id = ?
                """,
                (
                    status,
                    reason,
                    product_type,
                    product_type,
                    payment_status,
                    payment_status,
                    product_type,
                    status,
                    product_type,
                    status,
                    alert_id,
                ),
            )
            return cur.rowcount > 0

    def update_alert_product_type(
        self,
        alert_id: int,
        product_type: str,
        payment_status: str = "",
    ) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE price_alerts
                SET product_type = ?,
                    payment_status = ?
                WHERE id = ?
                """,
                (product_type, payment_status, alert_id),
            )
            return cur.rowcount > 0

    def update_alert_status_and_product_type(
        self,
        alert_id: int,
        status: str,
        product_type: str,
    ) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE price_alerts
                SET status = ?,
                    product_type = ?,
                    payment_status = CASE
                        WHEN ? = 'channel_resale' AND ? = 'resolved' THEN 'paid'
                        WHEN ? = 'channel_resale' THEN 'unpaid'
                        ELSE ''
                    END
                WHERE id = ?
                """,
                (status, product_type, product_type, status, product_type, alert_id),
            )
            return cur.rowcount > 0

    def update_fishing_session_status(
        self,
        session_id: int,
        status: str,
        current_step: str = "",
        error: str = "",
        finished: bool = False,
    ) -> None:
        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if finished else ""
        with self._get_conn() as conn:
            if finished:
                conn.execute(
                    """
                    UPDATE fishing_sessions
                    SET status = ?, current_step = ?, error = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (status, current_step, error, finished_at, session_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE fishing_sessions
                    SET status = ?, current_step = ?, error = ?
                    WHERE id = ?
                    """,
                    (status, current_step, error, session_id),
                )
