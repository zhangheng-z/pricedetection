import asyncio
import os
import random
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from reporter.judgment_labels import to_display_judgment
from desktop.ui.main_window import MainWindow
from llm.client import LLMClient
from services import MonitorService, RunOptions
from services.fishing_service import FishingService


class LogBridge(QObject):
    message = Signal(str)


class DesktopController:
    def __init__(self, window: MainWindow):
        self.window = window
        self.log_bridge = LogBridge()
        self.service = MonitorService(log_callback=self.log_bridge.message.emit)
        self.fishing_service = FishingService(log_callback=self.log_bridge.message.emit)
        self._last_summary = None
        self._run_task = None
        self._fishing_task = None
        self._reply_check_task = None
        self._reply_check_active = False
        self._batch_fishing_task = None
        self._batch_stop_requested = False
        self._review_alerts_task = None

    def bind(self) -> None:
        self.log_bridge.message.connect(self.window.append_log)
        self.window.start_requested.connect(self.start_run)
        self.window.stop_requested.connect(self.stop_run)
        self.window.refresh_requested.connect(self.load_runtime_config)
        self.window.save_config_requested.connect(self.save_config)
        self.window.save_llm_config_requested.connect(self.save_llm_config)
        self.window.open_file_requested.connect(self.open_path)
        self.window.open_account_storage_requested.connect(self.open_account_storage)
        self.window.open_account_storage_dir_requested.connect(self.open_account_storage_dir)
        self.window.result_details_requested.connect(self.show_result_details)
        self.window.open_login_requested.connect(self.open_login_browser)
        self.window.save_login_state_requested.connect(self.save_login_state)
        self.window.fishing_refresh_requested.connect(self.refresh_fishing_alerts)
        self.window.fishing_start_requested.connect(self.start_fishing)
        self.window.fishing_open_listing_requested.connect(self.open_fishing_listing)
        self.window.fishing_messages_requested.connect(self.show_fishing_messages)
        self.window.fishing_status_update_requested.connect(self.update_fishing_status)
        self.window.fishing_delete_requested.connect(self.delete_fishing_alert)
        self.window.fishing_batch_start_requested.connect(self.start_batch_fishing)
        self.window.fishing_batch_stop_requested.connect(self.stop_batch_fishing)
        self.window.fishing_review_requested.connect(self.start_review_alerts)
        self.load_runtime_config()
        self.load_config_documents()
        self.refresh_fishing_alerts()
        self._log_llm_usage()
        loop = asyncio.get_event_loop()
        self._reply_check_task = loop.create_task(self._reply_check_loop())

    def load_runtime_config(self) -> None:
        runtime = self.service.load_runtime_config()
        accounts = self.service.list_accounts()
        self.window.set_platforms(runtime["platforms"])
        self.window.set_runtime_info(
            products=[product.name for product in runtime["products"]],
            accounts=[account.id for account in runtime["accounts"]],
            provider=runtime["settings"].llm.provider,
            model=runtime["settings"].llm.model,
        )
        self.window.set_login_accounts(accounts)
        self.window.set_account_statuses(accounts)
        self.window.append_log("Runtime config reloaded.")

    def load_config_documents(self) -> None:
        documents = self.service.load_config_documents()
        self.window.set_config_documents(documents)

    def start_run(self, payload: dict) -> None:
        if self._run_task and not self._run_task.done():
            self.window.show_error("当前已有任务在运行。")
            return
        self._run_task = asyncio.create_task(self._run_monitor(payload))

    async def _run_monitor(self, payload: dict) -> None:
        self._last_summary = None
        stopped = False
        self.window.prepare_for_run()
        self.window.set_running(True)
        self.window.append_log(f"Run started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            summary = await self.service.run(
                RunOptions(
                    platform=payload["platform"],
                    dry_run=payload["dry_run"],
                    headless=payload["headless"],
                    debug_fast=payload["debug_fast"],
                    db_path=payload["db_path"],
                )
            )
            self._last_summary = summary
            self.window.show_summary(summary)
            self._log_llm_usage()
        except asyncio.CancelledError:
            stopped = True
            self.window.append_log("Run cancelled by user.")
        except Exception as exc:
            self.window.append_log(f"Run failed: {exc}")
            self.window.show_error(str(exc))
        finally:
            self.window.set_running(False)
            if stopped:
                self.window.mark_run_stopped()
            self._run_task = None

    def stop_run(self) -> None:
        if not self._run_task or self._run_task.done():
            self.window.append_log("No running task to stop.")
            return
        self.window.append_log("Stopping current task...")
        self._run_task.cancel()

    def save_config(self, payload: dict) -> None:
        try:
            self.service.save_config_document(payload["filename"], payload["content"])
            self.window.append_log(f"Saved config: {payload['filename']}")
            self.load_runtime_config()
            self.load_config_documents()
        except Exception as exc:
            self.window.show_error(str(exc))

    def save_llm_config(self, payload: dict) -> None:
        if not payload.get("provider"):
            self.window.show_error("Provider 不能为空。")
            return
        if not payload.get("model"):
            self.window.show_error("模型不能为空。")
            return
        if payload.get("provider") != "anthropic" and not payload.get("api_base"):
            self.window.show_error("OpenAI-compatible 模型需要填写 API Base。")
            return

        try:
            self.service.save_llm_config(payload)
            self.window.append_log("Saved model config.")
            self.load_runtime_config()
            self.load_config_documents()
        except Exception as exc:
            self.window.show_error(str(exc))

    def open_path(self, path_text: str) -> None:
        if not path_text:
            self.window.show_error("没有可打开的路径。")
            return

        path = Path(path_text)
        if not path.exists():
            self.window.show_error(f"路径不存在: {path}")
            return

        try:
            os.startfile(str(path.resolve()))
            self.window.append_log(f"Opened: {path.resolve()}")
        except Exception as exc:
            self.window.show_error(str(exc))

    def open_account_storage(self, account_id: str) -> None:
        account = self._find_account(account_id)
        if not account:
            self.window.show_error(f"账号不存在: {account_id}")
            return
        self.open_path(account["storage_state"])

    def open_account_storage_dir(self, account_id: str) -> None:
        account = self._find_account(account_id)
        if not account:
            self.window.show_error(f"账号不存在: {account_id}")
            return
        self.open_path(str(Path(account["storage_state"]).resolve().parent))

    def show_result_details(self, row_index: int) -> None:
        if self._last_summary is None:
            self.window.show_error("当前没有可查看的结果。")
            return
        if row_index < 0 or row_index >= len(self._last_summary.run_results):
            self.window.show_error("结果索引无效。")
            return

        result = self._last_summary.run_results[row_index]
        detail_lines = [
            f"平台: {result.platform}",
            f"商品: {result.product}",
            f"账号: {result.account}",
            f"采集数: {result.listings}",
            f"告警数: {result.alerts}",
            f"结果文件: {result.results_file or '-'}",
            f"原始结果文件: {result.raw_results_file or '-'}",
            "",
            "采集条目:",
        ]

        if result.items:
            for index, item in enumerate(result.items, start=1):
                detail_lines.append(
                    f"{index}. {item.get('title', '')} | price={item.get('price', '')} | "
                    f"judgment={to_display_judgment(item.get('judgment', ''))} | url={item.get('url', '')}"
                )
        else:
            detail_lines.append("无采集条目。")

        self.window.show_result_details(
            title=f"{result.platform} - {result.product}",
            content="\n".join(detail_lines),
        )

    def open_login_browser(self, account_id: str) -> None:
        asyncio.create_task(self._open_login_browser(account_id))

    async def _open_login_browser(self, account_id: str) -> None:
        self.window.set_login_busy(True)
        self.window.append_log(f"Starting login helper for {account_id}...")
        try:
            result = await self.service.open_login_browser(account_id)
            self.window.set_login_session_active(True, account_id)
            self.window.append_log(
                f"Login helper started for {result['account_id']} ({result['platform']}). "
                f"Profile: {result['user_data_dir']}"
            )
            self.window.show_info(
                "登录提示",
                "登录浏览器已经打开，请在浏览器中完成登录。\n完成后回到这里点击“完成登录并保存”。",
            )
        except Exception as exc:
            self.window.show_error(str(exc))
        finally:
            self.window.set_login_busy(False)

    def save_login_state(self, account_id: str) -> None:
        asyncio.create_task(self._save_login_state(account_id))

    async def _save_login_state(self, account_id: str) -> None:
        self.window.set_login_busy(True)
        self.window.append_log(f"Finishing login and saving state for {account_id}...")
        try:
            storage_state = await self.service.save_login_state(account_id)
            self.window.set_login_session_active(False, "")
            self.window.append_log(f"Saved login state: {storage_state}")
            self.load_runtime_config()
            self.window.show_info("保存成功", f"登录状态已保存到:\n{storage_state}")
        except Exception as exc:
            self.window.show_error(str(exc))
        finally:
            self.window.set_login_busy(False)

    def _find_account(self, account_id: str):
        for account in self.service.list_accounts():
            if account["id"] == account_id:
                return account
        return None

    def refresh_fishing_alerts(self) -> None:
        try:
            alerts = self.fishing_service.list_alerts(self._current_db_path())
            self.window.set_fishing_alerts(alerts)
            self.window.append_log(f"Fishing alerts loaded: {len(alerts)}")
        except Exception as exc:
            self.window.show_error(str(exc))

    def start_fishing(self, alert_id: int) -> None:
        if self._fishing_task and not self._fishing_task.done():
            self.window.show_error("当前已有询价任务在运行。")
            return
        if self._reply_check_active:
            self.window.show_error("自动检查回复正在运行，请稍后再发起询价。")
            return
        if self._batch_fishing_task and not self._batch_fishing_task.done():
            self.window.show_error("批量询价正在运行，请稍后再发起单条询价。")
            return
        self._fishing_task = asyncio.create_task(self._start_fishing(alert_id))

    async def _start_fishing(self, alert_id: int) -> None:
        self.window.append_log(f"Starting fishing session for alert {alert_id}...")
        try:
            result = await self.fishing_service.start_fishing(
                db_path=self._current_db_path(),
                alert_id=alert_id,
                auto_send=True,
                headless=self.window.fishing_headless_enabled(),
            )
            self.window.append_log(
                f"Fishing message sent for session {result.session_id}: {result.message}"
            )
            self.refresh_fishing_alerts()
            self.window.append_log(
                "Fishing session is running in the browser. "
                "If no seller reply is detected, continue manually in the chat window."
            )
            self._log_llm_usage()
        except Exception as exc:
            self.window.append_log(f"Fishing failed: {exc}")
            self.refresh_fishing_alerts()
            self.window.show_error(str(exc))
        finally:
            self._fishing_task = None

    async def _reply_check_loop(self) -> None:
        self.window.append_log("Reply checker scheduled: every 5 minutes, max 10 alerts per run.")
        while True:
            await asyncio.sleep(300)
            if self._fishing_task and not self._fishing_task.done():
                self.window.append_log("Reply checker skipped: fishing task is running.")
                continue
            if self._batch_fishing_task and not self._batch_fishing_task.done():
                self.window.append_log("Reply checker skipped: batch fishing is running.")
                continue
            try:
                self._reply_check_active = True
                summary = await self.fishing_service.check_waiting_replies(
                    db_path=self._current_db_path(),
                    limit=10,
                    headless=self.window.fishing_headless_enabled(),
                )
                if summary.checked:
                    self.window.append_log(
                        "Reply checker finished: "
                        f"checked={summary.checked}, updated={summary.updated}, "
                        f"waiting={summary.waiting}, failed={summary.failed}"
                    )
                    self.refresh_fishing_alerts()
                    self._log_llm_usage()
            except Exception as exc:
                self.window.append_log(f"Reply checker failed: {exc}")
            finally:
                self._reply_check_active = False

    def start_batch_fishing(self, alert_ids: list[int]) -> None:
        if self._batch_fishing_task and not self._batch_fishing_task.done():
            self.window.show_error("批量询价正在运行。")
            return
        if self._fishing_task and not self._fishing_task.done():
            self.window.show_error("当前已有单条询价任务在运行。")
            return
        if self._reply_check_active:
            self.window.show_error("自动检查回复正在运行，请稍后再启动批量询价。")
            return

        selected_ids = [int(alert_id) for alert_id in alert_ids if int(alert_id or 0)]
        if not selected_ids:
            self.window.show_error("请先选择要批量询价的商品。")
            return
        if len(selected_ids) > 10:
            self.window.append_log(f"Batch fishing selected {len(selected_ids)} alerts; only first 10 will run.")
            selected_ids = selected_ids[:10]

        self._batch_stop_requested = False
        self._batch_fishing_task = asyncio.create_task(self._run_batch_fishing(selected_ids))

    def stop_batch_fishing(self) -> None:
        if not self._batch_fishing_task or self._batch_fishing_task.done():
            self.window.append_log("No batch fishing task to stop.")
            return
        self._batch_stop_requested = True
        self.window.append_log("Batch fishing stop requested; current alert will finish first.")

    async def _run_batch_fishing(self, alert_ids: list[int]) -> None:
        self.window.set_fishing_batch_running(True)
        headless = self.window.fishing_headless_enabled()
        total = len(alert_ids)
        waiting = 0
        updated = 0
        failed = 0
        self.window.append_log(f"Batch fishing started: {total} alerts, headless={headless}.")
        try:
            for index, alert_id in enumerate(alert_ids, start=1):
                if self._batch_stop_requested:
                    self.window.append_log(f"Batch fishing stopped before alert {alert_id}.")
                    break

                self.window.append_log(f"Batch fishing [{index}/{total}] starting alert={alert_id}.")
                result = None
                try:
                    result = await self.fishing_service.start_fishing(
                        db_path=self._current_db_path(),
                        alert_id=alert_id,
                        auto_send=True,
                        headless=headless,
                    )
                    if result.status == "waiting_seller":
                        waiting += 1
                    else:
                        updated += 1
                    self.window.append_log(
                        f"Batch fishing [{index}/{total}] finished alert={alert_id}, status={result.status}."
                    )
                except Exception as exc:
                    failed += 1
                    self.window.append_log(f"Batch fishing [{index}/{total}] failed alert={alert_id}: {exc}")
                finally:
                    if result is not None:
                        await self.fishing_service.close_session(result.session_id)
                        self.window.append_log(
                            f"Batch fishing [{index}/{total}] closed browser session={result.session_id}."
                        )

                self.refresh_fishing_alerts()

                if self._batch_stop_requested or index >= total:
                    continue
                delay = random.randint(30, 90)
                self.window.append_log(f"Batch fishing waiting {delay}s before next alert.")
                await asyncio.sleep(delay)
        finally:
            self.window.append_log(
                f"Batch fishing finished: total={total}, updated={updated}, waiting={waiting}, failed={failed}."
            )
            self._log_llm_usage()
            self.window.set_fishing_batch_running(False)
            self.refresh_fishing_alerts()
            self._batch_fishing_task = None
            self._batch_stop_requested = False

    def open_fishing_listing(self, alert_id: int) -> None:
        alert = self._find_fishing_alert(alert_id)
        if not alert or not alert.get("url"):
            self.window.show_error(f"未找到商品链接: {alert_id}")
            return
        webbrowser.open(alert["url"])
        self.window.append_log(f"Opened listing URL: {alert['url']}")

    def show_fishing_messages(self, alert_id: int) -> None:
        alert = self._find_fishing_alert(alert_id)
        if not alert:
            self.window.show_error(f"未找到询价线索: {alert_id}")
            return
        listing_id = int(alert.get("listing_id") or 0)
        session_id = alert.get("latest_session_id")
        if not session_id:
            self.window.show_info("暂无会话", "这条线索还没有发起过询价。")
            return

        messages = self.fishing_service.list_messages(self._current_db_path(), listing_id)
        lines = [
            f"线索: {alert.get('title', '')}",
            f"会话 ID: {session_id}",
            "",
        ]
        if not messages:
            lines.append("暂无消息记录。")
        for message in messages:
            lines.append(
                f"[{message.get('created_at', '')}] {message.get('sender', '')}: {message.get('content', '')}"
            )
        self.window.show_result_details("询价会话", "\n".join(lines))

    def update_fishing_status(self, alert_id: int, status: str, product_type: str = "") -> None:
        try:
            self.fishing_service.update_alert_status(
                self._current_db_path(),
                alert_id,
                status,
                product_type,
            )
            self.window.append_log(
                f"Updated alert {alert_id} status to {status}, product_type={product_type or '-'}."
            )
            self.refresh_fishing_alerts()
        except Exception as exc:
            self.window.show_error(str(exc))

    def delete_fishing_alert(self, alert_ids: list[int]) -> None:
        try:
            if isinstance(alert_ids, int):
                alert_ids = [alert_ids]
            selected_ids = [int(alert_id) for alert_id in alert_ids if int(alert_id or 0)]
            if not selected_ids:
                return
            db_path = self._current_db_path()
            for alert_id in selected_ids:
                self.fishing_service.delete_alert(db_path, alert_id)
            self.window.append_log(f"Deleted {len(selected_ids)} alert(s): {', '.join(map(str, selected_ids))}.")
            self.refresh_fishing_alerts()
        except Exception as exc:
            self.window.show_error(str(exc))

    def start_review_alerts(self) -> None:
        if self._review_alerts_task and not self._review_alerts_task.done():
            self.window.show_error("REVIEW 复核正在运行。")
            return
        self._review_alerts_task = asyncio.create_task(self._run_review_alerts())

    async def _run_review_alerts(self) -> None:
        self.window.set_fishing_review_running(True)
        self.window.append_log("REVIEW 复核开始。")
        try:
            result = await asyncio.to_thread(
                self.service.review_database_alerts,
                self._current_db_path(),
            )
            self.window.append_log(
                f"REVIEW 复核完成: total={result.total_review_items}, updated={result.updated_items}."
            )
            if result.review_results_file:
                self.window.append_log(f"Review results file: {result.review_results_file}")
            self.refresh_fishing_alerts()
            self._log_llm_usage()
            self.window.show_info(
                "复核完成",
                f"已复核 {result.total_review_items} 条 REVIEW 商品，LLM 返回 {result.updated_items} 条结果。",
            )
        except Exception as exc:
            self.window.append_log(f"REVIEW 复核失败: {exc}")
            self.window.show_error(str(exc))
        finally:
            self.window.set_fishing_review_running(False)
            self._review_alerts_task = None

    def _find_fishing_alert(self, alert_id: int):
        for alert in self.fishing_service.list_alerts(self._current_db_path()):
            if int(alert.get("alert_id") or 0) == int(alert_id):
                return alert
        return None

    def _current_db_path(self) -> str:
        return self.window.db_path_input.text().strip() or "data/price_monitor.db"

    def _log_llm_usage(self) -> None:
        usage = LLMClient.usage_snapshot()
        self.window.set_token_usage(usage)
        self.window.append_log(LLMClient.usage_summary())
