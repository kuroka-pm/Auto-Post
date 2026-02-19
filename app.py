"""
app.py — 自動投稿デスクトップアプリ エントリポイント

customtkinter + CTkTabview による 5 タブ構成 GUI。
schedule + threading でバックグラウンドスケジュール実行。
"""

from __future__ import annotations

import datetime
import os
import random
import threading
import time

import customtkinter as ctk
import schedule

from config_manager import load_config, save_config
from logic import (
    fetch_trends,
    generate_note_promotion,
    generate_post,
    post_to_x,
    post_to_threads,
    sanitize_post,
    select_note_promotion_style,
    select_post_type,
    select_style,
    select_style_for_type,
)
from ui_components import (
    ApiSettingsTab,
    ExecutionTab,
    PersonaTab,
    PromptTab,
    SourcesTab,
    show_usage_guide,
)


# ---------------------------------------------------------------------------
# アプリケーション
# ---------------------------------------------------------------------------


def _sanitize_error(error: Exception, api_keys: dict) -> str:
    """エラーメッセージからAPIキーをマスクして漏洩を防ぐ。"""
    msg = str(error)
    for key_field in ("x_api_key", "x_api_secret", "x_access_token",
                      "x_access_token_secret", "gemini_api_key", "threads_api_key"):
        val = api_keys.get(key_field, "")
        if val and val in msg:
            msg = msg.replace(val, "***")
    return msg


def _threads_error_hint(error: Exception) -> str:
    """Threads エラーにユーザー向けの解決ヒントを付与する。"""
    msg = str(error)
    if "API access blocked" in msg or "OAuthException" in msg:
        return (
            f"{msg}\n"
            "    💡 ヒント: Threads API のアクセスがブロックされています。\n"
            "    • Meta 開発者ダッシュボードでアプリのステータスを確認してください\n"
            "    • threads_basic / threads_content_publish の権限が必要です\n"
            "    • アプリが「ライブ」モードか確認してください"
        )
    if "expired" in msg.lower() or "token" in msg.lower():
        return (
            f"{msg}\n"
            "    💡 ヒント: アクセストークンの有効期限が切れている可能性があります。\n"
            "    • Meta 開発者ダッシュボードで新しいトークンを発行してください"
        )
    return msg


class AutoPostApp(ctk.CTk):
    """メインウィンドウ。"""

    def __init__(self):
        super().__init__()

        # --- ウィンドウ設定 ---
        self.title("📮 Auto-Post — SNS自動投稿ツール")
        self.geometry("900x700")
        self.minsize(750, 550)

        # テーマ
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # --- 設定読み込み ---
        self.config_data = load_config()

        # --- スケジューラ状態 ---
        self._scheduler_running = False
        self._scheduler_thread: threading.Thread | None = None

        # --- UI 構築 ---
        self._build_ui()

        # --- ログファイル出力 ---
        self._setup_file_logging()

    # ----- UI -----

    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ヘッダー（ガイドボタン）
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=10, pady=(8, 0), sticky="ew")

        guide_btn = ctk.CTkButton(
            header_frame, text="📖 使い方ガイド",
            command=lambda: show_usage_guide(self),
            width=160, height=34, font=ctk.CTkFont(size=13),
            fg_color="#3A3A5C", hover_color="#4E4E7A",
        )
        guide_btn.pack(side="right")

        # タブビュー
        self.tabview = ctk.CTkTabview(self, anchor="nw")
        self.tabview.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nsew")

        tab_names = ["🔑 API設定", "👤 ペルソナ", "📝 プロンプト", "📡 情報源", "▶️ 実行"]
        for name in tab_names:
            self.tabview.add(name)
        self._tab_names = tab_names

        # 各タブにコンポーネントを配置
        self.api_tab = ApiSettingsTab(
            self.tabview.tab("🔑 API設定"), self.config_data, self._save_config)
        self.api_tab.pack(fill="both", expand=True)

        self.persona_tab = PersonaTab(
            self.tabview.tab("👤 ペルソナ"), self.config_data, self._save_config)
        self.persona_tab.pack(fill="both", expand=True)

        self.prompt_tab = PromptTab(
            self.tabview.tab("📝 プロンプト"), self.config_data, self._save_config)
        self.prompt_tab.pack(fill="both", expand=True)

        self.sources_tab = SourcesTab(
            self.tabview.tab("📡 情報源"), self.config_data, self._save_config)
        self.sources_tab.pack(fill="both", expand=True)

        self.exec_tab = ExecutionTab(
            self.tabview.tab("▶️ 実行"), self.config_data, self._save_config,
            generate_preview_callback=self._generate_preview,
            post_preview_callback=self._post_preview,
            start_schedule_callback=self._start_schedule,
            stop_schedule_callback=self._stop_schedule,
        )
        self.exec_tab.pack(fill="both", expand=True)

        # ステータスバー
        self.status_label = ctk.CTkLabel(
            self, text="Ready", anchor="w",
            font=ctk.CTkFont(size=12), text_color="gray")
        self.status_label.grid(row=2, column=0, padx=15, pady=(0, 8), sticky="ew")

        # タブ切り替えコールバック（最後に開いていたタブの記憶）
        self.tabview.configure(command=self._on_tab_changed)

        # 前回のタブを復帰
        last_tab = self.config_data.get("last_tab", "")
        if last_tab and last_tab in self._tab_names:
            try:
                self.tabview.set(last_tab)
            except Exception:
                pass  # 存在しないタブ名なら無視

    # ----- 設定保存 -----

    def _save_config(self):
        save_config(self.config_data)
        self._show_save_toast()

    def _show_save_toast(self):
        """保存完了を目立つ緑色で表示し、3秒後に元に戻す。"""
        self.status_label.configure(
            text="✅ 設定を保存しました！",
            text_color="#2ECC71",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.after(3000, lambda: self.status_label.configure(
            text="Ready", text_color="gray", font=ctk.CTkFont(size=12),
        ))

    def _set_status(self, text: str):
        self.status_label.configure(text=text)

    def _on_tab_changed(self):
        """タブ切替時に選択タブ名を保存する。"""
        current = self.tabview.get()
        self.config_data["last_tab"] = current
        save_config(self.config_data)

    def _setup_file_logging(self):
        """ログをファイルにも出力するよう append_log をラップする。"""
        from config_manager import CONFIG_PATH
        log_dir = CONFIG_PATH.parent / "logs"
        log_dir.mkdir(exist_ok=True)

        today = datetime.date.today().isoformat()
        log_file = log_dir / f"{today}.log"

        original_append_log = self.exec_tab.append_log

        def _wrapped_log(message: str):
            original_append_log(message)
            try:
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] {message}\n")
            except Exception:
                pass  # ファイル書き込み失敗は無視

        self.exec_tab.append_log = _wrapped_log

    # ----- プレビュー生成（投稿しない） -----

    def _generate_preview(self):
        """トレンド取得〜Gemini生成のみ実行し、プレビューに表示する。"""
        log = self.exec_tab.append_log
        cfg = self.config_data
        api = cfg.get("api_keys", {})
        sources = cfg.get("sources", {})
        persona_cfg = cfg.get("persona", {})
        prompt_cfg = cfg.get("prompt_settings", {})

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log(f"\n{'='*50}")
        log(f"📝 プレビュー生成開始: {now}")
        log(f"{'='*50}")

        try:
            gemini_key = api.get("gemini_api_key", "")
            model = api.get("gemini_model", "gemini-2.5-flash")
            if not gemini_key:
                log("⚠️ Gemini API Key が未設定です。API設定タブで入力してください。")
                raise RuntimeError("Gemini API Key未設定")

            persona_text = persona_cfg.get("generated_text", "")
            if "※ここにAIが自動生成した" in persona_text:
                persona_text = ""

            # note告知モード
            if self.exec_tab.note_promo_var.get():
                note_promo_cfg = cfg.get("note_promotion", {})
                articles = note_promo_cfg.get("articles", [])
                if not articles:
                    log("⚠️ note記事が未登録です。情報源タブで記事を追加してください。")
                    raise RuntimeError("note記事未登録")

                article = random.choice(articles)
                promo_styles = note_promo_cfg.get("promotion_styles", [])
                promo_style = select_note_promotion_style(promo_styles)
                log(f"📝 note告知モード: 「{article.get('title', '?')}」")
                log(f"🎨 告知スタイル: {promo_style.get('name', '?')}")
                log("🤖 Gemini で告知文を生成中...")

                raw_post = generate_note_promotion(
                    article=article,
                    promotion_style=promo_style,
                    persona=persona_text,
                    api_key=gemini_key,
                    model=model,
                )
                post = sanitize_post(raw_post)

            else:
                # 通常モード: トレンド連動
                rss_urls = sources.get("rss_urls", [])
                trends = []
                if rss_urls:
                    log("📡 トレンド取得中...")
                    blacklist = sources.get("blacklist", [])
                    trends = fetch_trends(rss_urls, blacklist)
                    if trends:
                        log(f"  ✅ {len(trends)}件のトレンドを取得")
                    else:
                        log("  ⚠️ トレンド取得0件 → ペルソナのみで生成します")
                else:
                    log("📝 トレンドなし → ペルソナのみで生成します")

                styles = prompt_cfg.get("writing_styles", [])
                selected_name = self.exec_tab.style_var.get()
                if selected_name.startswith("🎲"):
                    style = select_style(styles)
                else:
                    style = next((s for s in styles if s["name"] == selected_name), None)
                    if style is None:
                        style = select_style(styles)
                log(f"🎨 スタイル: {style['name']} ({style['char_range']})")

                log("🤖 Gemini で投稿文を生成中...")
                guidelines = prompt_cfg.get("writing_guidelines", "")
                ng = prompt_cfg.get("ng_expressions", "")

                raw_post = generate_post(
                    style=style, trends=trends, persona=persona_text,
                    guidelines=guidelines, ng_expressions=ng,
                    api_key=gemini_key, model=model,
                )
                post = sanitize_post(raw_post)

            log(f"  ✅ 生成完了 ({len(post)} 文字)")
            log("📝 プレビューエリアに表示しました。内容を確認・編集してください。")

            # プレビューエリアに設定
            self.exec_tab.set_preview_text(post)

        except Exception as e:
            log(f"❌ エラー: {e}")
            raise  # ExecutionTab 側で _done_err を呼ぶために再送出

    # ----- プレビューテキストを投稿 -----

    def _post_preview(self, text: str, image_path: str | None = None, alt_text: str | None = None):
        """プレビューエリアのテキストを実際に投稿する。"""
        log = self.exec_tab.append_log
        api = self.config_data.get("api_keys", {})
        sched_cfg = self.config_data.get("schedule", {})

        # 投稿先が1つも選択されていない場合はエラー
        if not sched_cfg.get("post_to_x") and not sched_cfg.get("post_to_threads"):
            log("❌ 投稿先が選択されていません。「投稿先」で X または Threads にチェックを入れてください。")
            raise RuntimeError("投稿先未選択")

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log(f"\n{'='*50}")
        log(f"📮 手動投稿開始: {now}")
        log(f"{'='*50}")
        log(f"投稿文 ({len(text)} 文字):\n{text}\n")
        if image_path:
            log(f"🖼️ 添付画像: {image_path}")
            if alt_text:
                log(f"  ALT: {alt_text}")

        any_success = False

        if sched_cfg.get("post_to_x"):
            log("📮 X に投稿中...")
            try:
                tweet_id = post_to_x(text, api, image_path=image_path, alt_text=alt_text)
                log(f"  ✅ X 投稿成功 (ID: {tweet_id})")
                any_success = True
            except Exception as e:
                log(f"  ❌ X 投稿失敗: {_sanitize_error(e, api)}")

        if sched_cfg.get("post_to_threads"):
            log("📮 Threads に投稿中...")
            try:
                threads_id = post_to_threads(text, api.get("threads_api_key", ""))
                log(f"  ✅ Threads 投稿成功 (ID: {threads_id})")
                any_success = True
            except Exception as e:
                log(f"  ❌ Threads 投稿失敗: {_threads_error_hint(e)}")

        if any_success:
            log("✅ 投稿処理完了")
        else:
            log("❌ すべての投稿先で失敗しました")
            raise RuntimeError("投稿失敗")

    # ----- 自動運用用の一括実行（スケジューラから呼ばれる） -----

    def _run_once(self):
        """投稿パイプラインを 1 回だけ実行する（自動運用用）。"""
        log = self.exec_tab.append_log
        cfg = self.config_data
        api = cfg.get("api_keys", {})
        sources = cfg.get("sources", {})
        persona_cfg = cfg.get("persona", {})
        prompt_cfg = cfg.get("prompt_settings", {})
        sched_cfg = cfg.get("schedule", {})

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log(f"\n{'='*50}")
        log(f"▶ 自動実行: {now}")
        log(f"{'='*50}")

        try:
            # 1. 投稿タイプ選択（A: トレンド連動 / B: 独立 / C: note告知）
            post_type_cfg = cfg.get("post_type", {})
            note_promo_cfg = cfg.get("note_promotion", {})
            post_type = select_post_type(post_type_cfg)

            # note記事が未登録の場合はC→Aにフォールバック
            articles = note_promo_cfg.get("articles", [])
            if post_type == "C" and not articles:
                post_type = "A"
                log("⚠️ note記事未登録のためタイプAに切替")

            type_labels = {"A": "トレンド連動", "B": "独立ポスト", "C": "note告知"}
            log(f"📋 投稿タイプ: {type_labels.get(post_type, '?')}（{post_type}）")

            gemini_key = api.get("gemini_api_key", "")
            model = api.get("gemini_model", "gemini-2.5-flash")
            if not gemini_key:
                log("⚠️ Gemini API Key が未設定です。")
                return

            persona_text = persona_cfg.get("generated_text", "")
            if "※ここにAIが自動生成した" in persona_text:
                persona_text = ""

            if post_type == "C":
                # --- タイプC: note告知 ---
                article = random.choice(articles)
                promo_styles = note_promo_cfg.get("promotion_styles", [])
                promo_style = select_note_promotion_style(promo_styles)
                log(f"📝 note告知: 「{article.get('title', '?')}」")
                log(f"🎨 告知スタイル: {promo_style.get('name', '?')}")
                log("🤖 Gemini で告知文を生成中...")

                raw_post = generate_note_promotion(
                    article=article,
                    promotion_style=promo_style,
                    persona=persona_text,
                    api_key=gemini_key,
                    model=model,
                )
                post = sanitize_post(raw_post)

            else:
                # --- タイプA/B: トレンド連動 / 独立 ---
                # 2. トレンド取得
                trends = []
                rss_urls = sources.get("rss_urls", [])
                if rss_urls:
                    try:
                        log("📡 トレンド取得中...")
                        blacklist = sources.get("blacklist", [])
                        trends = fetch_trends(rss_urls, blacklist)
                        if trends:
                            log(f"  ✅ {len(trends)}件のトレンドを取得")
                        else:
                            log("  ⚠️ トレンド取得0件 → ペルソナのみで生成します")
                    except Exception as e:
                        log(f"  ⚠️ トレンド取得失敗（ペルソナのみで続行）: {e}")
                else:
                    log("📝 トレンドソースなし → ペルソナのみで生成します")

                # 3. スタイル選択
                styles = prompt_cfg.get("writing_styles", [])
                style = select_style_for_type(post_type, styles, post_type_cfg)
                log(f"🎨 スタイル: {style['name']} ({style['char_range']})")

                # 4. 投稿文生成
                log("🤖 Gemini で投稿文を生成中...")
                guidelines = prompt_cfg.get("writing_guidelines", "")
                ng = prompt_cfg.get("ng_expressions", "")

                raw_post = generate_post(
                    style=style, trends=trends, persona=persona_text,
                    guidelines=guidelines, ng_expressions=ng,
                    api_key=gemini_key, model=model,
                )
                post = sanitize_post(raw_post)

            log(f"  ✅ 生成完了 ({len(post)} 文字)")
            log(f"\n--- 生成された投稿 ---\n{post}\n--- ここまで ---\n")

            if sched_cfg.get("post_to_x"):
                log("📮 X に投稿中...")
                try:
                    tweet_id = post_to_x(post, api)
                    log(f"  ✅ X 投稿成功 (ID: {tweet_id})")
                except Exception as e:
                    log(f"  ❌ X 投稿失敗: {_sanitize_error(e, api)}")

            if sched_cfg.get("post_to_threads"):
                log("📮 Threads に投稿中...")
                try:
                    threads_id = post_to_threads(post, api.get("threads_api_key", ""))
                    log(f"  ✅ Threads 投稿成功 (ID: {threads_id})")
                except Exception as e:
                    log(f"  ❌ Threads 投稿失敗: {_threads_error_hint(e)}")

            log("✅ 実行完了")

        except Exception as e:
            log(f"❌ エラー: {_sanitize_error(e, api)}")

    # ----- スケジュール -----

    def _start_schedule(self):
        """schedule ライブラリでバックグラウンドスケジュールを開始。

        固定時刻ベースで、ゆらぎ（jitter）を加えてBot検知を回避する。
        """
        schedule.clear()
        sched_cfg = self.config_data.get("schedule", {})
        times = sched_cfg.get("fixed_times", ["09:00"])
        jitter = sched_cfg.get("jitter_minutes", 15)

        def _jittered_run():
            """ゆらぎ付きで投稿を実行する。"""
            if jitter > 0:
                delay = random.randint(0, jitter * 60)  # 秒単位
                delay_min = delay // 60
                delay_sec = delay % 60
                self.exec_tab.append_log(
                    f"🎲 ゆらぎ遅延: {delay_min}分{delay_sec}秒 待機します...")
                time.sleep(delay)
            self._run_once()

        for t in times:
            schedule.every().day.at(t).do(_jittered_run)
            jitter_str = f"（±{jitter}分のゆらぎ付き）" if jitter > 0 else ""
            self.exec_tab.append_log(f"⏰ スケジュール登録: 毎日 {t}{jitter_str}")

        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        self._set_status("🟢 自動運用中")

    def _stop_schedule(self):
        """スケジュールを停止。"""
        self._scheduler_running = False
        schedule.clear()
        self.exec_tab.append_log("⏹️ 自動運用を停止しました")
        self._set_status("⏹️ 停止中")

    def _scheduler_loop(self):
        """バックグラウンドで schedule.run_pending() を回すループ。"""
        while self._scheduler_running:
            schedule.run_pending()
            time.sleep(1)


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = AutoPostApp()
    app.mainloop()
