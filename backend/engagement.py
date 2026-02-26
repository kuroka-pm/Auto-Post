"""
engagement.py — 投稿履歴の記録 & Xアナリティクス CSV インポート & AI分析

Phase 3: フィードバックループ（無料版）
- 投稿結果を post_history.json に保存
- Xアナリティクスの CSV をインポートしてエンゲージメントを取得（$0）
- Gemini でエンゲージメント傾向を分析し、次回生成に活用
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 投稿履歴の保存先（exe 対応: config_manager.py と同じパターン）
# ---------------------------------------------------------------------------

if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    _BASE_DIR = Path(__file__).resolve().parent

_HISTORY_FILE = _BASE_DIR / "post_history.json"
_DAILY_OVERVIEW_FILE = _BASE_DIR / "daily_overview.json"
_ANALYSIS_CACHE_FILE = _BASE_DIR / "analysis_cache.json"
_INBOX_DIR = _BASE_DIR / "INBOX"

# INBOX フォルダがなければ自動生成
_INBOX_DIR.mkdir(exist_ok=True)


def _load_history() -> list[dict]:
    """履歴ファイルを読み込む。"""
    if _HISTORY_FILE.exists():
        try:
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def get_post_history() -> list[dict]:
    """公開API用: 投稿履歴を返す。"""
    return _load_history()


def _save_history(history: list[dict]) -> None:
    """履歴ファイルに書き込む。"""
    _HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_post_history() -> list[dict]:
    """投稿履歴を取得する（UI表示用、新しい順）。"""
    return list(reversed(_load_history()))


# ---------------------------------------------------------------------------
# 投稿記録（アプリから投稿した分）
# ---------------------------------------------------------------------------

def record_post(
    post_text: str,
    post_id: str | None = None,
    platform: str = "x",
    style_name: str = "",
    trend_used: str = "",
    smart_analysis: bool = False,
) -> dict:
    """投稿を履歴に記録する。"""
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": int(time.time()),
        "platform": platform,
        "post_id": post_id,
        "text": post_text,
        "char_count": len(post_text),
        "style": style_name,
        "trend": trend_used,
        "smart_analysis": smart_analysis,
        "source": "app",
        "engagement": None,
    }

    history = _load_history()
    history.append(entry)

    # 最大500件に制限
    if len(history) > 500:
        history = history[-500:]

    _save_history(history)
    return entry


# ---------------------------------------------------------------------------
# 重複防止ヘルパー
# ---------------------------------------------------------------------------

def get_recent_note_urls(days: int = 3) -> set[str]:
    """直近 N 日間に投稿した note 記事の URL を返す。"""
    cutoff = int(time.time()) - days * 86400
    urls: set[str] = set()
    for entry in _load_history():
        if entry.get("epoch", 0) >= cutoff:
            text = entry.get("text", "")
            # note.com の URL を抽出
            for word in text.split():
                if "note.com/" in word:
                    urls.add(word.strip("()[]「」"))
    return urls


def get_recent_styles(count: int = 10) -> list[str]:
    """直近 N 件の投稿で使用されたスタイル名を返す。"""
    history = _load_history()
    return [
        e.get("style", "") for e in history[-count:]
        if e.get("source") == "app" and e.get("style")
    ]

# ---------------------------------------------------------------------------
# Daily Overview データ管理
# ---------------------------------------------------------------------------

def _load_daily_overview() -> list[dict]:
    """日次オーバービューデータを読み込む。"""
    if _DAILY_OVERVIEW_FILE.exists():
        try:
            return json.loads(_DAILY_OVERVIEW_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_daily_overview(data: list[dict]) -> None:
    """日次オーバービューデータを書き込む。"""
    _DAILY_OVERVIEW_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_daily_overview() -> list[dict]:
    """日次オーバービューデータを取得する（UI表示用、新しい順）。"""
    return list(reversed(_load_daily_overview()))


# ---------------------------------------------------------------------------
# CSV インポート（Xアナリティクスから）
# ---------------------------------------------------------------------------

def _parse_int(val: str) -> int:
    """CSV 値を安全に int に変換する。"""
    try:
        return int(val.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return 0


def detect_csv_type(csv_path: str | Path) -> str:
    """CSVファイルの種類を自動判定する。

    Returns:
        "content"  = 投稿単位 CSV (account_analytics_content_*.csv)
        "overview" = 日次概要 CSV (account_overview_analytics.csv)
        "unknown"  = 判定不能
    """
    csv_path = Path(csv_path)
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            with open(csv_path, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        return "unknown"

    if "ポストID" in headers:
        return "content"
    elif "Date" in headers and "インプレッション数" in headers:
        return "overview"
    return "unknown"


def import_csv(csv_path: str | Path | None = None) -> dict[str, int]:
    """XアナリティクスCSVをインポートして履歴にマージする。

    Args:
        csv_path: CSVファイルパス。None の場合は INBOX 内の最新CSVを使用。

    Returns:
        {"imported": 新規件数, "updated": 更新件数, "skipped": スキップ件数}
    """
    if csv_path is None:
        csv_path = _find_latest_csv()
        if csv_path is None:
            raise FileNotFoundError(
                f"INBOX フォルダにCSVファイルが見つかりません: {_INBOX_DIR}"
            )
    csv_path = Path(csv_path)

    # CSV 読み込み（BOM 対応）
    rows = []
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            with open(csv_path, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if not rows:
        raise ValueError(f"CSVの読み込みに失敗しました: {csv_path}")

    history = _load_history()
    existing_ids = {h.get("post_id") for h in history if h.get("post_id")}

    imported = 0
    updated = 0
    skipped = 0

    for row in rows:
        post_id = row.get("ポストID", "").strip()
        if not post_id or post_id == "":
            skipped += 1
            continue

        engagement = {
            "impressions": _parse_int(row.get("インプレッション数", "0")),
            "likes": _parse_int(row.get("いいね", "0")),
            "engagement": _parse_int(row.get("エンゲージメント", "0")),
            "bookmarks": _parse_int(row.get("ブックマーク", "0")),
            "shares": _parse_int(row.get("共有された回数", "0")),
            "follows": _parse_int(row.get("新しいフォロー", "0")),
            "replies": _parse_int(row.get("返信", "0")),
            "retweets": _parse_int(row.get("リポスト", "0")),
            "profile_clicks": _parse_int(row.get("プロフィールへのアクセス数", "0")),
            "detail_clicks": _parse_int(row.get("詳細のクリック数", "0")),
            "url_clicks": _parse_int(row.get("URLのクリック数", "0")),
        }

        # 既存エントリの更新
        if post_id in existing_ids:
            for h in history:
                if h.get("post_id") == post_id:
                    h["engagement"] = engagement
                    h["engagement_updated"] = int(time.time())
                    updated += 1
                    break
        else:
            # 新規エントリ
            text = row.get("ポスト本文", "").strip()
            date_str = row.get("日付", "").strip()

            entry = {
                "timestamp": date_str,
                "epoch": 0,
                "platform": "x",
                "post_id": post_id,
                "text": text,
                "char_count": len(text),
                "style": "",
                "trend": "",
                "smart_analysis": False,
                "source": "csv_import",
                "engagement": engagement,
                "engagement_updated": int(time.time()),
            }
            history.append(entry)
            imported += 1

    # 最大500件に制限
    if len(history) > 500:
        history = history[-500:]

    _save_history(history)
    return {"imported": imported, "updated": updated, "skipped": skipped}


def import_daily_overview_csv(csv_path: str | Path) -> dict[str, int]:
    """日次アカウント概要CSVをインポートする。

    Args:
        csv_path: CSVファイルパス

    Returns:
        {"imported": 新規件数, "updated": 更新件数, "skipped": スキップ件数}
    """
    csv_path = Path(csv_path)

    # CSV 読み込み（BOM 対応）
    rows = []
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            with open(csv_path, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if not rows:
        raise ValueError(f"CSVの読み込みに失敗しました: {csv_path}")

    existing = _load_daily_overview()
    existing_dates = {d.get("date") for d in existing}

    imported = 0
    updated = 0
    skipped = 0

    for row in rows:
        date_str = row.get("Date", "").strip()
        if not date_str:
            skipped += 1
            continue

        entry = {
            "date": date_str,
            "impressions": _parse_int(row.get("インプレッション数", "0")),
            "likes": _parse_int(row.get("いいね", "0")),
            "engagement": _parse_int(row.get("エンゲージメント", "0")),
            "bookmarks": _parse_int(row.get("ブックマーク", "0")),
            "shares": _parse_int(row.get("共有された回数\\", "0")),
            "new_follows": _parse_int(row.get("新しいフォロー", "0")),
            "unfollows": _parse_int(row.get("フォロー解除", "0")),
            "replies": _parse_int(row.get("返信", "0")),
            "retweets": _parse_int(row.get("リポスト", "0")),
            "profile_visits": _parse_int(row.get("プロフィールへのアクセス数", "0")),
            "posts_created": _parse_int(row.get("ポストを作成", "0")),
            "video_views": _parse_int(row.get("動画再生数", "0")),
            "media_views": _parse_int(row.get("メディアの再生数", "0")),
            "imported_at": int(time.time()),
        }

        if date_str in existing_dates:
            for d in existing:
                if d.get("date") == date_str:
                    d.update(entry)
                    updated += 1
                    break
        else:
            existing.append(entry)
            imported += 1

    # 日付順にソート（新しい順）
    existing.sort(key=lambda x: x.get("date", ""), reverse=True)

    # 最大365日分に制限
    if len(existing) > 365:
        existing = existing[:365]

    _save_daily_overview(existing)
    return {"imported": imported, "updated": updated, "skipped": skipped}


def import_csv_auto(csv_path: str | Path) -> dict[str, Any]:
    """CSVを自動判定してインポートする。

    Returns:
        {"type": "content"|"overview", "imported": N, "updated": N, "skipped": N}
    """
    csv_type = detect_csv_type(csv_path)
    if csv_type == "content":
        result = import_csv(csv_path)
        return {"type": "content", **result}
    elif csv_type == "overview":
        result = import_daily_overview_csv(csv_path)
        return {"type": "overview", **result}
    else:
        raise ValueError(
            "CSVの形式を判定できませんでした。\n"
            "XアナリティクスからエクスポートしたCSVを使用してください。"
        )


def _find_latest_csv() -> Path | None:
    """INBOX フォルダ内の最新CSVファイルを返す。"""
    if not _INBOX_DIR.exists():
        return None

    csvs = sorted(
        _INBOX_DIR.glob("*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    # account_overview は除外（content の方を使う）
    for c in csvs:
        if "overview" not in c.name.lower():
            return c
    return csvs[0] if csvs else None


# ---------------------------------------------------------------------------
# AI 傾向分析
# ---------------------------------------------------------------------------

_ANALYSIS_PROMPT = """\
## タスク
以下は X (Twitter) の過去の投稿データです。
エンゲージメント（いいね・RT・インプレッション）の傾向を分析し、
次回の投稿生成に活かせる具体的なアドバイスを5つ出せ。

## 投稿データ（個別ポスト）
{post_data}

{daily_section}

## 分析ルール
- 「伸びた投稿」と「伸びなかった投稿」の違いを明確に指摘する
- 文体スタイル・トレンドの種類・投稿時間帯・文字数の傾向を見る
- 日次データがあれば、曜日別のインプレ傾向やフォロワー増減も分析する
- 抽象的なアドバイスは禁止。具体的な改善案を出す
- 数字を根拠に語れ

## 出力形式
1行1アドバイス。番号付き。各80字以内。日本語で。
"""


def analyze_engagement_trends(
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> str:
    """過去の投稿のエンゲージメント傾向をGeminiで分析する。"""
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai.types import GenerateContentConfig

    history = _load_history()

    with_engagement = [
        h for h in history
        if h.get("engagement") is not None
    ]

    if len(with_engagement) < 3:
        return ("📊 分析に必要なデータが不足しています。\n"
                f"エンゲージメント取得済み: {len(with_engagement)}件 / 最低3件必要\n"
                "XアナリティクスからCSVをダウンロードし、INBOXフォルダに入れてください。")

    # 直近30件を整形
    post_summaries = []
    for h in with_engagement[-30:]:
        eng = h["engagement"]
        summary = (
            f"[{h.get('timestamp', '不明')}] "
            f"文字数:{h.get('char_count', 0)} "
            f"IMP:{eng.get('impressions', 0)} "
            f"♥:{eng.get('likes', 0)} "
            f"RT:{eng.get('retweets', 0)} "
            f"エンゲ:{eng.get('engagement', 0)} "
            f"本文: {h.get('text', '')[:60]}"
        )
        post_summaries.append(summary)

    post_data = "\n".join(post_summaries)

    # 日次オーバービューデータも含める
    daily_data = _load_daily_overview()
    daily_section = ""
    if daily_data:
        daily_lines = []
        for d in daily_data[:14]:  # 直近14日分
            net_follow = d.get("new_follows", 0) - d.get("unfollows", 0)
            daily_lines.append(
                f"[{d.get('date', '?')}] "
                f"IMP:{d.get('impressions', 0)} "
                f"♥:{d.get('likes', 0)} "
                f"エンゲ:{d.get('engagement', 0)} "
                f"投稿数:{d.get('posts_created', 0)} "
                f"新フォロー:{d.get('new_follows', 0)} "
                f"解除:{d.get('unfollows', 0)} "
                f"純増:{net_follow:+d}"
            )
        daily_section = (
            "## 日次アカウント概要データ\n"
            + "\n".join(daily_lines)
        )

    prompt = _ANALYSIS_PROMPT.format(
        post_data=post_data,
        daily_section=daily_section,
    )

    client = genai.Client(api_key=api_key)
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

    return response.text.strip()


def get_history_summary() -> dict[str, Any]:
    """投稿履歴のサマリーを返す（日次オーバービュー含む）。"""
    history = _load_history()

    total = len(history)
    with_eng = [h for h in history if h.get("engagement") is not None]
    count = len(with_eng)

    total_likes = 0
    total_rt = 0
    total_imp = 0
    for h in with_eng:
        eng = h["engagement"]
        total_likes += eng.get("likes", 0)
        total_rt += eng.get("retweets", 0)
        total_imp += eng.get("impressions", 0)

    # ベストいいね
    best_likes = max(
        (h.get("engagement", {}).get("likes", 0) for h in with_eng),
        default=0,
    )

    result: dict[str, Any] = {
        "total_posts": total,
        "with_engagement": count,
        "avg_likes": round(total_likes / count, 1) if count else 0,
        "avg_retweets": round(total_rt / count, 1) if count else 0,
        "avg_impressions": round(total_imp / count, 1) if count else 0,
        "best_likes": best_likes,
    }

    # 日次オーバービューのサマリーも追加
    daily = _load_daily_overview()
    if daily:
        total_daily_imp = sum(d.get("impressions", 0) for d in daily)
        total_new_follows = sum(d.get("new_follows", 0) for d in daily)
        total_unfollows = sum(d.get("unfollows", 0) for d in daily)
        days = len(daily)
        result["daily_overview"] = {
            "days": days,
            "total_impressions": total_daily_imp,
            "avg_daily_impressions": round(total_daily_imp / days) if days else 0,
            "total_new_follows": total_new_follows,
            "total_unfollows": total_unfollows,
            "net_follow_change": total_new_follows - total_unfollows,
            "best_day": max(daily, key=lambda d: d.get("impressions", 0)).get("date", "") if daily else "",
            "best_day_impressions": max(d.get("impressions", 0) for d in daily) if daily else 0,
        }

    return result


def get_feedback_for_prompt() -> str:
    """過去のエンゲージメントデータから、投稿生成プロンプトに
    組み込むためのフィードバック文を生成する。

    データが不足している場合は空文字を返す（プロンプトへの影響なし）。
    """
    history = _load_history()
    with_eng = [
        h for h in history
        if h.get("engagement") is not None
        and h.get("engagement", {}).get("impressions", 0) > 0
    ]

    if len(with_eng) < 5:
        return ""

    # いいね数でソート → 上位・下位を抽出
    sorted_by_likes = sorted(
        with_eng,
        key=lambda h: h.get("engagement", {}).get("likes", 0),
        reverse=True,
    )

    top_posts = sorted_by_likes[:3]
    low_posts = [p for p in sorted_by_likes[-3:] if p.get("engagement", {}).get("likes", 0) == 0]

    # 伸びた投稿の特徴
    top_lines = []
    for p in top_posts:
        eng = p["engagement"]
        top_lines.append(
            f"  - ♥{eng.get('likes',0)} IMP{eng.get('impressions',0)} "
            f"({p.get('char_count',0)}字): {p.get('text','')[:50]}"
        )

    # 伸びなかった投稿の特徴
    low_lines = []
    for p in low_posts[:2]:
        eng = p["engagement"]
        low_lines.append(
            f"  - ♥{eng.get('likes',0)} IMP{eng.get('impressions',0)} "
            f"({p.get('char_count',0)}字): {p.get('text','')[:50]}"
        )

    # 文字数の傾向
    liked_chars = [p.get("char_count", 0) for p in top_posts if p.get("char_count")]
    avg_liked_chars = sum(liked_chars) // len(liked_chars) if liked_chars else 0

    parts = ["## 過去投稿の分析（参考にせよ）"]
    parts.append("### 伸びた投稿の傾向:")
    parts.extend(top_lines)
    if low_lines:
        parts.append("### 伸びなかった投稿の傾向:")
        parts.extend(low_lines)
    if avg_liked_chars:
        parts.append(f"### 数値傾向: 高エンゲージ投稿の平均文字数は{avg_liked_chars}字")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 分析キャッシュ
# ---------------------------------------------------------------------------

def save_analysis_cache(analysis_text: str) -> None:
    """AI分析結果をファイルに保存する。"""
    data = {
        "analysis": analysis_text,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _ANALYSIS_CACHE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_analysis_cache() -> dict:
    """保存されたAI分析結果を読み込む。"""
    if _ANALYSIS_CACHE_FILE.exists():
        try:
            return json.loads(_ANALYSIS_CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


# ---------------------------------------------------------------------------
# ダッシュボード用統計
# ---------------------------------------------------------------------------

def get_dashboard_stats() -> dict:
    """ダッシュボード用: 今日の投稿数と最近の投稿を返す。"""
    history = _load_history()
    today = time.strftime("%Y-%m-%d")

    # source=app の投稿だけを対象にする
    app_posts = [h for h in history if h.get("source") == "app"]

    # 今日の投稿数
    today_count = 0
    for h in app_posts:
        ts = h.get("timestamp", "")
        if ts.startswith(today):
            today_count += 1

    # 最近の投稿（新しい順、最大10件）
    recent = app_posts[-10:][::-1]
    recent_posts = []
    for h in recent:
        recent_posts.append({
            "text": h.get("text", "")[:80],
            "timestamp": h.get("timestamp", ""),
            "platform": h.get("platform", ""),
            "style": h.get("style", ""),
        })

    return {
        "today_count": today_count,
        "recent_posts": recent_posts,
    }

