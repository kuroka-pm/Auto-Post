# 📮 Auto-Post — SNS 自動投稿ツール

Gemini AI × トレンド × ペルソナで、自然な SNS 投稿を自動生成・投稿する Windows デスクトップアプリ。

![Python](https://img.shields.io/badge/Python-3.12-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ 主な機能

| 機能 | 説明 |
|------|------|
| 🤖 **AI 投稿生成** | Gemini API でトレンドワード × ペルソナの掛け合わせ投稿を自動生成 |
| 🎭 **ペルソナ設計** | 年齢・職業・性格・口調などを設定し、AI がペルソナ全文を自動生成 |
| 📊 **3 タイプ投稿** | A: トレンド連動 / B: 独立意見 / C: note 記事告知 |
| ✍️ **5 つの文体** | 本音つぶやき・共感ポエム・ニュース一言 etc. 重み付きランダム選択 |
| 🐦 **X (Twitter) 投稿** | 画像添付 + ALT テキスト対応 |
| 🧵 **Threads 投稿** | 同時投稿 or 個別投稿 |
| ⏰ **自動スケジュール** | 指定時刻に自動投稿（時間ゆらぎでボット検知回避） |
| 📝 **note 告知** | note 記事の自然な告知投稿を AI が生成 |
| 🔌 **API 接続テスト** | Gemini / X / Threads の接続をワンクリック確認 |
| 📄 **ログ自動保存** | `logs/YYYY-MM-DD.log` に自動保存 |

## 📁 ファイル構成

```
auto-post/
├── app.py              # エントリポイント（GUI メインウィンドウ）
├── logic.py            # AI 生成・トレンド取得・SNS 投稿ロジック
├── ui_components.py    # GUI コンポーネント（タブ構成）
├── config_manager.py   # 設定の読み書き・暗号化
├── build_exe.py        # exe ビルドスクリプト
├── requirements.txt    # 依存パッケージ
├── .gitignore
└── README.md
```

## 🚀 セットアップ

### exe 版（推奨）

1. [Releases](../../releases) から `AutoPost.zip` をダウンロード
2. 解凍して `AutoPost.exe` を起動
3. 各タブで API キーとペルソナを設定

> ⚠️ **初回起動時の Windows セキュリティ警告について**
> 本ツールは PyInstaller でビルドしたコード未署名のアプリのため、Windows SmartScreen が警告を表示する場合があります。「詳細情報」→「実行」で起動できます。ソースコードは本リポジトリで全公開しています。

### Python から直接実行

```bash
# リポジトリのクローン
git clone https://github.com/kuroka-pm/Auto-Post.git
cd auto-post

# 仮想環境の作成
python -m venv .venv
.venv\Scripts\activate

# 依存パッケージをインストール
pip install -r requirements.txt

# 起動
python app.py
```

## 🔑 必要な API キー

| サービス | 取得先 | 用途 | 費用 |
|----------|--------|------|------|
| **Gemini API** | [Google AI Studio](https://aistudio.google.com/apikey) | 投稿文 / ペルソナ生成 | 無料枠あり（利用頻度が高い場合はクレカ登録が必要） |
| **X (Twitter) API** | [Developer Portal](https://developer.x.com/en/portal/dashboard) | X への投稿 | Basic: $5/月〜（Free 枠では投稿が制限される場合あり） |
| **Threads API**（任意） | [Meta for Developers](https://developers.facebook.com/) | Threads への投稿 | 無料 |

### X API の設定手順

1. Developer Portal で **App permissions** を **Read and Write** に設定
2. **OAuth 1.0a** を有効化
3. 以下の 4 つを取得:
   - API Key / API Secret
   - Access Token / Access Token Secret

> **注意**: 権限変更後に Access Token を再生成してください。

## 📖 使い方

詳しい使い方は [USAGE.md](USAGE.md) を参照してください。

### かんたん手順

1. **API 設定タブ** → API キーを入力 → 「🔌 接続テスト」で確認
2. **ペルソナタブ** → 性格などを入力 → 「🤖 AI でペルソナ生成」
3. **実行タブ** → 「📝 サンプル文章を生成」→ プレビュー確認 → 「🐦 投稿」
4. **自動運用**: 投稿時刻を設定 → 「▶️ 自動運用スタート」

## 🛡️ セキュリティ

- API キーは `config.json` に保存され、`.gitignore` で Git 管理から除外
- config 内のキーは難読化処理済み
- SSRF 対策: プライベート IP アドレスへのアクセスをブロック

## 📄 ライセンス

MIT License

## 👤 開発者

**黒歌｜人生を PM する黒猫**

- 🐦 X: [@kuroka_pm](https://x.com/kuroka_pm)
- 📝 note: [kuroka_pm](https://note.com/kuroka_pm)
