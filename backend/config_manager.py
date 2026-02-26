"""
config_manager.py — config.json の読み書きモジュール

全設定を config.json に集約し、GUI / ロジック双方から参照する。
APIキーは base64 難読化して保存する。
"""

import base64
import json
import sys
from pathlib import Path

# PyInstaller --onefile では __file__ が一時展開ディレクトリを指すため、
# sys.executable（exe本体の場所）を基準にする
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    # backend/ の親ディレクトリ = プロジェクトルート
    _BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_PATH = _BASE_DIR / "config.json"

# 難読化対象のキー名（model名などは対象外）
_SECRET_KEYS = {
    "gemini_api_key", "x_api_key", "x_api_secret",
    "x_access_token", "x_access_token_secret", "threads_api_key",
}
_OBF_PREFIX = "OBF:"


def _obfuscate(value: str) -> str:
    """平文を base64 難読化する。空文字列はそのまま返す。"""
    if not value or value.startswith(_OBF_PREFIX):
        return value
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"{_OBF_PREFIX}{encoded}"


def _deobfuscate(value: str) -> str:
    """難読化済みの値を復号する。OBF: プレフィックスがなければ平文とみなす。"""
    if not value or not value.startswith(_OBF_PREFIX):
        return value
    try:
        return base64.b64decode(value[len(_OBF_PREFIX):]).decode("utf-8")
    except Exception:
        return value  # 復号失敗時はそのまま返す


def get_default_config() -> dict:
    """main.py にハードコードされていた値をデフォルトとして返す。"""
    return {
        "api_keys": {
            "gemini_api_key": "",
            "gemini_model": "gemini-2.5-flash",
            "x_api_key": "",
            "x_api_secret": "",
            "x_access_token": "",
            "x_access_token_secret": "",
            "threads_api_key": "",
        },
        "persona": {
            "gender": "",
            "age": "",
            "occupation": "",
            "background": "",
            "hobbies": "",
            "personality": "",
            "first_person": "",
            "speech_style": "",
            "other": "",
            "generated_text": "",
        },
        "prompt_settings": {
            "writing_guidelines": (
                "## 書き方の指針（この順番に意識すること）\n\n"
                "1. **フックで始めろ**: 冒頭1〜2文でスクロールを止める。意外な事実、具体的な数字、"
                "または常識の逆を突く視点で入る。\n"
                "2. **1つだけ語れ**: トレンドと自分の背景（現場経験 or 簿記 or ジム or 株 etc.）の"
                "接点を「1つだけ」見つけて深掘りする。複数の背景を詰め込むな。\n"
                "3. **読みやすい改行を入れろ**: Xはスマホで読む人が多く、カラム幅が狭い。"
                "意味のまとまりごとに改行を入れ、視覚的なリズムを作れ。"
                "1行が40文字を超えたら意味の切れ目で改行しろ。"
                "全体を2〜3ブロックに分け、ブロック間に空行を1つ入れろ。"
                "ただし、意味が通じない中途半端な位置で改行するな。\n"
                "4. **余韻で終わろ**: 最後は「事実の描写」か「乾いた感想」でブツ切りにする。"
                "教訓、まとめ、問いかけ、前向きな宣言で終わらせるな。\n"
                "5. **中学生レベルの平易さ**: 難しい漢字はひらがなに開き、専門用語は日常の言葉に言い換える。"
                "スルスルと脳に入ってくる文章にすること。\n\n"
                "## 掛け合わせルール（必ず守れ）\n\n"
                "- トレンドネタ1つに対して、ペルソナの要素は「1つだけ」使う\n"
                "- 1つのポストで言及するテーマは「1つだけ」\n"
                "- 「トレンドの事実」→「ペルソナの1視点からの短いコメント」の2文構造を基本とする\n"
                "- 自分語りは最大2文まで。それ以上は削る\n"
                "- 「前の会社」「適応障害」などの重いテーマは、トレンドとの掛け合わせでは使わない\n\n"
                "## 出力後の自己チェック（生成後に必ず実行せよ）\n\n"
                "□ 改行なしで長い文が続いていないか？ → 意味の区切りで改行を入れる\n"
                "□ スマホで表示した時に壁のようなテキストになっていないか？ → ブロック分けする\n"
                "□ 空行ブロックが3つを超えていないか？ → ブロックを統合して減らす\n"
                "□ 最後に「まとめ」や「教訓」を入れていないか？ → 削除\n"
                "□ 「〜だった。」が3回以上連続していないか？ → 文末を変える\n"
                "□ 読み手が「で？」と思う文がないか？ → その文を削除"
            ),
            "ng_expressions": (
                "- ポエム: 「〜の歯車が」「絶望的」「〜という数字は嘘をつかない」のような大げさな比喩\n"
                "- 問いかけ: 「皆さんは？」「〜ですよね」\n"
                "- 教訓: 「〜を学んだ」「〜していきたい」「〜が大事だ」\n"
                "- ハッシュタグ: 一切不要\n"
                "- ビジネス用語（コンセンサス、PDCAなど）、不必要に難しいカタカナ語、業界の専門用語\n"
                "- 1ポストに3つ以上のテーマを含めない\n"
                "- 「結局〜」「つまり〜」で始まる総括文を入れない（エッセイ化の兆候）\n"
                "- 500文字を超えない（超えた場合は自動で短縮を試みる）"
            ),
            "writing_styles": [
                {
                    "name": "一撃キャッチコピー",
                    "weight": 5,
                    "char_range": "80〜140文字",
                    "description": "トレンドを制作現場の視点で一言に凝縮する。結論ファースト。余計な説明なし。",
                    "structure": "【フック1文】→【乾いた一行の感想】",
                    "example": (
                        "全社DX推進とか言ってるけど、うちの現場はまだRedmineのチケットをExcelに転記してた。\n"
                        "\n"
                        "推進する側が一番アナログだった。"
                    ),
                },
                {
                    "name": "ニュース×一言",
                    "weight": 4,
                    "char_range": "80〜140文字",
                    "description": "トレンドニュースに対して一言だけコメントする型。Xのアルゴリズムに最も強い。事実の引用＋短い私見。",
                    "structure": "【ニュースの要約1文】→【自分の一言コメント】",
                    "example": (
                        "ROG Ally Xが3万円値上げ。\n"
                        "\n"
                        "円安が趣味まで殴ってくる時代か。"
                    ),
                },
                {
                    "name": "共感エピソード",
                    "weight": 3,
                    "char_range": "140〜250文字",
                    "description": "自分の過去の具体的な体験1つだけを切り出し、トレンドに接続する。読んだ人が「あるある」と思えるリアルさが命。",
                    "structure": "【フック（意外な事実/数字）】→【エピソード展開（2〜3文）】→【ブツ切りの余韻】",
                    "example": (
                        "「納期は動かせません」って言われて、動かしたのは俺の生活リズムだった。\n"
                        "朝9時に出社して、気づいたら朝4時。仕様書のバージョンは8.3。\n"
                        "\n"
                        "数字は裏切らない、と思ったわけじゃない。\n"
                        "ただ、答えが1つしかない世界が楽だった。"
                    ),
                },
                {
                    "name": "構造分析",
                    "weight": 2,
                    "char_range": "140〜280文字",
                    "description": "トレンドの事象を「なぜそうなるか」の構造で腑分けする。感情を排し、淡々と因果関係を述べる。",
                    "structure": "【フック（反常識の切り口）】→【構造の解説（2〜3文）】→【余韻】",
                    "example": (
                        "大企業のDXが失敗する理由、技術じゃない。\n"
                        "稟議書のハンコの数だ。\n"
                        "\n"
                        "承認フロー5段階、それぞれの部署が「聞いてない」を恐れて保身の修正を入れる。\n"
                        "\n"
                        "前職でそれを「伝言ゲーム開発」と呼んでた。\n"
                        "誰も笑わなかった。"
                    ),
                },
                {
                    "name": "概念の再定義（独自理論）",
                    "weight": 3,
                    "char_range": "140〜250文字",
                    "description": "誰もが知る王道のテーマ（トレンド）に対して、自分の経験に基づいた独自の新しい定義（〇〇とは、△△である）を提示し、読者の脳にフックをかける。",
                    "structure": "【トレンド事象の提示】→【独自の再定義（〇〇とは、実は△△である）】→【理由・解説（2〜3文）】→【余韻】",
                    "example": (
                        "「AIによる業務効率化」のニュース。\n"
                        "\n"
                        "AI導入とは、魔法の杖ではなく「人間の泥臭いデバッグ作業の始まり」だ。\n"
                        "華やかなプレゼンの裏で、誰かが想定外の挙動を一つずつ手作業で潰している。\n"
                        "\n"
                        "結局、手を動かす人間が一番強い。"
                    ),
                },
            ],
        },
        "sources": {
            "rss_urls": [],
            "blacklist": [],
        },
        "schedule": {
            "fixed_times": ["09:00", "18:00"],
            "jitter_minutes": 15,
            "post_to_x": True,
            "post_to_threads": False,
            "active_days": [0, 1, 2, 3, 4, 5, 6],
            "threads_token_issued": 0,
        },
        "post_type": {
            "type_a_ratio": 3,  # トレンド連動の比率
            "type_b_ratio": 1,  # 独立ポストの比率
            "type_c_ratio": 1,  # note告知の比率
            "type_a_styles": ["一撃キャッチコピー", "ニュース×一言"],
            "type_b_styles": ["共感エピソード", "構造分析", "概念の再定義（独自理論）"],
        },
        "note_promotion": {
            "articles": [
                # {"url": "https://note.com/xxx/n/yyy",
                #  "title": "記事タイトル",
                #  "summary": "記事の概要（任意）"}
            ],
            "promotion_styles": [
                {
                    "name": "さりげない紹介",
                    "weight": 3,
                    "prompt": (
                        "この記事の内容に軽く触れながら、「こういう話を書きました」と"
                        "さりげなく紹介してください。押し付けがましさゼロで。"
                    ),
                },
                {
                    "name": "再告知・掘り起こし",
                    "weight": 2,
                    "prompt": (
                        "過去に書いた記事を再度紹介する体で書いてください。"
                        "「前に書いた記事が意外と読まれてて」「ふと思い出した記事」のような"
                        "自然な導入から入ること。"
                    ),
                },
                {
                    "name": "エピソード連動",
                    "weight": 2,
                    "prompt": (
                        "記事の内容に関連する短い個人的エピソード（2〜3文）を語り、"
                        "「この話、noteに詳しく書きました」と自然につなげてください。"
                    ),
                },
                {
                    "name": "問題提起型",
                    "weight": 2,
                    "prompt": (
                        "記事のテーマに関する問題提起や疑問を1〜2文で投げかけ、"
                        "「この辺の話をnoteにまとめてます」と続けてください。"
                        "読み手が「気になる」と思える切り口で。"
                    ),
                },
                {
                    "name": "学び・気づき共有",
                    "weight": 2,
                    "prompt": (
                        "記事を書く過程で得た気づきや学びを1つだけ短く共有し、"
                        "「詳しくはnoteに書いたので良かったら」とつなげてください。"
                        "上から目線にならないこと。"
                    ),
                },
            ],
        },
        "last_tab": "",
    }


def _deep_merge(base: dict, override: dict) -> dict:
    """base の構造を維持しつつ override の値で上書きする。

    override に存在しないキーは base の値を保持する。
    """
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict:
    """設定ファイルを読み込む。存在しなければデフォルトで生成して返す。

    APIキーは自動的に復号され、メモリ上では平文として扱う。
    """
    default = get_default_config()
    if not CONFIG_PATH.exists():
        save_config(default)
        return default

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # デフォルトとマージして、新規追加キーを補完
    merged = _deep_merge(default, data)

    # APIキーを復号
    api = merged.get("api_keys", {})
    for key in _SECRET_KEYS:
        if key in api:
            api[key] = _deobfuscate(api[key])

    return merged


def save_config(data: dict) -> None:
    """設定を config.json に書き出す。APIキーは難読化して保存する。"""
    # 元データを改変しないよう深いコピーを作成
    import copy
    to_save = copy.deepcopy(data)

    # APIキーを難読化
    api = to_save.get("api_keys", {})
    for key in _SECRET_KEYS:
        if key in api:
            api[key] = _obfuscate(api[key])

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)
