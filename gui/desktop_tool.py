"""桌面登记台（M2，入口B）——前台的工具，与群机器人写同一个库。

设计依据（docs/报名结算系统-设计.md 三·入口B；视觉规范参考 visualize 技能的设计原则）：

- **剪贴板双模式**：图片 → OCR（配置了腾讯云）或提示「复制图片内容」人肉兜底；
  身份证识别文本 → 自动填入，**可人工修正再登记**（机器只补空，人改的字段由人负责）；
- **双入口一个库**：有 config/enroll.yaml 就写真连多维表格，否则落本地演示库（标题栏注明）；
- 左右两栏：左「登记」右「记录 + 变更时间线」，底部常用动作（结算/提醒/导出）。
"""
from __future__ import annotations

import os
import sys

ROOT = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                             QListWidget, QMainWindow, QPlainTextEdit,
                             QPushButton, QSplitter, QTextEdit, QVBoxLayout,
                             QWidget)

from enroll.demo_store import DemoStore
from enroll.extract import looks_like_id_text
from enroll.intake import intake_text
from enroll.service import execute, fmt_time

#: 视觉规范：中性底 + 白卡片 + 单主色，字号 14/12，圆角 10/8，克制不堆装饰
STYLE = """
QWidget { background: #F5F6F8; color: #1F2329; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 14px; }
QFrame#card { background: #FFFFFF; border: 1px solid #E4E6EB; border-radius: 10px; }
QFrame#header { background: #FFFFFF; border-bottom: 1px solid #E4E6EB; }
QLabel#title { font-size: 17px; font-weight: 600; color: #1F2329; }
QLabel#subtitle, QLabel#hint { font-size: 12px; color: #6B7280; }
QLabel#section { font-size: 13px; font-weight: 600; color: #374151; }
QLabel#badge { font-size: 12px; color: #2563EB; background: #EFF4FF;
               border: 1px solid #D6E2FF; border-radius: 9px; padding: 2px 8px; }
QPushButton { background: #FFFFFF; border: 1px solid #D5D9E0; border-radius: 8px;
              min-height: 32px; padding: 0 14px; font-size: 13px; color: #1F2329; }
QPushButton:hover { background: #F2F4F7; }
QPushButton#primary { background: #2563EB; border-color: #2563EB; color: #FFFFFF; font-weight: 600; }
QPushButton#primary:hover { background: #1D4ED8; }
QPushButton#ghost { background: transparent; border-color: transparent; color: #374151; }
QPushButton#ghost:hover { background: #EEF0F3; }
QPlainTextEdit, QTextEdit { background: #FFFFFF; border: 1px solid #E4E6EB; border-radius: 8px;
                            padding: 8px; font-size: 13px; selection-background-color: #DBEAFE; }
QListWidget { background: #FFFFFF; border: 1px solid #E4E6EB; border-radius: 8px;
              font-size: 13px; outline: 0; }
QListWidget::item { padding: 8px 10px; border-bottom: 1px solid #F0F1F3; }
QListWidget::item:selected { background: #EFF4FF; color: #1F2329; }
QStatusBar { background: #FFFFFF; border-top: 1px solid #E4E6EB; font-size: 12px; color: #6B7280; }
"""


def make_store():
    """有凭据 → BitableStore（真连）；否则本地 JSON 演示库。返回 (store, 后端说明)。"""
    cfg_path = os.path.join(ROOT, "config", "enroll.yaml")
    if os.path.exists(cfg_path):
        try:
            import yaml
            from enroll.bitable import BitableClient
            from enroll.bitable_store import BitableStore
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            feishu, bitable = cfg.get("feishu", {}), cfg.get("bitable", {})
            if feishu.get("app_id") and bitable.get("app_token"):
                client = BitableClient(feishu["app_id"], feishu["app_secret"],
                                       bitable["app_token"])
                return (BitableStore(client, dict(bitable.get("tables", {}))),
                        "多维表格（真连）")
        except Exception as e:  # noqa: BLE001 — 配置坏/依赖缺 → 降级本地库，别崩
            print(f"[desktop] 真连配置不可用（{e}），降级本地演示库")
    path = os.path.join(ROOT, "data", "desktop_store.json")
    return DemoStore(path), "本地演示库（未配置真连凭据）"


def _card(title: str) -> tuple:
    """白卡片 + 标题，返回 (card, content_layout)。"""
    card = QFrame()
    card.setObjectName("card")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(14, 12, 14, 12)
    outer.setSpacing(10)
    label = QLabel(title)
    label.setObjectName("section")
    outer.addWidget(label)
    return card, outer


def make_ocr_from_config():
    """按 config/enroll.yaml 的 ocr 段构造识别函数；未配置返回 None。"""
    cfg_path = os.path.join(ROOT, "config", "enroll.yaml")
    if not os.path.exists(cfg_path):
        return None
    try:
        import yaml
        from enroll.ocr import make_ocr
        with open(cfg_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        return make_ocr(cfg)
    except Exception as e:  # noqa: BLE001 — OCR 配置坏只是降级，不影响登记
        print(f"[desktop] OCR 不可用（{e}）")
        return None


class DesktopTool(QMainWindow):
    def __init__(self, store=None, backend: str = ""):
        super().__init__()
        self.store, default_backend = (store, backend) if store else make_store()
        if not backend:
            backend = default_backend
        self.backend = backend
        self.ocr = make_ocr_from_config()
        self.setWindowTitle(f"EnrollPilot 培训报名结算助手 — {backend}")
        self.resize(1180, 760)
        self.setStyleSheet(STYLE)
        self._build_ui()
        self.refresh_records()
        self.clip = QApplication.clipboard()
        self.clip.dataChanged.connect(self.on_clipboard_changed)
        self.on_clipboard_changed()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 8)
        body_layout.setSpacing(12)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([520, 620])
        splitter.setChildrenCollapsible(False)
        body_layout.addWidget(splitter)
        layout.addWidget(body, 1)
        layout.addWidget(self._build_footer())
        self.setCentralWidget(root)
        self.statusBar().showMessage("就绪")

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 10, 16, 10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("报名登记台")
        title.setObjectName("title")
        subtitle = QLabel("剪贴板/粘贴身份证文本 → 核对 → 写入报名库（与群机器人同一个库）")
        subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        row.addLayout(titles)
        row.addStretch(1)
        badge = QLabel(self.backend)
        badge.setObjectName("badge")
        row.addWidget(badge)
        return header

    def _build_left(self) -> QWidget:
        card, layout = _card("① 登记")
        self.preview = QLabel("（剪贴板预览）")
        self.preview.setObjectName("hint")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "微信里对图片点「复制图片内容」，把文字粘贴到这里；"
            "或直接复制图片（配置了 OCR 会自动识别）。\n识别错位可以直接改，改完再登记。")
        self.text_edit.setMinimumHeight(120)
        layout.addWidget(self.text_edit)

        buttons = QHBoxLayout()
        self.btn_grab = grab = QPushButton("从剪贴板读取")
        grab.clicked.connect(self.on_clipboard_changed)
        self.btn_register = register = QPushButton("登记入库")
        register.setObjectName("primary")
        register.clicked.connect(self.do_register)
        buttons.addWidget(grab)
        buttons.addWidget(register)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.reply_view = QTextEdit()
        self.reply_view.setReadOnly(True)
        self.reply_view.setPlaceholderText("登记回执与存疑提示会显示在这里")
        layout.addWidget(self.reply_view, 1)
        return card

    def _build_right(self) -> QWidget:
        card, layout = _card("② 报名记录")
        self.record_list = QListWidget()
        self.record_list.currentRowChanged.connect(self.show_detail)
        layout.addWidget(self.record_list, 2)

        detail_title = QLabel("详情与变更时间线")
        detail_title.setObjectName("hint")
        layout.addWidget(detail_title)
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        layout.addWidget(self.detail_view, 2)

        actions = QHBoxLayout()
        self.btn_refresh = refresh = QPushButton("刷新")
        refresh.setObjectName("ghost")
        refresh.clicked.connect(self.refresh_records)
        self.btn_settle = settle = QPushButton("结算日报")
        settle.clicked.connect(self.do_settle)
        self.btn_remind = remind = QPushButton("提醒")
        remind.clicked.connect(self.do_remind)
        self.btn_export = export = QPushButton("导出名单")
        export.clicked.connect(self.do_export)
        for b in (refresh, settle, remind, export):
            actions.addWidget(b)
        actions.addStretch(1)
        layout.addLayout(actions)
        return card

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("header")
        row = QHBoxLayout(footer)
        row.setContentsMargins(16, 8, 16, 8)
        hint = QLabel("提示：状态类字段（报名/缴费/开票）只允许人工修改；机器只补空字段。")
        hint.setObjectName("hint")
        row.addWidget(hint)
        row.addStretch(1)
        return footer

    # ------------------------------------------------------------------
    # 行为
    # ------------------------------------------------------------------
    def on_clipboard_changed(self) -> None:
        image = self.clip.image()
        if not image.isNull():
            if self.ocr:
                self.preview.setText("检测到剪贴板图片，正在 OCR 识别…")
                QApplication.processEvents()
                path = os.path.join(ROOT, "data", "clipboard.png")
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    image.save(path, "PNG")
                    text = self.ocr(path)
                    self.text_edit.setPlainText(text)
                    self.preview.setText("OCR 识别完成，已填入——请核对后登记。")
                except Exception as e:  # noqa: BLE001 — 识别失败回退手动
                    self.preview.setText(f"OCR 失败（{e}）。请在微信里「复制图片内容」后粘贴文字。")
                finally:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
            else:
                self.preview.setText("（剪贴板是图片。OCR 未配置：请在微信里打开图片 →"
                                     "「复制图片内容」→ 回到这里粘贴文字）")
            return
        text = (self.clip.text() or "").strip()
        if not text:
            return
        if looks_like_id_text(text):
            self.text_edit.setPlainText(text)
            self.preview.setText("检测到身份证识别文本，已填入——可人工修正后登记。")
        else:
            self.preview.setText("（剪贴板文本不是身份证识别格式，需要时手动粘贴）")

    def do_register(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            self.reply_view.append("（文本框为空：先粘贴或从剪贴板读取）")
            return
        reply = intake_text(self.store, text, operator="桌面工具", source="桌面工具")
        lines = reply.splitlines()
        if len(lines) > 1:
            self.reply_view.append(f"[{lines[0]}]")
        self.reply_view.append(reply)
        self.reply_view.append("———")
        self.refresh_records()

    def refresh_records(self) -> None:
        self.record_list.clear()
        try:
            records = self.store.records()
        except Exception as e:  # noqa: BLE001 — 真连失败时界面别崩
            self.detail_view.setPlainText(f"读取记录失败：{e}")
            return
        for rec in records:
            self.record_list.addItem(
                f"{rec.get('姓名', '（无名）')}｜{rec.get('公司', '')}｜"
                f"缴费 {rec.get('缴费', '-')}｜{rec.get('缴费状态', '')}")
        self.statusBar().showMessage(f"共 {len(records)} 条记录 · 后端：{self.backend}")

    def show_detail(self, row: int) -> None:
        try:
            records = self.store.records()
        except Exception as e:  # noqa: BLE001
            self.detail_view.setPlainText(f"读取失败：{e}")
            return
        if row < 0 or row >= len(records):
            return
        rec = records[row]
        lines = [f"姓名：{rec.get('姓名', '')}    公司：{rec.get('公司', '')}",
                 f"身份证号：{rec.get('身份证号', '')}    手机号：{rec.get('手机号', '')}",
                 f"工种：{rec.get('工种', '')}    培训类型：{rec.get('培训类型', '')}",
                 f"登记：{fmt_time(rec.get('登记日期', ''))}（{rec.get('登记渠道', '')}）",
                 f"状态：报名 {rec.get('报名状态', '')} / 缴费 {rec.get('缴费状态', '')}"
                 f" / 开票 {rec.get('开票状态', '')}",
                 f"金额：缴费 {rec.get('缴费', '-')} = 公司收费 {rec.get('公司收费', '-')}"
                 f" + 返还 {rec.get('返还', '-')}",
                 "—— 变更时间线 ——"]
        for e in self.store.timeline(rec.get("姓名", "")):
            lines.append(f"{fmt_time(e.get('时间'))} [{e.get('变更类型', '')}] "
                         f"{e.get('字段')}：{e.get('旧值') or '（空）'} → {e.get('新值')}"
                         f"（{e.get('操作人')}，{e.get('触发来源')}）")
        self.detail_view.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # 底部动作
    # ------------------------------------------------------------------
    def do_settle(self) -> None:
        try:
            from enroll.settlement import render_daily
            text = render_daily(self.store.records(), self.store.payments_by_key())
            self.reply_view.append(text)
            self.reply_view.append("———")
        except Exception as e:  # noqa: BLE001
            self.detail_view.setPlainText(f"结算失败：{e}")

    def do_remind(self) -> None:
        try:
            from datetime import date
            from enroll.reminders import due_reminders, render_reminders
            items = due_reminders(self.store.records(), self.store.sessions(),
                                  date.today())
            self.reply_view.append(render_reminders(items))
            self.reply_view.append("———")
        except Exception as e:  # noqa: BLE001
            self.detail_view.setPlainText(f"提醒失败：{e}")

    def do_export(self) -> None:
        try:
            from enroll.export import export_for_command
            out_dir = os.path.join(ROOT, "data", "exports")
            path = export_for_command(self.store, "名单", out_dir)
            self.reply_view.append(f"已导出名单：{path}")
            self.reply_view.append("———")
            self.statusBar().showMessage(f"已导出：{path}")
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"导出失败：{e}")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = DesktopTool()
    window.show()
    if os.environ.get("ENROLLPILOT_SMOKE") == "1":
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1500, app.quit)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
