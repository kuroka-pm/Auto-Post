# ⚡ AutoPost v2

AI を活用した X (Twitter) & Threads 自動投稿ツール。トレンド分析・ペルソナ設定・スケジュール投稿をワンストップで実現します。

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey?logo=flask)
![Responsive](https://img.shields.io/badge/Responsive-Mobile%20Ready-orange)
![License](https://img.shields.io/badge/License-MIT-green)

## 📸 スクリーンショット

> アプリ起動後 `http://127.0.0.1:5199` にアクセスするとダッシュボードが表示されます。

## ✨ 主な機能

| 機能 | 説明 |
|------|------|
| 📊 ダッシュボード | 投稿数・インプレッション・いいね数などの KPI を表示 |
| 🔥 トレンド分析 | RSS ソースから最新トレンドを取得、AI がペルソナとの相性を分析 |
| ✍️ AI 投稿生成 | トレンド × ペルソナ × 8種スタイルで投稿文を自動生成（画像 + ALT 対応）|
| 🚀 バズ最適化 | 2025-2026 X アルゴリズム対応のバズ構成ルール（滞在時間・否定連鎖・メタファー）|
| ⏰ スケジューラ | 曜日・時間帯を指定して自動投稿（ランダムジッター付き）|
| 📈 アナリティクス | X アナリティクス CSV をインポートして視覚分析 |
| 🕐 最適投稿時間 | エンゲージメントデータからピーク時間帯を自動分析・表示 |
| 📔 note 連携 | note.com の記事を取得して告知投稿に活用 |
| 👤 ペルソナ | AI による詳細ペルソナ自動生成 |
| 📱 レスポンシブ | タブレット・スマホ対応（3段階ブレークポイント）|
| 🌗 ダーク/ライト | テーマ切り替え対応 |
| 📝 ファイルログ | 実行ログを日付別ファイルに自動保存 |
| 🔒 エラーサニタイズ | ログから API キーを自動マスク |
| 💾 ページ記憶 | 最後に開いたページで次回起動 |

### 📝 ライティングスタイル（8種）

| スタイル | 文字数 | 特徴 |
|---|---|---|
| 一撃キャッチコピー | 80-140 | 結論ファーストの一言凝縮 |
| ニュース×一言 | 80-140 | ニュース引用＋短い私見 |
| 共感エピソード | 140-250 | 過去の体験をトレンドに接続 |
| 構造分析 | 140-280 | 因果関係を淡々と解説 |
| 概念の再定義 | 140-250 | 独自の新しい定義を提示 |
| **有益リスト型** 🆕 | 200-280 | まとめ・Tips形式、保存＆RT向き |
| **逆説インサイト型** 🆕 | 180-260 | 否定連鎖→真の答えパターン |
| **問いかけ共感型** 🆕 | 120-200 | あるある描写でリプライ誘発 |

## 🚀 セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/kuroka-pm/Auto-Post.git
cd Auto-Post
```

### 2. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

### 3. アプリを起動

```bash
python app.py
```

ブラウザで `http://127.0.0.1:5199` が自動で開きます。

### 4. API キーを設定

サイドバーの **⚙️ 設定 → 🔑 API設定** で以下のキーを入力:

- **Gemini API Key** — [Google AI Studio](https://aistudio.google.com/apikey) で取得
- **X (Twitter) API** — [X Developer Portal](https://developer.x.com/) で取得
- **Threads API** — Meta Developer Portal で取得

## 📦 ビルド (exe)

### Windows

```bash
pip install pyinstaller
pyinstaller autopost.spec
```

成果物は `dist/AutoPost/` に出力されます。

### macOS

GitHub Actions で自動ビルドされます。Releases ページからダウンロードしてください。

## 🗂️ プロジェクト構成

```
Auto-Post/
├── app.py                  # エントリーポイント
├── requirements.txt        # 依存パッケージ
├── autopost.spec            # PyInstaller ビルド設定
├── icon.ico                # アプリアイコン
├── logs/                   # 実行ログ（日付別自動生成）
├── backend/
│   ├── api.py              # Flask API サーバー
│   ├── logic.py            # AI 生成・トレンド分析ロジック
│   ├── engagement.py       # エンゲージメント分析
│   ├── config_manager.py   # 設定管理
│   └── INBOX/              # CSV インポート用フォルダ
└── frontend/
    ├── index.html           # メイン SPA
    ├── guide.html           # 使い方ガイド
    ├── css/style.css        # スタイル
    └── js/app.js            # フロントエンドロジック
```

## ⚙️ 設定管理

- **エクスポート** — 現在の設定を JSON ファイルにバックアップ
- **インポート** — JSON ファイルから設定を復元
- **初期化** — デフォルト設定にリセット

> ⚠️ `config.json` には API キーが含まれます。`.gitignore` で除外済みですが、手動で共有しないでください。

## 📝 ライセンス

[MIT License](LICENSE) — 詳細は LICENSE ファイルをご確認ください。

## 👨‍💻 開発者

**kuroka**

- 𝕏: [@kuroka_pm](https://x.com/kuroka_pm)
- 📝: [note.com/kuroka_pm](https://note.com/kuroka_pm)
