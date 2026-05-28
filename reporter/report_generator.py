import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from storage.database import Database
from storage.models import DailyReport


class ReportGenerator:
    """Generate Markdown daily reports and persist them locally."""

    def __init__(self, db: Database, report_dir: str = "reports"):
        self.db = db
        self.report_dir = Path(report_dir)
        self.last_report_path: Optional[Path] = None

    def generate_markdown(
        self,
        run_results: List[dict],
        period: str = "morning",
    ) -> Tuple[str, DailyReport]:
        """Generate report Markdown and the matching database model."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        total_listings = sum(r.get("listings", 0) for r in run_results)
        total_alerts = sum(r.get("alerts", 0) for r in run_results)
        platforms = sorted(set(r.get("platform", "") for r in run_results if r.get("platform")))
        accounts = sorted(set(r.get("account", "") for r in run_results if r.get("account")))

        alerts = self.db.get_alerts_by_date(date_str)
        weekly = self.db.get_weekly_summary()
        alerts_by_product = {}
        for alert in alerts:
            alerts_by_product[alert.product_name] = alerts_by_product.get(alert.product_name, 0) + 1

        lines = [
            f"# Price Monitor Report - {date_str} {period}",
            "",
            "## Coverage",
            f"- Platforms: {', '.join(platforms) if platforms else 'none'}",
            f"- Listings collected: {total_listings}",
            f"- Accounts used: {', '.join(accounts) if accounts else 'none'}",
            "",
        ]

        if total_alerts > 0:
            lines.extend([
                f"## Price Alerts ({total_alerts})",
                "",
                "| Product | Platform | Price | Official Price | Judgment | Reason |",
                "| --- | --- | ---: | ---: | --- | --- |",
            ])
            for alert in alerts:
                reason = (alert.reason or "").replace("\n", " ")
                lines.append(
                    f"| {alert.product_name} | {alert.platform} | {alert.price} | "
                    f"{alert.official_price} | {alert.judgment} | {reason} |"
                )
        else:
            lines.extend([
                "## Price Alerts",
                "",
                "No price violations found in this run.",
            ])

        lines.extend([
            "",
            "## Weekly Summary",
            f"- Total alerts: {weekly['total']}",
        ])
        for product_name, count in weekly.get("by_product", {}).items():
            lines.append(f"- {product_name}: {count}")

        report = DailyReport(
            report_date=date_str,
            run_period=period,
            platforms_covered=json.dumps(platforms, ensure_ascii=False),
            total_listings=total_listings,
            total_alerts=total_alerts,
            alerts_by_product=json.dumps(alerts_by_product, ensure_ascii=False),
        )

        return "\n".join(lines), report

    def save_local_file(self, markdown: str) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.report_dir / f"price_report_{timestamp}.md"
        path.write_text(markdown, encoding="utf-8")
        self.last_report_path = path
        return path

    def save_and_send(
        self,
        run_results: List[dict],
        dingtalk_pusher=None,
        period: str = "morning",
    ) -> str:
        markdown, report = self.generate_markdown(run_results, period)
        self.save_local_file(markdown)
        if dingtalk_pusher:
            report.dingtalk_sent = dingtalk_pusher.send_markdown(markdown)
        self.db.save_report(report)
        return markdown
