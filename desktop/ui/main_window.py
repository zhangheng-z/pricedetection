from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):
    start_requested = Signal(dict)
    stop_requested = Signal()
    refresh_requested = Signal()
    save_config_requested = Signal(dict)
    open_file_requested = Signal(str)
    open_account_storage_requested = Signal(str)
    open_account_storage_dir_requested = Signal(str)
    result_details_requested = Signal(int)
    open_login_requested = Signal(str)
    save_login_state_requested = Signal(str)
    fishing_refresh_requested = Signal()
    fishing_start_requested = Signal(int)
    fishing_open_listing_requested = Signal(int)
    fishing_messages_requested = Signal(int)
    fishing_status_update_requested = Signal(int, str)
    fishing_delete_requested = Signal(int)

    def __init__(self):
        super().__init__()
        self._accounts = []
        self._fishing_alerts = []
        self._login_session_active = False
        self.setWindowTitle("Price Detection Desktop")
        self.resize(1220, 860)
        self._build_ui()
        self._set_output_button(self.open_deduped_button, "")
        self._set_output_button(self.open_report_button, "")
        self._set_output_button(self.open_output_dir_button, "")
        self.stop_button.setEnabled(False)
        self.save_login_state_button.setEnabled(False)

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("桌面控制台")
        header.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(header)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_run_tab(), "运行")
        tabs.addTab(self._build_fishing_tab(), "询价跟进")
        tabs.addTab(self._build_config_tab(), "配置")
        layout.addWidget(tabs)

        self.setCentralWidget(central)

    def _build_run_tab(self) -> QWidget:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)

        splitter = QSplitter(page)
        splitter.setOrientation(Qt.Horizontal)
        splitter.addWidget(self._build_control_panel())
        splitter.addWidget(self._build_output_panel())
        splitter.setSizes([380, 840])
        page_layout.addWidget(splitter)

        return page

    def _build_control_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        run_group = QGroupBox("运行参数", panel)
        run_form = QFormLayout(run_group)
        self.platform_combo = QComboBox(run_group)
        self.platform_combo.addItem("all")
        run_form.addRow("平台", self.platform_combo)
        self.db_path_input = QLineEdit("data/price_monitor.db", run_group)
        run_form.addRow("数据库", self.db_path_input)
        self.headless_checkbox = QCheckBox("无头模式", run_group)
        self.debug_fast_checkbox = QCheckBox("调试加速", run_group)
        self.dry_run_checkbox = QCheckBox("仅 dry-run", run_group)
        run_form.addRow("", self.headless_checkbox)
        run_form.addRow("", self.debug_fast_checkbox)
        run_form.addRow("", self.dry_run_checkbox)
        layout.addWidget(run_group)

        runtime_group = QGroupBox("运行时信息", panel)
        runtime_layout = QVBoxLayout(runtime_group)
        self.provider_label = QLabel("-", runtime_group)
        self.products_label = QLabel("-", runtime_group)
        self.accounts_label = QLabel("-", runtime_group)
        self.products_label.setWordWrap(True)
        self.accounts_label.setWordWrap(True)
        runtime_layout.addWidget(QLabel("模型", runtime_group))
        runtime_layout.addWidget(self.provider_label)
        runtime_layout.addWidget(QLabel("商品", runtime_group))
        runtime_layout.addWidget(self.products_label)
        runtime_layout.addWidget(QLabel("账号", runtime_group))
        runtime_layout.addWidget(self.accounts_label)
        layout.addWidget(runtime_group)

        login_group = QGroupBox("账号登录", panel)
        login_form = QFormLayout(login_group)
        self.login_platform_combo = QComboBox(login_group)
        self.login_account_combo = QComboBox(login_group)
        login_form.addRow("平台", self.login_platform_combo)
        login_form.addRow("账号", self.login_account_combo)

        login_hint = QLabel("点击“打开登录窗口”后在浏览器里完成登录，再回到这里点击“完成登录并保存”。", login_group)
        login_hint.setWordWrap(True)
        login_form.addRow("", login_hint)

        login_actions = QHBoxLayout()
        self.open_login_button = QPushButton("打开登录窗口", login_group)
        self.save_login_state_button = QPushButton("完成登录并保存", login_group)
        login_actions.addWidget(self.open_login_button)
        login_actions.addWidget(self.save_login_state_button)
        login_form.addRow("", self._wrap_layout(login_actions, login_group))
        layout.addWidget(login_group)

        account_group = QGroupBox("账号状态", panel)
        account_layout = QVBoxLayout(account_group)
        self.account_table = QTableWidget(0, 6, account_group)
        self.account_table.setHorizontalHeaderLabels(["平台", "账号", "状态", "已保存", "最近保存时间", "存档路径"])
        self.account_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.account_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.account_table.verticalHeader().setVisible(False)
        self.account_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        account_layout.addWidget(self.account_table)

        account_actions = QHBoxLayout()
        self.open_account_storage_button = QPushButton("打开登录态文件", account_group)
        self.open_account_storage_dir_button = QPushButton("打开登录态目录", account_group)
        account_actions.addWidget(self.open_account_storage_button)
        account_actions.addWidget(self.open_account_storage_dir_button)
        account_layout.addLayout(account_actions)
        layout.addWidget(account_group)

        run_actions = QHBoxLayout()
        self.start_button = QPushButton("开始运行", panel)
        self.stop_button = QPushButton("停止任务", panel)
        self.refresh_button = QPushButton("刷新配置", panel)
        run_actions.addWidget(self.start_button)
        run_actions.addWidget(self.stop_button)
        run_actions.addWidget(self.refresh_button)
        layout.addLayout(run_actions)
        layout.addStretch(1)

        self.start_button.clicked.connect(self._emit_start_requested)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.login_platform_combo.currentTextChanged.connect(self._refresh_login_account_combo)
        self.open_login_button.clicked.connect(self._emit_open_login_requested)
        self.save_login_state_button.clicked.connect(self._emit_save_login_state_requested)
        self.account_table.itemSelectionChanged.connect(self._sync_account_action_buttons)
        self.account_table.cellDoubleClicked.connect(lambda row, _column: self._open_selected_account_storage(row))
        self.open_account_storage_button.clicked.connect(self._emit_open_account_storage_requested)
        self.open_account_storage_dir_button.clicked.connect(self._emit_open_account_storage_dir_requested)
        self.open_account_storage_button.setEnabled(False)
        self.open_account_storage_dir_button.setEnabled(False)
        return panel

    def _build_output_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        summary_group = QGroupBox("运行摘要", panel)
        summary_layout = QVBoxLayout(summary_group)
        self.status_label = QLabel("空闲", summary_group)
        self.started_label = QLabel("-", summary_group)
        self.finished_label = QLabel("-", summary_group)
        self.totals_label = QLabel("-", summary_group)
        self.report_label = QLabel("-", summary_group)
        self.report_label.setWordWrap(True)
        summary_layout.addWidget(QLabel("状态", summary_group))
        summary_layout.addWidget(self.status_label)
        summary_layout.addWidget(QLabel("开始时间", summary_group))
        summary_layout.addWidget(self.started_label)
        summary_layout.addWidget(QLabel("结束时间", summary_group))
        summary_layout.addWidget(self.finished_label)
        summary_layout.addWidget(QLabel("统计", summary_group))
        summary_layout.addWidget(self.totals_label)
        summary_layout.addWidget(QLabel("输出文件", summary_group))
        summary_layout.addWidget(self.report_label)

        output_actions = QHBoxLayout()
        self.open_deduped_button = QPushButton("打开汇总结果", summary_group)
        self.open_report_button = QPushButton("打开日报文件", summary_group)
        self.open_output_dir_button = QPushButton("打开输出目录", summary_group)
        output_actions.addWidget(self.open_deduped_button)
        output_actions.addWidget(self.open_report_button)
        output_actions.addWidget(self.open_output_dir_button)
        summary_layout.addLayout(output_actions)
        layout.addWidget(summary_group)

        result_group = QGroupBox("本次结果", panel)
        result_layout = QVBoxLayout(result_group)
        self.results_table = QTableWidget(0, 5, result_group)
        self.results_table.setHorizontalHeaderLabels(["平台", "商品", "账号", "采集数", "告警数"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        result_layout.addWidget(self.results_table)
        layout.addWidget(result_group)

        log_group = QGroupBox("运行日志", panel)
        log_layout = QVBoxLayout(log_group)
        self.log_output = QPlainTextEdit(log_group)
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_group)

        self.open_deduped_button.clicked.connect(
            lambda: self.open_file_requested.emit(self.open_deduped_button.property("path") or "")
        )
        self.open_report_button.clicked.connect(
            lambda: self.open_file_requested.emit(self.open_report_button.property("path") or "")
        )
        self.open_output_dir_button.clicked.connect(
            lambda: self.open_file_requested.emit(self.open_output_dir_button.property("path") or "")
        )
        self.results_table.cellDoubleClicked.connect(lambda row, _column: self.result_details_requested.emit(row))
        return panel

    def _build_fishing_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        actions = QHBoxLayout()
        self.fishing_refresh_button = QPushButton("刷新线索", page)
        self.fishing_messages_button = QPushButton("查看会话", page)
        self.fishing_status_combo = QComboBox(page)
        self.fishing_status_combo.addItems(["pending", "fishing", "manual_required", "failed", "resolved"])
        self.fishing_update_status_button = QPushButton("更新状态", page)
        self.fishing_delete_button = QPushButton("删除商品", page)
        actions.addWidget(self.fishing_refresh_button)
        actions.addWidget(self.fishing_messages_button)
        actions.addWidget(self.fishing_status_combo)
        actions.addWidget(self.fishing_update_status_button)
        actions.addWidget(self.fishing_delete_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.fishing_table = QTableWidget(0, 11, page)
        self.fishing_table.setHorizontalHeaderLabels([
            "序号",
            "商品",
            "标题",
            "卖家",
            "页面价",
            "官方价",
            "判断",
            "状态",
            "创建时间",
            "商品链接",
            "操作",
        ])
        self.fishing_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.fishing_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fishing_table.verticalHeader().setVisible(False)
        self.fishing_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.fishing_table)

        self.fishing_log_output = QPlainTextEdit(page)
        self.fishing_log_output.setReadOnly(True)
        layout.addWidget(self.fishing_log_output)

        self.fishing_refresh_button.clicked.connect(self.fishing_refresh_requested.emit)
        self.fishing_messages_button.clicked.connect(self._emit_selected_fishing_messages)
        self.fishing_update_status_button.clicked.connect(self._emit_selected_fishing_status_update)
        self.fishing_delete_button.clicked.connect(self._emit_selected_fishing_delete)
        self.fishing_table.itemSelectionChanged.connect(self._sync_fishing_buttons)
        self._sync_fishing_buttons()
        return page

    def _build_config_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        description = QLabel("直接编辑 YAML 配置并保存。保存后会自动重新加载运行时配置。", page)
        description.setWordWrap(True)
        layout.addWidget(description)

        self.config_tabs = QTabWidget(page)
        self.config_editors = {}
        for filename in ["settings.yaml", "products.yaml", "accounts.yaml"]:
            editor = QPlainTextEdit(self.config_tabs)
            self.config_editors[filename] = editor

            tab = QWidget(self.config_tabs)
            tab_layout = QVBoxLayout(tab)
            tab_layout.addWidget(editor)

            save_button = QPushButton(f"保存 {filename}", tab)
            save_button.clicked.connect(lambda _checked=False, name=filename: self._emit_save_config(name))
            tab_layout.addWidget(save_button)

            self.config_tabs.addTab(tab, filename)

        layout.addWidget(self.config_tabs)
        return page

    def set_platforms(self, platforms: list[str]) -> None:
        current = self.platform_combo.currentText()
        self.platform_combo.blockSignals(True)
        self.platform_combo.clear()
        self.platform_combo.addItem("all")
        for platform in platforms:
            self.platform_combo.addItem(platform)
        index = self.platform_combo.findText(current)
        self.platform_combo.setCurrentIndex(index if index >= 0 else 0)
        self.platform_combo.blockSignals(False)

    def set_runtime_info(self, products: list[str], accounts: list[str], provider: str, model: str) -> None:
        self.provider_label.setText(f"{provider} / {model}")
        self.products_label.setText("，".join(products) if products else "无")
        self.accounts_label.setText("，".join(accounts) if accounts else "无")

    def set_login_accounts(self, accounts: list[dict]) -> None:
        self._accounts = accounts
        current_platform = self.login_platform_combo.currentText()

        platforms = sorted({account["platform"] for account in accounts})
        self.login_platform_combo.blockSignals(True)
        self.login_platform_combo.clear()
        for platform in platforms:
            self.login_platform_combo.addItem(platform)
        if current_platform:
            index = self.login_platform_combo.findText(current_platform)
            self.login_platform_combo.setCurrentIndex(index if index >= 0 else 0)
        self.login_platform_combo.blockSignals(False)
        self._refresh_login_account_combo()

    def set_account_statuses(self, accounts: list[dict]) -> None:
        self.account_table.setRowCount(len(accounts))
        for row_index, account in enumerate(accounts):
            values = [
                account["platform"],
                account["id"],
                account["status"],
                "是" if account.get("storage_state_exists") else "否",
                account.get("saved_at") or "-",
                account.get("storage_state") or "-",
            ]
            for column_index, value in enumerate(values):
                self.account_table.setItem(row_index, column_index, QTableWidgetItem(value))
        self._sync_account_action_buttons()

    def set_running(self, running: bool) -> None:
        self.start_button.setDisabled(running)
        self.stop_button.setEnabled(running)
        self.refresh_button.setDisabled(running)
        self.status_label.setText("运行中" if running else "空闲")

    def set_login_busy(self, busy: bool) -> None:
        self.open_login_button.setDisabled(busy or self._login_session_active)
        self.save_login_state_button.setDisabled(busy or not self._login_session_active)
        self.login_platform_combo.setDisabled(busy)
        self.login_account_combo.setDisabled(busy)

    def set_login_session_active(self, active: bool, account_id: str) -> None:
        self._login_session_active = active
        self.open_login_button.setEnabled(not active)
        self.save_login_state_button.setEnabled(active)

        if account_id:
            index = self.login_account_combo.findData(account_id)
            if index >= 0:
                self.login_account_combo.setCurrentIndex(index)

    def prepare_for_run(self) -> None:
        self.clear_log()
        self.status_label.setText("准备中")
        self.started_label.setText("-")
        self.finished_label.setText("-")
        self.totals_label.setText("-")
        self.report_label.setText("-")
        self.results_table.setRowCount(0)
        self._set_output_button(self.open_deduped_button, "")
        self._set_output_button(self.open_report_button, "")
        self._set_output_button(self.open_output_dir_button, "")

    def mark_run_stopped(self) -> None:
        self.status_label.setText("已停止")
        self.finished_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")
        if hasattr(self, "fishing_log_output"):
            self.fishing_log_output.appendPlainText(f"[{timestamp}] {message}")

    def clear_log(self) -> None:
        self.log_output.clear()

    def show_summary(self, summary) -> None:
        self.status_label.setText("完成")
        self.started_label.setText(summary.started_at.strftime("%Y-%m-%d %H:%M:%S"))
        self.finished_label.setText(summary.finished_at.strftime("%Y-%m-%d %H:%M:%S"))
        self.totals_label.setText(
            f"采集 {summary.total_listings} 条，告警 {summary.total_alerts} 条，任务 {len(summary.run_results)} 个"
        )

        output_files = []
        if summary.deduped_results_file:
            output_files.append(f"汇总结果: {Path(summary.deduped_results_file)}")
        if summary.report_file:
            output_files.append(f"日报: {Path(summary.report_file)}")
        self.report_label.setText("\n".join(output_files) if output_files else "无输出文件")
        self._set_output_actions(summary)
        self._populate_results_table(summary)

        if summary.options.dry_run:
            self.append_log("Dry-run completed.")
        else:
            self.append_log("Run completed.")

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "运行失败", message)

    def show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    def show_result_details(self, title: str, content: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(860, 560)
        layout = QVBoxLayout(dialog)

        viewer = QPlainTextEdit(dialog)
        viewer.setReadOnly(True)
        viewer.setPlainText(content)
        layout.addWidget(viewer)

        close_button = QPushButton("关闭", dialog)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        dialog.exec()

    def set_config_documents(self, documents: dict) -> None:
        for filename, content in documents.items():
            editor = self.config_editors.get(filename)
            if editor is not None:
                editor.setPlainText(content)

    def set_fishing_alerts(self, alerts: list[dict]) -> None:
        self._fishing_alerts = alerts
        self.fishing_table.setRowCount(len(alerts))
        for row_index, alert in enumerate(alerts):
            values = [
                str(row_index + 1),
                alert.get("product_name", ""),
                alert.get("title", ""),
                alert.get("seller_name", ""),
                str(alert.get("price", "")),
                str(alert.get("official_price", "")),
                alert.get("judgment", ""),
                alert.get("status", ""),
                alert.get("created_at", ""),
            ]
            alert_id = int(alert.get("alert_id") or 0)
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index == 0:
                    item.setData(Qt.UserRole, alert_id)
                self.fishing_table.setItem(row_index, column_index, item)

            open_button = QPushButton("打开", self.fishing_table)
            open_button.clicked.connect(
                lambda _checked=False, row_alert_id=alert_id: self.fishing_open_listing_requested.emit(row_alert_id)
            )
            self.fishing_table.setCellWidget(row_index, 9, open_button)

            start_button = QPushButton("发起询价", self.fishing_table)
            start_button.clicked.connect(
                lambda _checked=False, row_alert_id=alert_id: self.fishing_start_requested.emit(row_alert_id)
            )
            self.fishing_table.setCellWidget(row_index, 10, start_button)
        self._sync_fishing_buttons()

    def _emit_start_requested(self) -> None:
        self.start_requested.emit(
            {
                "platform": self.platform_combo.currentText(),
                "dry_run": self.dry_run_checkbox.isChecked(),
                "headless": self.headless_checkbox.isChecked(),
                "debug_fast": self.debug_fast_checkbox.isChecked(),
                "db_path": self.db_path_input.text().strip() or "data/price_monitor.db",
            }
        )

    def _emit_save_config(self, filename: str) -> None:
        editor = self.config_editors.get(filename)
        if editor is None:
            return
        self.save_config_requested.emit(
            {
                "filename": filename,
                "content": editor.toPlainText(),
            }
        )

    def _emit_open_login_requested(self) -> None:
        account_id = self.login_account_combo.currentData()
        if account_id:
            self.open_login_requested.emit(account_id)

    def _emit_save_login_state_requested(self) -> None:
        account_id = self.login_account_combo.currentData()
        if account_id:
            self.save_login_state_requested.emit(account_id)

    def _refresh_login_account_combo(self) -> None:
        selected_platform = self.login_platform_combo.currentText()
        current_account = self.login_account_combo.currentData()

        self.login_account_combo.blockSignals(True)
        self.login_account_combo.clear()
        for account in self._accounts:
            if not selected_platform or account["platform"] == selected_platform:
                label = f"{account['id']} ({account['status']})"
                self.login_account_combo.addItem(label, account["id"])

        if current_account:
            index = self.login_account_combo.findData(current_account)
            self.login_account_combo.setCurrentIndex(index if index >= 0 else 0)
        self.login_account_combo.blockSignals(False)

    def _populate_results_table(self, summary) -> None:
        self.results_table.setRowCount(len(summary.run_results))
        for row_index, result in enumerate(summary.run_results):
            values = [
                result.platform,
                result.product,
                result.account,
                str(result.listings),
                str(result.alerts),
            ]
            for column_index, value in enumerate(values):
                self.results_table.setItem(row_index, column_index, QTableWidgetItem(value))

    def _set_output_actions(self, summary) -> None:
        self._set_output_button(self.open_deduped_button, summary.deduped_results_file)
        self._set_output_button(self.open_report_button, summary.report_file)

        output_dir = ""
        if summary.deduped_results_file:
            output_dir = str(Path(summary.deduped_results_file).resolve().parent)
        elif summary.report_file:
            output_dir = str(Path(summary.report_file).resolve().parent)
        self._set_output_button(self.open_output_dir_button, output_dir)

    def _set_output_button(self, button: QPushButton, path_text: str) -> None:
        button.setProperty("path", path_text or "")
        button.setEnabled(bool(path_text))

    def _wrap_layout(self, layout, parent: QWidget) -> QWidget:
        wrapper = QWidget(parent)
        wrapper.setLayout(layout)
        return wrapper

    def _sync_account_action_buttons(self) -> None:
        account_id = self._selected_account_id()
        self.open_account_storage_button.setEnabled(bool(account_id))
        self.open_account_storage_dir_button.setEnabled(bool(account_id))

    def _selected_account_id(self) -> str:
        row = self.account_table.currentRow()
        if row < 0:
            return ""
        item = self.account_table.item(row, 1)
        return item.text() if item else ""

    def _emit_open_account_storage_requested(self) -> None:
        account_id = self._selected_account_id()
        if account_id:
            self.open_account_storage_requested.emit(account_id)

    def _emit_open_account_storage_dir_requested(self) -> None:
        account_id = self._selected_account_id()
        if account_id:
            self.open_account_storage_dir_requested.emit(account_id)

    def _open_selected_account_storage(self, row: int) -> None:
        item = self.account_table.item(row, 1)
        if item and item.text():
            self.open_account_storage_requested.emit(item.text())

    def _selected_fishing_alert_id(self) -> int:
        row = self.fishing_table.currentRow()
        if row < 0:
            return 0
        item = self.fishing_table.item(row, 0)
        if item is None:
            return 0
        alert_id = item.data(Qt.UserRole)
        try:
            return int(alert_id or 0)
        except (TypeError, ValueError):
            return 0

    def _sync_fishing_buttons(self) -> None:
        has_alert = bool(self._selected_fishing_alert_id())
        self.fishing_messages_button.setEnabled(has_alert)
        self.fishing_update_status_button.setEnabled(has_alert)
        self.fishing_delete_button.setEnabled(has_alert)
        self.fishing_status_combo.setEnabled(has_alert)
        if not has_alert:
            return
        status_item = self.fishing_table.item(self.fishing_table.currentRow(), 7)
        status = status_item.text() if status_item else ""
        index = self.fishing_status_combo.findText(status)
        if index >= 0:
            self.fishing_status_combo.setCurrentIndex(index)

    def _emit_selected_fishing_messages(self) -> None:
        alert_id = self._selected_fishing_alert_id()
        if alert_id:
            self.fishing_messages_requested.emit(alert_id)

    def _emit_selected_fishing_status_update(self) -> None:
        alert_id = self._selected_fishing_alert_id()
        if alert_id:
            self.fishing_status_update_requested.emit(alert_id, self.fishing_status_combo.currentText())

    def _emit_selected_fishing_delete(self) -> None:
        alert_id = self._selected_fishing_alert_id()
        if not alert_id:
            return
        reply = QMessageBox.question(
            self,
            "删除商品",
            "确定删除这条商品线索吗？相关询价会话记录也会一并删除。",
        )
        if reply == QMessageBox.Yes:
            self.fishing_delete_requested.emit(alert_id)
