"""
build_exe.py — PyInstaller を使って Auto-Post を .exe にパッケージする

使い方:
    python build_exe.py

出力:
    dist/AutoPost.exe   — 実行ファイル
    dist/AutoPost.zip   — 配布用 zip
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

APP_NAME = "AutoPost"
ENTRY_POINT = "app.py"
ICON = None  # .ico ファイルがあればパスを指定

# exe に含めるローカルモジュール
HIDDEN_IMPORTS = [
    "google.genai",
    "google.genai.types",
    "google.genai.errors",
    "tweepy",
    "feedparser",
    "bs4",
    "schedule",
    "requests",
    "dotenv",
    "customtkinter",
]

# ---------------------------------------------------------------------------
# customtkinter データファイルのパス取得
# ---------------------------------------------------------------------------


def _get_ctk_data_path() -> str:
    """customtkinter のインストールパスを取得し、PyInstaller の --add-data 形式で返す。"""
    import customtkinter
    ctk_dir = Path(customtkinter.__file__).resolve().parent
    # Windows: "src;dst" 形式
    return f"{ctk_dir}{os.pathsep}customtkinter"


# ---------------------------------------------------------------------------
# ビルド実行
# ---------------------------------------------------------------------------


def build():
    print("=" * 60)
    print(f"  {APP_NAME} — exe ビルド開始")
    print("=" * 60)

    # 1. PyInstaller の存在確認
    try:
        import PyInstaller  # noqa: F401
        print(f"✅ PyInstaller {PyInstaller.__version__} を検出")
    except ImportError:
        print("⚠️  PyInstaller が見つかりません。インストールします...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✅ PyInstaller をインストールしました")

    # 2. customtkinter のデータパス
    ctk_data = _get_ctk_data_path()
    print(f"📦 customtkinter データ: {ctk_data.split(os.pathsep)[0]}")

    # 3. PyInstaller コマンド組み立て
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        f"--name={APP_NAME}",
        f"--add-data={ctk_data}",
    ]

    # アイコンがあれば追加
    if ICON and Path(ICON).exists():
        cmd.append(f"--icon={ICON}")

    # hidden-import 追加
    for mod in HIDDEN_IMPORTS:
        cmd.append(f"--hidden-import={mod}")

    # エントリポイント
    cmd.append(ENTRY_POINT)

    print(f"\n🔨 ビルドコマンド:\n  {' '.join(cmd)}\n")

    # 4. ビルド実行
    result = subprocess.run(cmd, cwd=str(Path(__file__).resolve().parent))
    if result.returncode != 0:
        print("❌ ビルドに失敗しました")
        sys.exit(1)

    exe_path = Path("dist") / f"{APP_NAME}.exe"
    if not exe_path.exists():
        print(f"❌ {exe_path} が見つかりません")
        sys.exit(1)

    print(f"\n✅ exe ビルド成功: {exe_path}")
    print(f"   サイズ: {exe_path.stat().st_size / 1024 / 1024:.1f} MB")

    # 5. zip 作成
    zip_path = Path("dist") / f"{APP_NAME}.zip"
    print(f"\n📦 zip 作成中: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_path, f"{APP_NAME}.exe")

    print(f"✅ zip 作成完了: {zip_path}")
    print(f"   サイズ: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")

    # 6. クリーンアップ（build ディレクトリと .spec ファイル）
    spec_file = Path(f"{APP_NAME}.spec")
    build_dir = Path("build")
    if spec_file.exists():
        spec_file.unlink()
    if build_dir.exists():
        shutil.rmtree(build_dir)
    print("🧹 ビルド一時ファイルをクリーンアップしました")

    print(f"\n{'=' * 60}")
    print(f"  ✅ 完了！配布ファイル: dist/{APP_NAME}.zip")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    build()
