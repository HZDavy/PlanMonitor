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
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize, QCoreApplication, QByteArray
)
from PyQt5.QtGui import (
    QFont, QFontDatabase, QColor, QPainter, QLinearGradient, QRadialGradient, QBrush,
    QPen, QCursor, QPainterPath, QMouseEvent, QIcon, QPixmap
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QFrame, QFormLayout,
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


# ============================================================
# API
# ============================================================

def _fetch_log(msg: str):
    try:
        with open(os.path.join(APP_DIR, "_api.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def fetch_usage(cfg: dict) -> dict:
    body = "{}"
    headers = sign_request(cfg["ak"], cfg["sk"], body)
    url = f"https://{API_HOST}/?Action={API_ACTION}&Version={API_VERSION}"
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
    return j["Result"]


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
        super().__init__("设置", width=px(560), height=px(440), parent=parent)
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

        form.addRow(make_label("ACCESS KEY"), self.ak_edit)
        form.addRow(make_label("SECRET KEY"), self.sk_edit)
        form.addRow(make_label("REGION"), self.region_edit)
        self.content_layout.addLayout(form)

        hint = QLabel("AK / SK 仅保存在 config.json，不上传任何第三方。")
        hint.setStyleSheet(f"color: {T['fg3']}; font-family: '{ff}'; font-size: {px(13)}px;")
        hint.setWordWrap(True)
        self.content_layout.addWidget(hint)

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
        self.accept()


# ============================================================
# 信息提示对话框 - 暗色流体（替代 QMessageBox）
# ============================================================

class InfoDialog(FluidDialog):
    def __init__(self, title: str, message: str, parent=None):
        super().__init__(title, width=px(480), height=px(280), parent=parent)
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
    """绘制 64x64 托盘图标: 紫底圆角 + 白色 'C'"""
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    # 紫色径向背景
    from PyQt5.QtCore import QRectF
    rect = QRectF(pm.rect()).adjusted(2, 2, -2, -2)
    path = QPainterPath()
    path.addRoundedRect(rect, 14, 14)

    grad = QRadialGradient(
        rect.x() + rect.width() * 0.35,
        rect.y() + rect.height() * 0.30,
        rect.width() * 0.85,
    )
    grad.setColorAt(0.0, QColor(180, 165, 255, 255))
    grad.setColorAt(1.0, QColor(120, 100, 220, 255))
    p.fillPath(path, QBrush(grad))

    # 高光
    hi = QLinearGradient(0, rect.y(), 0, rect.y() + rect.height() * 0.6)
    hi.setColorAt(0.0, QColor(255, 255, 255, 50))
    hi.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, QBrush(hi))

    # 'C' 字符
    f = QFont(FONT_FAMILY, 36)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 235))
    p.drawText(rect, Qt.AlignCenter, "C")

    # 右上角状态点: 绿/红
    if ok:
        dot_color = QColor(124, 232, 168, 255)
    else:
        dot_color = QColor(255, 94, 94, 255)
    p.setBrush(QBrush(dot_color))
    p.setPen(QPen(QColor(10, 10, 12, 200), 2))
    p.drawEllipse(QRectF(rect.x() + rect.width() - 14, rect.y() + 4, 14, 14))

    p.end()
    return pm


# ============================================================
# 胶囊按钮
# ============================================================

# ============================================================
# 自定义圆角下拉菜单 (替代 QMenu, 解决 Windows QMenu border-radius 不生效)
# ============================================================

class _MenuItem(QToolButton):
    CHECK_W = 18  # ✓ 宽度

    def __init__(self, text: str, checkable: bool = False, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setCheckable(checkable)
        self.setChecked(checked)
        self.setMinimumHeight(px(40))
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setFocusPolicy(Qt.NoFocus)
        # 留出 ✓ 标记的位置: 左侧 CHECK_W + 间距
        self.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                color: {T['fg']};
                border: none;
                border-radius: 8px;
                padding: 0 {px(20)}px;
                text-align: left;
                font-family: '{FONT_FAMILY}';
                font-size: {px(18)}px;
                font-weight: 500;
                letter-spacing: 0.5px;
            }}
            QToolButton:hover {{
                background: rgba(155,138,255,0.14);
            }}
            QToolButton:checked {{
                color: #9b8aff;
            }}
            QToolButton:checked:hover {{
                background: rgba(155,138,255,0.10);
            }}
        """)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not (self.isCheckable() and self.isChecked()):
            return
        # 在最左侧画一个紫色 ✓
        from PyQt5.QtCore import QLineF
        from PyQt5.QtGui import QPainter, QPainterPath, QColor, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = px(12)
        cy = self.height() / 2
        # 紫色小方块
        path = QPainterPath()
        path.addRoundedRect(int(cx - 5), int(cy - 5), 10, 10, 2, 2)
        p.fillPath(path, QColor("#9b8aff"))
        # 白色 ✓ (QLineF 在 QtCore, 接 float)
        pen = QPen(QColor(255, 255, 255))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(QLineF(cx - 2.5, cy + 0.2, cx - 0.5, cy + 2.2))
        p.drawLine(QLineF(cx - 0.5, cy + 2.2, cx + 3.0, cy - 2.0))


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

    # ---- 关于 ----
    def show_about(self):
        InfoDialog(
            "关于",
            "Coding Plan Monitor\n\n"
            "火山方舟 Coding Plan / Agent Plan 用量浮窗\n"
            "数据每 30 秒自动刷新\n\n"
            "右键系统托盘图标可访问全部操作。",
            self,
        ).exec_()

    # ---- 退出 ----
    def quit_app(self):
        self._quitting = True
        self._save_geometry()
        save_config(self.cfg)
        QApplication.quit()

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

        add_and_hide("设置 Access Key...", self.open_settings)
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
        # 托盘菜单用 QMenu (Windows 原生, setContextMenu 类型签名只接受 QMenu)
        # 圆角只用在汉堡按钮的弹层 (用户能看到的那个)
        try:
            self.tray.setContextMenu(self._build_tray_menu())
        except Exception:
            self.tray.setContextMenu(self._build_menu())  # 兜底
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
        act = QAction("设置 Access Key...", menu); act.triggered.connect(self.open_settings); menu.addAction(act)
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
        if reason == QSystemTrayIcon.DoubleClick:
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
        if 0 <= idx < len(screens):
            geo = screens[idx].availableGeometry()
            self.move(geo.x() + 60, geo.y() + 60)
        # 根据 cfg 应用置顶 (Qt 标准 flag)
        if bool(self.cfg.get("always_on_top", True)) != bool(self.windowFlags() & Qt.WindowStaysOnTopHint):
            self._set_top(bool(self.cfg.get("always_on_top", True)))

    def moveEvent(self, ev):
        super().moveEvent(ev)
        # 副屏切换 / 多屏 DPI 切换后, OS 可能拉伸窗口, 立即复位
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

    win = FluidWindow()
    win.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
