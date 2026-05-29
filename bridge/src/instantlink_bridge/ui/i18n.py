"""Bridge UI localisation.

Single-file translation table keyed by the English source string. Calling
``t("Ready", language)`` returns the Chinese (or any future locale) string
when one is registered, else returns the English source unchanged.

Design choices:

* Source-string keys (gettext style) — adding a new English string costs
  nothing until we want to translate it; the literal in code stays self-
  documenting and a missing translation degrades gracefully.

* Single in-memory dict — at ~150 strings total the bridge UI doesn't
  warrant gettext .mo compilation or a runtime file load. Plain Python
  keeps the deploy path simple (no extra files to scp).

* Frozen at module load — registering at import time means a missing
  translation is a code-review issue, not a runtime surprise.

* No string formatting helpers — callers do ``t("Battery") + ": 95%"``
  rather than f-strings inside the translation, so the key set stays
  small (we don't multiply per-value variants). Helper functions that
  produce composite strings still work because they assemble already-
  translated fragments.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Language", "t", "translatable_strings"]


class Language(StrEnum):
    """User-selectable LCD languages.

    Tags follow BCP 47 so they can be reused for any future Mac/web
    surfaces without renaming.
    """

    EN = "en"
    ZH_HANS = "zh-Hans"  # Chinese, Simplified


# ---------------------------------------------------------------------------
# Translations — English source on the left, target string on the right.
# Untranslated keys fall through to the English source.
# ---------------------------------------------------------------------------

_ZH_HANS: dict[str, str] = {
    # --- Top status bar words ---------------------------------------------
    "Connected": "已连接",
    "Waiting": "等待中",
    "Searching": "搜索中",
    "Disconnected": "已断开",
    "Starting": "启动中",
    "No printer": "无打印机",
    "Pairing": "配对中",
    "Pair failed": "配对失败",
    "Validating": "校验中",
    "No film": "无相纸",
    "Received": "已接收",
    "Preview": "预览",
    "Printing": "打印中",
    "Done": "完成",
    "Error": "错误",
    "Settings": "设置",
    # --- READY body title + info row labels -------------------------------
    "Ready": "就绪",
    "Type": "型号",
    "Film": "相纸",
    "Battery": "电量",
    "Printer": "打印机",
    "SSID": "网络名",
    "Queue": "队列",
    "1 photo": "1 张照片",
    # --- Main Settings page rows ------------------------------------------
    "Connect": "连接",
    "Network": "网络",
    "Print": "打印",
    "System": "系统",
    "About": "关于",
    # --- Common Setting row labels ----------------------------------------
    "Serial": "序列号",
    "Find printer": "查找打印机",
    "Reset BLE link": "重置 BLE 连接",
    "Forget & re-pair": "忘记并重新配对",
    "Forget printer": "忘记打印机",
    "Printer type": "打印机型号",
    "Keepalive": "保持连接",
    "Search rate": "搜索频率",
    "Wi-Fi PIN": "Wi-Fi 密码",
    "FTP host": "FTP 主机",
    "FTP user": "FTP 用户",
    "FTP PIN": "FTP 密码",
    "Wi-Fi Mode": "Wi-Fi 模式",
    "Reset credentials": "重置凭据",
    "Bridge FTP": "桥接 FTP",
    "Bluetooth": "蓝牙",
    "Same Wi-Fi adv": "同 Wi-Fi 通告",
    "USB IP": "USB IP",
    "Auto print": "自动打印",
    "Image fit": "图像适配",
    "JPEG quality": "JPEG 质量",
    "No-film test": "无相纸测试",
    "Device ID": "设备 ID",
    "App version": "应用版本",
    "Python": "Python",
    "BlueZ": "BlueZ",
    "OS": "操作系统",
    "Idle": "空闲",
    "Idle poweroff": "空闲关机",
    "Text size": "文字大小",
    "Refresh status": "刷新状态",
    "Language": "语言",
    # --- Hint bar labels --------------------------------------------------
    "K1 Setting": "K1 设置",
    "K2 Refresh": "K2 刷新",
    "K3 FTP": "K3 FTP",
    "Hold K3": "长按 K3",
    "K1 Print": "K1 打印",
    "K2 Cancel": "K2 取消",
    "K1 OK": "K1 确认",
    "K2 Back": "K2 返回",
    "K3 Help": "K3 帮助",
    "K1 Select": "K1 选择",
    "K1 Retry": "K1 重试",
    "K3 Retry": "K3 重试",
    "Up/Dn": "上/下",
    "Up/Dn Edit": "上/下 编辑",
    "Left/Right": "左/右",
    "Left Back": "左 返回",
    "Move": "移动",
    "4-way Pan": "四向平移",
    # --- Body action / status lines ---------------------------------------
    "Turn printer on and keep awake": "请打开打印机并保持唤醒",
    "Phone Bluetooth may grab it": "手机蓝牙可能占用",
    "Looking for printer": "正在查找打印机",
    "Keep printer awake": "保持打印机唤醒",
    "Keep it awake near bridge": "保持打印机靠近桥接",
    "Close phone app if it fails": "失败时关闭手机应用",
    "Opening Bluetooth session": "正在打开蓝牙会话",
    "If stuck, close phone app": "卡住请关闭手机应用",
    "Close phone app or phone BT": "关闭手机应用或蓝牙",
    "Power-cycle printer, then retry": "重启打印机后重试",
    "Selected printer not visible": "无法找到所选打印机",
    "Turn selected printer on": "请打开所选打印机",
    "Printer not found nearby": "附近未发现打印机",
    # --- Confirm dialog toasts --------------------------------------------
    "Press K1 again to FORGET printer": "再按 K1 删除打印机",
    "Press K1 again to RESET BLE link": "再按 K1 重置 BLE 连接",
    "Press K1 again to FORGET and re-pair": "再按 K1 忘记并重新配对",
    "Reset Wi-Fi/FTP creds? K1 confirm K2 cancel": "重置 Wi-Fi/FTP 凭据？K1 确认 K2 取消",
    "Printer forgotten": "已删除打印机",
    "BLE link reset": "BLE 连接已重置",
    "No printer saved": "未保存打印机",
    # --- Picker / option labels ------------------------------------------
    "Hotspot": "热点",
    "Client": "客户端",
    "Auto": "自动",
    "Advanced": "高级",
    "Crop": "裁剪",
    "Contain": "适应",
    "Stretch": "拉伸",
    "On": "开",
    "Off": "关",
    "Small": "小",
    "Medium": "中",
    "Large": "大",
    "English": "英文",
    "中文": "中文",
}

_TRANSLATIONS: dict[Language, dict[str, str]] = {
    Language.EN: {},  # English keys are identity; never accessed.
    Language.ZH_HANS: _ZH_HANS,
}


def t(text: str, language: Language | str = Language.EN) -> str:
    """Return ``text`` translated to ``language``.

    Unknown translations fall through to the English source so a missing
    string degrades gracefully (text stays readable, never blank).
    """

    if isinstance(language, str):
        try:
            language = Language(language)
        except ValueError:
            return text
    if language is Language.EN:
        return text
    return _TRANSLATIONS.get(language, {}).get(text, text)


def translatable_strings(language: Language) -> dict[str, str]:
    """Return the registered (source → target) map for ``language``.

    Used by tests + tooling to enumerate coverage; not part of the
    runtime translation path.
    """

    return dict(_TRANSLATIONS.get(language, {}))
