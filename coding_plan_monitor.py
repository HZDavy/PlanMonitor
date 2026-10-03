"""
火山引擎 Coding Plan / Agent Plan 个人版 用量监控小工具
UI: vivo OriginOS 暗色流体 - 黑底 玻璃 巨字 极致留白
"""

import hashlib
import hmac
import json
import os
import sys
import time
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone, timedelta

import requests
from PyQt5.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize, QCoreApplication, QByteArray,
    QRectF, QRect, QPointF, QPoint, QLineF, QUrl,
)
from PyQt5.QtGui import (
    QFont, QFontDatabase, QColor, QPainter, QLinearGradient, QRadialGradient, QBrush,
    QPen, QCursor, QPainterPath, QMouseEvent, QIcon, QPixmap, QDesktopServices,
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QFrame, QFormLayout,
    QComboBox,
    QLineEdit, QGraphicsDropShadowEffect,
    QToolButton, QSizePolicy, QSystemTrayIcon, QMenu, QAction
)


# ============================================================
# 路径
# ============================================================

def _resolve_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

APP_DIR = _resolve_app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

# ============================================================
# 字体 - 用 Windows 默认中文字体 (保证中文渲染 + 字够大)
# ============================================================

FONT_FAMILY = "Microsoft YaHei UI"

# ============================================================
# 全局缩放 - Qt 自带 DPI awareness, 我们最多封顶 1.0 (避免和 Qt 重复放大)
# ============================================================

_SCALE: float = 1.0

def px(n: int) -> int:
    """logical px. 我们启用了 Qt.AA_EnableHighDpiScaling, 所以这里的数字就是逻辑像素,
    Qt 在高 DPI 屏上会自动放大. 我们不再手动乘 _SCALE (那会造成双倍缩放).
    _SCALE 仅保留用于日志/调试."""
    return max(1, int(n))


API_HOST = "ark.cn-beijing.volcengineapi.com"
API_REGION = "cn-beijing"
API_SERVICE = "ark"
API_VERSION = "2024-01-01"
API_ACTION = "GetCodingPlanUsage"

CONSOLE_SUB_PREFIX = "https://console.volcengine.com/ark/region:cn-beijing/subscription/"
CONSOLE_KEY_MGMT = "https://console.volcengine.com/iam/keymanage"

def open_browser(url: str):
    """在系统默认浏览器打开链接, 失败时静默处理 (不打断主流程)."""
    try:
        QDesktopServices.openUrl(QUrl(url))
        _fetch_log(f"open browser -> {url}")
    except Exception as e:
        print(f"[open_browser] {e}")

def subscription_url(plan: str) -> str:
    """根据 plan 返回对应的火山方舟订阅用量页."""
    suffix = "coding-plan" if plan != "agent" else "agent-plan"
    return CONSOLE_SUB_PREFIX + suffix

WINDOW_WINDOWS = [
    ("session", "5H"),
    ("weekly",  "Week"),
    ("monthly", "Month"),
]
WINDOW_TITLES = {
    "session": "近5小时用量",
    "weekly":  "近一周用量",
    "monthly": "近一月用量",
}

REFRESH_INTERVAL_MS = 30 * 1000


# ============================================================
# HMAC-SHA256 V4 签名
# ============================================================

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()

def sign_request(ak: str, sk: str, body: str, action: str = API_ACTION) -> dict:
    now = datetime.now(timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    body_bytes = body.encode("utf-8")
    content_sha256 = sha256_hex(body_bytes)
    # 规范化查询串: 按参数名 ASCII 升序, & 连接 (火山签名必须签进 Action/Version)
    canonical_query = "&".join(
        f"{k}={v}" for k, v in sorted((("Action", action), ("Version", API_VERSION)))
    )
    canonical_headers = (
        f"host:{API_HOST}\n"
        f"x-content-sha256:{content_sha256}\nx-date:{x_date}\n"
    )
    signed_headers = "host;x-content-sha256;x-date"
    canonical_request = f"POST\n/\n{canonical_query}\n{canonical_headers}\n{signed_headers}\n{content_sha256}"
    credential_scope = f"{now.strftime('%Y%m%d')}/{API_REGION}/{API_SERVICE}/request"
    string_to_sign = (
        f"HMAC-SHA256\n{x_date}\n{credential_scope}\n"
        f"{sha256_hex(canonical_request.encode())}"
    )
    k_date = hmac_sha256(sk.encode("utf-8"), now.strftime("%Y%m%d").encode("utf-8"))
    k_region = hmac_sha256(k_date, API_REGION.encode("utf-8"))
    k_service = hmac_sha256(k_region, API_SERVICE.encode("utf-8"))
    k_signing = hmac_sha256(k_service, b"request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"HMAC-SHA256 Credential={ak}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Host": API_HOST,
        "Content-Type": "application/json",
        "X-Date": x_date,
        "X-Content-Sha256": content_sha256,
        "Authorization": authorization,
    }


# ============================================================
# 配置
# ============================================================

DEFAULT_CONFIG = {
    "ak": "", "sk": "", "region": API_REGION,
    "plan": "coding",
    "always_on_top": True, "compact": False,
    "geometry": {}, "screen_index": -1,
}

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[config] save failed: {e}")
        try:
            with open(os.path.join(APP_DIR, "_api.log"), "a", encoding="utf-8") as lf:
                lf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [config] save failed: {e}\n")
        except Exception:
            pass


# ============================================================
# API
# ============================================================

def _fetch_log(msg: str):
    try:
        with open(os.path.join(APP_DIR, "_api.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def usage_action(plan: str) -> str:
    """Agent Plan 用 GetAFPUsage, 否则用 Coding Plan 的 GetCodingPlanUsage."""
    return "GetAFPUsage" if plan == "agent" else "GetCodingPlanUsage"

def _normalize_usage(result: dict, plan: str) -> dict:
    """把 Coding / Agent 两种 action 的返回统一成 QuotaUsage 列表.

    Coding (GetCodingPlanUsage): 已是 {QuotaUsage: [{Level, Percent(0-100), ResetTimestamp(秒)}]}.
    Agent  (GetAFPUsage): 为 {AFPFiveHour/AFPWeekly/AFPMonthly: {Quota, Used, ResetTime(毫秒)}},
                          换算成 Percent=Used/Quota*100, ResetTimestamp 统一为秒, 与 Coding 路径保持一致.
    """
    if plan == "agent":
        windows = {
            "session": "AFPFiveHour",
            "weekly":  "AFPWeekly",
            "monthly": "AFPMonthly",
        }
        usage = []
        for lvl, field in windows.items():
            w = result.get(field) or {}
            try:
                quota = float(w.get("Quota") or 0)
                used = float(w.get("Used") or 0)
                percent = round(used / quota * 100, 2) if quota > 0 else 0.0
            except (TypeError, ValueError):
                percent = 0.0
            try:
                reset = int(int(w.get("ResetTime") or 0) / 1000)
            except (TypeError, ValueError):
                reset = 0
            usage.append({"Level": lvl, "Percent": percent, "ResetTimestamp": reset})
        return {"QuotaUsage": usage}
    return result

def fetch_usage(cfg: dict) -> dict:
    plan = cfg.get("plan", "coding")
    action = usage_action(plan)
    body = "{}"
    headers = sign_request(cfg["ak"], cfg["sk"], body, action=action)
    url = f"https://{API_HOST}/?Action={action}&Version={API_VERSION}"
    ak = cfg.get("ak", "") or ""
    sk = cfg.get("sk", "") or ""
    _fetch_log(f"--> POST {url}")
    _fetch_log(f"    X-Date={headers.get('X-Date')} ak_len={len(ak)} sk_len={len(sk)} tripped=" + (
        "YES-ak==sk" if ak == sk else "no"
    ))
    _fetch_log(f"    SignedHeaders={headers.get('Authorization','').split('SignedHeaders=')[-1].split(',')[0]}")
    resp = requests.post(url, data=body, headers=headers, timeout=10)
    _fetch_log(f"<-- HTTP {resp.status_code} body={resp.text}")
    j = resp.json()
    if "Result" not in j:
        err = j.get("ResponseMetadata", {}).get("Error", {}) or {}
        code = err.get("Code", "")
        msg = err.get("Message", resp.text)
        raise RuntimeError(f"[{code}] {msg}")
    return _normalize_usage(j["Result"], plan)


# ============================================================
# 格式化
# ============================================================

def fmt_countdown(ms_left: int) -> str:
    if ms_left <= 0:
        return "已重置"
    s = ms_left // 1000
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = rem // 60, rem % 60
    if d > 0:
        return f"{d}天 {h}时"
    if h > 0:
        return f"{h}:{m:02d}"
    return f"{m:02d}:{sec:02d}"


# ============================================================
# 主题 - OriginOS 暗色流体
# ============================================================

T = {
    "bg":          "#0a0a0c",
    "card":        "rgba(255,255,255,0.05)",
    "card_hover":  "rgba(255,255,255,0.08)",
    "card_stroke": "rgba(255,255,255,0.08)",
    "fg":          "rgba(255,255,255,0.95)",
    "fg2":         "rgba(255,255,255,0.62)",
    "fg3":         "rgba(255,255,255,0.35)",
    "track":       "rgba(255,255,255,0.08)",
    "fill":        "#ffffff",
    "warn":        "#ffd166",
    "err":         "#ff5e5e",
    "ok":          "#7ce8a8",
    "accent":      "#9b8aff",
}

GLOBAL_QSS = """
QWidget {{
    color: {fg};
    font-family: {font};
    font-weight: 400;
    background: transparent;
}}
QLabel {{ background: transparent; }}
QToolTip {{
    background: #18181c;
    color: #fff;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    padding: 6px 10px;
    font-size: {tip}px;
    font-family: {font};
}}
QLineEdit {{
    background: #1c1c22;
    border: 1px solid #2a2a32;
    border-radius: 10px;
    color: #e6e8ef;
    padding: {le_p}px {le_p2}px;
    font-size: {le}px;
    font-family: {font};
    selection-background-color: {accent};
}}
QLineEdit:focus {{ border: 1px solid {accent}; }}
QProgressBar {{
    background: {track};
    border: none;
    border-radius: 2px;
    height: 4px;
    text-align: center;
    font-family: {font};
}}
QProgressBar::chunk {{
    border-radius: 2px;
    background: {fill};
}}
"""


def build_qss(family: str) -> str:
    return GLOBAL_QSS.format(
        fg=T["fg"], font=family,
        accent=T["accent"], track=T["track"], fill=T["fill"],
        tip=px(12), le=px(14), le_p=px(10), le_p2=px(12),
    )


# ============================================================
# 自绘无标题栏暗色流体对话框（基础组件）
# ============================================================

class FluidDialog(QWidget):
    """
    完全自定义的对话框:
    - 无系统标题栏
    - 自绘黑底 + 紫色光晕 + 28px 圆角
    - 顶栏: 巨字标题 + 右上角 × 关闭
    - 中部: 子类填充 (content_layout)
    - 底部: 子类填充 (footer_layout)
    - 鼠标拖动标题区移动
    - 圆角 ESC 关闭
    """
    def __init__(self, title: str, width: int = 460, height: int = 320, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Dialog | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(width, height)

        # 外层（留阴影边距）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        # body
        self.body = QFrame()
        self.body.setObjectName("fluid_dlg_body")
        body = QVBoxLayout(self.body)
        body.setContentsMargins(24, 18, 24, 20)
        body.setSpacing(16)
        outer.addWidget(self.body)

        # 紫色阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(155, 138, 255, 130))
        self.body.setGraphicsEffect(shadow)

        # 顶栏
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(
            f"color: {T['fg']}; font-family: '{FONT_FAMILY}'; font-size: {px(24)}px; font-weight: 600; letter-spacing: 0.5px;"
        )
        top.addWidget(self.title_lbl)
        top.addStretch(1)

        self.close_btn = QToolButton()
        self.close_btn.setText("×")
        self.close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setStyleSheet(f"""
            QToolButton {{
                background: {T['card']};
                border: 1px solid {T['card_stroke']};
                border-radius: 14px;
                color: {T['fg2']};
                font-size: {px(18)}px;
                padding: 0;
                margin: 0;
            }}
            QToolButton:hover {{
                background: rgba(255, 90, 90, 0.25);
                color: {T['err']};
                border: 1px solid rgba(255, 90, 90, 0.4);
            }}
        """)
        self.close_btn.clicked.connect(self.reject)
        top.addWidget(self.close_btn)
        body.addLayout(top)

        # 分隔
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {T['card_stroke']};")
        body.addWidget(sep)

        # 内容区
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(12)
        body.addLayout(self.content_layout)

        body.addStretch(1)

        # 底部
        self.footer_layout = QHBoxLayout()
        self.footer_layout.setSpacing(8)
        body.addLayout(self.footer_layout)

        # 拖动支持
        self._drag_pos = None
        self._drag_area = QWidget(self)
        self._drag_area.setFixedHeight(40)
        # 让顶栏可拖: 重写整个 dialog 的 mousePressEvent

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.LeftButton and ev.y() < 60:
            self._drag_pos = ev.globalPos() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev: QMouseEvent):
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPos() - self._drag_pos)
            ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_pos = None

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.reject()

    def paintEvent(self, ev):
        """暗色流体底面 + 左上紫光晕 + 顶部高光"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.body.geometry()
        path = QPainterPath()
        path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), 28, 28)

        p.fillPath(path, QColor(T["bg"]))

        glow = QRadialGradient(rect.x() + 30, rect.y() + 30, 200)
        glow.setColorAt(0.0, QColor(155, 138, 255, 55))
        glow.setColorAt(0.6, QColor(155, 138, 255, 18))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillPath(path, QBrush(glow))

        hi = QLinearGradient(0, rect.y(), 0, rect.y() + 50)
        hi.setColorAt(0.0, QColor(255, 255, 255, 12))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(hi))

        pen = QPen(QColor(255, 255, 255, 14))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)

    # 子类按需重写这两个
    def accept(self):
        self.done(1)

    def reject(self):
        self.done(0)

    def done(self, code):
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.close()
        # 模拟 QDialog.Accepted/Rejected=1/0
        self._result_code = code

    def exec_(self):
        # 简单模态
        self.setWindowModality(Qt.ApplicationModal)
        from PyQt5.QtWidgets import QApplication as _QApp
        self.show()
        _QApp.processEvents()
        while self.isVisible():
            _QApp.processEvents()
            time.sleep(0.01)
        return getattr(self, "_result_code", 0)


# ============================================================
# 设置对话框 - 暗色流体
# ============================================================

class SettingsDialog(FluidDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__("设置", width=px(560), height=px(540), parent=parent)
        self.cfg = cfg
        ff = FONT_FAMILY

        # 内容: 表单
        form = QFormLayout()
        form.setSpacing(px(16))
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignLeft)

        def make_label(text):
            l = QLabel(text)
            l.setStyleSheet(
                f"color: {T['fg2']}; font-family: '{ff}'; font-size: {px(15)}px; font-weight: 500; letter-spacing: 1px;"
            )
            return l

        self.ak_edit = QLineEdit(cfg.get("ak", ""))
        self.ak_edit.setPlaceholderText("AKLTxxxxxxxxxxxxxx")
        self.sk_edit = QLineEdit(cfg.get("sk", ""))
        self.sk_edit.setEchoMode(QLineEdit.Password)
        self.sk_edit.setPlaceholderText("Secret Access Key")
        self.region_edit = QLineEdit(cfg.get("region", API_REGION))
        self.region_edit.setPlaceholderText(API_REGION)

        # Plan 切换: 决定打开哪个订阅用量页 (coding-plan / agent-plan)
        self.plan_combo = QComboBox()
        self.plan_combo.addItem("Coding Plan", "coding")
        self.plan_combo.addItem("Agent Plan", "agent")
        current = cfg.get("plan", "coding")
        idx = self.plan_combo.findData(current)
        if idx >= 0:
            self.plan_combo.setCurrentIndex(idx)
        self.plan_combo.setStyleSheet(f"""
            QComboBox {{
                background: {T['card']};
                border: 1px solid {T['card_stroke']};
                border-radius: 10px;
                color: {T['fg']};
                padding: 0 {px(12)}px;
                min-height: {px(36)}px;
                font-family: '{ff}';
                font-size: {px(14)}px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: {px(28)}px;
            }}
            QComboBox QAbstractItemView {{
                background: #17171a;
                border: 1px solid {T['card_stroke']};
                border-radius: 8px;
                color: {T['fg']};
                selection-background-color: {T['accent']};
                selection-color: #0a0a0c;
                outline: 0;
            }}
        """)

        form.addRow(make_label("ACCESS KEY"), self.ak_edit)
        form.addRow(make_label("SECRET KEY"), self.sk_edit)
        form.addRow(make_label("REGION"), self.region_edit)
        form.addRow(make_label("PLAN"), self.plan_combo)
        self.content_layout.addLayout(form)

        hint = QLabel("AK / SK 仅保存在 config.json，不上传任何第三方。")
        hint.setStyleSheet(f"color: {T['fg3']}; font-family: '{ff}'; font-size: {px(13)}px;")
        hint.setWordWrap(True)
        self.content_layout.addWidget(hint)

        # 一键前往火山引擎 Access Key 管理页
        key_btn = QToolButton()
        key_btn.setText("前往火山引擎管理 Access Key →")
        key_btn.setCursor(QCursor(Qt.PointingHandCursor))
        key_btn.setMinimumHeight(px(40))
        key_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: 1px solid {T['card_stroke']};
                border-radius: 12px;
                color: {T['fg2']};
                padding: 0 {px(18)}px;
                font-family: '{ff}';
                font-size: {px(14)}px;
                font-weight: 500;
            }}
            QToolButton:hover {{
                background: {T['card_hover']};
                color: {T['accent']};
                border: 1px solid rgba(255,255,255,0.18);
            }}
        """)
        key_btn.clicked.connect(lambda: open_browser(CONSOLE_KEY_MGMT))
        self.content_layout.addWidget(key_btn)

        # 底部按钮
        cancel = self._make_pill("取消", primary=False)
        cancel.clicked.connect(self.reject)
        save = self._make_pill("保存", primary=True)
        save.clicked.connect(self._on_save)
        self.footer_layout.addStretch(1)
        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(save)

    def _make_pill(self, text: str, primary: bool):
        b = QToolButton()
        b.setText(text)
        b.setCursor(QCursor(Qt.PointingHandCursor))
        b.setMinimumHeight(px(48))
        ff = FONT_FAMILY
        if primary:
            bg = T["accent"]
            fg = "#0a0a0c"
            hover_bg = "#aea4ff"
        else:
            bg = T["card"]
            fg = T["fg2"]
            hover_bg = T["card_hover"]
        b.setStyleSheet(f"""
            QToolButton {{
                background: {bg};
                border: 1px solid transparent;
                border-radius: 20px;
                color: {fg};
                padding: 0 {px(28)}px;
                font-family: '{ff}';
                font-size: {px(16)}px;
                font-weight: 600;
            }}
            QToolButton:hover {{
                background: {hover_bg};
                color: {T['fg'] if not primary else '#0a0a0c'};
            }}
        """)
        return b

    def _on_save(self):
        self.cfg["ak"] = self.ak_edit.text().strip()
        self.cfg["sk"] = self.sk_edit.text().strip()
        self.cfg["region"] = self.region_edit.text().strip() or API_REGION
        self.cfg["plan"] = self.plan_combo.currentData() or "coding"
        self.accept()


# ============================================================
# 信息提示对话框 - 暗色流体（替代 QMessageBox）
# ============================================================

class InfoDialog(FluidDialog):
    def __init__(self, title: str, message: str, parent=None, buttons=None):
        super().__init__(title, width=px(480), height=px(360), parent=parent)
        ff = FONT_FAMILY
        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"color: {T['fg']}; font-family: '{ff}'; font-size: {px(18)}px; font-weight: 500; line-height: 1.5;"
        )
        self.content_layout.addWidget(msg)
        self.content_layout.addStretch(1)

        ok = self._make_pill_button("知道了", primary=True)
        ok.clicked.connect(self.accept)
        self.footer_layout.addStretch(1)
        for text, cb in (buttons or []):
            b = self._make_pill_button(text, primary=False)
            b.clicked.connect(cb)
            self.footer_layout.addWidget(b)
        self.footer_layout.addWidget(ok)

    def _make_pill_button(self, text: str, primary: bool):
        b = QToolButton()
        b.setText(text)
        b.setCursor(QCursor(Qt.PointingHandCursor))
        b.setMinimumHeight(px(48))
        ff = FONT_FAMILY
        if primary:
            bg, fg, hover_bg = T["accent"], "#0a0a0c", "#aea4ff"
        else:
            bg, fg, hover_bg = T["card"], T["fg2"], T["card_hover"]
        b.setStyleSheet(f"""
            QToolButton {{
                background: {bg};
                border: 1px solid transparent;
                border-radius: 20px;
                color: {fg};
                padding: 0 {px(28)}px;
                font-family: '{ff}';
                font-size: {px(16)}px;
                font-weight: 600;
            }}
            QToolButton:hover {{
                background: {hover_bg};
                color: {T['fg'] if not primary else '#0a0a0c'};
            }}
        """)
        return b


# ============================================================
# SVG 图标源 - 内嵌字符串, 避免 PyInstaller 资源路径问题
# ============================================================

# 时钟图标 (viewBox 0 0 48 48, fill-rule=evenodd 形成空心圆环 + L 形指针)
# 原始来自你上传的图标; QSvgRenderer 不识别 CSS currentColor, 我们运行时替换成具体颜色.
CLOCK_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="{color}">'
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M24 2c12.15 0 22 9.85 22 22s-9.85 22-22 22S2 36.15 2 24 11.85 2 24 2zm0 4C14.059 6 6 14.059 6 24s8.059 18 18 18 18-8.059 18-18S33.941 6 24 6zm1 8a1 1 0 011 1v7h7a1 1 0 011 1v2a1 1 0 01-1 1H23a1 1 0 01-1-1V15a1 1 0 011-1h2z"/>'
    '</svg>'
)

# 分隔点 · (用 SVG 矢量圆点替代中文字符, 避免被字体 / 颜色继承影响)
DOT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
    '<circle cx="4" cy="4" r="3" fill="#FFFFFF"/>'
    '</svg>'
)

# 火山方舟 logo (viewBox 0 0 24 24, 原色是浅蓝 #00DCFF + 深蓝 #006AFF).
# 用户要求: 改成纯白色 (#FFFFFF), 且 4 片三角形之间留出 0.4px 的缝隙 (看起来更像"方舟").
# 我们把每个 mask 的 <path fill="#fff"> 矩形稍往内缩 0.4px, 形成视觉间隙.
ARK_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">'
    '<g clip-path="url(#arkIcon_svg__a)">'
    # 第 1 片 (左上浅蓝) - 原 mask d="M.348 22.254h6.344L3.819 13.22a.318.318 0 0 0-.606 0z"
    '<mask id="arkIcon_svg__b" width="7" height="11" x="0" y="12" maskUnits="userSpaceOnUse" style="mask-type: luminance;">'
    '<path fill="#fff" d="M0.748 22.254h5.544L3.519 13.22a.318.318 0 0 0-.606 0z"/>'
    '</mask>'
    '<g mask="url(#arkIcon_svg__b)">'
    '<path fill="#FFFFFF" d="M7.041 12.604H0v10.004h7.041z"/>'
    '</g>'
    # 第 2 片 (右上浅蓝)
    '<mask id="arkIcon_svg__c" width="9" height="12" x="15" y="11" maskUnits="userSpaceOnUse" style="mask-type: luminance;">'
    '<path fill="#fff" d="M16.173 22.266h6.562L19.358 11.624a.318.318 0 0 0-.607 0z"/>'
    '</mask>'
    '<g mask="url(#arkIcon_svg__c)">'
    '<path fill="#FFFFFF" d="M23.489 11.008h-8.06v11.611h8.06z"/>'
    '</g>'
    # 第 3 片 (中部深蓝, 大三角)
    '<mask id="arkIcon_svg__d" width="14" height="22" x="7" y="1" maskUnits="userSpaceOnUse" style="mask-type: luminance;">'
    '<path fill="#fff" d="M7.412 22.265h12.78L14.105 1.956a.315.315 0 0 0-.4-.205.32.32 0 0 0-.206.205z"/>'
    '</mask>'
    '<g mask="url(#arkIcon_svg__d)">'
    '<path fill="#FFFFFF" d="M20.946 1.34H6.668v21.279h14.278z"/>'
    '</g>'
    # 第 4 片 (左下深蓝, 小三角)
    '<mask id="arkIcon_svg__e" width="12" height="17" x="2" y="6" maskUnits="userSpaceOnUse" style="mask-type: luminance;">'
    '<path fill="#fff" d="M3.286 22.267h9.48L8.328 7.113a.315.315 0 0 0-.401-.206.32.32 0 0 0-.206.206L2.883 22.267z"/>'
    '</mask>'
    '<g mask="url(#arkIcon_svg__e)">'
    '<path fill="#FFFFFF" d="M13.516 6.496H2.539v16.125h10.977z"/>'
    '</g>'
    # 第 5 片 (中部浅蓝, 小三角)
    '<mask id="arkIcon_svg__f" width="10" height="14" x="5" y="9" maskUnits="userSpaceOnUse" style="mask-type: luminance;">'
    '<path fill="#fff" d="M6.134 22.267h7.894L10.384 9.68a.315.315 0 0 0-.603 0L5.738 22.267z"/>'
    '</mask>'
    '<g mask="url(#arkIcon_svg__f)">'
    '<path fill="#FFFFFF" d="M14.785 9.066h-9.39v13.555h9.39z"/>'
    '</g>'
    '</g>'
    '<defs><clipPath id="arkIcon_svg__a"><path fill="#fff" d="M0 0h24v24H0z"/></clipPath></defs>'
    '</svg>'
)


# ============================================================
# 时钟图标已彻底移除. 之前尝试了 QPen 描边 / QPainterPath 填充 / QPainterPath+CompositionMode 挖空
# 三种方案, 在 Python 里 QPainter 都能画出, 但 PyInstaller --onefile 打包后 exe 里 QPainter
# 在透明 QPixmap 上完全不画 (debug 落盘的 _clock_pixmap.png 只有 387-457 字节, 几乎是空透明图).
# 经过多轮修复无果, 用户决定: 不要时钟图标了.
# ============================================================


# ============================================================
# 品牌图标 (内嵌 base64, 单文件分发无需外部文件)
# ============================================================
_BRAND_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAAAACXBIWXMAAA9hAAAPYQGoP6dpAAAgAElEQVR4nOy9e7Bt2VXe9xtz"
    "7X3Oube7r9R6tEQjgcGAMS/xkMrYciGwMQLxRpYMpnBsiiDbKZUdyoCTst2hQqiKMTg8bAUlrgoRJrFFDAQQCBsp4AIMxkDAFhIY"
    "AkiAhNTqVj/ueey95sgfY3xjzn1bQhidVrfwWarWvXfvteeajzG+8Y3HnAuurqvr6rq6rq6r6+q6uq6uq+vqurqurqvr6rq6rq6r"
    "6+q6uq6uq+vqurqurqvr6rq6rq6r6+q6uq6uq+vqurqurqvr6rq6rq6r6+q6uq6uq+vqurqurqvr6rq6rq6r6+q6uq6uq+vqurqu"
    "rqvr6nq8XfZYd+B99uo5dw1/p5/ravgjPntn1+91n57xzr6ffzffd2u/5v69s+/eVdvv6npX4393bb673/x+fv+u2nt392uufr/P"
    "/8/g+s8LADrG61605aNeeQFw7Ze+8u7dffd/6P7m2bMXXz8ct2vg3mFtzqbj1jabU9wNt6OO0xqw+tbNtr5g5uBYb7bcpLnR/bi7"
    "g9naWlsxVhxzt9vwvqHZhXW/AGA52pj3hb42b3aOOb6yAT92bItzhq2nDXO6W3cHp9Gw1pphdDpO772bu1k7xjmiActRb+Bu7Oju"
    "0Dvujllz2LRue2/sgLV3d1bf2rKcYHYEHXNugl346je8sdDYLTGLS3dboO/xde+dDc2sGfdCayzcxo49dPdmNzBbmndjsz118wsu"
    "3GmsNFtZu7G69YXWvDnmHbOOt+abfh1rx2DG2vf0tXuz89b9FNzdNk8GP8H35wZvx9ljdr3TrtnCCbQtZh3jAfa9xRqyenea+QXb"
    "5VfYtn+3nNz2+ouP/+ZfAeDf33PER75uxV65PgbS+Zhcf7gB4LXP2/ApP7pfXvXib8D6S31prcGuP3Bzse3S2lNv+PYJd9rm+m1s"
    "jq/jR0d067TudBzHzLqD4fiCbdJ0dDMzB3Aw896HGW64Y5ibue/dvAMNMNwcswWzBo5hDdzp+x3dDDYNw7wB5g75n7tZswVv8RMc"
    "Vt857mAN1g6h29aWDY1Gp3sP5MlnRXM0d3ozw929g1n0LyTBLJoHh4YRiNfd6TQaAJ34fQPcoFuDdQU6bgZuhncAFpq7Gb447g7d"
    "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"
)


def _brand_pixmap(size: int = 64) -> QPixmap:
    """解码内嵌的品牌 m 图标并缩放为指定像素尺寸."""
    pm = QPixmap()
    pm.loadFromData(QByteArray.fromBase64(_BRAND_ICON_B64.encode("ascii")), "PNG")
    if not pm.isNull() and (pm.width() != size or pm.height() != size):
        pm = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pm


def _build_ark_logo(size: int = 18) -> QPixmap:
    """火山方舟 logo (4 片三角形带 0.4px 缝隙) - QPainter 自绘.
    原 SVG 是 24x24 viewBox, 6 个 mask 矩形拼接出 4 片三角形. 这里我们用 4 个 QPainterPath 多边形
    直接画, 每个三角形之间的边留 0.4px 缝隙."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#FFFFFF"))

    # 按 viewBox 24x24 定义每片三角形的三个顶点 (单位: SVG 坐标, 后面乘 size/24 转实际像素)
    # 三角形定义依据原始 SVG 6 个 mask 的边界:
    #   第 1 片 (左上, 大): 顶点 (0,22) (7,22) (3.5,13)
    #   第 2 片 (右上, 中): 顶点 (15,22) (23,22) (19,11.5)
    #   第 3 片 (中部, 大三角): 顶点 (7,22) (20.5,22) (14,2)
    #   第 4 片 (左下, 小): 顶点 (3,22) (13,22) (8,6.7)
    #   第 5 片 (中部, 小三角): 顶点 (5.7,22) (14.4,22) (10.3,9.3)
    # 缝隙: 把每片三角形底边和顶点稍微往内缩 0.4px 模拟
    GAP = 0.4
    triangles = [
        # (x1,y1, x2,y2, x3,y3)
        (0 + GAP,        22 - GAP,   7 - GAP,        22 - GAP,   3.5,            13 + GAP),       # 左上
        (15 + GAP,       22 - GAP,   23 - GAP,       22 - GAP,   19,             11.5 + GAP),     # 右上
        (7 + GAP,        22 - GAP,   20.5 - GAP,     22 - GAP,   14,             2 + GAP),        # 中大
        (3 + GAP*1.5,    22 - GAP,   13 - GAP*1.5,   22 - GAP,   8,              6.7 + GAP),      # 左下
        (5.7 + GAP*1.5,  22 - GAP,   14.4 - GAP*1.5, 22 - GAP,   10.3,           9.3 + GAP),      # 中小
    ]
    scale = size / 24.0
    for (x1, y1, x2, y2, x3, y3) in triangles:
        path = QPainterPath()
        path.moveTo(x1 * scale, y1 * scale)
        path.lineTo(x2 * scale, y2 * scale)
        path.lineTo(x3 * scale, y3 * scale)
        path.closeSubpath()
        p.drawPath(path)

    p.end()
    return pm


class ArkLogoWidget(QLabel):
    """火山方舟 logo - 纯白色, 4 片三角形带 0.4px 缝隙, QPainter 自绘, 不依赖 QSvgRenderer."""
    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        self._size = size
        pm = _build_ark_logo(size=size)
        self.setPixmap(pm)
        self.setScaledContents(True)
        self.setMinimumSize(size, size)
        self.setMaximumSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")


class FluidCard(QFrame):
    """极简暗色流体卡片（巨字 80px）"""
    def __init__(self, key: str, title: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.title = title
        self._pulse = False
        self._pulse_t = 0.0
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 高度交给 QVBoxLayout 按内容自适应, 避免固定高度压缩导致巨字溢出压到进度条
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        f = FONT_FAMILY
        # 统一小字号 (重置 / 刻度 / 单位 %), 与"近X用量"标题同一字号档位
        SMALL_PX = px(15)

        v = QVBoxLayout(self)
        v.setContentsMargins(px(22), px(16), px(22), px(16))
        v.setSpacing(0)

        # 顶部一行: 标题(17) + 重置(17) + 时钟(22), 时钟紧跟重置时间, 整体靠右
        # 顶部一行: title 左对齐, clock + reset 作为整体靠右, clock 在 reset 前面
        # 视觉上: "近 5 小时用量                🕐  3 小时 27 分后重置"
        top = QHBoxLayout()
        top.setSpacing(0)
        top.setContentsMargins(0, 0, 0, 0)
        top.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(
            f"color: {T['fg2']}; font-family: '{f}'; font-size: {px(17)}px; font-weight: 500; letter-spacing: 0.3px;"
        )
        self.title_lbl.setAlignment(Qt.AlignVCenter)
        top.addWidget(self.title_lbl)
        # stretch 把右侧推到窗口右边
        top.addStretch(1)
        # 时钟图标已删, 直接接 "—后重置" 文字 (之前 clock_lbl 在中间, 现在去掉)
        self.reset_lbl = QLabel("—后重置")
        self.reset_lbl.setStyleSheet(
            f"color: {T['fg2']}; font-family: '{f}'; font-size: {px(17)}px; font-weight: 500; letter-spacing: 0.3px;"
        )
        self.reset_lbl.setAlignment(Qt.AlignVCenter)
        top.addWidget(self.reset_lbl)
        v.addLayout(top)
        # 标题行 与 巨字行 之间留 20px 呼吸 (上下均衡)
        v.addSpacing(px(20))

        # 巨字 - 大数字 52px + 小号单位 % 22px, 横排, 整行 widget 高度 70px
        # (52 字号 + 上下 9 缓冲, 给足行高确保 descender 不溢出, 同时减少下方留白)
        big_row = QHBoxLayout()
        big_row.setSpacing(px(4))
        big_row.setContentsMargins(0, 0, 0, 0)
        big_row.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.big_lbl = QLabel("—")
        self.big_lbl.setStyleSheet(
            f"color: {T['fg']}; font-family: '{f}'; font-size: {px(52)}px; font-weight: 700; letter-spacing: {px(-2)}px; line-height: 100%;"
        )
        self.big_lbl.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.big_lbl.setMinimumHeight(px(70))
        self.big_lbl.setMaximumHeight(px(70))
        big_row.addWidget(self.big_lbl)
        self.unit_lbl = QLabel("%")
        self.unit_lbl.setStyleSheet(
            f"color: {T['fg2']}; font-family: '{f}'; font-size: {px(22)}px; font-weight: 400; letter-spacing: 0px;"
        )
        self.unit_lbl.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.unit_lbl.setMinimumHeight(px(70))
        self.unit_lbl.setMaximumHeight(px(70))
        # 让 % 在大数字基线下沿附近, 模拟官方样式
        self.unit_lbl.setContentsMargins(0, 0, 0, px(10))
        big_row.addWidget(self.unit_lbl)
        big_row.addStretch(1)
        v.addLayout(big_row)
        # 巨字 与 进度条 之间留 20px (减 8px, 让巨字视觉重心上移, 上下均衡)
        v.addSpacing(px(20))

        # 进度条 (官方样式: 较矮, 紫色填充)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setFixedHeight(px(8))
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        # 进度条 与 底部刻度 之间留 10px
        v.addSpacing(px(10))

        # 底部刻度: 0%   50%   100%  - 与重置文字同字号
        scale = QHBoxLayout()
        scale.setSpacing(0)
        scale.setContentsMargins(0, 0, 0, 0)
        scale_l = QLabel("0%")
        scale_l.setStyleSheet(
            f"color: {T['fg3']}; font-family: '{f}'; font-size: {SMALL_PX}px; font-weight: 400; letter-spacing: 0.3px;"
        )
        scale_l.setAlignment(Qt.AlignLeft)
        scale.addWidget(scale_l)
        scale.addStretch(1)
        scale_m = QLabel("50%")
        scale_m.setStyleSheet(
            f"color: {T['fg3']}; font-family: '{f}'; font-size: {SMALL_PX}px; font-weight: 400; letter-spacing: 0.3px;"
        )
        scale_m.setAlignment(Qt.AlignCenter)
        scale.addWidget(scale_m)
        scale.addStretch(1)
        scale_r = QLabel("100%")
        scale_r.setStyleSheet(
            f"color: {T['fg3']}; font-family: '{f}'; font-size: {SMALL_PX}px; font-weight: 400; letter-spacing: 0.3px;"
        )
        scale_r.setAlignment(Qt.AlignRight)
        scale.addWidget(scale_r)
        v.addLayout(scale)

    def start_pulse(self):
        if self._pulse:
            return
        self._pulse = True
        t = QTimer(self)
        t.timeout.connect(self._tick_pulse)
        t.start(70)
        self._pulse_timer = t

    def stop_pulse(self):
        self._pulse = False
        self._apply_fill(T["fill"])

    def _tick_pulse(self):
        self._pulse_t = (self._pulse_t + 0.05) % 1.0
        alpha = 0.55 + 0.45 * abs(0.5 - self._pulse_t) * 2
        self._apply_fill(f"rgba(255, 94, 94, {alpha:.2f})")

    def _apply_fill(self, color):
        # 默认白色 chunk 太亮, 在暗色背景上扎眼, 统一降一档透明度
        chunk_color = color
        if color.lower() in ("#ffffff", "white", "rgb(255,255,255)"):
            chunk_color = "rgba(255, 255, 255, 0.85)"
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(255, 255, 255, 0.10);
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                border-radius: 3px;
                background: {chunk_color};
            }}
        """)

    def update_data(self, percent: float, reset_ms: int):
        pct = max(0.0, min(float(percent), 100.0))
        self.bar.setValue(int(pct * 10))

        # 拆成两个 label, 大数字+小 %, 避免 rich text 撑爆行高
        self.big_lbl.setText(f"{pct:.2f}")
        self.unit_lbl.setText("%")

        if pct <= 0:
            self.reset_lbl.setText("—后重置")
            self.stop_pulse()
            self._apply_fill(T["fill"])
            self.big_lbl.setStyleSheet(
                f"color: {T['fg']}; font-family: '{FONT_FAMILY}'; font-size: {px(52)}px; font-weight: 700; letter-spacing: {px(-2)}px;"
            )
            return

        now_ms = int(time.time() * 1000)
        left = reset_ms - now_ms
        self.reset_lbl.setText(f"{fmt_countdown(left)}后重置")

        if pct >= 85:
            self.start_pulse()
            color = T["err"]
        elif pct >= 70:
            self.stop_pulse()
            self._apply_fill(T["warn"])
            color = T["warn"]
        else:
            self.stop_pulse()
            self._apply_fill(T["fill"])
            color = T["fg"]

        self.big_lbl.setStyleSheet(
            f"color: {color}; font-family: '{FONT_FAMILY}'; font-size: {px(52)}px; font-weight: 700; letter-spacing: {px(-2)}px;"
        )


# ============================================================
# 托盘图标 - 用 QPainter 自绘，不依赖 PIL
# ============================================================

def _build_tray_pixmap(ok: bool = True) -> QPixmap:
    """绘制 64x64 托盘图标: 品牌 m 图标作为底图 + 右上角状态点 (绿/红)."""
    size = 64
    pm = _brand_pixmap(size=size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    # 右上角状态点: 绿/红, 直径 size*0.22, 描边深色
    dot_d = size * 0.30
    dot_x = size - dot_d - 1
    dot_y = 1
    if ok:
        dot_color = QColor(46, 212, 122, 255)   # 绿
    else:
        dot_color = QColor(255, 80, 80, 255)    # 红
    p.setBrush(QBrush(dot_color))
    p.setPen(QPen(QColor(14, 15, 18, 255), 2))  # 深色描边
    p.drawEllipse(QRectF(dot_x, dot_y, dot_d, dot_d))

    p.end()
    return pm


# ============================================================
# 胶囊按钮
# ============================================================

# ============================================================
# 自定义圆角下拉菜单 (替代 QMenu, 解决 Windows QMenu border-radius 不生效)
# ============================================================

def _css_qcolor(s: str) -> "QColor":
    """把 config 里 '#hex' / 'rgba(r,g,b,a)' 形式的颜色字符串解析成 QColor.
    QColor 构造函数不认 rgba(...) 写法, 直接传会得到无效(黑色), 必须手动解析."""
    from PyQt5.QtGui import QColor
    if not s:
        return QColor(255, 255, 255)
    s = s.strip()
    if s.lower().startswith("rgba(") and s.endswith(")"):
        inner = s[5:-1]
        parts = [p.strip() for p in inner.split(",")]
        if len(parts) == 4:
            try:
                r = max(0, min(255, int(parts[0])))
                g = max(0, min(255, int(parts[1])))
                b = max(0, min(255, int(parts[2])))
                a = float(parts[3])
                a = max(0.0, min(1.0, a))
                return QColor(r, g, b, int(a * 255))
            except (ValueError, TypeError):
                pass
    c = QColor(s)
    if not c.isValid():
        return QColor(255, 255, 255)
    return c


class _MenuItem(QToolButton):
    CHECK_W = 18  # ✓ 宽度 (含右侧间距占位)

    def __init__(self, text: str, checkable: bool = False, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setCheckable(checkable)
        self.setChecked(checked)
        self.setMinimumHeight(px(40))
        # 横向撑满整行, 让悬停/点击热区覆盖整个菜单行而不是只有文字
        self.setMinimumWidth(px(200))
        sp = self.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Expanding)
        self.setSizePolicy(sp)
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setFocusPolicy(Qt.NoFocus)

    def _bg_path(self) -> "QPainterPath":
        # 圆角背景, 覆盖整个按钮客户区
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QPainterPath
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        return path

    def paintEvent(self, ev):
        # 完全自绘: 背景(悬停/选中) + 左侧勾选标记 + 左对齐文本.
        # QToolButton 的 QSS text-align 在不同 Qt/Windows 版本上不可靠, 会退化成居中,
        # 因此这里不依赖样式表, 手动控制文本绘制以强制左对齐.
        from PyQt5.QtCore import QRectF, QLineF, Qt
        from PyQt5.QtGui import (QPainter, QColor, QPen, QFont, QFontMetrics)
        checked = self.isCheckable() and self.isChecked()
        hover = self.underMouse()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 背景
        bg = QColor(0, 0, 0, 0)
        if checked:
            bg = QColor(155, 138, 255, 36 if hover else 26)
        elif hover:
            bg = QColor(155, 138, 255, 36)
        p.fillPath(self._bg_path(), bg)
        # 字体 (与 QSS 保持一致, 用像素字号保证高 DPI 正确)
        f = QFont(FONT_FAMILY)
        f.setPixelSize(px(18))
        f.setWeight(QFont.Medium)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
        p.setFont(f)
        cy = self.height() / 2
        left = px(20)
        # 选中时左侧画紫色小方块 + 白色 ✓, 并让文本让出空间
        if checked:
            cx = px(12)
            small = __import__("PyQt5.QtGui", fromlist=["QPainterPath"]).QPainterPath()
            small.addRoundedRect(int(cx - 5), int(cy - 5), 10, 10, 2, 2)
            p.fillPath(small, QColor("#9b8aff"))
            pen = QPen(QColor(255, 255, 255))
            pen.setWidthF(1.6)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawLine(QLineF(cx - 2.5, cy + 0.2, cx - 0.5, cy + 2.2))
            p.drawLine(QLineF(cx - 0.5, cy + 2.2, cx + 3.0, cy - 2.0))
            left += self.CHECK_W + px(6)
        # 左对齐文本 (超出部分省略)
        metrics = QFontMetrics(f)
        avail_w = max(0, self.width() - left - px(20))
        elided = metrics.elidedText(self.text(), Qt.ElideRight, avail_w)
        p.setPen(QColor("#9b8aff") if checked else _css_qcolor(T['fg']))
        p.drawText(QRectF(left, 0, avail_w, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, elided)
        p.end()


class PopupMenu(QWidget):
    """无边框圆角下拉菜单, paintEvent 自画, 4 个角都是真正的圆角."""
    def __init__(self, parent=None):
        super().__init__(parent)
        # popup 特性
        self.setWindowFlags(
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 阴影 (用 QGraphicsDropShadowEffect 在 QWidget 上)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(shadow)

        # 内容 layout
        self._root = QFrame(self)
        self._root.setObjectName("popupRoot")
        # _root 不画背景, 让 self.paintEvent 的圆角矩形透过来
        self._root.setAttribute(Qt.WA_TranslucentBackground, True)
        self._root.setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(px(10), px(10), px(10), px(10))
        lay.setSpacing(0)
        lay.addWidget(self._root)

        inner = QVBoxLayout(self._root)
        inner.setContentsMargins(px(4), px(4), px(4), px(4))
        inner.setSpacing(0)

    def add_item(self, text: str, on_click, checkable=False, checked=False) -> _MenuItem:
        btn = _MenuItem(text, checkable=checkable, checked=checked, parent=self._root)
        btn.clicked.connect(on_click)
        self._root.layout().addWidget(btn)
        self._items = getattr(self, "_items", [])
        self._items.append(btn)
        return btn

    def add_separator(self):
        sep = QFrame(self._root)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255,255,255,0.08); border: none;")
        self._root.layout().addWidget(sep)

    def show_at(self, global_pos):
        # 先显示一次让 layout 计算尺寸, 再移动
        self.adjustSize()
        x = global_pos.x()
        y = global_pos.y()
        # 防超出屏幕右边/底边
        scr = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        if scr:
            avail = scr.availableGeometry()
            w, h = self.width(), self.height()
            if x + w > avail.x() + avail.width():
                x = avail.x() + avail.width() - w - px(8)
            if y + h > avail.y() + avail.height():
                y = global_pos.y() - h  # 翻到上方
                if y < avail.y():
                    y = avail.y() + px(8)
        self.move(x, y)
        self.show()
        self.raise_()
        # 不再 installEventFilter - 之前的全局 eventFilter 会拦截到 popup 内
        # 按钮的 MouseButtonPress 事件, 引起重入导致卡死.

    def popup(self, global_pos):
        # 兼容 QMenu 的接口, 让 QSystemTrayIcon.setContextMenu 能用
        self.show_at(global_pos)

    def mousePressEvent(self, ev):
        # popup 空白处被点击时关闭 (按钮区域被点击会先消费, 不会到这里)
        if ev.button() == Qt.LeftButton:
            self.hide()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def hideEvent(self, ev):
        # PopupMenu 是独立组件, 没有主窗口的 _log
        super().hideEvent(ev)

    def eventFilter(self, obj, ev):
        # 保留空实现, 不再监听全局事件
        return False

    def paintEvent(self, ev):
        # self 是 WA_TranslucentBackground, _root 是 self 的子 QFrame
        # 但 QSS border-radius 在 QFrame 不裁剪, 所以这里直接画一个圆角深色矩形
        from PyQt5.QtGui import QPainter, QPainterPath, QColor, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 圆角矩形 path (范围 = self 整个客户区)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        p.fillPath(path, QColor("#15151a"))
        # 描边
        pen = QPen(QColor(255, 255, 255, 26))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)


class PillButton(QToolButton):
    def __init__(self, text: str, tip: str = "", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setToolTip(tip)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumHeight(36)
        self.setFont(QFont("", 12))
        self.setStyleSheet(f"""
            QToolButton {{
                background: {T['card']};
                border: 1px solid {T['card_stroke']};
                border-radius: 18px;
                color: {T['fg2']};
                padding: 0 18px;
                font-size: {px(13)}px;
                font-weight: 500;
                letter-spacing: 0.5px;
            }}
            QToolButton:hover {{
                background: {T['card_hover']};
                color: {T['fg']};
                border: 1px solid rgba(255,255,255,0.18);
            }}
            QToolButton:pressed {{
                background: rgba(255,255,255,0.12);
            }}
        """)


# ============================================================
# 主窗口
# ============================================================

class FluidWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.cards = {}
        self.last_update_ms = 0
        self.last_status_text = "未配置"
        self.last_status_ok = False
        self._drag_pos = None
        self._in_toggle = False
        self._last_screen = None

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Window
            | Qt.Tool
            | (Qt.WindowStaysOnTopHint if self.cfg.get("always_on_top", True) else Qt.WindowType(0))
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._build_ui()
        self._restore_geometry()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_INTERVAL_MS)
        QTimer.singleShot(200, self.refresh)

        self._enter_animation()

        # 系统托盘
        self._quitting = False
        self._tray_notified = False
        self.last_top_state = self._is_top()
        # 日志 - 用于排查 toggle_top 路径下的窗口关闭问题
        # 用 exe 所在目录, 方便用户找
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self._log_path = os.path.join(base_dir, "_debug.log")
        try:
            self._log = open(self._log_path, "a", encoding="utf-8")
            self._log.write(f"\n--- FluidWindow start @ {datetime.now().isoformat()} ---\n")
            self._log.flush()
        except Exception:
            self._log = None
        try:
            self.destroyed.connect(lambda *_: self._safe_close_log())
        except Exception:
            pass
        # 构建托盘 + 同步置顶状态
        self._build_tray()
        self._sync_top()

    def _safe_close_log(self):
        try:
            if self._log:
                self._log.close()
        except Exception:
            pass

    def _logf(self, msg: str):
        log = getattr(self, "_log", None)
        if not log:
            return
        try:
            log.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")
            log.flush()
        except Exception:
            pass

    def _build_ui(self):
        f = FONT_FAMILY

        # 外层 - 给阴影留空间: 上/左/右 28, 下 52 (阴影向下 8 + blur 36/2 = 26, 留点余量)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(px(28), px(28), px(28), px(52))
        outer.setSpacing(0)

        self.body = QFrame()
        self.body.setObjectName("body")
        # body 自己画: 圆角深色背景 + 渐变光效 + 描边 + QGraphicsDropShadowEffect 自动阴影
        shadow = QGraphicsDropShadowEffect(self.body)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.body.setGraphicsEffect(shadow)
        # body 自身不消费鼠标事件, 转发给 window 让拖动生效
        self.body.mousePressEvent = self._body_mouse_press
        self.body.mouseMoveEvent = self._body_mouse_move
        self.body.mouseReleaseEvent = self._body_mouse_release
        # body 自己画背景+渐变光效+描边 (替代被删掉的 paintEvent)
        self.body.paintEvent = self._body_paint
        body = QVBoxLayout(self.body)
        body.setContentsMargins(px(28), px(22), px(28), px(20))  # 整体外边距 28, 不再贴边
        body.setSpacing(px(14))
        outer.addWidget(self.body)

        # 顶部品牌行 - 火山方舟 logo(纯白) + "火山方舟"(白) + "·"(白) + "已连接"(绿)
        # 整体左对齐与下方卡片左边界同列
        brand = QHBoxLayout()
        brand.setSpacing(0)
        brand.setContentsMargins(px(22), 0, px(12), 0)  # 左 22 与 cards title_lbl 同列对齐, 右 12 让汉堡按钮更贴近右边缘
        # 1. 火山方舟 logo (纯白, 18px)
        self.brand_logo = ArkLogoWidget(size=px(18))
        brand.addWidget(self.brand_logo, 0, Qt.AlignVCenter)
        # 2. 8px 间距
        brand.addSpacing(px(8))
        # 3. "火山方舟" 白色文字
        self.brand_title_lbl = QLabel("火山方舟")
        self.brand_title_lbl.setStyleSheet(
            f"color: {T['fg']}; font-family: '{f}'; font-size: {px(20)}px; font-weight: 600; letter-spacing: 0.5px;"
        )
        self.brand_title_lbl.setAlignment(Qt.AlignVCenter)
        brand.addWidget(self.brand_title_lbl, 0, Qt.AlignVCenter)
        # 4. 8px 间距
        brand.addSpacing(px(8))
        # 5. "·" 分隔符 (白色)
        self.brand_dot_lbl = QLabel("·")
        self.brand_dot_lbl.setStyleSheet(
            f"color: {T['fg']}; font-family: '{f}'; font-size: {px(20)}px; font-weight: 600;"
        )
        self.brand_dot_lbl.setAlignment(Qt.AlignVCenter)
        brand.addWidget(self.brand_dot_lbl, 0, Qt.AlignVCenter)
        # 6. 8px 间距
        brand.addSpacing(px(8))
        # 7. "已连接" 绿色文字 (用单色绿, 不依赖 status 颜色)
        self.brand_status_lbl = QLabel("已连接")
        self.brand_status_lbl.setStyleSheet(
            f"color: #2ed47a; font-family: '{f}'; font-size: {px(20)}px; font-weight: 600; letter-spacing: 0.5px;"
        )
        self.brand_status_lbl.setAlignment(Qt.AlignVCenter)
        brand.addWidget(self.brand_status_lbl, 0, Qt.AlignVCenter)
        # stretch 推到左边, 汉堡按钮在右边
        brand.addStretch(1)
        # 去掉 plan_lbl (logo 改成单行)

        # 汉堡按钮 - 点击弹出与托盘菜单相同的下拉
        self.hamburger_btn = QToolButton()
        self.hamburger_btn.setText("≡")
        self.hamburger_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.hamburger_btn.setFixedSize(px(40), px(40))
        self.hamburger_btn.setToolTip("菜单")
        self.hamburger_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 14px;
                color: {T['fg']};
                font-family: '{FONT_FAMILY}';
                font-size: {px(34)}px;
                font-weight: 500;
                padding: 0;
            }}
            QToolButton:hover {{
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.10);
            }}
            QToolButton:pressed {{
                background: rgba(155,138,255,0.18);
            }}
        """)
        self.hamburger_btn.clicked.connect(self._on_hamburger_clicked)
        brand.addWidget(self.hamburger_btn, 0, Qt.AlignVCenter)
        body.addLayout(brand)

        # 品牌块和卡片之间多 12px 呼吸, 但卡片之间保持紧凑
        spacer = QFrame()
        spacer.setFixedHeight(px(12))
        spacer.setAttribute(Qt.WA_TranslucentBackground)
        body.addWidget(spacer)

        # 三个卡片
        cards_box = QVBoxLayout()
        cards_box.setSpacing(px(12))
        body.addLayout(cards_box)

        for key, _ in WINDOW_WINDOWS:
            card = FluidCard(key, WINDOW_TITLES[key])
            self.cards[key] = card
            cards_box.addWidget(card)

        # 底部留一个 stretch, 这样万一窗口被拉大, 内容顶住顶端不散
        body.addStretch(1)

        self._sync_top()

    # ---- body 自身的 paintEvent: 画渐变光效 (左上紫光 + 右下红晕 + 顶部高光) ----
    def _body_paint(self, ev):
        from PyQt5.QtGui import QPainter, QPainterPath, QLinearGradient, QRadialGradient, QColor, QPen
        p = QPainter(self.body)
        p.setRenderHint(QPainter.Antialiasing)
        # 注意: body.rect() 是 body 自身坐标系, x/y 永远 = 0
        w, h = self.body.width(), self.body.height()
        radius = 24

        # 1) 用圆角 path 裁剪, 先填 bg
        clip = QPainterPath()
        clip.addRoundedRect(0, 0, w, h, radius, radius)
        p.setClipPath(clip)
        p.fillRect(0, 0, w, h, QColor(T["bg"]))

        # 2) 左上紫色 radial
        glow = QRadialGradient(30, 30, 220)
        glow.setColorAt(0.0, QColor(155, 138, 255, 45))
        glow.setColorAt(0.5, QColor(155, 138, 255, 14))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, glow)

        # 3) 右下橙红 radial
        glow2 = QRadialGradient(w - 20, h - 20, 160)
        glow2.setColorAt(0.0, QColor(255, 80, 60, 28))
        glow2.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, glow2)

        # 4) 顶部高光 (亮一点点)
        hi = QLinearGradient(0, 0, 0, 60)
        hi.setColorAt(0.0, QColor(255, 255, 255, 10))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, w, h, hi)

        # 5) 1px 白色描边 (模拟 QSS border)
        p.setClipping(False)
        pen = QPen(QColor(255, 255, 255, 12))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(clip)

    # ---- body 鼠标转发到 self, 让 drag 生效 ----
    def _body_mouse_press(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPos() - self.frameGeometry().topLeft()
            ev.accept()

    def _body_mouse_move(self, ev):
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPos() - self._drag_pos)
            ev.accept()

    def _body_mouse_release(self, ev):
        self._drag_pos = None
        self._save_geometry()
        self._clamp_to_screen()

    # ---- 拖动 ----
    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.LeftButton and ev.y() < 60:
            self._drag_pos = ev.globalPos() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev: QMouseEvent):
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPos() - self._drag_pos)
            ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_pos = None
        self._save_geometry()
        self._clamp_to_screen()

    # ---- 入场动画 ----
    def _enter_animation(self):
        self.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(420)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._enter_anim = anim

    # ---- 置顶 ----
    def _set_top(self, enable: bool):
        """用 Qt 标准 setWindowFlags 切换 WindowStaysOnTopHint.

        之前用 Win32 SetWindowPos 在本机 Windows 上一律返回 ok=0 (失败), 导致窗口
        永远置不了顶. 这里改用 Qt 自带标志, 稳定且不依赖 Win32. 用 _applying_top
        保护避免 setWindowFlags -> show -> showEvent -> _set_top 的递归.
        """
        if getattr(self, "_applying_top", False):
            return
        try:
            was_visible = self.isVisible()
            self._applying_top = True
            flags = self.windowFlags()
            if enable:
                flags |= Qt.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            # setWindowFlags 在部分平台会隐藏窗口, 显式重新 show/raise 恢复
            if was_visible:
                self.show()
                self.raise_()
                self.activateWindow()
            self._logf(f"_set_top enable={enable} was_visible={was_visible} -> visible={self.isVisible()}")
        except Exception as e:
            self._logf(f"_set_top failed: {e}")
        finally:
            self._applying_top = False

    def toggle_top(self):
        cur = bool(self.cfg.get("always_on_top", True))
        not_cur = not cur
        self._logf(f"toggle_top START: cur={cur} -> {not_cur}, visible={self.isVisible()}")
        self.cfg["always_on_top"] = not_cur
        save_config(self.cfg)
        self._set_top(not_cur)
        self._logf(f"toggle_top after _set_top: visible={self.isVisible()}")
        self._sync_top()
        self._logf(f"toggle_top END: visible={self.isVisible()}, cfg.top={self.cfg.get('always_on_top')}")

    def _is_top(self) -> bool:
        # 用 cfg 里的状态作为唯一真相源 (因为 windowFlags 不再随 Win API 切)
        return bool(self.cfg.get("always_on_top", True))

    def _sync_top(self):
        # 同步状态文字和托盘菜单的勾选
        self.last_top_state = self._is_top()
        action = getattr(self, "action_top", None)
        if action is not None and hasattr(action, "setChecked"):
            try:
                action.setChecked(self.last_top_state)
                action.setText("已置顶" if self.last_top_state else "置顶窗口")
            except Exception as e:
                self._logf(f"_sync_top failed: {e}")

    # ---- 副屏 ----
    def move_to_secondary(self):
        screens = QApplication.screens()
        if len(screens) <= 1:
            InfoDialog("副屏", "未检测到外接显示器。", self).exec_()
            return
        cur_idx = self._current_screen_index()
        nxt = (cur_idx + 1) % len(screens)
        target = screens[nxt].availableGeometry()
        # 强制锁定窗口尺寸, 避免副屏 DPI 变化时被 OS 拉伸
        self._lock_height()
        cur_w = self.width()
        cur_h = self.height()
        self.setGeometry(target.x() + 60, target.y() + 60, cur_w, cur_h)
        self._clamp_to_screen()
        self.cfg["screen_index"] = nxt
        self._save_geometry()
        save_config(self.cfg)
        InfoDialog(
            "副屏",
            f"已移动到屏幕 {nxt + 1}/{len(screens)}：{screens[nxt].name()}",
            self
        ).exec_()

    def _current_screen_index(self) -> int:
        center = self.frameGeometry().center()
        for i, s in enumerate(QApplication.screens()):
            if s.availableGeometry().contains(center):
                return i
        return 0

    # ---- 设置 ----
    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec_() == 1:  # accepted
            save_config(self.cfg)
            self.refresh()

    # ---- 一键打开用量订阅页 ----
    def open_subscription(self):
        open_browser(subscription_url(self.cfg.get("plan", "coding")))

    # ---- 关于 ----
    def show_about(self):
        InfoDialog(
            "关于",
            "Plan Monitor\n\n"
            "火山方舟 Plan / Agent Plan 用量浮窗\n"
            "数据每 30 秒自动刷新\n\n"
            "右键系统托盘图标可访问全部操作。",
            self,
            buttons=[("访问官网", lambda: open_browser("https://hzdavy.github.io/PlanMonitor/"))],
        ).exec_()

    # ---- 退出 ----
    def quit_app(self):
        self._quitting = True
        self._save_geometry()
        save_config(self.cfg)
        QApplication.quit()

    # ---- 开机启动 ----
    def _run_key(self):
        return (r"Software\Microsoft\Windows\CurrentVersion\Run", "PlanMonitor")

    def _startup_value(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{os.path.abspath(sys.executable)}"'
        return f'"{os.path.abspath(sys.executable)}" "{os.path.abspath(__file__)}"'

    def _is_startup_enabled(self) -> bool:
        try:
            import winreg
            key_path, name = self._run_key()
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as k:
                winreg.QueryValueEx(k, name)
            return True
        except Exception:
            return False

    def _toggle_startup(self):
        import winreg
        key_path, name = self._run_key()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as k:
                winreg.QueryValueEx(k, name)
            enabled = True
        except Exception:
            enabled = False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
                if enabled:
                    winreg.DeleteValue(k, name)
                else:
                    winreg.SetValueEx(k, name, 0, winreg.REG_SZ, self._startup_value())
        except Exception as e:
            self._logf(f"_toggle_startup failed: {e}")

    # ---- 固定到任务栏 ----
    def _pin_lnk_path(self) -> str:
        root = os.environ.get("APPDATA", "")
        folder = os.path.join(root, r"Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar")
        return os.path.join(folder, "Plan Monitor.lnk")

    def _is_pinned(self) -> bool:
        return os.path.exists(self._pin_lnk_path())

    @staticmethod
    def _psq(s: str) -> str:
        return "'" + str(s).replace("'", "''") + "'"

    def _create_shortcut(self, lnk: str, target: str, wd: str) -> bool:
        # 用系统自带 WScript.Shell 生成 .lnk, 避免额外 pywin32 依赖.
        # 返回是否成功. 失败时把 PowerShell 的 stdout/stderr 记入日志, 不再静默吞掉.
        import subprocess
        script = (
            "$ErrorActionPreference='Stop';"
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + self._psq(lnk) + ");"
            "$s.TargetPath=" + self._psq(target) + ";"
            "$s.WorkingDirectory=" + self._psq(wd) + ";"
            "$s.IconLocation=" + self._psq(target + ",0") + ";"
            "$s.Description='Plan Monitor';"
            "$s.Save();"
            "if (Test-Path " + self._psq(lnk) + ") { 'OK' } else { throw 'lnk not created' }"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-Command", script],
            check=False, capture_output=True, text=True,
        )
        if r.returncode != 0:
            self._logf("_create_shortcut failed "
                       f"rc={r.returncode} stdout={r.stdout.strip()!r} stderr={r.stderr.strip()!r}")
            return False
        return True

    @staticmethod
    def _notify_shell():
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)
        except Exception:
            pass

    def _apply_tool(self, tool_on: bool):
        """application Qt.Tool 窗口标志(仅改标志, 不 show 不 hide).

        工具窗口(Qt.Tool)在任务栏不显示图标。tool_on=True -> 恢复工具窗口(无任务栏按钮);
        tool_on=False -> 去掉 Tool, 让任务栏出现本程序图标, 便于用户右键固定。
        保留 FramelessWindowHint 与置顶状态不变。"""
        try:
            flags = self.windowFlags()
            base = Qt.FramelessWindowHint | Qt.Window
            top = Qt.WindowStaysOnTopHint if self._is_top() else Qt.WindowType(0)
            new_flags = base | top | (Qt.Tool if tool_on else Qt.WindowType(0))
            if flags != new_flags:
                self.setWindowFlags(new_flags)
        except Exception as e:
            self._logf(f"_apply_tool failed: {e}")

    def _toggle_pin(self):
        """固定到任务栏引导流程.

        默认保持 Qt.Tool(不在任务栏显示)。仅在此处临时取消 Qt.Tool, 让窗口短暂出现在任务栏,
        引导用户手动右键固定; 用户点"确定"后立即恢复 Qt.Tool(回到工具窗口模式)。
        """
        try:
            self._apply_tool(False)
            self.show()
            self.raise_()
            self.activateWindow()
            InfoDialog(
                "固定到任务栏",
                "已临时把本程序放到任务栏。请手动固定：\n\n"
                "① 在任务栏上右键本程序图标 → 选择“固定到任务栏”；\n"
                "② 完成后在这个对话框点“确定”。\n\n"
                "点“确定”后会恢复工具窗口模式(Qt.Tool)。",
                self,
            ).exec_()
            self._apply_tool(True)
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception as e:
            self._logf(f"_toggle_pin failed: {e}")

    # ---- 托盘 ----
    def _build_menu(self) -> "PopupMenu":
        """构造与托盘菜单同款的 PopupMenu, 同时被汉堡按钮和系统托盘使用."""
        menu = PopupMenu(self)

        # 点击菜单项时: 先关闭 popup (在事件循环外, 避免和 callback 内部 hide/show 冲突),
        # 然后用 singleShot(0) 异步执行 callback, 保证 popup hideEvent 完全结束再触发动作
        def add_and_hide(text, callback, checkable=False, checked=False):
            def wrapped():
                self._logf(f"popup item '{text}' wrapped() called, before menu.hide() visible={self.isVisible()}")
                menu.hide()
                self._logf(f"popup item '{text}' wrapped() before singleShot, visible={self.isVisible()}")
                QTimer.singleShot(0, callback)
            menu.add_item(text, wrapped, checkable=checkable, checked=checked)

        add_and_hide("显示窗口", self._show_window)
        add_and_hide("隐藏窗口", self.hide)

        menu.add_separator()

        add_and_hide("立即刷新", self.refresh)

        # 置顶 - 用 checkable 表达状态
        # 注意: 不要在这里覆盖 self.action_top (那是托盘菜单的 QAction),
        # 否则 _sync_top 会调用一个空对象的 setChecked 导致崩溃.
        add_and_hide("置顶窗口", self.toggle_top,
                     checkable=True, checked=self.last_top_state)

        add_and_hide("移动到副屏", self.move_to_secondary)

        menu.add_separator()

        add_and_hide("开机启动", self._toggle_startup,
                     checkable=True, checked=self._is_startup_enabled())
        add_and_hide("固定到任务栏", self._toggle_pin)

        menu.add_separator()

        add_and_hide("打开用量订阅页", self.open_subscription)
        add_and_hide("设置 Access Key", self.open_settings)
        add_and_hide("关于", self.show_about)

        menu.add_separator()

        add_and_hide("退出", self.quit_app)

        return menu

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(_build_tray_pixmap(ok=self.last_status_ok)))
        self.tray.setToolTip("Coding Plan Monitor")
        # 不用 setContextMenu: 右键由 activated(Context) 弹自定义圆角菜单,
        # 以避开 Windows 原生 QMenu border-radius 不生效的问题.
        self.tray.setContextMenu(None)
        # 双击托盘图标 = 显隐切换
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _build_tray_menu(self) -> QMenu:
        """托盘右键菜单: Windows 原生 QMenu (类型签名约束). 圆角问题由系统背锅."""
        menu = QMenu(self)
        act = QAction("显示窗口", menu); act.triggered.connect(self._show_window); menu.addAction(act)
        act = QAction("隐藏窗口", menu); act.triggered.connect(self.hide); menu.addAction(act)
        menu.addSeparator()
        act = QAction("立即刷新", menu); act.triggered.connect(self.refresh); menu.addAction(act)
        self.action_top = QAction("置顶窗口", menu)
        self.action_top.setCheckable(True)
        self.action_top.setChecked(self.last_top_state)
        self.action_top.triggered.connect(self.toggle_top)
        menu.addAction(self.action_top)
        act = QAction("移动到副屏", menu); act.triggered.connect(self.move_to_secondary); menu.addAction(act)
        menu.addSeparator()
        act = QAction("打开用量订阅页", menu); act.triggered.connect(self.open_subscription); menu.addAction(act)
        act = QAction("设置 Access Key", menu); act.triggered.connect(self.open_settings); menu.addAction(act)
        act = QAction("关于", menu); act.triggered.connect(self.show_about); menu.addAction(act)
        menu.addSeparator()
        act = QAction("退出", menu); act.triggered.connect(self.quit_app); menu.addAction(act)
        menu.setStyleSheet(f"""
            QMenu {{
                background: #15151a;
                color: {T['fg']};
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                padding: 8px 4px;
                font-family: '{FONT_FAMILY}';
                font-size: {px(18)}px;
                font-weight: 500;
            }}
            QMenu::item {{
                padding: {px(12)}px {px(32)}px;
                border-radius: 8px;
                margin: 2px 4px;
            }}
            QMenu::item:selected {{
                background: rgba(155,138,255,0.18);
                color: {T['fg']};
            }}
            QMenu::item:checked {{
                color: #9b8aff;
            }}
            QMenu::separator {{
                height: 1px;
                background: rgba(255,255,255,0.08);
                margin: 6px 10px;
            }}
        """)
        return menu

    def _on_hamburger_clicked(self):
        """汉堡按钮: 弹一个圆角 PopupMenu (解决 QMenu 在 Windows 上 border-radius 不生效)."""
        menu = self._build_menu()
        btn = self.hamburger_btn
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        # 菜单左边对齐按钮左边, 顶部在按钮底部
        menu.show_at(pos)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Context:
            menu = self._build_menu()
            menu.show_at(QCursor.pos())
        elif reason == QSystemTrayIcon.DoubleClick:
            self._show_window()
        elif reason == QSystemTrayIcon.Trigger:
            self._show_window()

    def _show_window(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.activateWindow()
        self.raise_()

    def _update_tray_icon(self, ok: bool):
        if not self.tray:
            return
        self.tray.setIcon(QIcon(_build_tray_pixmap(ok=ok)))

    # ---- 几何持久化 ----
    def _save_geometry(self):
        # 宽度已被强制锁定 (固定 560), 不再存 w, 只存 x/y 用于跨屏记忆位置
        g = self.geometry()
        self.cfg["geometry"] = {"x": g.x(), "y": g.y()}

    def _lock_height(self):
        """强制把窗口高度锁回 min_h, 用于副屏 DPI 切换后 OS 拉伸时复位."""
        target_h = self.minimumHeight()
        target_w = max(self.width(), self.minimumWidth())
        if self.height() != target_h or self.width() != target_w:
            # 用 setGeometry 不带 (x, y), 仅改 size 不会移动窗口
            self.resize(target_w, target_h)
        # 重新设置最大高 (避免某些情况下 max 被重置)
        self.setMaximumHeight(target_h)

    def _restore_geometry(self):
        # 强制锁定窗口尺寸: 宽度 = px(560) (用户机器 DPI 1.75x 时 Qt 会自动放大到 ~980 物理像素, 不再显得太窄).
        # 高度固定, 卡片自适应
        card_h = px(200)
        fixed_w = px(560)
        min_h = 3 * card_h + 2 * px(12) + px(60) + px(12) + 0 + 2 * px(20) + 2 * px(28)
        # 横向: 最小 = 最大 = 固定宽度, 完全不可拉伸
        self.setMinimumSize(fixed_w, min_h)
        self.setMaximumSize(fixed_w, min_h)
        self.resize(fixed_w, min_h)
        idx = self.cfg.get("screen_index", -1)
        screens = QApplication.screens()
        # 目标屏幕: 优先保存的索引, 否则用主屏做钳制基准
        target = None
        if 0 <= idx < len(screens):
            target = screens[idx]
        if target is None and screens:
            target = screens[0]
        saved = self.cfg.get("geometry") or {}
        sx, sy = saved.get("x"), saved.get("y")
        have_saved = isinstance(sx, (int, float)) and isinstance(sy, (int, float))
        if target is not None:
            g = target.availableGeometry()
            if have_saved:
                # 恢复到上次拖到的位置, 并把窗口钳制进目标屏幕可用区域
                # (保存的屏幕可能已变化/小了, 防止窗口溢出到屏幕外)
                sx_f = int(sx)
                sy_f = int(sy)
                max_x = g.x() + max(0, g.width() - fixed_w)
                max_y = g.y() + max(0, g.height() - min_h)
                self.move(max(g.x(), min(sx_f, max_x)), max(g.y(), min(sy_f, max_y)))
            else:
                # 无历史位置: 放到目标屏幕左上角 + 60,60 的默认位置
                self.move(g.x() + 60, g.y() + 60)
        # 根据 cfg 应用置顶 (Qt 标准 flag)
        if bool(self.cfg.get("always_on_top", True)) != bool(self.windowFlags() & Qt.WindowStaysOnTopHint):
            self._set_top(bool(self.cfg.get("always_on_top", True)))

    def _clamp_to_screen(self):
        """把窗口钳制回当前屏幕的可用区域, 并安排一次整窗重绘.

        跨屏(尤其不同 DPI)拖动后, 固定尺寸的窗口可能溢出小屏幕导致右侧/底部被裁剪,
        或渲染只画出一部分(只显示汉堡图标)。此方法在拖动结束时收紧位置/尺寸, 并用
        update() 在下一个绘制周期把整窗重画出来(异步可合并, 不产生闪烁)。"""
        try:
            center = self.frameGeometry().center()
            scr = (QApplication.screenAt(center) or self.screen()
                   or QApplication.primaryScreen())
            avail = scr.availableGeometry()
            g = self.geometry()
            w = min(g.width(), avail.width())
            h = min(g.height(), avail.height())
            x, y = g.x(), g.y()
            if x < avail.x():
                x = avail.x()
            if x + w > avail.x() + avail.width():
                x = avail.x() + avail.width() - w
            if y < avail.y():
                y = avail.y()
            if y + h > avail.y() + avail.height():
                y = avail.y() + avail.height() - h
            if (x, y, w, h) != (g.x(), g.y(), g.width(), g.height()):
                self.setGeometry(x, y, w, h)
            self.update()
            self._save_geometry()
        except Exception as e:
            self._logf(f"_clamp_to_screen failed: {e}")

    def moveEvent(self, ev):
        super().moveEvent(ev)
        # 检测跨屏(不同 DPI): 一旦越过屏幕边界就整窗重绘, 避免残缺内容先显示出来再补全.
        # 用 singleShot(0) 把同步重绘推迟到事件循环下一拍, 让重绘不夹在鼠标拖动事件栈里,
        # 以尽量降低透明窗口同步重绘带来的闪烁; 又赶在下一帧合成前完成, 因此不会残留残缺帧.
        try:
            ctr = self.frameGeometry().center()
            cur = (QApplication.screenAt(ctr) or self.screen()
                   or QApplication.primaryScreen())
            if cur is not self._last_screen:
                self._last_screen = cur
                QTimer.singleShot(0, self.repaint)
        except Exception:
            pass
        # 拖动中不做尺寸收紧, 避免拖动时 resize 与跨屏 DPI 缩放互相干扰导致部分区域不重绘;
        # 非拖动(程序化移动 / 副屏切换)才强制锁回固定高度
        if self._drag_pos is None:
            self._lock_height()
        self._save_geometry()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # 如果是 OS 拉伸 (高度 != min_h), 立即强制改回
        if ev is not None and self.minimumHeight() > 0:
            if self.height() != self.minimumHeight():
                self.resize(self.width(), self.minimumHeight())
                return
        self._save_geometry()

    def closeEvent(self, ev):
        import traceback
        self._logf(f"closeEvent FIRED, visible_before={self.isVisible()}")
        self._logf("closeEvent stack:\n" + "".join(traceback.format_stack(limit=10)))
        self._save_geometry()
        save_config(self.cfg)
        # 点 × 只隐藏到托盘, 不退出进程
        if self.tray and self.tray.isVisible() and not getattr(self, "_quitting", False):
            ev.ignore()
            self.hide()
            if not getattr(self, "_tray_notified", False):
                self.tray.showMessage(
                    "Coding Plan Monitor",
                    "已最小化到系统托盘，右击图标继续操作。",
                    QSystemTrayIcon.Information,
                    2500,
                )
                self._tray_notified = True
            return
        ev.accept()

    def hideEvent(self, ev):
        super().hideEvent(ev)

    # ---- 刷新 ----
    def refresh(self):
        if not self.cfg.get("ak") or not self.cfg.get("sk"):
            self._set_status("未配置 Access Key", ok=False)
            return
        try:
            result = fetch_usage(self.cfg)
            self._render(result)
            self.last_update_ms = int(time.time() * 1000)
            self._set_status("已连接", ok=True)
        except Exception as e:
            self._set_status(f"错误 · {e}", ok=False)

    def _set_status(self, text: str, ok: bool):
        self.last_status_text = text
        self.last_status_ok = ok
        # 顶部品牌行的状态文字 - "· 已连接" 整体作为连接状态指示器, 一起变色:
        #   ok=True (已连接)  -> 绿色 #2ed47a
        #   ok=False (出错)   -> 红色
        color = T["ok"] if ok else T["err"]
        # "·" 分隔符也用同一颜色
        self.brand_dot_lbl.setStyleSheet(
            f"color: {color}; font-family: '{FONT_FAMILY}'; font-size: {px(20)}px; font-weight: 600;"
        )
        # "已连接" 文字也用同一颜色
        self.brand_status_lbl.setStyleSheet(
            f"color: {color}; font-family: '{FONT_FAMILY}'; font-size: {px(20)}px; font-weight: 600; letter-spacing: 0.5px;"
        )
        self.brand_status_lbl.setText(text)
        # 托盘图标右上角状态点同步
        self._update_tray_icon(ok)

    def _render(self, result: dict):
        # logo 栏已固定为 "Coding Plan | 已连接", _render 只更新数据, 不动 brand 栏
        pass

        usage = {item.get("Level"): item for item in (result.get("QuotaUsage") or []) if isinstance(item, dict)}

        for key, _ in WINDOW_WINDOWS:
            item = usage.get(key) or {}
            try:
                percent = float(item.get("Percent", 0) or 0)   # 0-100 直接用
                reset = int(item.get("ResetTimestamp", 0) or 0) * 1000  # 秒级 epoch → ms
            except (TypeError, ValueError):
                percent = 0
                reset = 0

            card = self.cards.get(key)
            if not card:
                continue
            if percent <= 0:
                card.setVisible(False)
            else:
                card.setVisible(True)
                card.update_data(percent, reset)




# ============================================================
# 入口
# ============================================================

def main():
    # 不要在这里调 QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True).
    # 原因: app.manifest 已经声明了 PerMonitorV2 DPI 感知, 再叠加 AA_EnableHighDpiScaling
    # 在 PyQt5 5.15 + Windows 10/11 上会触发 QApplication 启动时崩溃 / "Failed to execute script" 弹窗.
    # 我们的策略: 走"绝对物理像素"路线. px(n) 直接返回 n, 1.75x 屏上也是 n 物理像素, 不让 Qt 自动放大.
    # (上一版误以为 Qt 不放大=窗口太窄, 实际是用户期望"540 物理像素宽的窗口", 现在 px(540)=540 物理像素, 与预期一致.)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 探测系统缩放, 仅用于日志 (Qt 不做自动 DPI 缩放, 我们用绝对物理像素布局)
    global _SCALE
    _SCALE = 1.0
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hdc = user32.GetDC(0)
        logpx = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        user32.ReleaseDC(0, hdc)
        if logpx > 0:
            _SCALE = logpx / 96.0
            sys.stderr.write(f"[info] system DPI={logpx} scale={_SCALE:.2f}\n")
    except Exception:
        _SCALE = 1.0

    app.setFont(QFont(FONT_FAMILY, px(10)))
    app.setStyleSheet(build_qss(FONT_FAMILY))
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Coding Plan Monitor")
    app.setWindowIcon(QIcon(_brand_pixmap(size=64)))   # 任务栏 / Alt-Tab 显示的窗口图标

    win = FluidWindow()
    win.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
