"""
ui_components.py — 5 タブの UI 定義（customtkinter ベース）

各タブは CTkFrame を継承し、config dict との読み書きを行う。
"""

from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable

import customtkinter as ctk
from tkinter import filedialog


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

# grid() に渡すべきレイアウト用キーワード
_GRID_KEYS = {"row", "column", "columnspan", "rowspan", "padx", "pady", "sticky", "in_"}


# ---------------------------------------------------------------------------
# Undo / Redo ヘルパー
# ---------------------------------------------------------------------------

def _enable_entry_undo(entry: ctk.CTkEntry) -> None:
    """CTkEntry に Ctrl+Z / Ctrl+Y の Undo/Redo を追加する。"""
    undo_stack: list[str] = []
    redo_stack: list[str] = []
    last_value = [entry.get()]  # mutable container for closure

    def _save_state(_event=None):
        current = entry.get()
        if current != last_value[0]:
            undo_stack.append(last_value[0])
            redo_stack.clear()
            last_value[0] = current

    def _undo(_event=None):
        if undo_stack:
            redo_stack.append(entry.get())
            value = undo_stack.pop()
            entry.delete(0, "end")
            entry.insert(0, value)
            last_value[0] = value
        return "break"

    def _redo(_event=None):
        if redo_stack:
            undo_stack.append(entry.get())
            value = redo_stack.pop()
            entry.delete(0, "end")
            entry.insert(0, value)
            last_value[0] = value
        return "break"

    entry.bind("<KeyRelease>", _save_state, add="+")
    entry.bind("<Control-z>", _undo)
    entry.bind("<Control-y>", _redo)


def _enable_textbox_redo(tb: ctk.CTkTextbox) -> None:
    """CTkTextbox に Ctrl+Y の Redo を追加する（Ctrl+Z は undo=True で既に動作）。"""
    def _redo(_event=None):
        try:
            tb.edit_redo()
        except tk.TclError:
            pass  # redo スタックが空
        return "break"

    def _undo(_event=None):
        try:
            tb.edit_undo()
        except tk.TclError:
            pass  # undo スタックが空
        return "break"

    tb.bind("<Control-z>", _undo)
    tb.bind("<Control-y>", _redo)


def _split_grid_kw(kw: dict) -> tuple[dict, dict]:
    """kw を (grid用, ウィジェット用) に分離して返す。"""
    grid_kw = {k: v for k, v in kw.items() if k in _GRID_KEYS}
    widget_kw = {k: v for k, v in kw.items() if k not in _GRID_KEYS}
    return grid_kw, widget_kw


def _make_label(parent: ctk.CTkFrame, text: str, row: int, col: int = 0, **kw):
    grid_kw, widget_kw = _split_grid_kw(kw)
    label = ctk.CTkLabel(parent, text=text, anchor="w", **widget_kw)
    label.grid(row=row, column=col, padx=10, pady=(8, 2), sticky="w", **grid_kw)
    return label


def _make_entry(parent: ctk.CTkFrame, row: int, col: int = 1, show: str = "",
                width: int = 400, **kw) -> ctk.CTkEntry:
    grid_kw, widget_kw = _split_grid_kw(kw)
    entry = ctk.CTkEntry(parent, width=width, show=show if show else None, **widget_kw)
    entry.grid(row=row, column=col, padx=10, pady=(8, 2), sticky="ew", **grid_kw)
    _enable_entry_undo(entry)
    return entry


def _make_textbox(parent: ctk.CTkFrame, height: int = 200, **kw) -> ctk.CTkTextbox:
    grid_kw, widget_kw = _split_grid_kw(kw)
    tb = ctk.CTkTextbox(parent, height=height, wrap="word", undo=True, **widget_kw)
    _enable_textbox_redo(tb)
    return tb


def _set_textbox(tb: ctk.CTkTextbox, text: str):
    """テキストボックスの内容を置換する。"""
    tb.delete("1.0", "end")
    tb.insert("1.0", text)


def _get_textbox(tb: ctk.CTkTextbox) -> str:
    return tb.get("1.0", "end").strip()


# =====================================================================
# 1. API設定タブ
# =====================================================================

# Gemini モデル選択肢
_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-flash"]


class ApiSettingsTab(ctk.CTkFrame):
    """Gemini / X (4キー) / Threads の APIキー入力・保存。

    3つのセクション（Gemini / X / Threads）に分けて表示。
    伏字キーは 👁 ボタンで表示/非表示を切り替える。
    """

    def __init__(self, parent, config: dict, save_callback: Callable):
        super().__init__(parent)
        self.config = config
        self.save_callback = save_callback
        self.entries: dict[str, ctk.CTkEntry | ctk.CTkOptionMenu] = {}
        self._toggle_btns: list[tuple[ctk.CTkButton, ctk.CTkEntry]] = []

        self.columnconfigure(0, weight=1)
        api = self.config.get("api_keys", {})

        # ─── 枠1: 🤖 Gemini 設定 ─────────────────
        gemini_frame = ctk.CTkFrame(self)
        gemini_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        gemini_frame.columnconfigure(1, weight=1)

        _make_label(gemini_frame, "🤖 Gemini 設定", row=0,
                    font=ctk.CTkFont(size=14, weight="bold"))

        # Gemini API Key（伏字）
        _make_label(gemini_frame, "API Key", row=1)
        self._add_secret_entry(gemini_frame, "gemini_api_key", api, row=1)

        # Gemini モデル名（プルダウン）
        _make_label(gemini_frame, "モデル名", row=2)
        current_model = api.get("gemini_model", "gemini-2.5-flash")
        model_menu = ctk.CTkOptionMenu(
            gemini_frame, values=_GEMINI_MODELS, width=250,
            font=ctk.CTkFont(size=13),
        )
        model_menu.set(current_model if current_model in _GEMINI_MODELS
                       else _GEMINI_MODELS[0])
        model_menu.grid(row=2, column=1, padx=10, pady=(8, 2), sticky="w")
        self.entries["gemini_model"] = model_menu

        # ─── 枠2: 🐦 X (Twitter) 設定 ─────────────
        x_frame = ctk.CTkFrame(self)
        x_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        x_frame.columnconfigure(1, weight=1)

        _make_label(x_frame, "🐦 X (Twitter) 設定", row=0,
                    font=ctk.CTkFont(size=14, weight="bold"))

        x_fields = [
            ("API Key", "x_api_key"),
            ("API Secret", "x_api_secret"),
            ("Access Token", "x_access_token"),
            ("Access Token Secret", "x_access_token_secret"),
        ]
        for i, (label_text, key) in enumerate(x_fields, start=1):
            _make_label(x_frame, label_text, row=i)
            self._add_secret_entry(x_frame, key, api, row=i)

        # ─── 枠3: 🧵 Threads 設定 ─────────────────
        threads_frame = ctk.CTkFrame(self)
        threads_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        threads_frame.columnconfigure(1, weight=1)

        _make_label(threads_frame, "🧵 Threads 設定", row=0,
                    font=ctk.CTkFont(size=14, weight="bold"))

        _make_label(threads_frame, "API Key", row=1)
        self._add_secret_entry(threads_frame, "threads_api_key", api, row=1)

        # ─── テスト & 保存ボタン ──────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=3, column=0, pady=10)

        btn = ctk.CTkButton(btn_frame, text="💾 保存", command=self._save, width=200,
                            height=40, font=ctk.CTkFont(size=14))
        btn.pack(side="left", padx=(0, 15))

        self.test_btn = ctk.CTkButton(
            btn_frame, text="🔌 接続テスト", command=self._run_test, width=200,
            height=40, font=ctk.CTkFont(size=14),
            fg_color="#6C3FB5", hover_color="#8B5BD5",
        )
        self.test_btn.pack(side="left")

        # テスト結果表示
        self.test_result = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12),
            wraplength=600, justify="left",
        )
        self.test_result.grid(row=4, column=0, padx=15, pady=(0, 10), sticky="w")

    def _add_secret_entry(self, parent_frame: ctk.CTkFrame, key: str,
                          api: dict, row: int):
        """伏字エントリ + 👁 トグルボタンを配置するヘルパー。"""
        entry = ctk.CTkEntry(parent_frame, width=400, show="*")
        entry.grid(row=row, column=1, padx=(10, 5), pady=(8, 2), sticky="ew")
        entry.insert(0, api.get(key, ""))

        toggle_btn = ctk.CTkButton(
            parent_frame, text="👁", width=36, height=28,
            font=ctk.CTkFont(size=14),
            fg_color="transparent", hover_color="#444444",
            border_width=1, border_color="#555555",
            command=lambda e=entry: self._toggle_show(e),
        )
        toggle_btn.grid(row=row, column=2, padx=(0, 10), pady=(8, 2))
        self._toggle_btns.append((toggle_btn, entry))
        self.entries[key] = entry

    @staticmethod
    def _toggle_show(entry: ctk.CTkEntry):
        """伏字と平文を切り替える。"""
        current = entry.cget("show")
        entry.configure(show="" if current else "*")

    def _save(self):
        for key, widget in self.entries.items():
            self.config["api_keys"][key] = widget.get()
        self.save_callback()

    def _run_test(self):
        """全APIの接続テストを実行する（バックグラウンド）。"""
        self.test_btn.configure(state="disabled", text="⏳ テスト中...")
        self.test_result.configure(text="テスト実行中...", text_color="gray")

        def _run():
            from logic import (test_gemini_connection, test_x_connection,
                              test_threads_connection)

            # 現在のエントリから値を取得
            api = {}
            for key, widget in self.entries.items():
                api[key] = widget.get()

            results = []

            # Gemini テスト
            model = api.get("gemini_model", "gemini-2.5-flash")
            ok, msg = test_gemini_connection(api.get("gemini_api_key", ""), model)
            results.append(f"🤖 Gemini: {msg}")

            # X テスト
            ok_x, msg_x = test_x_connection(api)
            results.append(f"🐦 X: {msg_x}")

            # Threads テスト
            ok_t, msg_t = test_threads_connection(api.get("threads_api_key", ""))
            results.append(f"🧵 Threads: {msg_t}")

            result_text = "\n".join(results)
            all_ok = all("✅" in r for r in results)

            def _update():
                self.test_result.configure(
                    text=result_text,
                    text_color="#2D8C46" if all_ok else "#FFAA00",
                )
                self.test_btn.configure(state="normal", text="🔌 接続テスト")

            self.after(0, _update)

        threading.Thread(target=_run, daemon=True).start()


# =====================================================================
# 2. ペルソナ設定タブ
# =====================================================================

class PersonaTab(ctk.CTkFrame):
    """年齢/職業/趣味/性格/その他 入力 + 自動生成 + テキストエリア編集・保存。

    初期値は空。プレースホルダーで入力例を表示。
    """

    def __init__(self, parent, config: dict, save_callback: Callable):
        super().__init__(parent)
        self.config = config
        self.save_callback = save_callback
        self.entries: dict[str, ctk.CTkEntry] = {}

        self.columnconfigure(1, weight=1)

        persona = self.config.get("persona", {})

        # (ラベル, configキー, プレースホルダー)
        fields = [
            ("性別", "gender", "例: 男性 / 女性 / その他"),
            ("年齢", "age", "例: 30代"),
            ("職業", "occupation", "例: IT業界の営業職"),
            ("経歴", "background", "例: 前職はアニメ制作進行、適応障害で退職"),
            ("趣味", "hobbies", "例: 筋トレ、投資、読書"),
            ("性格", "personality", "例: 冷静で分析的、皮肉っぽいが優しい"),
            ("一人称", "first_person", "例: 俺 / 僕 / 私 / 自分"),
            ("口調・語尾", "speech_style", "例: 断定口調、体言止め多用、「〜だな」"),
            ("その他", "other", "例: 猫を飼っている"),
        ]

        for i, (label_text, key, placeholder) in enumerate(fields):
            _make_label(self, label_text, row=i)
            entry = ctk.CTkEntry(self, width=400, placeholder_text=placeholder)
            entry.grid(row=i, column=1, padx=10, pady=(8, 2), sticky="ew")
            _enable_entry_undo(entry)
            # 既存の保存値があれば入力
            saved_val = persona.get(key, "")
            if saved_val:
                entry.insert(0, saved_val)
            self.entries[key] = entry

        # 自動生成ボタン
        self.gen_btn = ctk.CTkButton(
            self, text="🤖 ペルソナ自動生成（Gemini）", command=self._generate,
            width=280, height=40, font=ctk.CTkFont(size=14),
            fg_color="#6C3FB5", hover_color="#8B5BD5",
        )
        self.gen_btn.grid(row=len(fields), column=0, columnspan=2, pady=10)

        # 生成されたペルソナのテキストエリア
        _make_label(self, "ペルソナ設定文（手動編集可）", row=len(fields) + 1, columnspan=2)
        self.persona_text = _make_textbox(self, height=300)
        self.persona_text.grid(row=len(fields) + 2, column=0, columnspan=2,
                               padx=10, pady=5, sticky="nsew")
        self.rowconfigure(len(fields) + 2, weight=1)

        # 既存値があれば表示、なければプレースホルダー（グレーアウト）
        self._placeholder_text = (
            "※ここにAIが自動生成したペルソナのプロンプトが表示されます。\n"
            "手動での直接入力・修正も可能です。\n\n"
            "上のフィールドに情報を入力して「🤖 ペルソナ自動生成」ボタンを\n"
            "押すと、AIが詳細なキャラクター設定を自動で作成します。"
        )
        self._placeholder_active = False

        saved_text = persona.get("generated_text", "")
        if saved_text:
            _set_textbox(self.persona_text, saved_text)
        else:
            self._show_placeholder()

        # フォーカスイベントでプレースホルダーを制御
        self.persona_text.bind("<FocusIn>", self._on_focus_in)
        self.persona_text.bind("<FocusOut>", self._on_focus_out)

        # 保存ボタン
        btn = ctk.CTkButton(self, text="💾 保存", command=self._save, width=200,
                            height=40, font=ctk.CTkFont(size=14))
        btn.grid(row=len(fields) + 3, column=0, columnspan=2, pady=10)

    def _generate(self):
        """Gemini でペルソナを自動生成（バックグラウンドスレッド）。"""
        self.gen_btn.configure(state="disabled", text="⏳ 生成中...")

        def _run():
            try:
                from logic import generate_persona
                api_key = self.config.get("api_keys", {}).get("gemini_api_key", "")
                model = self.config.get("api_keys", {}).get("gemini_model", "gemini-2.5-flash")
                if not api_key:
                    self.after(0, lambda: _set_textbox(
                        self.persona_text, "⚠️ Gemini API Key が設定されていません。API設定タブで入力してください。"))
                    return
                result = generate_persona(
                    gender=self.entries["gender"].get(),
                    age=self.entries["age"].get(),
                    occupation=self.entries["occupation"].get(),
                    background=self.entries["background"].get(),
                    hobbies=self.entries["hobbies"].get(),
                    personality=self.entries["personality"].get(),
                    first_person=self.entries["first_person"].get(),
                    speech_style=self.entries["speech_style"].get(),
                    other=self.entries["other"].get(),
                    api_key=api_key,
                    model=model,
                )
                self.after(0, lambda: self._set_persona_text(result))
            except Exception as e:
                self.after(0, lambda: _set_textbox(
                    self.persona_text, f"⚠️ 生成エラー:\n{e}"))
            finally:
                self.after(0, lambda: self.gen_btn.configure(
                    state="normal", text="🤖 ペルソナ自動生成（Gemini）"))

        threading.Thread(target=_run, daemon=True).start()

    def _set_persona_text(self, text: str):
        """ペルソナテキストを設定し、プレースホルダー状態を解除する。"""
        self._placeholder_active = False
        _set_textbox(self.persona_text, text)
        self.persona_text.configure(text_color=("gray10", "gray90"))

    def _show_placeholder(self):
        """プレースホルダーをグレーアウトで表示する。"""
        self._placeholder_active = True
        self.persona_text.delete("1.0", "end")
        self.persona_text.insert("1.0", self._placeholder_text)
        self.persona_text.configure(text_color="gray")

    def _hide_placeholder(self):
        """プレースホルダーを消す。"""
        if self._placeholder_active:
            self._placeholder_active = False
            self.persona_text.delete("1.0", "end")
            self.persona_text.configure(text_color=("gray10", "gray90"))

    def _on_focus_in(self, _event=None):
        """テキストボックスにフォーカスが当たったらプレースホルダーを消す。"""
        if self._placeholder_active:
            self._hide_placeholder()

    def _on_focus_out(self, _event=None):
        """テキストボックスからフォーカスが外れたら、空ならプレースホルダーを戻す。"""
        content = self.persona_text.get("1.0", "end").strip()
        if not content:
            self._show_placeholder()

    def _save(self):
        persona = self.config.setdefault("persona", {})
        for key, entry in self.entries.items():
            persona[key] = entry.get()
        # プレースホルダー表示中、またはプレースホルダー文と同一の場合は空文字として保存
        raw = _get_textbox(self.persona_text)
        if self._placeholder_active or raw == self._placeholder_text:
            persona["generated_text"] = ""
        else:
            persona["generated_text"] = raw
        self.save_callback()


# =====================================================================
# 3. プロンプト設定タブ
# =====================================================================

class PromptTab(ctk.CTkFrame):
    """書き方の指針 / NG表現 をテキストエリアで編集・保存。"""

    def __init__(self, parent, config: dict, save_callback: Callable):
        super().__init__(parent)
        self.config = config
        self.save_callback = save_callback

        self.columnconfigure(0, weight=1)

        ps = self.config.get("prompt_settings", {})

        # 書き方の指針
        _make_label(self, "📝 書き方の指針（ルール）", row=0, font=ctk.CTkFont(size=14, weight="bold"))
        self.guidelines_text = _make_textbox(self, height=200)
        self.guidelines_text.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        _set_textbox(self.guidelines_text, ps.get("writing_guidelines", ""))
        self.rowconfigure(1, weight=1)

        # NG表現
        _make_label(self, "🚫 NG表現", row=2, font=ctk.CTkFont(size=14, weight="bold"))
        self.ng_text = _make_textbox(self, height=120)
        self.ng_text.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        _set_textbox(self.ng_text, ps.get("ng_expressions", ""))
        self.rowconfigure(3, weight=1)

        # 保存ボタン
        btn = ctk.CTkButton(self, text="💾 保存", command=self._save, width=200,
                            height=40, font=ctk.CTkFont(size=14))
        btn.grid(row=4, column=0, pady=10)

    def _save(self):
        ps = self.config.setdefault("prompt_settings", {})
        ps["writing_guidelines"] = _get_textbox(self.guidelines_text)
        ps["ng_expressions"] = _get_textbox(self.ng_text)
        self.save_callback()


# =====================================================================
# 4. 情報源（ソース）設定タブ
# =====================================================================

class SourcesTab(ctk.CTkFrame):
    """RSS URL の追加・削除、ブラックリストの編集。"""

    def __init__(self, parent, config: dict, save_callback: Callable):
        super().__init__(parent)
        self.config = config
        self.save_callback = save_callback

        self.columnconfigure(0, weight=1)
        sources = self.config.get("sources", {})

        # --- RSS URL リスト ---
        _make_label(self, "🔗 RSS URL リスト", row=0, font=ctk.CTkFont(size=14, weight="bold"))

        # リストボックス風にテキストボックスで表示
        self.rss_listbox = tk.Listbox(self, height=8, font=("Consolas", 11),
                                      selectmode=tk.SINGLE,
                                      bg="#2B2B2B", fg="#DCE4EE",
                                      selectbackground="#4A6FA5",
                                      highlightthickness=0, bd=0,
                                      relief="flat")
        self.rss_listbox.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        self.rowconfigure(1, weight=1)

        for url in sources.get("rss_urls", []):
            self.rss_listbox.insert(tk.END, url)

        # 入力 + ボタン
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        input_frame.columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(input_frame, placeholder_text="新しい RSS URL を入力...")
        self.url_entry.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        add_btn = ctk.CTkButton(input_frame, text="➕ 追加", width=80, command=self._add_url)
        add_btn.grid(row=0, column=1, padx=(0, 5))

        del_btn = ctk.CTkButton(input_frame, text="🗑️ 削除", width=80, command=self._del_url,
                                fg_color="#B33A3A", hover_color="#D44A4A")
        del_btn.grid(row=0, column=2)

        # --- ブラックリスト ---
        _make_label(self, "🚫 除外ワード（カンマ区切り）", row=3,
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.blacklist_text = _make_textbox(self, height=80)
        self.blacklist_text.grid(row=4, column=0, padx=10, pady=5, sticky="ew")
        _set_textbox(self.blacklist_text, ", ".join(sources.get("blacklist", [])))

        # 保存ボタン
        btn = ctk.CTkButton(self, text="💾 保存", command=self._save, width=200,
                            height=40, font=ctk.CTkFont(size=14))
        btn.grid(row=5, column=0, pady=10)

    def _add_url(self):
        url = self.url_entry.get().strip()
        if url:
            self.rss_listbox.insert(tk.END, url)
            self.url_entry.delete(0, "end")

    def _del_url(self):
        sel = self.rss_listbox.curselection()
        if sel:
            self.rss_listbox.delete(sel[0])

    def _save(self):
        sources = self.config.setdefault("sources", {})
        sources["rss_urls"] = list(self.rss_listbox.get(0, tk.END))
        raw = _get_textbox(self.blacklist_text)
        sources["blacklist"] = [w.strip() for w in raw.split(",") if w.strip()]
        self.save_callback()


# =====================================================================
# 5. 実行・スケジュールタブ
# =====================================================================

class ExecutionTab(ctk.CTkFrame):
    """スケジュール設定 + プレビュー＆手動投稿 + 自動運用 + ログ表示。"""

    def __init__(self, parent, config: dict, save_callback: Callable,
                 generate_preview_callback: Callable,
                 post_preview_callback: Callable,
                 start_schedule_callback: Callable,
                 stop_schedule_callback: Callable):
        super().__init__(parent)
        self.config = config
        self.save_callback = save_callback
        self.generate_preview_callback = generate_preview_callback
        self.post_preview_callback = post_preview_callback
        self.start_schedule_callback = start_schedule_callback
        self.stop_schedule_callback = stop_schedule_callback

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # スクロール可能なコンテナ
        sf = ctk.CTkScrollableFrame(self)
        sf.grid(row=0, column=0, sticky="nsew")
        sf.columnconfigure(0, weight=1)

        sched = self.config.get("schedule", {})

        # --- スケジュール設定 ---
        settings_frame = ctk.CTkFrame(sf)
        settings_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        settings_frame.columnconfigure(1, weight=1)

        _make_label(settings_frame, "⏰ スケジュール設定", row=0,
                    font=ctk.CTkFont(size=14, weight="bold"))

        # 実行時刻
        _make_label(settings_frame, "実行時刻（カンマ区切り: 09:00, 18:00）", row=1)
        self.times_entry = ctk.CTkEntry(settings_frame, width=300)
        self.times_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        self.times_entry.insert(0, ", ".join(sched.get("fixed_times", ["09:00", "18:00"])))
        _enable_entry_undo(self.times_entry)

        # 時間的ゆらぎ（Jitter）
        _make_label(settings_frame, "時間的ゆらぎ（分）", row=2)
        jitter_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        jitter_frame.grid(row=2, column=1, padx=10, pady=5, sticky="w")

        self.jitter_entry = ctk.CTkEntry(jitter_frame, width=80)
        self.jitter_entry.pack(side="left", padx=(0, 5))
        self.jitter_entry.insert(0, str(sched.get("jitter_minutes", 15)))
        _enable_entry_undo(self.jitter_entry)

        ctk.CTkLabel(jitter_frame, text="分（0で無効化）").pack(side="left")

        ctk.CTkLabel(settings_frame, text="※ 設定時刻から±0〜ゆらぎ分のランダム遅延を加えてBot検知を回避します",
                     font=ctk.CTkFont(size=11), text_color="gray"
                     ).grid(row=3, column=0, columnspan=2, padx=15, pady=(0, 5), sticky="w")

        # --- 投稿先 ---
        dest_frame = ctk.CTkFrame(sf)
        dest_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

        _make_label(dest_frame, "📮 投稿先", row=0,
                    font=ctk.CTkFont(size=14, weight="bold"))

        self.x_var = ctk.BooleanVar(value=sched.get("post_to_x", True))
        self.threads_var = ctk.BooleanVar(value=sched.get("post_to_threads", False))

        cb_frame = ctk.CTkFrame(dest_frame, fg_color="transparent")
        cb_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        ctk.CTkCheckBox(cb_frame, text="X (Twitter)", variable=self.x_var).pack(
            side="left", padx=(0, 20))
        ctk.CTkCheckBox(cb_frame, text="Threads", variable=self.threads_var).pack(
            side="left")

        # --- 投稿タイプ & noteリンク設定 ---
        type_frame = ctk.CTkFrame(sf)
        type_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        type_frame.columnconfigure(1, weight=1)

        _make_label(type_frame, "📋 投稿タイプ & note導線", row=0,
                    font=ctk.CTkFont(size=14, weight="bold"))

        # A:B:C 比率
        post_type_cfg = self.config.get("post_type", {})
        ratio_frame = ctk.CTkFrame(type_frame, fg_color="transparent")
        ratio_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        ctk.CTkLabel(ratio_frame, text="A:B:C比率",
                     font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 5))
        ctk.CTkLabel(ratio_frame, text="トレンド(A):",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(5, 2))
        self.type_a_entry = ctk.CTkEntry(ratio_frame, width=40)
        self.type_a_entry.pack(side="left", padx=(0, 5))
        self.type_a_entry.insert(0, str(post_type_cfg.get("type_a_ratio", 3)))
        _enable_entry_undo(self.type_a_entry)

        ctk.CTkLabel(ratio_frame, text="独立(B):",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(5, 2))
        self.type_b_entry = ctk.CTkEntry(ratio_frame, width=40)
        self.type_b_entry.pack(side="left", padx=(0, 5))
        self.type_b_entry.insert(0, str(post_type_cfg.get("type_b_ratio", 1)))
        _enable_entry_undo(self.type_b_entry)

        ctk.CTkLabel(ratio_frame, text="note告知(C):",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(5, 2))
        self.type_c_entry = ctk.CTkEntry(ratio_frame, width=40)
        self.type_c_entry.pack(side="left", padx=(0, 5))
        self.type_c_entry.insert(0, str(post_type_cfg.get("type_c_ratio", 1)))
        _enable_entry_undo(self.type_c_entry)

        ctk.CTkLabel(type_frame,
                     text="※ 自動運用時に「A:B:Cの比率」でトレンド連動 / 独立ポスト / note告知をランダム選択します",
                     font=ctk.CTkFont(size=11), text_color="gray"
                     ).grid(row=2, column=0, columnspan=2, padx=15, pady=(0, 5), sticky="w")

        # --- note記事管理 ---
        note_promo_cfg = self.config.get("note_promotion", {})

        note_frame = ctk.CTkFrame(sf)
        note_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        note_frame.columnconfigure(0, weight=1)

        _make_label(note_frame, "📝 note記事管理（タイプC用）", row=0,
                    font=ctk.CTkFont(size=14, weight="bold"))

        ctk.CTkLabel(note_frame,
                     text="※ タイプC選択時、登録した記事からランダムに選び、AIが自然な告知文を生成します",
                     font=ctk.CTkFont(size=11), text_color="gray"
                     ).grid(row=1, column=0, columnspan=2, padx=15, pady=(0, 5), sticky="w")

        # 記事リスト表示エリア
        self._note_articles_frame = ctk.CTkFrame(note_frame, fg_color="transparent")
        self._note_articles_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        self._note_article_widgets: list[dict] = []
        existing_articles = note_promo_cfg.get("articles", [])
        for art in existing_articles:
            self._add_note_article_row(art)

        # 追加ボタン
        add_btn = ctk.CTkButton(
            note_frame, text="＋ 記事を追加", width=140,
            command=self._add_note_article_row,
            font=ctk.CTkFont(size=12),
        )
        add_btn.grid(row=3, column=0, padx=10, pady=5, sticky="w")

        # --- プレビュー＆手動投稿エリア ---
        preview_frame = ctk.CTkFrame(sf)
        preview_frame.grid(row=4, column=0, padx=10, pady=5, sticky="ew")
        preview_frame.columnconfigure(0, weight=1)

        _make_label(preview_frame, "📝 プレビュー＆手動投稿", row=0,
                    font=ctk.CTkFont(size=14, weight="bold"))

        # スタイル選択ドロップダウン
        style_select_frame = ctk.CTkFrame(preview_frame, fg_color="transparent")
        style_select_frame.grid(row=1, column=0, padx=10, pady=(5, 0), sticky="ew")

        ctk.CTkLabel(style_select_frame, text="文体スタイル:",
                     font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))

        styles = self.config.get("prompt_settings", {}).get("writing_styles", [])
        style_names = ["🎲 おまかせ（ランダム）"] + [s["name"] for s in styles]
        self.style_var = ctk.StringVar(value=style_names[0])
        self.style_dropdown = ctk.CTkOptionMenu(
            style_select_frame, variable=self.style_var,
            values=style_names, width=250,
            font=ctk.CTkFont(size=13),
        )
        self.style_dropdown.pack(side="left", padx=(0, 15))

        # note告知として生成チェックボックス
        self.note_promo_var = ctk.BooleanVar(value=False)
        self.note_promo_cb = ctk.CTkCheckBox(
            style_select_frame, text="📝 note告知として生成",
            variable=self.note_promo_var,
            font=ctk.CTkFont(size=12),
        )
        self.note_promo_cb.pack(side="left")

        # 画像添付
        img_frame = ctk.CTkFrame(preview_frame, fg_color="transparent")
        img_frame.grid(row=2, column=0, padx=10, pady=(5, 0), sticky="ew")

        self._selected_image_path: str | None = None

        self.img_select_btn = ctk.CTkButton(
            img_frame, text="🖼️ 画像を添付", command=self._select_image,
            width=140, height=30, font=ctk.CTkFont(size=12),
            fg_color="#666666", hover_color="#888888",
        )
        self.img_select_btn.pack(side="left", padx=(0, 8))

        self.img_label = ctk.CTkLabel(img_frame, text="画像なし",
                                       font=ctk.CTkFont(size=12), text_color="gray")
        self.img_label.pack(side="left", padx=(0, 8))

        self.img_clear_btn = ctk.CTkButton(
            img_frame, text="✕", command=self._clear_image,
            width=30, height=30, font=ctk.CTkFont(size=12),
            fg_color="#B33A3A", hover_color="#D44A4A",
        )
        self.img_clear_btn.pack(side="left", padx=(0, 15))

        ctk.CTkLabel(img_frame, text="ALT:", font=ctk.CTkFont(size=12)).pack(
            side="left", padx=(0, 4))
        self.alt_entry = ctk.CTkEntry(img_frame, width=200,
                                       placeholder_text="画像の説明文（任意）")
        self.alt_entry.pack(side="left")
        _enable_entry_undo(self.alt_entry)

        # ① 生成ボタン + ③ 投稿ボタン を横並び
        preview_btn_frame = ctk.CTkFrame(preview_frame, fg_color="transparent")
        preview_btn_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")

        self.gen_preview_btn = ctk.CTkButton(
            preview_btn_frame, text="📝 サンプル文章を生成",
            command=self._generate_preview, width=220, height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2D8C46", hover_color="#3AAF5A",
        )
        self.gen_preview_btn.pack(side="left", padx=(0, 10))

        self.regen_btn = ctk.CTkButton(
            preview_btn_frame, text="🔄",
            command=self._generate_preview, width=40, height=40,
            font=ctk.CTkFont(size=16),
            fg_color="#555555", hover_color="#777777",
            state="disabled",
        )
        self.regen_btn.pack(side="left", padx=(0, 10))

        self.post_btn = ctk.CTkButton(
            preview_btn_frame, text="🐦 この文章を投稿する",
            command=self._post_preview, width=220, height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1A73E8", hover_color="#4A90E8",
            state="disabled",
        )
        self.post_btn.pack(side="left")

        # ② プレビュー用テキストエリア（編集可能）
        self.preview_text = ctk.CTkTextbox(
            preview_frame, height=160, wrap="word",
            font=ctk.CTkFont(size=13), undo=True,
        )
        self.preview_text.grid(row=4, column=0, padx=10, pady=(0, 2), sticky="nsew")
        _enable_textbox_redo(self.preview_text)
        self.preview_text.insert("1.0",
            "ここに生成されたサンプル文章が表示されます。\n"
            "「📝 サンプル文章を生成」ボタンを押してください。")
        self.preview_text.configure(state="disabled")

        # 文字数カウンター
        self.char_counter = ctk.CTkLabel(
            preview_frame, text="📝 0 / 140 文字",
            font=ctk.CTkFont(size=12), anchor="e",
        )
        self.char_counter.grid(row=5, column=0, padx=15, pady=(0, 5), sticky="e")
        self.preview_text.bind("<KeyRelease>", lambda e: self._update_char_count())

        # --- 自動運用ボタン ---
        auto_frame = ctk.CTkFrame(sf, fg_color="transparent")
        auto_frame.grid(row=5, column=0, padx=10, pady=5, sticky="ew")

        self.start_btn = ctk.CTkButton(
            auto_frame, text="▶️ 自動運用スタート",
            command=self._start_schedule, width=220, height=45,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1A73E8", hover_color="#4A90E8",
        )
        self.start_btn.pack(side="left", padx=(0, 10))

        self.stop_btn = ctk.CTkButton(
            auto_frame, text="⏹️ 停止",
            command=self._stop_schedule, width=120, height=45,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#B33A3A", hover_color="#D44A4A",
            state="disabled",
        )
        self.stop_btn.pack(side="left")

        # 保存ボタン
        save_btn = ctk.CTkButton(auto_frame, text="💾 設定保存", command=self._save,
                                 width=120, height=45, font=ctk.CTkFont(size=14))
        save_btn.pack(side="right")

        # --- ログ表示 ---
        _make_label(sf, "📋 ログ", row=6, font=ctk.CTkFont(size=14, weight="bold"))
        self.log_text = _make_textbox(sf, height=150)
        self.log_text.grid(row=7, column=0, padx=10, pady=(5, 10), sticky="ew")
        self.log_text.configure(state="disabled")

    def append_log(self, message: str):
        """ログエリアにメッセージを追加する（スレッドセーフ）。"""
        def _update():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _update)

    def set_preview_text(self, text: str):
        """プレビューエリアにテキストを設定する（スレッドセーフ）。"""
        def _update():
            self.preview_text.configure(state="normal")
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", text)
            # 編集可能なままにする
            self._update_char_count()
        self.after(0, _update)

    def get_preview_text(self) -> str:
        """プレビューエリアのテキストを取得する。"""
        return self.preview_text.get("1.0", "end").strip()

    def _update_char_count(self):
        """文字数カウンターを更新する。"""
        text = self.preview_text.get("1.0", "end").strip()
        count = len(text)
        self.char_counter.configure(text=f"📝 {count} / 140 文字")
        if count > 140:
            self.char_counter.configure(text_color="#FF4444")
        elif count > 100:
            self.char_counter.configure(text_color="#FFAA00")
        else:
            self.char_counter.configure(text_color="gray")

    def _save(self):
        sched = self.config.setdefault("schedule", {})
        sched["fixed_times"] = [t.strip() for t in self.times_entry.get().split(",") if t.strip()]
        try:
            sched["jitter_minutes"] = int(self.jitter_entry.get())
        except ValueError:
            sched["jitter_minutes"] = 15
        sched["post_to_x"] = self.x_var.get()
        sched["post_to_threads"] = self.threads_var.get()

        # 投稿タイプ A:B:C 比率
        pt = self.config.setdefault("post_type", {})
        try:
            pt["type_a_ratio"] = max(1, int(self.type_a_entry.get()))
        except ValueError:
            pt["type_a_ratio"] = 3
        try:
            pt["type_b_ratio"] = max(1, int(self.type_b_entry.get()))
        except ValueError:
            pt["type_b_ratio"] = 1
        try:
            pt["type_c_ratio"] = max(0, int(self.type_c_entry.get()))
        except ValueError:
            pt["type_c_ratio"] = 1

        # note記事設定
        np = self.config.setdefault("note_promotion", {})
        articles = []
        for w in self._note_article_widgets:
            url = w["url"].get().strip()
            title = w["title"].get().strip()
            summary = w["summary"].get().strip()
            if url or title:  # URLかタイトルがあれば保存
                articles.append({
                    "url": url,
                    "title": title,
                    "summary": summary,
                })
        np["articles"] = articles

        self.save_callback()

    def _add_note_article_row(self, article: dict | None = None):
        """note記事の入力行を追加する。"""
        row_frame = ctk.CTkFrame(self._note_articles_frame, fg_color="transparent")
        row_frame.pack(fill="x", pady=2)

        ctk.CTkLabel(row_frame, text="URL:", font=ctk.CTkFont(size=11),
                     width=40).pack(side="left", padx=(0, 2))
        url_entry = ctk.CTkEntry(row_frame, width=280,
                                 placeholder_text="https://note.com/...")
        url_entry.pack(side="left", padx=(0, 5))

        ctk.CTkLabel(row_frame, text="タイトル:", font=ctk.CTkFont(size=11),
                     width=55).pack(side="left", padx=(0, 2))
        title_entry = ctk.CTkEntry(row_frame, width=180,
                                   placeholder_text="記事タイトル")
        title_entry.pack(side="left", padx=(0, 5))

        ctk.CTkLabel(row_frame, text="概要:", font=ctk.CTkFont(size=11),
                     width=35).pack(side="left", padx=(0, 2))
        summary_entry = ctk.CTkEntry(row_frame, width=180,
                                     placeholder_text="任意")
        summary_entry.pack(side="left", padx=(0, 5))

        widget_info = {
            "frame": row_frame,
            "url": url_entry,
            "title": title_entry,
            "summary": summary_entry,
        }

        # Undo/Redo
        _enable_entry_undo(url_entry)
        _enable_entry_undo(title_entry)
        _enable_entry_undo(summary_entry)

        remove_btn = ctk.CTkButton(
            row_frame, text="✕", width=30, fg_color="gray40",
            hover_color="red",
            command=lambda: self._remove_note_article_row(widget_info),
        )
        remove_btn.pack(side="left", padx=(5, 0))

        # 既存データがあれば入力
        if article:
            url_entry.insert(0, article.get("url", ""))
            title_entry.insert(0, article.get("title", ""))
            summary_entry.insert(0, article.get("summary", ""))

        self._note_article_widgets.append(widget_info)

    def _remove_note_article_row(self, widget_info: dict):
        """note記事の入力行を削除する。"""
        widget_info["frame"].destroy()
        if widget_info in self._note_article_widgets:
            self._note_article_widgets.remove(widget_info)

    def _generate_preview(self):
        """サンプル文章を生成（投稿はしない）。"""
        self._save()
        self.gen_preview_btn.configure(state="disabled", text="⏳ 生成中...")
        self.regen_btn.configure(state="disabled")

        def _done_ok():
            self.gen_preview_btn.configure(state="normal", text="📝 サンプル文章を生成")
            self.regen_btn.configure(state="normal")
            self.post_btn.configure(state="normal")

        def _done_err():
            self.gen_preview_btn.configure(state="normal", text="📝 サンプル文章を生成")
            self.regen_btn.configure(state="normal")
            self.post_btn.configure(state="disabled")

        def _run():
            try:
                self.generate_preview_callback()
                self.after(0, _done_ok)
            except Exception:
                self.after(0, _done_err)

        threading.Thread(target=_run, daemon=True).start()

    def _post_preview(self):
        """プレビューエリアの文章を投稿する。"""
        self.post_btn.configure(state="disabled", text="⏳ 投稿中...")

        def _done_ok():
            # 投稿成功 → ボタンは無効のまま維持（再生成で復帰）
            self.post_btn.configure(state="disabled", text="✅ 投稿済み")

        def _done_err():
            # 投稿失敗 → ボタンを再有効化してリトライ可能にする
            self.post_btn.configure(state="normal", text="🐦 この文章を投稿する")

        def _run():
            try:
                text = self.get_preview_text()
                image_path = self._selected_image_path
                alt_text = self.alt_entry.get().strip() or None
                self.post_preview_callback(text, image_path, alt_text)
                self.after(0, _done_ok)
            except Exception:
                self.after(0, _done_err)

        threading.Thread(target=_run, daemon=True).start()

    def _select_image(self):
        """ファイルダイアログで画像を選択する。"""
        path = filedialog.askopenfilename(
            title="画像を選択",
            filetypes=[
                ("画像ファイル", "*.png *.jpg *.jpeg *.gif *.webp"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if path:
            self._selected_image_path = path
            basename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            self.img_label.configure(text=f"📎 {basename}", text_color="white")

    def _clear_image(self):
        """選択した画像をクリアする。"""
        self._selected_image_path = None
        self.img_label.configure(text="画像なし", text_color="gray")
        self.alt_entry.delete(0, "end")

    def _start_schedule(self):
        self._save()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.start_schedule_callback()

    def _stop_schedule(self):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.stop_schedule_callback()


# =====================================================================
# 使い方ガイド ポップアップ
# =====================================================================

_USAGE_GUIDE_TEXT = """\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📮 Auto-Post 使い方ガイド
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

このアプリは、Googleトレンドや業界ニュースRSSから
最新のトピックを自動取得し、あなたの「ペルソナ」に
なりきった投稿文をAI（Gemini）で生成、
X（Twitter）やThreadsに自動投稿するツールです。

以下の手順で設定を進めてください。


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔑 ステップ1: API設定
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【Gemini API Key】
投稿文の自動生成に使用します。
Google AI Studio（https://aistudio.google.com/）
で無料で取得できます。

  1. Google AI Studio にアクセス
  2. 「Get API Key」をクリック
  3. 取得したキーをコピーして貼り付け

【Gemini モデル名】
通常は「gemini-2.5-flash」のままでOKです。
より高品質な生成を求める場合は
「gemini-2.5-pro」に変更できます。

【X (Twitter) API — 4つのキー】
X に投稿するために必要な4種類の認証情報です。
X Developer Portal（https://developer.x.com/）
で取得します。

  ⚠️ 重要: アプリの権限を「Read and Write」に
  設定してください。「Read Only」では投稿できません。

  必要なキー:
  ・API Key（Consumer Key）
  ・API Secret（Consumer Secret）
  ・Access Token
  ・Access Token Secret

  取得手順:
  1. X Developer Portal でプロジェクトを作成
  2. App の「User authentication settings」で
     Read and Write 権限を有効化
  3. 「Keys and Tokens」タブから4つのキーを取得
  4. それぞれの欄に貼り付けて「保存」

  ※ キーは伏字（*****）で表示されます。
    「👁」ボタンで表示/非表示を切り替えられます。

【Threads API Key】
  Threads への投稿に使用する User Access Token です。
  Meta for Developers
  （https://developers.facebook.com/）で取得できます。

  取得手順:
  1. Meta for Developers でアプリを作成
  2. Threads API を有効化
  3. User Access Token を発行
  4. 「API Key」欄に貼り付けて「保存」


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 ステップ2: ペルソナ設定
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

投稿する際の「キャラクター」を設定します。
AIはこのペルソナになりきって投稿文を作成します。

【基本項目を入力】
  ・年齢: 例）30代、25歳 など
  ・職業: 例）IT業界の営業職、フリーランスデザイナー
  ・趣味: 例）筋トレ、投資、読書、ゲーム
  ・性格: 例）冷静で分析的、ユーモアがある
  ・その他: 例）転職経験3回、猫を飼っている

【自動生成ボタン】
  上記の項目を入力してから
  「🤖 ペルソナ自動生成（Gemini）」ボタンを押すと、
  AIが詳細なキャラクター設定文を自動で作成します。

  生成には数秒〜十数秒かかります。
  生成中はボタンが「⏳ 生成中...」に変わります。

【手動編集】
  生成されたテキストは自由に書き直せます。
  より自分らしい言い回しや、具体的なエピソードを
  追加することで、投稿のリアリティが増します。

  編集後は必ず「💾 保存」を押してください。


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 ステップ3: プロンプト設定
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AIに投稿文を作らせる際の「ルール」を設定します。

【書き方の指針】
  投稿の構成や文体についてのルールです。
  初期値はX(Twitter)で効果的な書き方の
  ベストプラクティスが登録されています。

  例:
  ・冒頭でスクロールを止めるフックを書く
  ・1つのトピックだけに絞って深掘りする
  ・空行で読みやすくする
  ・余韻を残して終わる

  自由にカスタマイズできます。

【NG表現】
  AIが使ってほしくない表現パターンです。
  ・大げさな比喩（ポエム調）
  ・問いかけ（「皆さんは？」など）
  ・教訓・まとめ
  ・ハッシュタグ

  投稿のトーンに合わせて追加・変更してください。


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📡 ステップ4: 情報源（ソース）設定
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

投稿の「ネタ元」となるRSSフィードを管理します。

【RSS URL リスト】
  初期設定では以下が登録されています:
  ・Googleトレンド（ビジネスカテゴリ）
  ・Googleトレンド（テクノロジーカテゴリ）
  ・GameBusiness.jp（ゲーム業界ニュース）

  業界に合わせて追加・変更できます。
  例えば:
  ・ITメディアやTechCrunchのRSS
  ・自分の業界のニュースサイトのRSS
  ・Yahoo!ニュースの特定カテゴリRSS

  💡 スマート入力対応:
  RSS URL だけでなく、通常のブラウザ用 URL
  も入力できます。
  ・Googleトレンドのブラウザ版 URL → RSSに自動変換
  ・一般のニュースサイト URL → RSSフィードを自動検出

  「➕ 追加」でURL追加、
  リストを選択して「🗑️ 削除」で削除できます。

【除外ワード（ブラックリスト）】
  トレンドから除外したいワードをカンマ区切りで
  入力します。エンタメや芸能系のニュースなど、
  ペルソナに合わないトピックをフィルタできます。

  例: ドラマ, 映画, 歌手, 俳優, アイドル


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶️ ステップ5: 実行・スケジュール
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【スケジュール設定】

  実行時刻:
    毎日投稿する時刻をカンマ区切りで指定します。
    例: 09:00, 12:30, 18:00, 22:00

  時間的ゆらぎ（Jitter）:
    設定時刻から0〜指定分のランダム遅延を加えて
    投稿タイミングに自然なバラつきを持たせます。
    Bot検知を回避するための機能です。
    例: 15分のゆらぎ → 18:00〜18:15の間に投稿
    0を設定するとゆらぎ無効（定刻で実行）。

【投稿先チェックボックス】
  ・X (Twitter): チェックで有効化
  ・Threads: チェックで有効化（API Key設定が必要）

【プレビュー＆手動投稿】

  📝 サンプル文章を生成:
    トレンド取得〜AI生成までを実行し、
    結果をプレビューエリアに表示します。
    ※ この時点ではXへの投稿は行われません。

  プレビューエリア:
    生成された文章が表示されます。
    ここで自由にテキストを手直し（編集）できます。

  🐦 この文章を投稿する:
    プレビューエリアの文章をXやThreadsに投稿します。
    サンプル生成後にのみ押せるようになります。
    ⚠️ 投稿前にプレビューをよく確認してください。

【自動運用】

  ▶️ 自動運用スタート:
    設定したスケジュールで自動投稿を開始します。

    ⚠️ 重要: 自動運用中はアプリを起動したまま
    にしてください。アプリを閉じるとスケジュールが
    停止します。

    PCのスリープ設定にもご注意ください。
    スリープ中は投稿が実行されません。

  ⏹️ 停止:
    自動運用を停止します。

【ログエリア】
  投稿の実行状況がリアルタイムで表示されます。
  ・トレンド取得結果
  ・選択されたスタイル
  ・生成された投稿文
  ・投稿の成功/失敗


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 Tips
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

・各タブで設定変更後は「💾 保存」を忘れずに。
・設定は config.json に保存されます。
・APIキーは伏字で保存されますが、
  config.json には平文で記録されます。
  ファイルの取り扱いにご注意ください。
・最初は「📝 サンプル文章を生成」で内容を確認し、
  納得してから「🐦 この文章を投稿する」を押す
  のがおすすめです。
・アプリを閉じて再起動すると、
  前回最後に開いていたタブが自動で復帰されます。
"""


# シングルトン制御用
_guide_window_ref: ctk.CTkToplevel | None = None


def show_usage_guide(parent):
    """使い方ガイドのモードレスウィンドウを表示する。

    既に開いている場合は最前面に出す（シングルトン）。
    """
    global _guide_window_ref

    # 既存ウィンドウが生きていればフォーカスを当てるだけ
    if _guide_window_ref is not None and _guide_window_ref.winfo_exists():
        _guide_window_ref.lift()
        _guide_window_ref.focus_force()
        return

    guide_window = ctk.CTkToplevel(parent)
    guide_window.title("📖 使い方ガイド — Auto-Post")
    guide_window.geometry("650x700")
    guide_window.minsize(500, 400)

    # モードレス: transient のみ。grab_set() は呼ばない
    guide_window.transient(parent)

    # ウィンドウ破棄時に参照をクリア
    def _on_close():
        global _guide_window_ref
        _guide_window_ref = None
        guide_window.destroy()

    guide_window.protocol("WM_DELETE_WINDOW", _on_close)

    # テキスト表示
    text_box = ctk.CTkTextbox(
        guide_window, wrap="word",
        font=ctk.CTkFont(family="Meiryo UI", size=13),
    )
    text_box.pack(fill="both", expand=True, padx=15, pady=(15, 5))
    text_box.insert("1.0", _USAGE_GUIDE_TEXT)
    text_box.configure(state="disabled")

    # 閉じるボタン
    close_btn = ctk.CTkButton(
        guide_window, text="✕ 閉じる", command=_on_close,
        width=150, height=38, font=ctk.CTkFont(size=13),
    )
    close_btn.pack(pady=(5, 15))

    _guide_window_ref = guide_window
