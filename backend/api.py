"""
api.py — Flask REST API エンドポイント

フロントエンド (HTML/JS) とバックエンド (logic.py 等) をつなぐ。
"""

import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request

from backend.config_manager import load_config, save_config, get_default_config
from backend import logic
from backend import engagement

# プロジェクトルート = backend/ の親
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"

app = Flask(
    __name__,
    static_folder=str(_FRONTEND_DIR),
    static_url_path="",
)

# ---------------------------------------------------------------------------
# グローバル状態
# ---------------------------------------------------------------------------
_scheduler_running = False
_scheduler_thread = None
_execution_logs: list[dict] = []
_MAX_LOGS = 200


def _add_log(level: str, message: str):
    """実行ログを追加する。"""
    _execution_logs.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "message": message,
    })
    if len(_execution_logs) > _MAX_LOGS:
        _execution_logs.pop(0)


# ---------------------------------------------------------------------------
# ページ配信
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/icon.ico")
def favicon():
    return app.response_class(
        (_PROJECT_ROOT / "icon.ico").read_bytes(),
        mimetype="image/x-icon",
    )

# ---------------------------------------------------------------------------
# 設定 API
# ---------------------------------------------------------------------------

@app.route("/api/config", methods=["GET"])
def get_config():
    """設定を取得する。APIキーはマスクして返す。"""
    config = load_config()
    # フロントに返す際はAPIキーをマスク
    safe_config = _mask_api_keys(config)
    return jsonify(safe_config)


@app.route("/api/config/raw", methods=["GET"])
def get_config_raw():
    """設定を生値で取得する（設定画面での表示用）。"""
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def update_config():
    """設定を更新する。"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    config = load_config()
    config.update(data)
    save_config(config)
    return jsonify({"status": "ok"})


@app.route("/api/config/section/<section>", methods=["POST"])
def update_config_section(section):
    """設定の特定セクションを更新する。"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    config = load_config()
    if section in config:
        config[section].update(data)
    else:
        config[section] = data
    save_config(config)
    return jsonify({"status": "ok"})


@app.route("/api/config/reset", methods=["POST"])
def reset_config():
    """設定を初期値にリセットする。"""
    default = get_default_config()
    save_config(default)
    return jsonify({"status": "ok"})


def _mask_api_keys(config: dict) -> dict:
    """APIキーをマスクする。"""
    import copy
    masked = copy.deepcopy(config)
    api = masked.get("api_keys", {})
    for key in ("gemini_api_key", "x_api_key", "x_api_secret",
                "x_access_token", "x_access_token_secret", "threads_api_key"):
        val = api.get(key, "")
        if val:
            api[key] = val[:4] + "***" + val[-4:] if len(val) > 8 else "***"
    return masked


# ---------------------------------------------------------------------------
# トレンド API
# ---------------------------------------------------------------------------

@app.route("/api/trends", methods=["GET"])
def get_trends():
    """トレンドを取得する。"""
    config = load_config()
    sources = config.get("sources", {})
    rss_urls = sources.get("rss_urls", [])
    blacklist = sources.get("blacklist", [])
    try:
        trends = logic.fetch_trends(rss_urls=rss_urls, blacklist=blacklist)
        return jsonify({"trends": trends})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trends/analyze", methods=["POST"])
def analyze_trends():
    """トレンドをペルソナとの相性で分析する。"""
    config = load_config()
    api_keys = config.get("api_keys", {})
    persona = config.get("persona", {})
    data = request.get_json() or {}
    trends = data.get("trends", [])
    try:
        analysis = logic.analyze_trends(
            trends=trends,
            persona=persona.get("generated_text", ""),
            api_key=api_keys.get("gemini_api_key", ""),
            model=api_keys.get("gemini_model", "gemini-2.5-flash"),
        )
        return jsonify({"analysis": analysis})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# 投稿生成 API
# ---------------------------------------------------------------------------

@app.route("/api/generate", methods=["POST"])
def generate_post():
    """投稿を生成する。"""
    config = load_config()
    data = request.get_json() or {}

    post_type = data.get("post_type", "A")
    count = data.get("count", 1)
    trend = data.get("trend")
    style_name = data.get("style")
    use_smart = data.get("smart_analysis", False)

    results = []
    api_keys = config.get("api_keys", {})
    persona_text = config.get("persona", {}).get("generated_text", "")
    writing_styles = config.get("prompt_settings", {}).get("writing_styles", [])
    guidelines = config.get("prompt_settings", {}).get("writing_guidelines", "")
    ng_expr = config.get("prompt_settings", {}).get("ng_expressions", "")
    rss_urls = config.get("sources", {}).get("rss_urls", [])
    blacklist = config.get("sources", {}).get("blacklist", [])
    gemini_key = api_keys.get("gemini_api_key", "")
    gemini_model = api_keys.get("gemini_model", "gemini-2.5-flash")

    # トレンド取得
    if post_type in ("A",) and not trend:
        try:
            trends_list = logic.fetch_trends(rss_urls=rss_urls, blacklist=blacklist)
        except Exception:
            trends_list = []
    else:
        trends_list = [trend] if trend else []

    for _ in range(count):
        try:
            if post_type == "C":
                # note告知
                articles = config.get("note_promotion", {}).get("articles", [])
                if not articles:
                    results.append({"error": "note記事が登録されていません"})
                    continue
                import random as _rnd
                article = _rnd.choice(articles)
                promotion_styles = config.get("note_promotion", {}).get("promotion_styles", [])
                promo_style = logic.select_note_promotion_style(promotion_styles)
                post = logic.generate_note_promotion(
                    article=article,
                    promotion_style=promo_style,
                    persona=persona_text,
                    api_key=gemini_key,
                    model=gemini_model,
                )
            else:
                # スタイル選択
                if style_name:
                    style = next((s for s in writing_styles if s.get("name") == style_name), None)
                    if not style:
                        style = logic.select_style(writing_styles)
                else:
                    style = logic.select_style(writing_styles)

                # フィードバック（smart analysis）
                feedback = ""
                if use_smart:
                    try:
                        feedback = engagement.get_feedback_for_prompt()
                    except Exception:
                        feedback = ""

                post = logic.generate_post(
                    style=style,
                    trends=trends_list,
                    persona=persona_text,
                    guidelines=guidelines,
                    ng_expressions=ng_expr,
                    api_key=gemini_key,
                    model=gemini_model,
                    smart_analysis=use_smart,
                    feedback=feedback,
                )
            results.append({"text": post, "char_count": len(post)})
        except Exception as e:
            results.append({"error": str(e)})

    return jsonify({"posts": results})


# ---------------------------------------------------------------------------
# 投稿実行 API
# ---------------------------------------------------------------------------

@app.route("/api/post", methods=["POST"])
def execute_post():
    """X / Threads に投稿する。画像付きにも対応。"""
    config = load_config()
    api_keys = config.get("api_keys", {})

    # JSON or FormData の両方に対応
    if request.content_type and "multipart/form-data" in request.content_type:
        text = request.form.get("text", "")
        post_to_x = request.form.get("post_to_x", "true") == "true"
        post_to_threads = request.form.get("post_to_threads", "false") == "true"
        alt_text = request.form.get("alt_text", "")
        image_file = request.files.get("image")
    else:
        data = request.get_json() or {}
        text = data.get("text", "")
        post_to_x = data.get("post_to_x", True)
        post_to_threads = data.get("post_to_threads", False)
        alt_text = ""
        image_file = None

    # 画像を一時ファイルに保存
    image_path = None
    if image_file and image_file.filename:
        import tempfile
        suffix = Path(image_file.filename).suffix or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=str(_PROJECT_ROOT))
        image_file.save(tmp)
        tmp.close()
        image_path = tmp.name

    results = {}
    any_success = False

    if post_to_x:
        try:
            logic.post_to_x(
                text=text,
                api_keys=api_keys,
                image_path=image_path,
                alt_text=alt_text or None,
            )
            results["x"] = "success"
            any_success = True
            _add_log("success", f"X投稿成功: {text[:30]}...")
        except Exception as e:
            results["x"] = f"error: {e}"
            _add_log("error", f"X投稿失敗: {e}")

    if post_to_threads:
        try:
            # Threads は公開URLが必要なため、ローカル画像は送れない → テキストのみ
            logic.post_to_threads(text=text, api_key=api_keys.get("threads_api_key", ""))
            results["threads"] = "success"
            any_success = True
            _add_log("success", f"Threads投稿成功")
        except Exception as e:
            results["threads"] = f"error: {e}"
            _add_log("error", f"Threads投稿失敗: {e}")

    # 一時ファイルを削除
    if image_path:
        try:
            Path(image_path).unlink(missing_ok=True)
        except Exception:
            pass

    # 投稿成功時に履歴に記録
    if any_success:
        platforms = []
        if results.get("x") == "success":
            platforms.append("x")
        if results.get("threads") == "success":
            platforms.append("threads")
        engagement.record_post(
            post_text=text,
            platform=",".join(platforms),
        )

    return jsonify(results)


# ---------------------------------------------------------------------------
# スケジューラ API
# ---------------------------------------------------------------------------

@app.route("/api/scheduler/status", methods=["GET"])
def scheduler_status():
    """スケジューラの状態を返す。"""
    return jsonify({
        "running": _scheduler_running,
        "logs": _execution_logs[-50:],
    })


@app.route("/api/scheduler/start", methods=["POST"])
def scheduler_start():
    """スケジューラを開始する。"""
    global _scheduler_running, _scheduler_thread
    if _scheduler_running:
        return jsonify({"status": "already_running"})

    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    _add_log("info", "スケジューラ開始")
    return jsonify({"status": "started"})


@app.route("/api/scheduler/stop", methods=["POST"])
def scheduler_stop():
    """スケジューラを停止する。"""
    global _scheduler_running
    _scheduler_running = False
    _add_log("info", "スケジューラ停止")
    return jsonify({"status": "stopped"})


def _scheduler_loop():
    """スケジューラのメインループ。"""
    global _scheduler_running
    import schedule as sched

    sched.clear()
    _setup_schedules(sched)

    while _scheduler_running:
        sched.run_pending()
        time.sleep(10)


def _setup_schedules(sched):
    """config の fixed_times からスケジュールを設定する。"""
    import random
    config = load_config()
    schedule_conf = config.get("schedule", {})
    fixed_times = schedule_conf.get("fixed_times", [])
    jitter = schedule_conf.get("jitter_minutes", 15)
    active_days = schedule_conf.get("active_days", list(range(7)))

    for t in fixed_times:
        sched.every().day.at(t).do(
            _scheduled_post, jitter=jitter, active_days=active_days
        )


def _scheduled_post(jitter: int = 0, active_days: list = None):
    """スケジュール実行時のコールバック。"""
    import random
    now = datetime.now()
    if active_days and now.weekday() not in active_days:
        _add_log("skip", f"今日 ({now.strftime('%A')}) は休止日")
        return

    if jitter > 0:
        delay = random.randint(0, jitter * 60)
        _add_log("info", f"ゆらぎ遅延: {delay // 60}分{delay % 60}秒")
        time.sleep(delay)

    config = load_config()
    try:
        # タイプ選択
        post_type = logic.select_post_type(config.get("post_type", {}))
        _add_log("info", f"投稿タイプ: {post_type}")

        if post_type == "C":
            articles = config.get("note_promotion", {}).get("articles", [])
            if not articles:
                _add_log("skip", "note記事未登録 → スキップ")
                return
            import random as _rnd
            article = _rnd.choice(articles)
            promotion_styles = config.get("note_promotion", {}).get("promotion_styles", [])
            promo_style = logic.select_note_promotion_style(promotion_styles)
            api_keys = config.get("api_keys", {})
            text = logic.generate_note_promotion(
                article=article,
                promotion_style=promo_style,
                persona=config.get("persona", {}).get("generated_text", ""),
                api_key=api_keys.get("gemini_api_key", ""),
                model=api_keys.get("gemini_model", "gemini-2.5-flash"),
            )
        else:
            api_keys = config.get("api_keys", {})
            writing_styles = config.get("prompt_settings", {}).get("writing_styles", [])
            style = logic.select_style_for_type(post_type, writing_styles, config.get("post_type", {}))
            rss_urls = config.get("sources", {}).get("rss_urls", [])
            blacklist = config.get("sources", {}).get("blacklist", [])
            trends = logic.fetch_trends(rss_urls=rss_urls, blacklist=blacklist) if post_type == "A" else []
            text = logic.generate_post(
                style=style,
                trends=trends,
                persona=config.get("persona", {}).get("generated_text", ""),
                guidelines=config.get("prompt_settings", {}).get("writing_guidelines", ""),
                ng_expressions=config.get("prompt_settings", {}).get("ng_expressions", ""),
                api_key=api_keys.get("gemini_api_key", ""),
                model=api_keys.get("gemini_model", "gemini-2.5-flash"),
            )

        _add_log("success", f"生成完了: {text[:40]}...")

        schedule_conf = config.get("schedule", {})
        api_keys = config.get("api_keys", {})
        if schedule_conf.get("post_to_x", True):
            logic.post_to_x(text=text, api_keys=api_keys)
            _add_log("success", "X投稿成功")

        if schedule_conf.get("post_to_threads", False):
            logic.post_to_threads(text=text, api_key=api_keys.get("threads_api_key", ""))
            _add_log("success", "Threads投稿成功")

    except Exception as e:
        _add_log("error", f"投稿失敗: {e}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# エンゲージメント API
# ---------------------------------------------------------------------------

@app.route("/api/engagement/data", methods=["GET"])
def get_engagement_data():
    """エンゲージメントデータを取得する。"""
    try:
        data = engagement.get_post_history()
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e), "data": []}), 200


@app.route("/api/engagement/import", methods=["POST"])
def import_engagement_csv():
    """CSVファイルからエンゲージメントデータをインポートする。"""
    if "file" not in request.files:
        return jsonify({"error": "ファイルが選択されていません"}), 400
    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error": "CSVファイルのみ対応"}), 400
    try:
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
            file.save(tmp)
            tmp_path = tmp.name
        result = engagement.import_csv_auto(tmp_path)
        os.unlink(tmp_path)
        csv_type_label = "投稿単位" if result.get("type") == "content" else "日次概要"
        return jsonify({"status": "ok", "csv_type_label": csv_type_label, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/engagement/analyze", methods=["POST"])
def analyze_engagement():
    """エンゲージメントデータをAIで分析する。"""
    config = load_config()
    api_keys = config.get("api_keys", {})
    try:
        analysis = engagement.analyze_engagement_trends(
            api_key=api_keys.get("gemini_api_key", ""),
            model=api_keys.get("gemini_model", "gemini-2.5-flash"),
        )
        # 分析結果をキャッシュに保存
        engagement.save_analysis_cache(analysis)
        return jsonify({"analysis": analysis})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/engagement/analysis-cache", methods=["GET"])
def get_analysis_cache():
    """保存されたAI分析結果を返す。"""
    try:
        cache = engagement.load_analysis_cache()
        return jsonify(cache)
    except Exception:
        return jsonify({})


@app.route("/api/engagement/summary", methods=["GET"])
def engagement_summary():
    """エンゲージメントデータのサマリーを返す（ダッシュボード用）。"""
    try:
        summary = engagement.get_history_summary()
        return jsonify(summary)
    except Exception:
        return jsonify({"total_posts": 0, "avg_likes": 0, "avg_impressions": 0, "best_likes": 0})


@app.route("/api/dashboard/stats", methods=["GET"])
def dashboard_stats():
    """ダッシュボード用: 今日の投稿数と最近の投稿を返す。"""
    try:
        stats = engagement.get_dashboard_stats()
        return jsonify(stats)
    except Exception:
        return jsonify({"today_count": 0, "recent_posts": []})


# ---------------------------------------------------------------------------
# note 記事 API
# ---------------------------------------------------------------------------

@app.route("/api/note/fetch", methods=["POST"])
def fetch_note_articles():
    """note.com から記事一覧を取得し、キャッシュに保存する。"""
    data = request.get_json() or {}
    note_url = data.get("note_url", "")
    if not note_url:
        return jsonify({"error": "note URL が指定されていません"}), 400
    try:
        articles = logic.fetch_note_articles(note_url)
        # キャッシュに保存
        import json
        cache_path = _PROJECT_ROOT / "note_cache.json"
        cache_data = {"articles": articles, "fetched_at": time.time(), "note_url": note_url}
        cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify({"articles": articles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/note/cache", methods=["GET"])
def get_note_cache():
    """保存済みのnote記事キャッシュを返す。"""
    import json
    cache_path = _PROJECT_ROOT / "note_cache.json"
    if not cache_path.exists():
        return jsonify({"articles": []})
    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        return jsonify(cache_data)
    except Exception:
        return jsonify({"articles": []})


# ---------------------------------------------------------------------------
# ペルソナ API
# ---------------------------------------------------------------------------

@app.route("/api/persona/generate", methods=["POST"])
def generate_persona():
    """ペルソナの要素からペルソナテキストを自動生成する。"""
    config = load_config()
    persona = config.get("persona", {})
    api_keys = config.get("api_keys", {})
    try:
        text = logic.generate_persona(
            age=persona.get("age", ""),
            occupation=persona.get("occupation", ""),
            hobbies=persona.get("hobbies", ""),
            personality=persona.get("personality", ""),
            api_key=api_keys.get("gemini_api_key", ""),
            model=api_keys.get("gemini_model", "gemini-2.5-flash"),
            gender=persona.get("gender", ""),
            background=persona.get("background", ""),
            first_person=persona.get("first_person", ""),
            speech_style=persona.get("speech_style", ""),
            other=persona.get("other", ""),
        )
        return jsonify({"generated_text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/persona/suggest-keywords", methods=["POST"])
def suggest_rss_keywords():
    """ペルソナからRSSキーワードを提案する。"""
    config = load_config()
    persona = config.get("persona", {})
    api_keys = config.get("api_keys", {})
    persona_info = persona.get("generated_text", "")
    if not persona_info:
        # generated_text がなければ要素から組み立て
        parts = [f"{k}: {v}" for k, v in persona.items() if v and k != "generated_text"]
        persona_info = "\n".join(parts)
    try:
        keywords = logic.suggest_keywords_from_persona(
            persona_info=persona_info,
            api_key=api_keys.get("gemini_api_key", ""),
            model=api_keys.get("gemini_model", "gemini-2.5-flash"),
        )
        return jsonify({"keywords": keywords})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# ユーティリティ API
# ---------------------------------------------------------------------------

@app.route("/api/status", methods=["GET"])
def api_status():
    """API接続状態を確認する。"""
    config = load_config()
    api_keys = config.get("api_keys", {})
    return jsonify({
        "gemini": bool(api_keys.get("gemini_api_key")),
        "x": bool(api_keys.get("x_api_key") and api_keys.get("x_access_token")),
        "threads": bool(api_keys.get("threads_api_key")),
        "scheduler": _scheduler_running,
    })


@app.route("/api/logs", methods=["GET"])
def get_logs():
    """実行ログを取得する。"""
    count = request.args.get("count", 50, type=int)
    return jsonify({"logs": _execution_logs[-count:]})


# ---------------------------------------------------------------------------
# API 接続テスト
# ---------------------------------------------------------------------------

@app.route("/api/test-connections", methods=["POST"])
def test_connections():
    """全API（Gemini / X / Threads）の接続テストを実行する。"""
    config = load_config()
    api_keys = config.get("api_keys", {})
    results = []

    # Gemini
    model = api_keys.get("gemini_model", "gemini-2.5-flash")
    ok, msg = logic.test_gemini_connection(api_keys.get("gemini_api_key", ""), model)
    results.append({"service": "gemini", "ok": ok, "message": msg})

    # X
    ok_x, msg_x = logic.test_x_connection(api_keys)
    results.append({"service": "x", "ok": ok_x, "message": msg_x})

    # Threads
    ok_t, msg_t = logic.test_threads_connection(api_keys.get("threads_api_key", ""))
    results.append({"service": "threads", "ok": ok_t, "message": msg_t})

    return jsonify({"results": results})


# ---------------------------------------------------------------------------
# Threads トークン更新
# ---------------------------------------------------------------------------

@app.route("/api/threads/refresh-token", methods=["POST"])
def refresh_threads_token_api():
    """Threads アクセストークンを長期トークンに更新する。"""
    config = load_config()
    api_keys = config.get("api_keys", {})
    token = api_keys.get("threads_api_key", "")
    if not token:
        return jsonify({"error": "Threads トークンが未設定です"}), 400
    try:
        result = logic.refresh_threads_token(token)
        new_token = result["access_token"]
        # 設定を更新
        api_keys["threads_api_key"] = new_token
        config.setdefault("schedule", {})["threads_token_issued"] = int(time.time())
        save_config(config)
        expires_days = result.get("expires_in", 0) // 86400
        return jsonify({
            "message": f"✅ トークン更新完了（有効期限: {expires_days}日）",
            "expires_days": expires_days,
        })
    except Exception as e:
        safe_msg = str(e)
        if token and token in safe_msg:
            safe_msg = safe_msg.replace(token, "***")
        return jsonify({"error": safe_msg}), 500


# ---------------------------------------------------------------------------
# キーワード → RSS URL 変換
# ---------------------------------------------------------------------------

@app.route("/api/keywords-to-rss", methods=["POST"])
def keywords_to_rss():
    """キーワードリストを Google News RSS URL に変換する。"""
    data = request.get_json() or {}
    keywords = data.get("keywords", [])
    if not keywords:
        return jsonify({"error": "キーワードが指定されていません"}), 400
    urls = logic.keywords_to_rss_urls(keywords)
    return jsonify({"urls": urls})
