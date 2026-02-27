"""
Auto-Post v2 — pywebview + Flask エントリポイント

ローカルで Flask サーバーを起動し、pywebview でネイティブウィンドウに表示する。
"""

import sys
import threading
from pathlib import Path

# Windows コンソールの文字化け対策（cp932 → utf-8）
if sys.platform == "win32":
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if _stream and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

# PyInstaller --onefile 対応
if getattr(sys, "frozen", False):
    _BASE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    _BASE = Path(__file__).resolve().parent

# backend をインポートパスに追加
sys.path.insert(0, str(_BASE))


def _start_flask():
    """Flask サーバーをバックグラウンドで起動する。"""
    from backend.api import app
    app.run(host="127.0.0.1", port=5199, debug=False, use_reloader=False)


def main():
    try:
        import webview
        HAS_WEBVIEW = True
    except ImportError:
        HAS_WEBVIEW = False

    if HAS_WEBVIEW:
        # Flask をバックグラウンドスレッドで起動
        server_thread = threading.Thread(target=_start_flask, daemon=True)
        server_thread.start()

        # アイコンパス
        icon_path = _BASE / "icon.ico"
        icon = str(icon_path) if icon_path.exists() else None

        # pywebview ウィンドウ作成
        window = webview.create_window(
            title="⚡ AutoPost v2",
            url="http://127.0.0.1:5199",
            width=1100,
            height=750,
            min_size=(900, 600),
        )

        # Windows: タスクバーアイコン設定
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("kuroka.autopost.2.0")

        webview.start(debug=False)
    else:
        # pywebview なし → ブラウザで開くフォールバック
        import webbrowser
        print("⚡ AutoPost v2 — ブラウザモードで起動します")
        print("  → http://127.0.0.1:5199")
        webbrowser.open("http://127.0.0.1:5199")
        _start_flask()  # メインスレッドで Flask 起動（ブロッキング）


if __name__ == "__main__":
    main()
