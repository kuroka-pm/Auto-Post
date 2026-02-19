"""
logic.py — 生成・投稿ロジック（main.py から分離）

全パラメータを引数で受け取り、ハードコード値に依存しない疎結合設計。
アルゴリズム（トレンド取得、ランダムスタイル選択、サニタイズ処理）は
元の main.py のロジックをそのまま維持している。
"""

from __future__ import annotations

import ipaddress
import random
import re
import socket
import time
from urllib.parse import parse_qs, urlparse

import feedparser
import requests
import tweepy
from bs4 import BeautifulSoup
from google import genai
from google.genai import errors as genai_errors
from google.genai.types import GenerateContentConfig


# ---------------------------------------------------------------------------
# SSRF 防止 — プライベートIPへのアクセスをブロック
# ---------------------------------------------------------------------------

def _is_private_url(url: str) -> bool:
    """URL のホストがプライベート / ループバック / リンクローカルなら True を返す。"""
    try:
        hostname = urlparse(url).hostname or ""
        # localhost は即ブロック
        if hostname.lower() in ("localhost", "[::1]"):
            return True
        # DNS 解決してIPアドレスを検査
        addr_infos = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except (socket.gaierror, ValueError, OSError):
        # 解決不能ホストはブロックしない（feedparser に任せる）
        pass
    return False


# ---------------------------------------------------------------------------
# RSS URL 正規化・オートディスカバリ
# ---------------------------------------------------------------------------

# Googleトレンド: ブラウザ版 category 番号 → RSS用 cat パラメータ
_GTRENDS_CAT_MAP: dict[str, str] = {
    "0": "",     # すべて
    "2": "e",    # エンタメ
    "3": "b",    # ビジネス
    "5": "s",    # スポーツ
    "7": "h",    # 健康
    "8": "t",    # テクノロジー
}


def normalize_rss_url(url: str) -> str:
    """ブラウザ向け URL を RSS URL に自動変換する。

    対応パターン:
    - Googleトレンド: https://trends.google.co.jp/trending?geo=JP&category=X
      →  https://trends.google.co.jp/trends/trendingsearches/daily/rss?geo=JP&cat=Y
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # Googleトレンドのブラウザ版 URL を検知
    if "trends.google" in host and parsed.path.rstrip("/") in ("/trending", "/trends/trending"):
        qs = parse_qs(parsed.query)
        geo = qs.get("geo", ["JP"])[0]
        cats = qs.get("category", ["0"])
        cat_num = cats[0] if cats else "0"
        rss_cat = _GTRENDS_CAT_MAP.get(cat_num, "")
        rss_url = f"https://{host}/trends/trendingsearches/daily/rss?geo={geo}"
        if rss_cat:
            rss_url += f"&cat={rss_cat}"
        return rss_url

    return url


def discover_rss_from_html(url: str, timeout: int = 10) -> str | None:
    """HTML ページから RSS フィード URL を自動探索する（オートディスカバリ）。

    <link rel="alternate" type="application/rss+xml" href="..."> を探す。
    見つからなければ None を返す。
    """
    if _is_private_url(url):
        print(f"[WARN] プライベートURL をブロックしました: {url}")
        return None
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (AutoPost RSS Discoverer)"
        })
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    link = soup.find("link", attrs={
        "rel": "alternate",
        "type": re.compile(r"application/(rss|atom)\+xml"),
    })
    if link and link.get("href"):
        href = link["href"]
        # 相対パスの場合は絶対 URL に変換
        if href.startswith("/"):
            parsed = urlparse(url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        return href
    return None


def _is_feed_url(url: str) -> bool:
    """URL が RSS/Atom フィードらしいかを簡易判定する。"""
    lower = url.lower()
    return any(kw in lower for kw in ("rss", "feed", "atom", ".xml", ".rdf"))


# ---------------------------------------------------------------------------
# トレンド取得
# ---------------------------------------------------------------------------

def fetch_trends(rss_urls: list[str], blacklist: list[str]) -> list[str]:
    """RSS URL リストからトレンドワードを取得する。

    - 複数ソースを統合し、重複を除去
    - ブラックリストに含まれる語を除外
    - 新しい順にソートし、最大15件を返す
    """
    # --- 前処理: URL 正規化 & オートディスカバリ ---
    resolved_urls: list[str] = []
    for raw_url in rss_urls:
        normalized = normalize_rss_url(raw_url)
        if normalized != raw_url or _is_feed_url(normalized):
            # 変換済み or もともとフィード URL
            resolved_urls.append(normalized)
        else:
            # フィードらしくない URL → HTML からオートディスカバリ
            discovered = discover_rss_from_html(normalized)
            if discovered:
                print(f"[INFO] RSS自動検出: {normalized} → {discovered}")
                resolved_urls.append(discovered)
            else:
                # 発見できなかった場合はそのまま渡す（feedparser に任せる）
                resolved_urls.append(normalized)

    collected: list[tuple[str, float | None]] = []
    for url in resolved_urls:
        if _is_private_url(url):
            print(f"[WARN] プライベートURL をブロックしました: {url}")
            continue
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                ts = None
                if pub:
                    try:
                        ts = time.mktime(pub)
                    except Exception:
                        ts = None
                collected.append((title, ts))
        except Exception as e:
            # 1つのソースが失敗しても他を続行
            print(f"[WARN] RSS取得失敗 ({url}): {e}")

    # 重複除去（新しい順）
    collected.sort(key=lambda x: x[1] or 0, reverse=True)
    seen: set[str] = set()
    trends: list[str] = []
    for title, _ in collected:
        key = title.lower()
        if key in seen:
            continue
        if any(term in title for term in blacklist):
            continue
        seen.add(key)
        trends.append(title)

    if len(trends) > 15:
        trends = trends[:15]

    if not trends:
        return []

    return trends


# ---------------------------------------------------------------------------
# スタイル選択
# ---------------------------------------------------------------------------

def select_style(writing_styles: list[dict]) -> dict:
    """投稿スタイルを重み付きランダムで選択する。"""
    weights = [s.get("weight", 1) for s in writing_styles]
    chosen = random.choices(writing_styles, weights=weights, k=1)[0]
    return chosen


def select_post_type(post_type_cfg: dict) -> str:
    """投稿タイプをA/B/C比率に基づいてランダム選択する。

    Returns:
        "A" (トレンド連動) / "B" (独立ポスト) / "C" (note告知)
    """
    a_ratio = post_type_cfg.get("type_a_ratio", 3)
    b_ratio = post_type_cfg.get("type_b_ratio", 1)
    c_ratio = post_type_cfg.get("type_c_ratio", 1)
    chosen = random.choices(
        ["A", "B", "C"], weights=[a_ratio, b_ratio, c_ratio], k=1
    )[0]
    return chosen


def select_style_for_type(
    post_type: str,
    writing_styles: list[dict],
    post_type_cfg: dict,
) -> dict:
    """投稿タイプに応じたスタイルを重み付きで選択する。

    タイプA: type_a_styles に含まれるスタイルのみから選択
    タイプB: type_b_styles に含まれるスタイルのみから選択
    """
    if post_type == "A":
        allowed = set(post_type_cfg.get("type_a_styles", []))
    else:
        allowed = set(post_type_cfg.get("type_b_styles", []))

    candidates = [s for s in writing_styles if s["name"] in allowed]
    if not candidates:
        # フォールバック: 全スタイルから選択
        candidates = writing_styles
    return select_style(candidates)


# ---------------------------------------------------------------------------
# note告知投稿生成（タイプC）
# ---------------------------------------------------------------------------


def select_note_promotion_style(promotion_styles: list[dict]) -> dict:
    """告知スタイルを重み付きランダムで選択する。"""
    weights = [s.get("weight", 1) for s in promotion_styles]
    return random.choices(promotion_styles, weights=weights, k=1)[0]


def generate_note_promotion(
    article: dict,
    promotion_style: dict,
    persona: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> str:
    """note記事の告知投稿をGeminiで生成する。

    記事の内容を踏まえた自然な告知文を生成し、URLを文中に組み込む。
    """
    client = genai.Client(api_key=api_key)

    url = article.get("url", "")
    title = article.get("title", "")
    summary = article.get("summary", "")
    style_prompt = promotion_style.get("prompt", "")
    style_name = promotion_style.get("name", "")

    prompt = (
        f"あなたは以下のペルソナです。\n{persona}\n\n"
        f"---\n"
        f"以下のnote記事を紹介する投稿を書いてください。\n\n"
        f"記事タイトル: {title}\n"
        f"記事概要: {summary if summary else '（タイトルから推測してください）'}\n"
        f"記事URL: {url}\n\n"
        f"告知スタイル「{style_name}」:\n{style_prompt}\n\n"
        f"ルール:\n"
        f"- 80〜200文字以内\n"
        f"- 2〜3段落のブロックに分ける。文ごとに改行を入れ、ブロック間に空行を1つ入れる\n"
        f"- URLは文中または末尾に自然に配置する\n"
        f"- 「ぜひ読んで」「よかったら」等の押し付けは避ける\n"
        f"- ハッシュタグ不要\n"
        f"- 投稿文のみを出力（説明や注釈は不要）\n"
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(
                system_instruction=persona if persona else None,
                temperature=0.9,
            ),
        )
    except genai_errors.ClientError as e:
        msg = str(e)
        if "404" in msg or "not found" in msg.lower():
            fallback = "gemini-2.5-pro"
            response = client.models.generate_content(
                model=fallback,
                contents=prompt,
                config=GenerateContentConfig(
                    system_instruction=persona if persona else None,
                    temperature=0.9,
                ),
            )
        else:
            raise

    post = response.text.strip()

    # 引用符除去
    quote_pairs = [('"', '"'), ('\u201c', '\u201d'), ('\u300c', '\u300d')]
    for open_ch, close_ch in quote_pairs:
        if post.startswith(open_ch) and post.endswith(close_ch):
            post = post[len(open_ch):-len(close_ch)]

    # URLが含まれていない場合は末尾に追加
    if url and url not in post:
        post = f"{post}\n\n{url}"

    return post.strip()


# ---------------------------------------------------------------------------
# プロンプト組み立て
# ---------------------------------------------------------------------------

_STEP2_TEMPLATE = """\
## タスク
トレンドワードを1つ選び、以下の人物の独白としてX（Twitter）用ポストを1つだけ書け。

## 今回の投稿スタイル: {style_name}
- 文字数目安: {char_range}
- 構成: {structure}

### スタイルの手本
以下はこのスタイルで書かれた投稿の例。トーン・リズム・構成を参考にせよ（内容はコピーしない）:
---
{example}
---

{guidelines}

## NG表現（これだけは守れ）
{ng_expressions}

## 入力データ

### トレンドワード
{trends}

### 人物背景
{persona}

## 出力
ポスト本文のみを出力せよ。見出し・説明・引用符は不要。
"""


_STEP2_TRENDLESS_TEMPLATE = """\
## タスク
以下の人物の独白としてX（Twitter）用ポストを1つだけ書け。
トレンドなしで、ペルソナの日常・価値観・経験から自由にテーマを選べ。

## 今回の投稿スタイル: {style_name}
- 文字数目安: {char_range}
- 構成: {structure}

### スタイルの手本
以下はこのスタイルで書かれた投稿の例。トーン・リズム・構成を参考にせよ（内容はコピーしない）:
---
{example}
---

{guidelines}

## NG表現（これだけは守れ）
{ng_expressions}

## 入力データ

### 人物背景
{persona}

## 出力
ポスト本文のみを出力せよ。見出し・説明・引用符は不要。
"""


# ---------------------------------------------------------------------------
# Gemini API — 投稿文生成
# ---------------------------------------------------------------------------

def generate_post(
    style: dict,
    trends: list[str],
    persona: str,
    guidelines: str,
    ng_expressions: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> str:
    """選択されたスタイル + トレンド + ペルソナから投稿文を生成する。"""
    client = genai.Client(api_key=api_key)

    # トレンドなしの場合は専用テンプレートを使う
    if not trends:
        prompt = _STEP2_TRENDLESS_TEMPLATE.format(
            style_name=style["name"],
            char_range=style["char_range"],
            structure=style["structure"],
            example=style["example"],
            guidelines=guidelines,
            ng_expressions=ng_expressions,
            persona=persona,
        )
    else:
        # ニュース選択のランダム化（1〜2件）
        pick_count = min(2, max(1, len(trends)))
        selected_trends = random.sample(trends, k=pick_count)
        trends_text = "\n".join(f"- {t}" for t in selected_trends)

        prompt = _STEP2_TEMPLATE.format(
            style_name=style["name"],
            char_range=style["char_range"],
            structure=style["structure"],
            example=style["example"],
            guidelines=guidelines,
            ng_expressions=ng_expressions,
            trends=trends_text,
            persona=persona,
        )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(
                system_instruction=persona,
                temperature=0.9,
            ),
        )
    except genai_errors.ClientError as e:
        msg = str(e)
        if "404" in msg or "not found" in msg.lower():
            fallback = "gemini-2.5-pro"
            response = client.models.generate_content(
                model=fallback,
                contents=prompt,
                config=GenerateContentConfig(
                    system_instruction=persona,
                    temperature=0.9,
                ),
            )
        else:
            raise

    post = response.text.strip()

    # 引用符除去
    quote_pairs = [('"', '"'), ('\u201c', '\u201d'), ('\u300c', '\u300d')]
    for open_ch, close_ch in quote_pairs:
        if post.startswith(open_ch) and post.endswith(close_ch):
            post = post[len(open_ch):-len(close_ch)]

    return post.strip()


# ---------------------------------------------------------------------------
# ペルソナ自動生成
# ---------------------------------------------------------------------------

_PERSONA_GENERATION_PROMPT = """\
以下の情報をもとに、SNS自動投稿bot用の「ペルソナ設定文」を生成してください。

## 入力情報
- 性別: {gender}
- 年齢: {age}
- 職業: {occupation}
- 経歴: {background}
- 趣味: {hobbies}
- 性格: {personality}
- 一人称: {first_person}
- 口調・語尾: {speech_style}
- その他: {other}

## 出力フォーマット
以下の形式で、具体的かつ詳細なペルソナ設定文を書いてください:

あなたはSNSに独り言を投稿する一個人として文章を書く。以下の人物像になりきり、
この人物の「内面の声」をそのまま文字にする。

## 人物像
（箇条書きで5〜8項目。具体的なエピソードや数字を含める）

## 声のトーン
（箇条書きで4〜6項目。一人称、口調、語尾、特徴的な癖を明記）

## 絶対ルール
- 一人称は必ず「{first_person}」を使う（指定がない場合は性別と性格から自然なものを選ぶ）
- 口調・語尾は「{speech_style}」に従う（指定がない場合は性格から推定）

## 話し方の例
（3〜5例。実際の投稿のようなリアルな文を書く）
"""


def generate_persona(
    age: str,
    occupation: str,
    hobbies: str,
    personality: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
    gender: str = "",
    background: str = "",
    first_person: str = "",
    speech_style: str = "",
    other: str = "",
) -> str:
    """Gemini API でペルソナ設定文を自動生成する。"""
    client = genai.Client(api_key=api_key)

    prompt = _PERSONA_GENERATION_PROMPT.format(
        gender=gender if gender else "未指定",
        age=age,
        occupation=occupation,
        background=background if background else "特になし",
        hobbies=hobbies,
        personality=personality,
        first_person=first_person if first_person else "性別・性格から自然に推定",
        speech_style=speech_style if speech_style else "性格から自然に推定",
        other=other if other else "特になし",
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(temperature=0.8),
        )
    except genai_errors.ClientError as e:
        msg = str(e)
        if "404" in msg or "not found" in msg.lower():
            fallback = "gemini-2.5-pro"
            response = client.models.generate_content(
                model=fallback,
                contents=prompt,
                config=GenerateContentConfig(temperature=0.8),
            )
        else:
            raise

    result = response.text.strip()

    # AIの前置き（「承知いたしました〜」等）を除去
    lines = result.split("\n")
    start_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("あなたは") or stripped.startswith("##"):
            start_idx = i
            break
    if start_idx > 0:
        result = "\n".join(lines[start_idx:]).strip()

    return result


# ---------------------------------------------------------------------------
# テキストクリーンアップ
# ---------------------------------------------------------------------------

def sanitize_post(text: str) -> str:
    """投稿テキストの改行・記号を整理し、X で意図通りに表示されるようにする。"""
    # マークダウン記法の置換
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\-\*\+]\s+", "・", text, flags=re.MULTILINE)

    # 各行末尾空白除去
    lines = text.split("\n")
    lines = [line.rstrip() for line in lines]
    text = "\n".join(lines)

    # 3つ以上の連続改行を統一
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ---------------------------------------------------------------------------
# X / Threads 投稿
# ---------------------------------------------------------------------------

def post_to_x(
    text: str,
    api_keys: dict,
    image_path: str | None = None,
    alt_text: str | None = None,
) -> str:
    """tweepy (API v2) を使って X に投稿する。投稿IDを返す。

    image_path が指定された場合:
      - API v1.1 (tweepy.API) で画像をアップロード
      - API v2 (tweepy.Client) で media_ids を付けてツイート
    """
    client = tweepy.Client(
        consumer_key=api_keys["x_api_key"],
        consumer_secret=api_keys["x_api_secret"],
        access_token=api_keys["x_access_token"],
        access_token_secret=api_keys["x_access_token_secret"],
    )

    media_ids = None
    if image_path:
        # v1.1 API でメディアアップロード
        auth = tweepy.OAuth1UserHandler(
            consumer_key=api_keys["x_api_key"],
            consumer_secret=api_keys["x_api_secret"],
            access_token=api_keys["x_access_token"],
            access_token_secret=api_keys["x_access_token_secret"],
        )
        api_v1 = tweepy.API(auth)
        media = api_v1.media_upload(filename=image_path)

        # ALTテキストがあれば設定
        if alt_text:
            api_v1.create_media_metadata(
                media_id=media.media_id, alt_text=alt_text
            )

        media_ids = [media.media_id]

    response = client.create_tweet(text=text, media_ids=media_ids)
    return str(response.data["id"])


def post_to_threads(text: str, api_key: str) -> str:
    """Threads Graph API を使って投稿する。投稿IDを返す。

    2ステップ構成:
      1. POST /me/threads  → コンテナ（下書き）を作成
      2. POST /me/threads_publish → コンテナを公開

    api_key は Threads User Access Token として扱う。
    """
    base = "https://graph.threads.net/v1.0/me"

    if not api_key:
        raise ValueError("Threads User Access Token が未設定です")

    headers = {"Authorization": f"Bearer {api_key}"}

    # Step 1: コンテナ作成
    create_resp = requests.post(
        f"{base}/threads",
        params={
            "media_type": "TEXT",
            "text": text,
        },
        headers=headers,
        timeout=30,
    )
    if create_resp.status_code != 200:
        detail = create_resp.text
        raise RuntimeError(
            f"Threads コンテナ作成失敗 (HTTP {create_resp.status_code}): {detail}"
        )

    creation_id = create_resp.json().get("id")
    if not creation_id:
        raise RuntimeError(f"Threads コンテナIDが取得できません: {create_resp.text}")

    # Step 2: 公開
    publish_resp = requests.post(
        f"{base}/threads_publish",
        params={"creation_id": creation_id},
        headers=headers,
        timeout=30,
    )
    if publish_resp.status_code != 200:
        detail = publish_resp.text
        raise RuntimeError(
            f"Threads 公開失敗 (HTTP {publish_resp.status_code}): {detail}"
        )

    post_id = publish_resp.json().get("id", "unknown")
    return str(post_id)


# ---------------------------------------------------------------------------
# API 接続テスト
# ---------------------------------------------------------------------------

def test_gemini_connection(api_key: str, model: str = "gemini-2.5-flash") -> tuple[bool, str]:
    """Gemini API の接続テスト。短いプロンプトを送り応答を確認する。"""
    if not api_key:
        return False, "API Key が未設定です"
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents="テスト。「OK」とだけ返してください。",
            config=GenerateContentConfig(temperature=0.0),
        )
        return True, f"✅ 接続成功（モデル: {model}）"
    except Exception as e:
        return False, f"❌ 接続失敗: {e}"


def test_x_connection(api_keys: dict) -> tuple[bool, str]:
    """X (Twitter) API の接続テスト。認証情報を検証する。"""
    required = ["x_api_key", "x_api_secret", "x_access_token", "x_access_token_secret"]
    for key in required:
        if not api_keys.get(key):
            return False, f"{key} が未設定です"
    try:
        client = tweepy.Client(
            consumer_key=api_keys["x_api_key"],
            consumer_secret=api_keys["x_api_secret"],
            access_token=api_keys["x_access_token"],
            access_token_secret=api_keys["x_access_token_secret"],
        )
        me = client.get_me()
        if me and me.data:
            return True, f"✅ 接続成功（@{me.data.username}）"
        return False, "❌ ユーザー情報を取得できませんでした"
    except Exception as e:
        return False, f"❌ 接続失敗: {e}"


def test_threads_connection(api_key: str) -> tuple[bool, str]:
    """Threads API の接続テスト。/me エンドポイントで認証を確認する。"""
    if not api_key:
        return False, "API Key が未設定です"
    try:
        resp = requests.get(
            "https://graph.threads.net/v1.0/me",
            params={"fields": "id,username"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            username = data.get("username", "?")
            return True, f"✅ 接続成功（@{username}）"
        return False, f"❌ HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"❌ 接続失敗: {e}"
