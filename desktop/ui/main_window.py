from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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
import yaml


LLM_PRESETS = {
    "DashScope / Qwen": {
        "provider": "openai_compatible",
        "model": "qwen3.6-plus",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "${DASHSCOPE_API_KEY}",
    },
    "DeepSeek": {
        "provider": "openai_compatible",
        "model": "deepseek-chat",
        "api_base": "https://api.deepseek.com/v1",
        "api_key": "${DEEPSEEK_API_KEY}",
    },
    "OpenAI / GPT": {
        "provider": "openai_compatible",
        "model": "gpt-4o-mini",
        "api_base": "https://api.openai.com/v1",
        "api_key": "${OPENAI_API_KEY}",
    },
    "Anthropic / Claude": {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-latest",
        "api_base": "",
        "api_key": "${ANTHROPIC_API_KEY}",
    },
    "自定义 OpenAI-compatible": {
        "provider": "openai_compatible",
        "model": "",
        "api_base": "",
        "api_key": "",
    },
}


class MainWindow(QMainWindow):
    start_requested = Signal(dict)
    stop_requested = Signal()
    refresh_requested = Signal()
    save_config_requested = Signal(dict)
    save_llm_config_requested = Signal(dict)
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
    fishing_batch_start_requested = Signal(list)
    fishing_batch_stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self._accounts = []
        self._fishing_alerts = []
        self._fishing_batch_running = False
        self._login_session_active = False
        self.setWindowTitle("Price Detection Desktop")
        self.resize(1180, 720)
        self._build_ui()
        self._localize_text()
        self._apply_styles()
        self._style_tables()
        self._set_button_roles()
        self._set_output_button(self.open_deduped_button, "")
        self._set_output_button(self.open_report_button, "")
        self._set_output_button(self.open_output_dir_button, "")
        self.stop_button.setEnabled(False)
        self.save_login_state_button.setEnabled(False)

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QLabel("价格监控工作台")
        header.setStyleSheet("font-size: 15pt; font-weight: 700; color: #0F172A;")
        layout.addWidget(header)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_run_tab(), "运行")
        tabs.addTab(self._build_fishing_tab(), "询价跟进")
        layout.addWidget(tabs)

        self.setCentralWidget(central)

    def _localize_text(self) -> None:
        self.setWindowTitle("价格监控工作台")

        tabs = self.findChildren(QTabWidget)
        if tabs:
            tabs[0].setTabText(0, "监控运行")
            tabs[0].setTabText(1, "询价跟进")

        self.start_button.setText("开始运行")
        self.stop_button.setText("停止任务")
        self.refresh_button.setText("刷新配置")
        self.headless_checkbox.setText("无头模式")
        self.open_login_button.setText("打开登录窗口")
        self.save_login_state_button.setText("完成登录并保存")
        self.open_account_storage_button.setText("打开登录态文件")
        self.open_account_storage_dir_button.setText("打开登录态目录")
        self.open_deduped_button.setText("打开汇总结果")
        self.open_report_button.setText("打开日报文件")
        self.open_output_dir_button.setText("打开输出目录")

        self.fishing_refresh_button.setText("刷新线索")
        self.fishing_messages_button.setText("查看会话")
        self.fishing_headless_checkbox.setText("无头模式")
        self.fishing_update_status_button.setText("更新状态")
        self.fishing_delete_button.setText("删除商品")
        self.fishing_batch_start_button.setText("批量询价")
        self.fishing_batch_stop_button.setText("停止批量")

        if hasattr(self, "save_llm_config_button"):
            self.save_llm_config_button.setText("保存模型配置")
        if hasattr(self, "reload_llm_config_button"):
            self.reload_llm_config_button.setText("重新加载")

        self.account_table.setHorizontalHeaderLabels(["平台", "账号", "状态", "已保存", "最近保存时间", "存档路径"])
        self.results_table.setHorizontalHeaderLabels(["平台", "商品", "账号", "采集数", "告警数"])
        self.fishing_table.setHorizontalHeaderLabels([
            "选择",
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
        self._set_status_label("空闲", "idle")

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #F6F7F9;
                color: #1F2937;
                font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Segoe UI";
                font-size: 9pt;
            }
            QTabWidget::pane {
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                background: #FFFFFF;
                top: -1px;
            }
            QTabBar::tab {
                background: transparent;
                color: #64748B;
                padding: 7px 16px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                color: #0F766E;
                font-weight: 600;
                border: 1px solid #E5E7EB;
                border-bottom-color: #FFFFFF;
            }
            QGroupBox {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                margin-top: 10px;
                padding: 10px 10px 8px 10px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #0F172A;
            }
            QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit {
                background: #FFFFFF;
                border: 1px solid #D6DAE1;
                border-radius: 6px;
                padding: 4px 7px;
                selection-background-color: #99F6E4;
            }
            QLineEdit:disabled {
                background: #F1F5F9;
                color: #64748B;
                border-color: #D6DAE1;
            }
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {
                border-color: #0F766E;
            }
            QPushButton {
                min-height: 26px;
                padding: 4px 10px;
                border-radius: 6px;
                border: 1px solid #CBD5E1;
                background: #FFFFFF;
                color: #334155;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #F8FAFC;
                border-color: #94A3B8;
            }
            QPushButton:disabled {
                color: #94A3B8;
                background: #F1F5F9;
                border-color: #E2E8F0;
            }
            QPushButton[role="primary"] {
                background: #0F766E;
                border-color: #0F766E;
                color: #FFFFFF;
                font-weight: 600;
            }
            QPushButton[role="primary"]:hover {
                background: #115E59;
                border-color: #115E59;
            }
            QPushButton[role="danger"] {
                color: #B91C1C;
                border-color: #FCA5A5;
                background: #FFF7F7;
            }
            QPushButton[role="danger"]:hover {
                background: #FEE2E2;
            }
            QPushButton[role="small"] {
                min-height: 22px;
                max-height: 22px;
                padding: 2px 8px;
                font-size: 8pt;
                font-weight: 500;
            }
            QTableWidget {
                background: #FFFFFF;
                alternate-background-color: #F8FAFC;
                gridline-color: #E5E7EB;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
            }
            QHeaderView::section {
                background: #F1F5F9;
                color: #334155;
                padding: 5px 6px;
                border: 0;
                border-right: 1px solid #E2E8F0;
                font-weight: 600;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:hover {
                background: transparent;
                color: #1F2937;
            }
            QTableWidget::item:selected {
                background: #F1F5F9;
                color: #1F2937;
            }
            QTableWidget::item:selected:active {
                background: #F1F5F9;
                color: #1F2937;
            }
            QTableWidget::item:selected:!active {
                background: #F1F5F9;
                color: #1F2937;
            }
            QPlainTextEdit {
                font-family: Consolas, "Microsoft YaHei UI", "Microsoft YaHei", "SimHei";
                font-size: 8pt;
            }
            QLabel[state="idle"] {
                color: #475569;
                background: #F1F5F9;
                border: 1px solid #E2E8F0;
                border-radius: 11px;
                padding: 3px 10px;
                font-weight: 600;
            }
            QLabel[state="running"] {
                color: #1D4ED8;
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 11px;
                padding: 3px 10px;
                font-weight: 600;
            }
            QLabel[state="success"] {
                color: #047857;
                background: #ECFDF5;
                border: 1px solid #A7F3D0;
                border-radius: 11px;
                padding: 3px 10px;
                font-weight: 600;
            }
            QLabel[state="warning"] {
                color: #B45309;
                background: #FFFBEB;
                border: 1px solid #FDE68A;
                border-radius: 11px;
                padding: 3px 10px;
                font-weight: 600;
            }
        """)

    def _style_tables(self) -> None:
        for table in [self.account_table, self.results_table, self.fishing_table]:
            table.setAlternatingRowColors(True)
            table.verticalHeader().setDefaultSectionSize(28)
            table.horizontalHeader().setHighlightSections(False)

    def _set_button_roles(self) -> None:
        roles = {
            self.start_button: "primary",
            self.fishing_batch_start_button: "primary",
            self.stop_button: "danger",
            self.fishing_delete_button: "danger",
            self.fishing_batch_stop_button: "danger",
        }
        if hasattr(self, "save_llm_config_button"):
            roles[self.save_llm_config_button] = "primary"
        for button, role in roles.items():
            button.setProperty("role", role)
            self._refresh_widget_style(button)

    def _set_status_label(self, text: str, state: str) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.setFixedWidth(max(72, len(text) * 18))
        self.status_label.setAlignment(Qt.AlignCenter)
        self._refresh_widget_style(self.status_label)

    def _refresh_widget_style(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

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
        self.platform_combo.addItem("xianyu")
        run_form.addRow("平台", self.platform_combo)
        self.db_path_input = QLineEdit("data/price_monitor.db", run_group)
        self.db_path_input.setEnabled(False)
        run_form.addRow("数据库", self.db_path_input)
        self.headless_checkbox = QCheckBox("无头模式", run_group)
        run_form.addRow("", self.headless_checkbox)
        layout.addWidget(run_group)

        runtime_group = QGroupBox("运行时信息", panel)
        runtime_layout = QVBoxLayout(runtime_group)
        self.provider_label = QLabel("-", runtime_group)
        self.products_label = QLabel("-", runtime_group)
        self.accounts_label = QLabel("-", runtime_group)
        self.token_usage_label = QLabel("-", runtime_group)
        self.products_label.setWordWrap(True)
        self.accounts_label.setWordWrap(True)
        self.token_usage_label.setWordWrap(True)
        self.products_label.setMaximumHeight(36)
        self.accounts_label.setMaximumHeight(36)
        runtime_layout.addWidget(QLabel("模型", runtime_group))
        runtime_layout.addWidget(self.provider_label)
        runtime_layout.addWidget(QLabel("商品", runtime_group))
        runtime_layout.addWidget(self.products_label)
        runtime_layout.addWidget(QLabel("账号", runtime_group))
        runtime_layout.addWidget(self.accounts_label)
        runtime_layout.addWidget(QLabel("Token", runtime_group))
        runtime_layout.addWidget(self.token_usage_label)
        layout.addWidget(runtime_group)

        login_group = QGroupBox("账号登录", panel)
        login_form = QFormLayout(login_group)
        self.login_platform_combo = QComboBox(login_group)
        self.login_account_combo = QComboBox(login_group)
        login_form.addRow("平台", self.login_platform_combo)
        login_form.addRow("账号", self.login_account_combo)

        login_hint = QLabel("点击“打开登录窗口”后在浏览器里完成登录，再回到这里点击“完成登录并保存”。", login_group)
        login_hint.setWordWrap(True)
        login_hint.setMaximumHeight(42)
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
        self.account_table.setMaximumHeight(120)
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
        layout.setSpacing(8)

        summary_group = QGroupBox("运行摘要", panel)
        summary_layout = QFormLayout(summary_group)
        summary_layout.setLabelAlignment(Qt.AlignRight)
        summary_layout.setHorizontalSpacing(12)
        summary_layout.setVerticalSpacing(6)
        self.status_label = QLabel("空闲", summary_group)
        self.started_label = QLabel("-", summary_group)
        self.finished_label = QLabel("-", summary_group)
        self.totals_label = QLabel("-", summary_group)
        self.report_label = QLabel("-", summary_group)
        self.report_label.setWordWrap(True)
        summary_layout.addRow("状态", self.status_label)
        summary_layout.addRow("开始时间", self.started_label)
        summary_layout.addRow("结束时间", self.finished_label)
        summary_layout.addRow("统计", self.totals_label)
        summary_layout.addRow("输出文件", self.report_label)

        output_actions = QHBoxLayout()
        self.open_deduped_button = QPushButton("打开汇总结果", summary_group)
        self.open_report_button = QPushButton("打开日报文件", summary_group)
        self.open_output_dir_button = QPushButton("打开输出目录", summary_group)
        output_actions.addWidget(self.open_deduped_button)
        output_actions.addWidget(self.open_report_button)
        output_actions.addWidget(self.open_output_dir_button)
        summary_layout.addRow("", self._wrap_layout(output_actions, summary_group))
        summary_group.setMaximumHeight(190)
        layout.addWidget(summary_group)

        result_group = QGroupBox("本次结果", panel)
        result_layout = QVBoxLayout(result_group)
        self.results_table = QTableWidget(0, 5, result_group)
        self.results_table.setHorizontalHeaderLabels(["平台", "商品", "账号", "采集数", "告警数"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setMinimumHeight(160)
        result_layout.addWidget(self.results_table)
        layout.addWidget(result_group, 1)

        log_group = QGroupBox("运行日志", panel)
        log_layout = QVBoxLayout(log_group)
        self.log_output = QPlainTextEdit(log_group)
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
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
        layout.setSpacing(8)

        actions = QHBoxLayout()
        self.fishing_refresh_button = QPushButton("刷新线索", page)
        self.fishing_messages_button = QPushButton("查看会话", page)
        self.fishing_headless_checkbox = QCheckBox("无头模式", page)
        self.fishing_headless_checkbox.setChecked(True)
        self.fishing_status_combo = QComboBox(page)
        self.fishing_status_combo.addItems([
            "pending",
            "fishing",
            "seller_replied",
            "manual_required",
            "failed",
            "evidence_collected",
            "resolved",
        ])
        self.fishing_update_status_button = QPushButton("更新状态", page)
        self.fishing_delete_button = QPushButton("删除商品", page)
        self.fishing_batch_start_button = QPushButton("批量询价", page)
        self.fishing_batch_stop_button = QPushButton("停止批量", page)
        actions.addWidget(self.fishing_refresh_button)
        actions.addWidget(self.fishing_messages_button)
        actions.addWidget(self.fishing_headless_checkbox)
        actions.addWidget(self.fishing_status_combo)
        actions.addWidget(self.fishing_update_status_button)
        actions.addWidget(self.fishing_delete_button)
        actions.addWidget(self.fishing_batch_start_button)
        actions.addWidget(self.fishing_batch_stop_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.fishing_table = QTableWidget(0, 12, page)
        self.fishing_table.setHorizontalHeaderLabels([
            "选择",
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
        self.fishing_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.fishing_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fishing_table.verticalHeader().setVisible(False)
        self.fishing_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.fishing_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.fishing_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.fishing_table.horizontalHeader().setSectionResizeMode(10, QHeaderView.Fixed)
        self.fishing_table.horizontalHeader().setSectionResizeMode(11, QHeaderView.Fixed)
        self.fishing_table.setColumnWidth(0, 46)
        self.fishing_table.setColumnWidth(1, 52)
        self.fishing_table.setColumnWidth(10, 68)
        self.fishing_table.setColumnWidth(11, 86)
        layout.addWidget(self.fishing_table)

        self.fishing_log_output = QPlainTextEdit(page)
        self.fishing_log_output.setReadOnly(True)
        self.fishing_log_output.setMaximumHeight(120)
        layout.addWidget(self.fishing_log_output)

        self.fishing_refresh_button.clicked.connect(self.fishing_refresh_requested.emit)
        self.fishing_messages_button.clicked.connect(self._emit_selected_fishing_messages)
        self.fishing_update_status_button.clicked.connect(self._emit_selected_fishing_status_update)
        self.fishing_delete_button.clicked.connect(self._emit_selected_fishing_delete)
        self.fishing_batch_start_button.clicked.connect(self._emit_selected_fishing_batch_start)
        self.fishing_batch_stop_button.clicked.connect(self.fishing_batch_stop_requested.emit)
        self.fishing_table.itemSelectionChanged.connect(self._sync_fishing_buttons)
        self.fishing_table.itemChanged.connect(lambda _item: self._sync_fishing_buttons())
        self.fishing_messages_button.setEnabled(False)
        self.fishing_batch_start_button.setEnabled(False)
        self.fishing_batch_stop_button.setEnabled(False)
        self._sync_fishing_buttons()
        return page

    def fishing_headless_enabled(self) -> bool:
        return self.fishing_headless_checkbox.isChecked()

    def set_fishing_batch_running(self, running: bool) -> None:
        self._fishing_batch_running = running
        self.fishing_batch_start_button.setEnabled(False)
        self.fishing_batch_stop_button.setEnabled(running)
        self._sync_fishing_buttons()

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

    def _build_model_config_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        model_group = QGroupBox("LLM 模型", page)
        form = QFormLayout(model_group)

        self.llm_preset_combo = QComboBox(model_group)
        self.llm_preset_combo.addItems(list(LLM_PRESETS.keys()))
        form.addRow("服务", self.llm_preset_combo)

        self.llm_provider_input = QComboBox(model_group)
        self.llm_provider_input.addItems(["openai_compatible", "anthropic"])
        form.addRow("Provider", self.llm_provider_input)

        self.llm_model_input = QComboBox(model_group)
        self.llm_model_input.setEditable(True)
        self.llm_model_input.addItems([
            "qwen3.6-plus",
            "deepseek-chat",
            "gpt-4o-mini",
            "gpt-4o",
            "claude-3-5-sonnet-latest",
        ])
        form.addRow("模型", self.llm_model_input)

        self.llm_api_base_input = QLineEdit(model_group)
        form.addRow("API Base", self.llm_api_base_input)

        self.llm_api_key_input = QLineEdit(model_group)
        self.llm_api_key_input.setEchoMode(QLineEdit.Password)
        form.addRow("API Key", self.llm_api_key_input)

        self.llm_temperature_input = QDoubleSpinBox(model_group)
        self.llm_temperature_input.setRange(0, 2)
        self.llm_temperature_input.setSingleStep(0.1)
        self.llm_temperature_input.setDecimals(2)
        form.addRow("Temperature", self.llm_temperature_input)

        actions = QHBoxLayout()
        self.save_llm_config_button = QPushButton("保存模型配置", model_group)
        self.reload_llm_config_button = QPushButton("重新加载", model_group)
        actions.addWidget(self.save_llm_config_button)
        actions.addWidget(self.reload_llm_config_button)
        actions.addStretch(1)
        form.addRow("", self._wrap_layout(actions, model_group))

        layout.addWidget(model_group)
        layout.addStretch(1)

        self.llm_preset_combo.currentTextChanged.connect(self._apply_llm_preset)
        self.save_llm_config_button.clicked.connect(self._emit_save_llm_config)
        self.reload_llm_config_button.clicked.connect(self.refresh_requested.emit)
        return page

    def set_platforms(self, platforms: list[str]) -> None:
        current = self.platform_combo.currentText()
        self.platform_combo.blockSignals(True)
        self.platform_combo.clear()
        self.platform_combo.addItem("xianyu")
        index = self.platform_combo.findText(current)
        self.platform_combo.setCurrentIndex(index if index >= 0 else 0)
        self.platform_combo.blockSignals(False)

    def set_runtime_info(self, products: list[str], accounts: list[str], provider: str, model: str) -> None:
        self.provider_label.setText(f"{provider} / {model}")
        self.products_label.setText("，".join(products) if products else "无")
        self.accounts_label.setText("，".join(accounts) if accounts else "无")

    def set_token_usage(self, usage: dict) -> None:
        self.token_usage_label.setText(
            f"requests={usage.get('requests', 0)}, "
            f"prompt={usage.get('prompt_tokens', 0)}, "
            f"completion={usage.get('completion_tokens', 0)}, "
            f"total={usage.get('total_tokens', 0)}"
        )

    def set_login_accounts(self, accounts: list[dict]) -> None:
        self._accounts = [account for account in accounts if account["platform"] == "xianyu"]
        current_platform = self.login_platform_combo.currentText()

        platforms = sorted({account["platform"] for account in self._accounts})
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
        accounts = [account for account in accounts if account["platform"] == "xianyu"]
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
        self._set_status_label("运行中" if running else "空闲", "running" if running else "idle")

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
        self._set_status_label("准备中", "warning")
        self.started_label.setText("-")
        self.finished_label.setText("-")
        self.totals_label.setText("-")
        self.report_label.setText("-")
        self.results_table.setRowCount(0)
        self._set_output_button(self.open_deduped_button, "")
        self._set_output_button(self.open_report_button, "")
        self._set_output_button(self.open_output_dir_button, "")

    def mark_run_stopped(self) -> None:
        self._set_status_label("已停止", "warning")
        self.finished_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")
        if hasattr(self, "fishing_log_output"):
            self.fishing_log_output.appendPlainText(f"[{timestamp}] {message}")

    def clear_log(self) -> None:
        self.log_output.clear()

    def show_summary(self, summary) -> None:
        self._set_status_label("已完成", "success")
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
        settings_text = documents.get("settings.yaml")
        if settings_text is not None and hasattr(self, "llm_provider_input"):
            try:
                settings = yaml.safe_load(settings_text) or {}
                self.set_llm_config(settings.get("llm", {}))
            except yaml.YAMLError as exc:
                self.append_log(f"Failed to load model config: {exc}")

        if not hasattr(self, "config_editors"):
            return
        for filename, content in documents.items():
            editor = self.config_editors.get(filename)
            if editor is not None:
                editor.setPlainText(content)

    def set_llm_config(self, llm_config: dict) -> None:
        provider = str(llm_config.get("provider") or "openai_compatible")
        model = str(llm_config.get("model") or "")
        api_base = str(llm_config.get("api_base") or "")
        api_key = str(llm_config.get("api_key") or "")
        temperature = float(llm_config.get("temperature", 0.7))

        self.llm_provider_input.setCurrentText(provider)
        if self.llm_model_input.findText(model) < 0:
            self.llm_model_input.addItem(model)
        self.llm_model_input.setCurrentText(model)
        self.llm_api_base_input.setText(api_base)
        self.llm_api_key_input.setText(api_key)
        self.llm_temperature_input.setValue(temperature)

        preset = self._llm_preset_for(provider, model, api_base)
        if preset:
            self.llm_preset_combo.blockSignals(True)
            self.llm_preset_combo.setCurrentText(preset)
            self.llm_preset_combo.blockSignals(False)

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
            check_item = QTableWidgetItem()
            check_item.setData(Qt.UserRole, alert_id)
            check_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            check_item.setCheckState(Qt.Unchecked)
            self.fishing_table.setItem(row_index, 0, check_item)
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index == 0:
                    item.setData(Qt.UserRole, alert_id)
                self.fishing_table.setItem(row_index, column_index + 1, item)

            open_button = QPushButton("打开", self.fishing_table)
            open_button.setProperty("role", "small")
            open_button.setFixedSize(54, 22)
            self._refresh_widget_style(open_button)
            open_button.clicked.connect(
                lambda _checked=False, row_alert_id=alert_id: self.fishing_open_listing_requested.emit(row_alert_id)
            )
            self.fishing_table.setCellWidget(row_index, 10, open_button)

            start_button = QPushButton("发起询价", self.fishing_table)
            start_button.setProperty("role", "small")
            start_button.setFixedSize(72, 22)
            start_button.setEnabled(False)
            self._refresh_widget_style(start_button)
            start_button.clicked.connect(
                lambda _checked=False, row_alert_id=alert_id: self.fishing_start_requested.emit(row_alert_id)
            )
            self.fishing_table.setCellWidget(row_index, 11, start_button)
        self._sync_fishing_buttons()

    def _emit_start_requested(self) -> None:
        self.start_requested.emit(
            {
                "platform": self.platform_combo.currentText(),
                "dry_run": False,
                "headless": self.headless_checkbox.isChecked(),
                "debug_fast": False,
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

    def _emit_save_llm_config(self) -> None:
        self.save_llm_config_requested.emit(
            {
                "provider": self.llm_provider_input.currentText().strip(),
                "model": self.llm_model_input.currentText().strip(),
                "api_key": self.llm_api_key_input.text().strip(),
                "api_base": self.llm_api_base_input.text().strip(),
                "temperature": self.llm_temperature_input.value(),
            }
        )

    def _apply_llm_preset(self, preset_name: str) -> None:
        preset = LLM_PRESETS.get(preset_name)
        if not preset:
            return
        self.llm_provider_input.setCurrentText(preset["provider"])
        if preset["model"]:
            self.llm_model_input.setCurrentText(preset["model"])
        self.llm_api_base_input.setText(preset["api_base"])
        if preset["api_key"]:
            self.llm_api_key_input.setText(preset["api_key"])

    def _llm_preset_for(self, provider: str, model: str, api_base: str) -> str:
        for name, preset in LLM_PRESETS.items():
            if (
                preset["provider"] == provider
                and preset["model"] == model
                and preset["api_base"] == api_base
            ):
                return name
        return "自定义 OpenAI-compatible"

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
        return self._fishing_alert_id_for_row(row)

    def _fishing_alert_id_for_row(self, row: int) -> int:
        item = self.fishing_table.item(row, 0)
        if item is None:
            return 0
        alert_id = item.data(Qt.UserRole)
        try:
            return int(alert_id or 0)
        except (TypeError, ValueError):
            return 0

    def _selected_fishing_alert_ids(self) -> list[int]:
        checked_rows = []
        for row in range(self.fishing_table.rowCount()):
            item = self.fishing_table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                checked_rows.append(row)

        rows = []
        if checked_rows:
            rows = checked_rows
        selection = self.fishing_table.selectionModel()
        if not rows and selection is not None:
            rows = sorted(index.row() for index in selection.selectedRows())
        if not rows and self.fishing_table.currentRow() >= 0:
            rows = [self.fishing_table.currentRow()]

        alert_ids = []
        seen = set()
        for row in rows:
            alert_id = self._fishing_alert_id_for_row(row)
            if alert_id and alert_id not in seen:
                seen.add(alert_id)
                alert_ids.append(alert_id)
        return alert_ids

    def _sync_fishing_buttons(self) -> None:
        has_alert = bool(self._selected_fishing_alert_id())
        self.fishing_messages_button.setEnabled(False)
        self.fishing_update_status_button.setEnabled(has_alert)
        self.fishing_delete_button.setEnabled(has_alert)
        self.fishing_batch_start_button.setEnabled(False)
        self.fishing_status_combo.setEnabled(has_alert)
        if not has_alert:
            return
        status_item = self.fishing_table.item(self.fishing_table.currentRow(), 8)
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

    def _emit_selected_fishing_batch_start(self) -> None:
        alert_ids = self._selected_fishing_alert_ids()
        if alert_ids:
            self.fishing_batch_start_requested.emit(alert_ids)
