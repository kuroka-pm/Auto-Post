"""
logic.py — 生成・投稿ロジック（main.py から分離）

全パラメータを引数で受け取り、ハードコード値に依存しない疎結合設計。
アルゴリズム（トレンド取得、ランダムスタイル選択、サニタイズ処理）は
元の main.py のロジックをそのまま維持している。
"""

from __future__ import annotations

import ipaddress
import logging
import random
import re
import socket
import time
from functools import wraps
from typing import TypeVar, Callable
from urllib.parse import parse_qs, urlparse

import feedparser
import requests
import tweepy
from bs4 import BeautifulSoup
from google import genai
from google.genai import errors as genai_errors
from google.genai.types import GenerateContentConfig

_log = logging.getLogger(__name__)

T = TypeVar("T")


def _retry_api_call(
    fn: Callable[..., T],
    *args,
    max_retries: int = 3,
    base_delay: float = 2.0,
    **kwargs,
) -> T:
    """指数バックオフ付きリトライでAPI呼び出しを実行する。

    429 (Rate Limit) / 503 (Service Unavailable) / 接続エラー時に自動リトライ。
    """
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last_err = e
        except requests.exceptions.HTTPError as e:
            if hasattr(e, "response") and e.response is not None:
                if e.response.status_code in (429, 503):
                    last_err = e
                else:
                    raise
            else:
                last_err = e
        except Exception as e:
            err_str = str(e).lower()
            if any(kw in err_str for kw in ("429", "503", "resource_exhausted",
                                             "rate", "quota", "overloaded")):
                last_err = e
            else:
                raise

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            _log.info("API リトライ %d/%d (%.1f秒後): %s",
                      attempt + 1, max_retries, delay, last_err)
            time.sleep(delay)

    raise last_err  # type: ignore[misc]


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
# キーワード自動提案 & Google News RSS 自動生成
# ---------------------------------------------------------------------------

_KEYWORD_SUGGESTION_PROMPT = """\
## タスク
以下のペルソナが X (Twitter) で発信するとき、
トレンド情報の収集元として最適な **検索キーワード** を5つ提案せよ。

## ペルソナ情報
{persona_info}

## ルール
- キーワードは日本語（Google News Japan で検索する用途）
- 1キーワードは1〜3語（例: "AI 副業", "転職 30代", "プロジェクト管理"）
- ペルソナの職業・趣味・関心に基づいて選べ
- 汎用すぎるキーワード（"ニュース", "日本"）は避けろ
- このペルソナが語ると「自然で伸びやすい」テーマを選べ

## 出力形式
キーワードだけを1行1つで出力せよ。番号・説明・記号は不要。
"""


def suggest_keywords_from_persona(
    persona_info: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> list[str]:
    """ペルソナ情報からトレンド収集用キーワードを5つ提案する。

    Args:
        persona_info: ペルソナの基本情報（職業・趣味・性格など）
        api_key: Gemini API Key
        model: Gemini モデル名

    Returns:
        キーワードのリスト（最大5件）
    """
    client = genai.Client(api_key=api_key)
    prompt = _KEYWORD_SUGGESTION_PROMPT.format(persona_info=persona_info)

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(temperature=0.7),
        )
    except genai_errors.ClientError as e:
        msg = str(e)
        if "404" in msg or "not found" in msg.lower():
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=prompt,
                config=GenerateContentConfig(temperature=0.7),
            )
        else:
            raise

    text = response.text.strip()
    keywords = [
        line.strip().lstrip("・-•0123456789. 　")
        for line in text.splitlines()
        if line.strip() and len(line.strip()) < 30
    ]
    return keywords[:5]


def keywords_to_rss_urls(keywords: list[str]) -> list[str]:
    """キーワードリストを Google News RSS URL に変換する。

    Args:
        keywords: 検索キーワードのリスト

    Returns:
        Google News RSS URL のリスト
    """
    from urllib.parse import quote

    base = "https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    urls = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        url = base.format(query=quote(kw))
        urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# トレンド取得
# ---------------------------------------------------------------------------

def fetch_trends(rss_urls: list[str], blacklist: list[str]) -> list[dict]:
    """RSS URL リストからトレンドワードを取得する。

    - 複数ソースを統合し、重複を除去
    - ブラックリストに含まれる語を除外
    - 新しい順にソートし、最大15件を返す
    - 各トレンドにソースURL・ソース名を付与
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

    collected: list[tuple[str, float | None, str, str]] = []  # (title, ts, link, feed_title)
    for url in resolved_urls:
        if _is_private_url(url):
            print(f"[WARN] プライベートURL をブロックしました: {url}")
            continue
        try:
            feed = feedparser.parse(url)
            feed_title = feed.feed.get("title", url) if hasattr(feed, "feed") else url
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                link = entry.get("link", "")
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                ts = None
                if pub:
                    try:
                        ts = time.mktime(pub)
                    except Exception:
                        ts = None
                collected.append((title, ts, link, feed_title))
        except Exception as e:
            # 1つのソースが失敗しても他を続行
            print(f"[WARN] RSS取得失敗 ({url}): {e}")

    # 重複除去（新しい順）
    collected.sort(key=lambda x: x[1] or 0, reverse=True)
    seen: set[str] = set()
    trends: list[dict] = []
    for title, _, link, feed_title in collected:
        key = title.lower()
        if key in seen:
            continue
        if any(term in title for term in blacklist):
            continue
        seen.add(key)
        trends.append({
            "title": title,
            "source_url": link,
            "source_name": feed_title,
        })

    if len(trends) > 15:
        trends = trends[:15]

    if not trends:
        return []

    return trends


# ---------------------------------------------------------------------------
# スマートテーマ分析（Phase 2）
# ---------------------------------------------------------------------------

_TREND_ANALYSIS_PROMPT = """\
## タスク
以下のトレンドワードを、指定ペルソナが X (Twitter) で語った場合の
「伸びやすさ」を分析し、上位3件をスコア付きで返せ。

## 評価基準（各1〜10点）
1. **ペルソナ親和性** — その人が語ると自然か
2. **共感性** — 多くの人が「わかる」と思うか
3. **独自性** — 独自の切り口が出せるか

## ペルソナ
{persona}

## トレンドワード
{trends}

## 出力形式（JSON配列のみ出力。説明不要）
[
  {{"trend": "ワード", "angle": "この角度で語ると伸びる（20字以内）", "score": 8}},
  ...
]
上位3件のみ。scoreは3基準の平均（整数）。
"""


def analyze_trends(
    trends: list[str],
    persona: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> list[dict]:
    """トレンドをGeminiで分析し、ペルソナとの相性が良い順にランク付けする。

    Returns:
        [{"trend": "...", "angle": "...", "score": 8}, ...]
        最大3件。解析失敗時は空リストを返す。
    """
    import json as _json

    if not trends:
        return []

    client = genai.Client(api_key=api_key)
    trends_text = "\n".join(f"- {t}" for t in trends)
    prompt = _TREND_ANALYSIS_PROMPT.format(persona=persona, trends=trends_text)

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(temperature=0.3),
        )
    except genai_errors.ClientError as e:
        msg = str(e)
        if "404" in msg or "not found" in msg.lower():
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=prompt,
                config=GenerateContentConfig(temperature=0.3),
            )
        else:
            raise

    text = response.text.strip()

    # JSON 抽出（コードブロック対応）
    if "```" in text:
        # ```json ... ``` のパターン
        import re as _re
        match = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
        if match:
            text = match.group(1).strip()

    try:
        result = _json.loads(text)
        if isinstance(result, list):
            # score 降順で最大3件
            result.sort(key=lambda x: x.get("score", 0), reverse=True)
            return result[:3]
    except (_json.JSONDecodeError, TypeError):
        pass

    return []


# ---------------------------------------------------------------------------
# スタイル選択
# ---------------------------------------------------------------------------

def select_style(writing_styles: list[dict]) -> dict:
    """投稿スタイルを重み付きランダムで選択する。"""
    if not writing_styles:
        # フォールバック: 空リストの場合は最低限のスタイルを返す
        return {
            "name": "フリースタイル",
            "weight": 1,
            "char_range": "80〜200文字",
            "description": "自由な形式で書く",
            "structure": "自由構成",
            "example": "",
        }
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
    if not promotion_styles:
        return {
            "name": "さりげない紹介",
            "weight": 1,
            "prompt": "記事の内容に軽く触れながら、さりげなく紹介してください。",
        }
    weights = [s.get("weight", 1) for s in promotion_styles]
    return random.choices(promotion_styles, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# note.com 記事自動取得
# ---------------------------------------------------------------------------

def _extract_note_username(note_url_or_name: str) -> str:
    """noteのURLまたはユーザー名からユーザー名部分を抽出する。"""
    s = note_url_or_name.strip().rstrip("/")
    # https://note.com/kuroka_pm → kuroka_pm
    if "note.com/" in s:
        parts = s.split("note.com/")
        return parts[-1].split("/")[0].split("?")[0]
    return s


def fetch_note_articles(note_url_or_name: str) -> list[dict]:
    """note.comの非公式APIから公開記事一覧を取得する。

    Args:
        note_url_or_name: noteマイページURL (例: https://note.com/kuroka_pm)
                          またはユーザー名 (例: kuroka_pm)

    Returns:
        [{"url": "...", "title": "...", "summary": "..."}, ...] のリスト。
        generate_note_promotion() にそのまま渡せる形式。
    """
    username = _extract_note_username(note_url_or_name)
    if not username:
        return []

    api_url = (
        f"https://note.com/api/v2/creators/{username}"
        f"/contents?kind=note&page=1&per_page=50"
    )

    try:
        resp = requests.get(api_url, timeout=15, headers={
            "User-Agent": "AutoPost/1.0",
        })
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    articles = []
    for item in data.get("data", {}).get("contents", []):
        url = item.get("noteUrl", "")
        title = item.get("name", "")
        body = item.get("body", "")
        # bodyの先頭100文字をsummaryとして利用
        summary = body[:100].replace("\n", " ").strip() if body else ""
        if url and title:
            articles.append({
                "url": url,
                "title": title,
                "summary": summary,
            })

    return articles

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
        f"- URLは文中または末尾に自然に配置する\n"
        f"- 「ぜひ読んで」「よかったら」等の押し付けは避ける\n"
        f"- ハッシュタグ不要\n"
        f"- 投稿文のみを出力（説明や注釈は不要）\n\n"
        f"改行のルール（最重要）:\n"
        f"- 基本的に1文（。まで）を1行にしろ。複数の文を同じ行に詰め込むな\n"
        f"- 1文が長い場合は、読点（、）の後の自然な区切りで改行してよい\n"
        f"- ただし語句や節の途中では絶対に改行するな\n"
        f"- 全体を2〜4ブロックに分け、ブロック間に空行を入れろ\n"
        f"- URLの前後には空行を入れて読みやすくしろ\n"
        f"- 締めの一言は空行で独立させろ\n\n"
        f"良い改行の例:\n"
        f"---\n"
        f"他者のプロジェクト進行管理には長けていた。\n"
        f"だが、私自身のキャリアや人生を一つのプロジェクトとして捉え、\n"
        f"能動的に管理する視点は、退職して初めて得た気づきだ。\n"
        f"\n"
        f"しかし、自分の人生は客観的なPM思考で。\n"
        f"その具体的な実践がこのnote記事にある。\n"
        f"https://example.com/article\n"
        f"\n"
        f"一読の価値はある。\n"
        f"---\n\n"
        f"悪い改行の例（意味の途中で細切れに改行している）:\n"
        f"---\n"
        f"だが、私自身のキャリアや人生を\n"
        f"一つのプロジェクトとして捉え、\n"
        f"能動的に管理する視点は、\n"
        f"退職して初めて得た気づきだ。\n"
        f"---\n"
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(
                system_instruction=persona.strip() if persona and persona.strip() else None,
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
                    system_instruction=persona.strip() if persona and persona.strip() else None,
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

    # AIが幻覚で生成した間違ったnote URLを除去し、正しいURLだけを残す
    if url:
        # note.com のURLパターンを全て除去（正しいURLも含めて一旦除去）
        post = re.sub(r'https?://note\.com/\S+', '', post)
        # 空行の連続を整理
        post = re.sub(r'\n{3,}', '\n\n', post).strip()
        # 正しいURLを末尾に追加
        post = f"{post}\n\n{url}"

    return post.strip()


# ---------------------------------------------------------------------------
# プロンプト組み立て
# ---------------------------------------------------------------------------

_STEP2_TEMPLATE = """\
## タスク
トレンドワードを1つ選び、以下の人物の独白としてX（Twitter）用ポストを1つだけ書け。

## バズ構成ルール（必ず守れ）
1. 【フック】冒頭1行でスクロールを止めろ。方法は以下のいずれか:
   - 意外性のある断言（"〜は嘘だった"）
   - 共感を誘う問いかけ（"〜って思ったこと、ない？"）
   - 衝撃のエピソード（"〜した日の話。"）
   - 否定の連鎖（"〇〇？違う。△△？違う。本当は——"）
   - 具体的数字で権威づけ（"400人以上見てきた" "3年で〜"）
2. 【展開】抽象論は禁止。固有名詞・数字・体験を必ず入れろ。
3. 【余韻】最後は言い切らない。"含み"を残して読者に考えさせろ。
4. 文字数は {char_range} を厳守。超過は絶対に不可。

## バズ強化テクニック（2025-2026 アルゴリズム対応）
- 滞在時間を稼げ: 読者が「続きを読みたい」と思う構造にしろ
- 具体的な数字を入れろ: 「多くの」ではなく「400人以上」「3ヶ月で1,000人」
- メタファーを1つ使え: 「穴の空いたバケツ」のような一発で伝わる比喩
- 1文＝1行: 短い文を積み重ねてリズムを作れ。体言止めも有効
- CTA禁止: 「いいねしてね」「フォローお願い」は絶対に書くな。さりげなさが命
- 外部リンクは本文に入れるな（アルゴリズムが減点する）
- ハッシュタグは使うな
- 忖度した無難な文は書くな。主張がない投稿は誰の心も動かさない

## X表示のフォーマット規則（最重要）
Xのタイムラインはスマホで見る人が多く、カラム幅が狭い。以下を必ず守れ：

- 基本的に1文（。まで）を1行にしろ。複数の文を同じ行に詰め込むな
- 1文が長い場合は、読点（、）の後の自然な区切りで改行してよい
- ただし、語句や節の途中では絶対に改行するな。「〜の〜を」のような結びつきの強い文の途中で切るのは禁止
- 全体を2〜3ブロックに分け、ブロック間に空行（\n\n）を1つ入れろ
- 改行なしの長い段落は絶対に禁止。Xでは「空白」が読みやすさの鍵

### 良い例（Xで読みやすい）:
```
ゲーム業界の生成AI「悪影響」という調査結果。
その本質は異なる。

GDC調査で「悪影響が過半数」というデータが出た。
私からすれば、これはAIの悪影響ではない。
「人間の思考停止」の指標だ。

道具を使いこなす側の問題。
それは、どの時代も変わらない。
```

### 悪い例（スマホで読みにくい）:
```
ゲーム業界の生成AI「悪影響」という調査結果。その本質は異なる。GDC調査で「悪影響が過半数」というデータが出た。私からすれば、これはAIの悪影響ではない。「人間の思考停止」の指標だ。道具を使いこなす側の問題。それは、どの時代も変わらない。
```

## 今回の投稿スタイル: {style_name}
- スタイル指示（最優先で従え）: {style_description}
- 文字数目安: {char_range}
- 構成: {structure}

### スタイルの手本
以下はこのスタイルで書かれた投稿の例。トーン・リズム・構成・改行の入れ方を参考にせよ（内容はコピーしない）:
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

{feedback}

## 出力
ポスト本文のみを出力せよ。見出し・説明・引用符は不要。
「X表示のフォーマット規則」に従い、スマホで読みやすい改行を入れろ。
"""


_STEP2_TRENDLESS_TEMPLATE = """\
## タスク
以下の人物の独白としてX（Twitter）用ポストを1つだけ書け。
トレンドなしで、ペルソナの日常・価値観・経験から自由にテーマを選べ。

## バズ構成ルール（必ず守れ）
1. 【フック】冒頭1行でスクロールを止めろ。方法は以下のいずれか:
   - 意外性のある断言（"〜は嘘だった"）
   - 共感を誘う問いかけ（"〜って思ったこと、ない？"）
   - 衝撃のエピソード（"〜した日の話。"）
   - 否定の連鎖（"〇〇？違う。△△？違う。本当は——"）
   - 具体的数字で権威づけ（"400人以上見てきた" "3年で〜"）
2. 【展開】抽象論は禁止。固有名詞・数字・体験を必ず入れろ。
3. 【余韻】最後は言い切らない。"含み"を残して読者に考えさせろ。
4. 文字数は {char_range} を厳守。超過は絶対に不可。

## バズ強化テクニック（2025-2026 アルゴリズム対応）
- 滞在時間を稼げ: 読者が「続きを読みたい」と思う構造にしろ
- 具体的な数字を入れろ: 「多くの」ではなく「400人以上」「3ヶ月で1,000人」
- メタファーを1つ使え: 「穴の空いたバケツ」のような一発で伝わる比喩
- 1文＝1行: 短い文を積み重ねてリズムを作れ。体言止めも有効
- CTA禁止: 「いいねしてね」「フォローお願い」は絶対に書くな。さりげなさが命
- 外部リンクは本文に入れるな（アルゴリズムが減点する）
- ハッシュタグは使うな
- 忖度した無難な文は書くな。主張がない投稿は誰の心も動かさない

## X表示のフォーマット規則（最重要）
Xのタイムラインはスマホで見る人が多く、カラム幅が狭い。以下を必ず守れ：

- 基本的に1文（。まで）を1行にしろ。複数の文を同じ行に詰め込むな
- 1文が長い場合は、読点（、）の後の自然な区切りで改行してよい
- ただし、語句や節の途中では絶対に改行するな。「〜の〜を」のような結びつきの強い文の途中で切るのは禁止
- 全体を2〜3ブロックに分け、ブロック間に空行（\n\n）を1つ入れろ
- 改行なしの長い段落は絶対に禁止。Xでは「空白」が読みやすさの鍵

## 今回の投稿スタイル: {style_name}
- スタイル指示（最優先で従え）: {style_description}
- 文字数目安: {char_range}
- 構成: {structure}

### スタイルの手本
以下はこのスタイルで書かれた投稿の例。トーン・リズム・構成・改行の入れ方を参考にせよ（内容はコピーしない）:
---
{example}
---

{guidelines}

## NG表現（これだけは守れ）
{ng_expressions}

## 入力データ

### 人物背景
{persona}

{feedback}

## 出力
ポスト本文のみを出力せよ。見出し・説明・引用符は不要。
「X表示のフォーマット規則」に従い、スマホで読みやすい改行を入れろ。
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
    smart_analysis: bool = False,
    feedback: str = "",
) -> str:
    """選択されたスタイル + トレンド + ペルソナから投稿文を生成する。"""
    client = genai.Client(api_key=api_key)

    # トレンドなしの場合は専用テンプレートを使う
    if not trends:
        prompt = _STEP2_TRENDLESS_TEMPLATE.format(
            style_name=style["name"],
            style_description=style.get("description", ""),
            char_range=style["char_range"],
            structure=style["structure"],
            example=style["example"],
            guidelines=guidelines,
            ng_expressions=ng_expressions,
            persona=persona,
            feedback=feedback,
        )
    else:
        # スマート分析（有効な場合）
        if smart_analysis:
            analyzed = analyze_trends(trends, persona, api_key, model)
            if analyzed:
                best = analyzed[0]
                trends_text = (
                    f"- {best['trend']}\n"
                    f"  （推奨角度: {best.get('angle', '')}）"
                )
            else:
                # 分析失敗時はフォールバック
                pick_count = min(2, max(1, len(trends)))
                selected_trends = random.sample(trends, k=pick_count)
                trends_text = "\n".join(f"- {t}" for t in selected_trends)
        else:
            # 従来どおりランダム選択
            pick_count = min(2, max(1, len(trends)))
            selected_trends = random.sample(trends, k=pick_count)
            trends_text = "\n".join(f"- {t}" for t in selected_trends)

        prompt = _STEP2_TEMPLATE.format(
            style_name=style["name"],
            style_description=style.get("description", ""),
            char_range=style["char_range"],
            structure=style["structure"],
            example=style["example"],
            guidelines=guidelines,
            ng_expressions=ng_expressions,
            trends=trends_text,
            persona=persona,
            feedback=feedback,
        )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(
                system_instruction=persona.strip() if persona and persona.strip() else None,
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
                    system_instruction=persona.strip() if persona and persona.strip() else None,
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


def post_to_threads(text: str, api_key: str, image_url: str = "") -> str:
    """Threads Graph API を使って投稿する。投稿IDを返す。

    2ステップ構成:
      1. POST /me/threads  → コンテナ（下書き）を作成
      2. POST /me/threads_publish → コンテナを公開

    api_key は Threads User Access Token として扱う。
    image_url が指定された場合、画像付き投稿になる。
    """
    base = "https://graph.threads.net/v1.0/me"

    if not api_key:
        raise ValueError("Threads User Access Token が未設定です")

    headers = {"Authorization": f"Bearer {api_key}"}

    # Step 1: コンテナ作成
    params: dict[str, str] = {"text": text}
    if image_url:
        params["media_type"] = "IMAGE"
        params["image_url"] = image_url
    else:
        params["media_type"] = "TEXT"

    create_resp = requests.post(
        f"{base}/threads",
        params=params,
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

    # Step 1.5: コンテナの処理完了を待つ（最大30秒）
    import time as _time
    for attempt in range(15):
        _time.sleep(2)
        status_resp = requests.get(
            f"https://graph.threads.net/v1.0/{creation_id}",
            params={"fields": "status"},
            headers=headers,
            timeout=10,
        )
        if status_resp.status_code == 200:
            status = status_resp.json().get("status", "")
            if status == "FINISHED":
                break
            if status == "ERROR":
                err_msg = status_resp.json().get("error_message", "不明なエラー")
                raise RuntimeError(f"Threads コンテナ処理失敗: {err_msg}")
        # IN_PROGRESS や PUBLISHED 以外の場合は待機続行
    else:
        logging.getLogger(__name__).warning("Threads コンテナステータス確認タイムアウト。公開を試みます。")

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


def refresh_threads_token(current_token: str) -> dict:
    """短期トークンを長期トークン（60日）に交換する。

    Returns:
        {"access_token": "...", "expires_in": 5184000} 形式の dict。
    """
    resp = requests.get(
        "https://graph.threads.net/refresh_access_token",
        params={
            "grant_type": "th_refresh_token",
            "access_token": current_token,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        # レスポンスにトークンが含まれる可能性があるためサニタイズ
        detail = resp.text
        if current_token and current_token in detail:
            detail = detail.replace(current_token, "***")
        raise RuntimeError(f"トークン更新失敗 (HTTP {resp.status_code}): {detail}")
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError("トークン更新レスポンス不正: access_token が含まれていません")
    return data


def check_threads_token_expiry(api_key: str) -> int | None:
    """Threads トークンの残り日数を返す。取得失敗時は None。"""
    try:
        resp = requests.get(
            "https://graph.threads.net/v1.0/me",
            params={"fields": "id", "access_token": api_key},
            timeout=10,
        )
        # トークン期限は直接取得不可なので、有効性チェックのみ
        # 実際の期限管理は config に保存した issued_at で計算
        if resp.status_code == 200:
            return None  # 有効だが残り日数は不明
        return 0  # 無効
    except Exception:
        return None

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
