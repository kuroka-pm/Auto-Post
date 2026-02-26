/* ==========================================================================
   Auto-Post v2 — メインアプリケーション JS
   ========================================================================== */

const App = {
    config: {},
    currentPage: "dashboard",
};

// ==========================================================================
// ルーティング
// ==========================================================================

App.init = async function () {
    // ナビゲーション
    document.querySelectorAll(".nav-item").forEach((item) => {
        item.addEventListener("click", () => {
            const page = item.dataset.page;
            App.navigateTo(page);
        });
    });

    // 設定タブ
    document.querySelectorAll(".settings-tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".settings-tab").forEach((t) => t.classList.remove("active"));
            document.querySelectorAll(".settings-panel").forEach((p) => p.classList.remove("active"));
            tab.classList.add("active");
            const panel = document.getElementById("settings-" + tab.dataset.settingsTab);
            if (panel) {
                panel.classList.add("active");
                // タブ表示後にテキストエリアを自動リサイズ
                requestAnimationFrame(function () {
                    setTimeout(function () {
                        panel.querySelectorAll("textarea").forEach(function (ta) {
                            if (ta.value) App.autoResize(ta);
                        });
                    }, 0);
                });
            }
        });
    });

    // 初期データ読込
    await App.loadConfig();
    App.settings.load();  // DOM を先に埋めておく（save時の空値上書き防止）
    await App.updateStatus();
    App.navigateTo(localStorage.getItem("autopost_lastPage") || "dashboard");

    // 定期更新
    setInterval(() => App.updateStatus(), 15000);
    setInterval(() => App.scheduler.refreshLogs(), 10000);
};

App.navigateTo = function (page) {
    App.currentPage = page;
    localStorage.setItem("autopost_lastPage", page);

    // ページ切替
    document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
    const target = document.getElementById("page-" + page);
    if (target) target.classList.remove("hidden");

    // サイドバーアクティブ
    document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
    const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (navItem) navItem.classList.add("active");

    // ページ初期化
    if (page === "dashboard") App.dashboard.load();
    if (page === "trends") App.trends.load();
    if (page === "generator") App.generator.load();
    if (page === "scheduler") App.scheduler.load();
    if (page === "analytics") App.analytics.load();
    if (page === "settings") App.settings.load();
};

App.loadConfig = async function () {
    try {
        const res = await fetch("/api/config/raw");
        App.config = await res.json();
    } catch (e) {
        console.error("Config load failed:", e);
    }
};

App.updateStatus = async function () {
    try {
        const res = await fetch("/api/status");
        const status = await res.json();

        const xDot = document.querySelector("#status-x .status-dot");
        const geminiDot = document.querySelector("#status-gemini .status-dot");
        const threadsDot = document.querySelector("#status-threads .status-dot");

        if (xDot) xDot.classList.toggle("connected", status.x);
        if (geminiDot) geminiDot.classList.toggle("connected", status.gemini);
        if (threadsDot) threadsDot.classList.toggle("connected", status.threads);

        // LIVE badge
        const badge = document.getElementById("live-badge");
        if (badge) {
            badge.style.display = status.scheduler ? "inline" : "none";
        }

        // Scheduler buttons
        const startBtn = document.getElementById("btn-scheduler-start");
        const stopBtn = document.getElementById("btn-scheduler-stop");
        if (startBtn && stopBtn) {
            startBtn.classList.toggle("hidden", status.scheduler);
            stopBtn.classList.toggle("hidden", !status.scheduler);
        }
    } catch (e) { /* silent */ }
};

App.toast = function (message, duration = 3000) {
    const existing = document.querySelector(".toast");
    if (existing) existing.remove();

    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), duration);
};

App.api = async function (url, options = {}) {
    const res = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    return res.json();
};

// ==========================================================================
// ダッシュボード
// ==========================================================================

App.dashboard = {};

App.dashboard.load = async function () {
    // KPI 読込
    try {
        const summary = await App.api("/api/engagement/summary");
        document.getElementById("kpi-likes").textContent = App.formatNumber(summary.avg_likes);
        document.getElementById("kpi-impressions").textContent = App.formatNumber(summary.avg_impressions);
    } catch (e) { /* silent */ }

    // ダッシュボード統計（今日の投稿・最近の投稿）
    try {
        const stats = await App.api("/api/dashboard/stats");
        document.getElementById("kpi-today").textContent = stats.today_count || 0;

        const container = document.getElementById("dashboard-recent-posts");
        if (stats.recent_posts && stats.recent_posts.length > 0) {
            container.innerHTML = stats.recent_posts.map(function (p) {
                const platform = p.platform === "x" ? "𝕏" : p.platform === "threads" ? "🔗" : p.platform || "";
                const ts = p.timestamp ? p.timestamp.slice(5, 16) : "";
                return '<div class="recent-post-item">' +
                    '<div class="recent-post-text">' + App.escapeHtml(p.text) + '</div>' +
                    '<div class="recent-post-meta">' +
                    '<span>' + platform + '</span>' +
                    '<span>' + ts + '</span>' +
                    (p.style ? '<span class="tag-sm">' + App.escapeHtml(p.style) + '</span>' : '') +
                    '</div>' +
                    '</div>';
            }).join("");
        } else {
            container.innerHTML = '<div class="empty-state"><span class="empty-icon">📝</span><p>まだ投稿がありません</p></div>';
        }
    } catch (e) {
        document.getElementById("kpi-today").textContent = "0";
    }

    // トレンド読込
    App.dashboard.loadTrends();

    // スケジューラ状態
    const config = App.config;
    const times = (config.schedule || {}).fixed_times || [];
    const now = new Date();
    const currentMinutes = now.getHours() * 60 + now.getMinutes();
    let nextTime = "--:--";
    for (const t of times) {
        const [h, m] = t.split(":").map(Number);
        if (h * 60 + m > currentMinutes) { nextTime = t; break; }
    }
    document.getElementById("kpi-next").textContent = nextTime;
};

App.dashboard.loadTrends = async function () {
    const container = document.getElementById("dashboard-trends");
    try {
        const data = await App.api("/api/trends");
        const trends = data.trends || [];
        if (trends.length === 0) {
            container.innerHTML = '<div class="loading-placeholder">トレンドなし</div>';
            return;
        }
        container.innerHTML = trends.slice(0, 5).map((t, i) =>
            `<div class="trend-item">
        <span class="trend-rank">#${i + 1}</span>
        <span class="trend-name">${App.escapeHtml(typeof t === "string" ? t : t.title || t)}</span>
      </div>`
        ).join("");
    } catch (e) {
        container.innerHTML = '<div class="loading-placeholder">トレンド取得に失敗</div>';
    }
};

// ==========================================================================
// トレンド分析
// ==========================================================================

App.trends = {};
App.trends._data = [];

App.trends.load = async function () {
    if (App.trends._data.length === 0) {
        await App.trends.refresh();
    }
};

App.trends.refresh = async function () {
    const container = document.getElementById("trend-tags");
    container.innerHTML = '<div class="loading-placeholder">トレンドを取得中...</div>';

    try {
        const data = await App.api("/api/trends");
        App.trends._data = data.trends || [];
        App.trends.renderTags();

        // AIおすすめ分析
        if (App.trends._data.length > 0) {
            App.trends.analyzeRecommend();
        }
    } catch (e) {
        container.innerHTML = `<div class="loading-placeholder">エラー: ${e.message}</div>`;
    }
};

App.trends.analyzeRecommend = async function () {
    const container = document.getElementById("ai-recommendation");
    if (!container) return;
    container.innerHTML = '<div class="loading-placeholder">🧠 ペルソナとの相性を分析中...</div>';

    try {
        const trendWords = App.trends._data.map(function (t) { return t.title || t; });
        const data = await App.api("/api/trends/analyze", {
            method: "POST",
            body: JSON.stringify({ trends: trendWords }),
        });
        const analysis = data.analysis || [];
        if (analysis.length === 0) {
            container.innerHTML = '<div class="loading-placeholder">分析結果がありません</div>';
            return;
        }
        container.innerHTML = analysis.map(function (item) {
            const stars = '⭐'.repeat(Math.min(Math.max(Math.round(item.score / 2), 1), 5));
            return '<div class="recommend-item">' +
                '<div class="recommend-trend">' + App.escapeHtml(item.trend) + '</div>' +
                '<div class="recommend-angle">🎯 ' + App.escapeHtml(item.angle) + '</div>' +
                '<div class="recommend-score">' + stars + ' <span>' + item.score + '/10</span></div>' +
                '</div>';
        }).join('');
    } catch (e) {
        container.innerHTML = '<div class="loading-placeholder" style="color:var(--accent-red)">分析失敗: ' + e.message + '</div>';
    }
};

App.trends.renderTags = function () {
    const container = document.getElementById("trend-tags");
    const trends = App.trends._data;
    if (trends.length === 0) {
        container.innerHTML = '<div class="loading-placeholder">トレンドなし</div>';
        return;
    }
    container.innerHTML = '<div class="trend-list-items">' + trends.map((t, i) => {
        const title = t.title || t;
        const sourceUrl = t.source_url || "";
        const sourceName = t.source_name || "";
        const hot = i < 3 ? " hot" : "";
        return `<div class="trend-row${hot}">
            <span class="trend-rank">${i + 1}</span>
            <div class="trend-info">
                <span class="trend-title" onclick="App.trends.selectForGenerate('${App.escapeHtml(title).replace(/'/g, "\\'")}')">${App.escapeHtml(title)}</span>
                ${sourceUrl ? `<a class="trend-source" href="${App.escapeHtml(sourceUrl)}" target="_blank">${App.escapeHtml(sourceName || sourceUrl)}</a>` : ""}
            </div>
            <button class="btn btn-sm trend-remove" onclick="App.trends.removeTrend(${i})" title="削除">✕</button>
        </div>`;
    }).join("") + '</div>';

    // 投稿生成のトレンドセレクトも更新
    App.generator.updateTrendOptions(trends);
};

App.trends.removeTrend = function (index) {
    App.trends._data.splice(index, 1);
    App.trends.renderTags();
};

App.trends.selectForGenerate = function (trend) {
    App.navigateTo("generator");
    const trendSelect = document.getElementById("gen-trend");
    // トレンド選択肢にあれば選択
    for (const opt of trendSelect.options) {
        if (opt.value === trend) { trendSelect.value = trend; break; }
    }
};

// ==========================================================================
// 投稿生成
// ==========================================================================

App.generator = {};

App.generator.load = function () {
    App.generator.updateStyleOptions();
};

App.generator.updateStyleOptions = function () {
    const styles = (App.config.prompt_settings || {}).writing_styles || [];
    const select = document.getElementById("gen-style");
    const current = select.value;
    select.innerHTML = '<option value="">ランダム</option>';
    styles.forEach((s) => {
        const opt = document.createElement("option");
        opt.value = s.name;
        opt.textContent = s.name;
        select.appendChild(opt);
    });
    if (current) select.value = current;
};

App.generator.updateTrendOptions = function (trends) {
    const select = document.getElementById("gen-trend");
    const current = select.value;
    select.innerHTML = '<option value="">自動選択</option>';
    trends.forEach((t) => {
        const name = typeof t === "string" ? t : t.title || t;
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
    });
    if (current) select.value = current;
};

App.generator.generate = async function () {
    const btn = document.getElementById("btn-generate");
    const container = document.getElementById("generated-posts");

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> 生成中...';
    container.innerHTML = '<div class="loading-placeholder">AIが投稿を生成中です...</div>';

    const postType = document.getElementById("gen-post-type").value;
    const style = document.getElementById("gen-style").value;
    const trend = document.getElementById("gen-trend").value;
    const count = parseInt(document.getElementById("gen-count").value);
    const smart = document.getElementById("gen-smart").checked;

    try {
        const data = await App.api("/api/generate", {
            method: "POST",
            body: JSON.stringify({
                post_type: postType,
                style: style || null,
                trend: trend || null,
                count: count,
                smart_analysis: smart,
            }),
        });

        const posts = data.posts || [];
        if (posts.length === 0) {
            container.innerHTML = '<div class="empty-state"><p>生成結果なし</p></div>';
            return;
        }

        container.innerHTML = posts.map((p, i) => {
            if (p.error) {
                return `<div class="post-card"><div class="post-text" style="color:var(--accent-red)">エラー: ${App.escapeHtml(p.error)}</div></div>`;
            }
            const overClass = p.char_count > 140 ? "over" : "";
            return `
        <div class="post-card">
          <div class="post-text" contenteditable="true" id="post-text-${i}">${App.escapeHtml(p.text)}</div>
          <div class="post-image-upload">
            <label class="btn btn-sm btn-outline post-image-label" for="post-image-${i}">🖼️ 画像を追加</label>
            <input type="file" id="post-image-${i}" accept="image/*" style="display:none" onchange="App.generator.previewImage(${i}, event)">
            <input type="text" id="post-alt-${i}" class="form-input post-alt-input" placeholder="ALT テキスト（画像の説明）" style="display:none">
            <div id="post-image-preview-${i}" class="post-image-preview"></div>
          </div>
          <div class="post-meta">
            <span class="post-char-count ${overClass}">${p.char_count}文字</span>
            <div class="post-actions">
              <button class="btn btn-sm btn-outline" onclick="App.generator.copy(${i})">📋 コピー</button>
              <button class="btn btn-sm btn-primary" onclick="App.generator.post(${i})">🐦 投稿</button>
            </div>
          </div>
        </div>`;
        }).join("");
    } catch (e) {
        container.innerHTML = `<div class="empty-state"><p>エラー: ${e.message}</p></div>`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = "⚡ 投稿を生成する";
    }
};

App.generator.copy = function (index) {
    const el = document.getElementById("post-text-" + index);
    if (el) {
        navigator.clipboard.writeText(el.textContent);
        App.toast("📋 コピーしました");
    }
};

App.generator.previewImage = function (index, event) {
    var file = event.target.files[0];
    var preview = document.getElementById("post-image-preview-" + index);
    var altInput = document.getElementById("post-alt-" + index);
    if (!file) {
        preview.innerHTML = "";
        altInput.style.display = "none";
        return;
    }
    var url = URL.createObjectURL(file);
    preview.innerHTML = '<div class="preview-thumb">' +
        '<img src="' + url + '" alt="preview">' +
        '<button class="btn btn-sm btn-outline preview-remove" onclick="App.generator.removeImage(' + index + ')">✕</button>' +
        '</div>';
    altInput.style.display = "block";
};

App.generator.removeImage = function (index) {
    var fileInput = document.getElementById("post-image-" + index);
    var preview = document.getElementById("post-image-preview-" + index);
    var altInput = document.getElementById("post-alt-" + index);
    fileInput.value = "";
    preview.innerHTML = "";
    altInput.style.display = "none";
    altInput.value = "";
};

App.generator.post = async function (index) {
    const el = document.getElementById("post-text-" + index);
    if (!el) return;

    const text = el.textContent;
    const postX = document.getElementById("gen-post-x").checked;
    const postThreads = document.getElementById("gen-post-threads").checked;

    if (!postX && !postThreads) {
        App.toast("⚠️ 投稿先を選択してください");
        return;
    }

    // ボタンを即座に無効化（二重投稿防止）
    const btn = el.closest(".post-card").querySelector(".btn-primary");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = "⏳ 投稿中...";
    }

    try {
        // 画像がある場合は FormData で送信
        var fileInput = document.getElementById("post-image-" + index);
        var altInput = document.getElementById("post-alt-" + index);
        var hasImage = fileInput && fileInput.files && fileInput.files.length > 0;

        var result;
        if (hasImage) {
            var formData = new FormData();
            formData.append("text", text);
            formData.append("post_to_x", postX ? "true" : "false");
            formData.append("post_to_threads", postThreads ? "true" : "false");
            formData.append("image", fileInput.files[0]);
            if (altInput && altInput.value) {
                formData.append("alt_text", altInput.value);
            }
            var resp = await fetch("/api/post", { method: "POST", body: formData });
            if (!resp.ok) {
                var errData = await resp.json().catch(function () { return {}; });
                throw new Error(errData.error || "HTTP " + resp.status);
            }
            result = await resp.json();
        } else {
            result = await App.api("/api/post", {
                method: "POST",
                body: JSON.stringify({
                    text: text,
                    post_to_x: postX,
                    post_to_threads: postThreads,
                }),
            });
        }

        const msgs = [];
        let hasSuccess = false;
        if (result.x === "success") { msgs.push("X ✅"); hasSuccess = true; }
        if (result.threads === "success") { msgs.push("Threads ✅"); hasSuccess = true; }
        if (result.x && result.x.startsWith("error")) msgs.push("X ❌");
        if (result.threads && result.threads.startsWith("error")) msgs.push("Threads ❌");
        App.toast(msgs.join("  "));

        if (btn) {
            if (hasSuccess) {
                btn.innerHTML = "✅ 投稿済み";
                btn.classList.remove("btn-primary");
                btn.classList.add("btn-outline");
            } else {
                // 全失敗時は再試行可能にする
                btn.disabled = false;
                btn.innerHTML = "🐦 投稿";
            }
        }
    } catch (e) {
        App.toast("❌ 投稿失敗: " + e.message);
        // エラー時は再試行可能にする
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = "🐦 投稿";
        }
    }
};

// ==========================================================================
// スケジューラー
// ==========================================================================

App.scheduler = {};

App.scheduler.load = function () {
    App.scheduler.renderCards();
    App.scheduler.renderCalendar();
    App.scheduler.loadSettings();
    App.scheduler.refreshLogs();
};

App.scheduler.renderCards = function () {
    const container = document.getElementById("schedule-cards");
    const times = (App.config.schedule || {}).fixed_times || [];
    const now = new Date();
    const currentMinutes = now.getHours() * 60 + now.getMinutes();

    let foundNext = false;
    const cards = times.map((t, i) => {
        const [h, m] = t.split(":").map(Number);
        const mins = h * 60 + m;
        let status = "waiting";
        let statusLabel = "待機";
        if (mins < currentMinutes) { status = "done"; statusLabel = "✅ 済"; }
        else if (!foundNext) { status = "next"; statusLabel = "⏳ 次回"; foundNext = true; }

        return `
      <div class="schedule-card">
        <button class="schedule-delete" onclick="App.scheduler.removeSlot(${i})">✕</button>
        <div class="schedule-time">${t}</div>
        <div class="schedule-type">ランダム</div>
        <span class="schedule-status ${status}">${statusLabel}</span>
      </div>`;
    }).join("");

    container.innerHTML = cards + `
    <div class="add-schedule-card" onclick="App.scheduler.addSlot()">
      <div style="font-size:1.5rem">+</div>
      <div style="font-size:0.8rem">追加</div>
    </div>`;
};

App.scheduler.renderCalendar = function () {
    const container = document.getElementById("schedule-calendar");
    const times = (App.config.schedule || {}).fixed_times || [];
    const activeDays = (App.config.schedule || {}).active_days || [0, 1, 2, 3, 4, 5, 6];
    const days = ["月", "火", "水", "木", "金", "土", "日"];

    let html = '<div class="cal-header"></div>';
    days.forEach((d) => { html += `<div class="cal-header">${d}</div>`; });

    times.forEach((t) => {
        html += `<div class="cal-time">${t}</div>`;
        for (let d = 0; d < 7; d++) {
            const active = activeDays.includes(d) ? "active" : "";
            html += `<div class="cal-cell ${active}" data-time="${t}" data-day="${d}" onclick="App.scheduler.toggleDay(this)"></div>`;
        }
    });

    container.innerHTML = html;
};

App.scheduler.toggleDay = function (cell) {
    cell.classList.toggle("active");
};

App.scheduler.addSlot = function () {
    const time = prompt("追加する時刻 (HH:MM):", "15:00");
    if (!time || !/^\d{2}:\d{2}$/.test(time)) return;

    const schedule = App.config.schedule || {};
    const times = schedule.fixed_times || [];
    if (!times.includes(time)) {
        times.push(time);
        times.sort();
        schedule.fixed_times = times;
        App.config.schedule = schedule;
        App.scheduler.saveSettings();
        App.scheduler.renderCards();
        App.scheduler.renderCalendar();
    }
};

App.scheduler.removeSlot = function (index) {
    const schedule = App.config.schedule || {};
    const times = schedule.fixed_times || [];
    times.splice(index, 1);
    schedule.fixed_times = times;
    App.config.schedule = schedule;
    App.scheduler.saveSettings();
    App.scheduler.renderCards();
    App.scheduler.renderCalendar();
};

App.scheduler.loadSettings = function () {
    const schedule = App.config.schedule || {};
    const postType = App.config.post_type || {};
    document.getElementById("sched-jitter").value = schedule.jitter_minutes || 15;
    document.getElementById("sched-ratio-a").value = postType.type_a_ratio || 3;
    document.getElementById("sched-ratio-b").value = postType.type_b_ratio || 1;
    document.getElementById("sched-ratio-c").value = postType.type_c_ratio || 1;
    document.getElementById("sched-post-x").checked = schedule.post_to_x !== false;
    document.getElementById("sched-post-threads").checked = !!schedule.post_to_threads;
};

App.scheduler.saveSettings = async function () {
    const schedule = App.config.schedule || {};
    schedule.jitter_minutes = parseInt(document.getElementById("sched-jitter").value) || 15;
    schedule.post_to_x = document.getElementById("sched-post-x").checked;
    schedule.post_to_threads = document.getElementById("sched-post-threads").checked;

    const postType = App.config.post_type || {};
    postType.type_a_ratio = parseInt(document.getElementById("sched-ratio-a").value) || 3;
    postType.type_b_ratio = parseInt(document.getElementById("sched-ratio-b").value) || 1;
    postType.type_c_ratio = parseInt(document.getElementById("sched-ratio-c").value) || 1;

    try {
        await App.api("/api/config/section/schedule", {
            method: "POST",
            body: JSON.stringify(schedule),
        });
        await App.api("/api/config/section/post_type", {
            method: "POST",
            body: JSON.stringify(postType),
        });
        App.toast("💾 設定を保存しました");
    } catch (e) {
        App.toast("❌ 保存失敗: " + e.message);
    }
};

App.scheduler.start = async function () {
    try {
        await App.api("/api/scheduler/start", { method: "POST" });
        App.toast("▶️ スケジューラー開始");
        App.updateStatus();
    } catch (e) {
        App.toast("❌ " + e.message);
    }
};

App.scheduler.stop = async function () {
    try {
        await App.api("/api/scheduler/stop", { method: "POST" });
        App.toast("⏹ スケジューラー停止");
        App.updateStatus();
    } catch (e) {
        App.toast("❌ " + e.message);
    }
};

App.scheduler.refreshLogs = async function () {
    if (App.currentPage !== "scheduler" && App.currentPage !== "dashboard") return;
    try {
        const data = await App.api("/api/logs?count=30");
        const logs = data.logs || [];
        const container = document.getElementById("execution-logs");
        if (!container) return;

        if (logs.length === 0) {
            container.innerHTML = '<div class="log-entry log-info"><span class="log-time">--:--:--</span><span class="log-message">ログなし</span></div>';
            return;
        }

        container.innerHTML = logs.reverse().map((l) =>
            `<div class="log-entry log-${l.level}">
        <span class="log-time">${l.time}</span>
        <span class="log-message">${App.escapeHtml(l.message)}</span>
      </div>`
        ).join("");
    } catch (e) { /* silent */ }
};

// ==========================================================================
// アナリティクス
// ==========================================================================

App.analytics = {};
App.analytics._engData = [];

App.analytics.load = async function () {
    // サマリー KPI
    try {
        const summary = await App.api("/api/engagement/summary");
        document.getElementById("analytics-total").textContent = summary.total_posts;
        document.getElementById("analytics-avg-likes").textContent = summary.avg_likes;
        document.getElementById("analytics-avg-imp").textContent = App.formatNumber(summary.avg_impressions);

        // ベストいいね
        const bestLikes = summary.best_likes || 0;
        document.getElementById("analytics-best").textContent = bestLikes;
    } catch (e) { /* silent */ }

    // エンゲージメントデータ取得
    try {
        const res = await App.api("/api/engagement/data");
        App.analytics._engData = res.data || [];
        App.analytics.renderChart("7");
        App.analytics.renderStyleRanking();
    } catch (e) { /* silent */ }

    // 期間セレクタ
    document.querySelectorAll(".chart-period-selector .btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".chart-period-selector .btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            App.analytics.renderChart(btn.dataset.period);
        });
    });

    // 保存されたAI分析結果を読み込み
    try {
        const cache = await App.api("/api/engagement/analysis-cache");
        if (cache && cache.analysis) {
            const container = document.getElementById("ai-advice");
            container.innerHTML = '<p>' + App.escapeHtml(cache.analysis).replace(/\n/g, "<br>") + '</p>' +
                '<div class="analysis-timestamp">📅 ' + cache.timestamp + ' の分析</div>';
        }
    } catch (e) { /* silent */ }
};

App.analytics.renderChart = function (period) {
    const container = document.getElementById("engagement-chart");
    const data = App.analytics._engData;

    if (!data || data.length === 0) {
        container.innerHTML = '<div class="loading-placeholder">データなし — CSVをインポートしてください</div>';
        return;
    }

    // 日付ごとに集計
    const dailyMap = {};
    data.forEach((p) => {
        if (!p.engagement) return;
        const raw = (p.timestamp || "").trim();
        if (!raw) return;

        // 日付を正規化: "Wed, Feb 25, 2026" or "2026-02-25 12:00:00" → "YYYY-MM-DD"
        let date;
        if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
            date = raw.slice(0, 10); // YYYY-MM-DD
        } else {
            const parsed = new Date(raw);
            if (!isNaN(parsed.getTime())) {
                date = parsed.toISOString().slice(0, 10);
            } else {
                date = raw; // fallback
            }
        }

        if (!dailyMap[date]) {
            dailyMap[date] = { impressions: 0, likes: 0, count: 0 };
        }
        dailyMap[date].impressions += p.engagement.impressions || 0;
        dailyMap[date].likes += p.engagement.likes || 0;
        dailyMap[date].count += 1;
    });

    // 日付順にソート
    let sortedDays = Object.keys(dailyMap).sort();

    // 期間フィルタ
    if (period !== "all") {
        const days = parseInt(period) || 7;
        sortedDays = sortedDays.slice(-days);
    }

    if (sortedDays.length === 0) {
        container.innerHTML = '<div class="loading-placeholder">選択期間にデータがありません</div>';
        return;
    }

    const maxImp = Math.max(...sortedDays.map((d) => dailyMap[d].impressions), 1);

    // 日付を M/D 形式に変換
    function toMD(dateStr) {
        const parts = dateStr.split("-");
        if (parts.length >= 3) {
            return parseInt(parts[1]) + "/" + parseInt(parts[2]);
        }
        return dateStr;
    }

    // バーチャート描画 — 同一スケール(maxImp基準)
    let html = '<div class="eng-chart">';
    sortedDays.forEach((date) => {
        const d = dailyMap[date];
        const impPct = Math.max((d.impressions / maxImp) * 100, 2);
        const likesPct = Math.max((d.likes / maxImp) * 100, d.likes > 0 ? 1 : 0);

        html += `
        <div class="eng-bar-group" title="${date}\nIMP: ${d.impressions.toLocaleString()}\n♥: ${d.likes}\n投稿数: ${d.count}">
            <div class="eng-bar-wrap">
                <div class="eng-bar-imp" style="height:${impPct}%"></div>
                <div class="eng-bar-likes" style="height:${likesPct}%"></div>
            </div>
            <div class="eng-bar-label">${toMD(date)}</div>
        </div>`;
    });
    html += '</div>';

    // 凡例
    html += `<div class="eng-legend">
        <span class="eng-legend-item"><span class="eng-legend-dot imp"></span>インプレッション</span>
        <span class="eng-legend-item"><span class="eng-legend-dot likes"></span>いいね</span>
    </div>`;

    container.innerHTML = html;
};

App.analytics.renderStyleRanking = function () {
    const container = document.getElementById("style-ranking");
    const data = App.analytics._engData;

    // スタイル別集計
    const styleMap = {};
    data.forEach((p) => {
        const style = p.style || "";
        if (!style || !p.engagement) return;
        if (!styleMap[style]) {
            styleMap[style] = { likes: 0, impressions: 0, count: 0 };
        }
        styleMap[style].likes += p.engagement.likes || 0;
        styleMap[style].impressions += p.engagement.impressions || 0;
        styleMap[style].count += 1;
    });

    const styles = Object.entries(styleMap)
        .map(([name, s]) => ({
            name,
            avgLikes: s.count > 0 ? (s.likes / s.count).toFixed(1) : 0,
            avgImp: s.count > 0 ? Math.round(s.impressions / s.count) : 0,
            count: s.count,
        }))
        .sort((a, b) => b.avgLikes - a.avgLikes);

    if (styles.length === 0) {
        container.innerHTML = '<div class="loading-placeholder">データなし</div>';
        return;
    }

    container.innerHTML = styles.map((s, i) => {
        const medal = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `${i + 1}.`;
        return `<div class="style-rank-item">
            <span class="style-rank-medal">${medal}</span>
            <span class="style-rank-name">${App.escapeHtml(s.name)}</span>
            <span class="style-rank-stats">♥${s.avgLikes} / ${App.formatNumber(s.avgImp)}IMP (${s.count}件)</span>
        </div>`;
    }).join("");
};

App.analytics.importCSV = function () {
    const input = document.getElementById("csv-file-input");
    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append("file", file);

        try {
            const res = await fetch("/api/engagement/import", { method: "POST", body: formData });
            const data = await res.json();
            if (data.error) { App.toast("❌ " + data.error); return; }
            const label = data.csv_type_label || "";
            App.toast(`📥 ${label}: ${data.imported}件取込 / ${data.updated}件更新`);
            App.analytics.load();
        } catch (e) {
            App.toast("❌ インポート失敗");
        }
        input.value = "";
    };
    input.click();
};

App.analytics.analyze = async function () {
    const container = document.getElementById("ai-advice");
    container.innerHTML = '<div class="loading-placeholder">🧠 AIが分析中...</div>';

    try {
        const data = await App.api("/api/engagement/analyze", { method: "POST" });
        if (data.error) {
            container.innerHTML = `<p style="color:var(--accent-red)">エラー: ${App.escapeHtml(data.error)}</p>`;
            return;
        }
        container.innerHTML = `<p>${App.escapeHtml(data.analysis).replace(/\n/g, "<br>")}</p>`;
    } catch (e) {
        container.innerHTML = `<p style="color:var(--accent-red)">分析失敗: ${e.message}</p>`;
    }
};

// ==========================================================================
// 設定
// ==========================================================================

App.settings = {};

App.settings.load = function () {
    const c = App.config;
    const api = c.api_keys || {};
    const persona = c.persona || {};
    const prompt = c.prompt_settings || {};
    const sources = c.sources || {};

    // API
    document.getElementById("set-gemini-key").value = api.gemini_api_key || "";
    document.getElementById("set-gemini-model").value = api.gemini_model || "gemini-2.5-flash";
    document.getElementById("set-x-key").value = api.x_api_key || "";
    document.getElementById("set-x-secret").value = api.x_api_secret || "";
    document.getElementById("set-x-token").value = api.x_access_token || "";
    document.getElementById("set-x-token-secret").value = api.x_access_token_secret || "";
    document.getElementById("set-threads-key").value = api.threads_api_key || "";

    // ペルソナ
    document.getElementById("set-persona-gender").value = persona.gender || "";
    document.getElementById("set-persona-age").value = persona.age || "";
    document.getElementById("set-persona-occupation").value = persona.occupation || "";
    document.getElementById("set-persona-first-person").value = persona.first_person || "";
    document.getElementById("set-persona-background").value = persona.background || "";
    document.getElementById("set-persona-hobbies").value = persona.hobbies || "";
    document.getElementById("set-persona-personality").value = persona.personality || "";
    document.getElementById("set-persona-speech").value = persona.speech_style || "";
    document.getElementById("set-persona-other").value = persona.other || "";
    document.getElementById("set-persona-generated").value = persona.generated_text || "";
    // ペルソナ生成テキストエリア — ページ表示後に自動リサイズ
    var personaTextarea = document.getElementById("set-persona-generated");
    personaTextarea.removeEventListener("input", App._personaAutoResizeHandler);
    App._personaAutoResizeHandler = function () { App.autoResize(personaTextarea); };
    personaTextarea.addEventListener("input", App._personaAutoResizeHandler);

    // プロンプト
    document.getElementById("set-writing-guidelines").value = prompt.writing_guidelines || "";
    document.getElementById("set-ng-expressions").value = prompt.ng_expressions || "";

    // プロンプト系テキストエリアも入力時リサイズ
    ["set-writing-guidelines", "set-ng-expressions"].forEach(function (id) {
        var ta = document.getElementById(id);
        var handlerKey = "_autoResize_" + id;
        if (App[handlerKey]) ta.removeEventListener("input", App[handlerKey]);
        App[handlerKey] = function () { App.autoResize(ta); };
        ta.addEventListener("input", App[handlerKey]);
    });

    // 全テキストエリアをページ表示後にリサイズ（hidden解除後にブラウザ再描画を待つ）
    requestAnimationFrame(function () {
        setTimeout(function () {
            ["set-persona-generated", "set-writing-guidelines", "set-ng-expressions"].forEach(function (id) {
                var ta = document.getElementById(id);
                if (ta && ta.value) App.autoResize(ta);
            });
        }, 0);
    });

    // 情報源
    // 情報源リストをレンダリング
    App.settings.renderSourceList();
    document.getElementById("set-blacklist").value = (sources.blacklist || []).join(", ");

    // note
    document.getElementById("set-note-url").value = c.note_url || "";

    // note記事キャッシュを読み込み
    App.settings.loadNoteCache();

    // Threads トークン有効期限表示
    App.settings.updateThreadsExpiry();
};

App.settings.save = async function () {
    const c = App.config;

    c.api_keys = {
        gemini_api_key: document.getElementById("set-gemini-key").value,
        gemini_model: document.getElementById("set-gemini-model").value,
        x_api_key: document.getElementById("set-x-key").value,
        x_api_secret: document.getElementById("set-x-secret").value,
        x_access_token: document.getElementById("set-x-token").value,
        x_access_token_secret: document.getElementById("set-x-token-secret").value,
        threads_api_key: document.getElementById("set-threads-key").value,
    };

    c.persona = {
        gender: document.getElementById("set-persona-gender").value,
        age: document.getElementById("set-persona-age").value,
        occupation: document.getElementById("set-persona-occupation").value,
        first_person: document.getElementById("set-persona-first-person").value,
        background: document.getElementById("set-persona-background").value,
        hobbies: document.getElementById("set-persona-hobbies").value,
        personality: document.getElementById("set-persona-personality").value,
        speech_style: document.getElementById("set-persona-speech").value,
        other: document.getElementById("set-persona-other").value,
        generated_text: document.getElementById("set-persona-generated").value,
    };

    c.prompt_settings = c.prompt_settings || {};
    c.prompt_settings.writing_guidelines = document.getElementById("set-writing-guidelines").value;
    c.prompt_settings.ng_expressions = document.getElementById("set-ng-expressions").value;

    c.sources = c.sources || {};
    c.sources.blacklist = document.getElementById("set-blacklist").value.split(",").map(s => s.trim()).filter(Boolean);
    // rss_sources から rss_urls を同期
    c.sources.rss_urls = (c.sources.rss_sources || []).map(s => s.url);

    c.note_url = document.getElementById("set-note-url").value;

    try {
        await App.api("/api/config", {
            method: "POST",
            body: JSON.stringify(c),
        });
        App.toast("💾 設定を保存しました");
        App.updateStatus();
    } catch (e) {
        App.toast("❌ 保存失敗: " + e.message);
    }
};

App.settings.saveSources = async function () {
    const c = App.config;
    c.sources = c.sources || {};
    c.sources.blacklist = document.getElementById("set-blacklist").value.split(",").map(s => s.trim()).filter(Boolean);
    // rss_sources から rss_urls を同期（バックエンド互換性）
    c.sources.rss_urls = (c.sources.rss_sources || []).map(s => s.url);
    try {
        await App.api("/api/config", {
            method: "POST",
            body: JSON.stringify(c),
        });
        App.toast("💾 ソース設定を保存しました");
    } catch (e) {
        App.toast("❌ 保存失敗: " + e.message);
    }
};

// --- 設定エクスポート / インポート / 初期化 ---

App.settings.exportConfig = function () {
    var json = JSON.stringify(App.config, null, 2);
    var blob = new Blob([json], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "autopost_config_" + new Date().toISOString().slice(0, 10) + ".json";
    a.click();
    URL.revokeObjectURL(a.href);
    App.toast("📤 設定をエクスポートしました");
};

App.settings.importConfig = async function (event) {
    var file = event.target.files[0];
    if (!file) return;
    try {
        var text = await file.text();
        var imported = JSON.parse(text);
        await App.api("/api/config", {
            method: "POST",
            body: JSON.stringify(imported),
        });
        await App.loadConfig();
        App.settings.load();
        App.toast("📥 設定をインポートしました");
    } catch (e) {
        App.toast("❌ インポート失敗: " + e.message);
    }
    event.target.value = "";
};

App.settings.resetConfig = async function () {
    if (!confirm("⚠️ すべての設定を初期状態にリセットします。\nこの操作は取り消せません。よろしいですか？")) return;
    try {
        await App.api("/api/config/reset", { method: "POST" });
        await App.loadConfig();
        App.settings.load();
        App.toast("🔄 設定を初期化しました");
    } catch (e) {
        App.toast("❌ 初期化失敗: " + e.message);
    }
};

App.settings.generatePersona = async function () {
    const textarea = document.getElementById("set-persona-generated");
    textarea.value = "🧠 AIがペルソナを生成中...";

    // 先に現在のペルソナ値を保存
    await App.settings.save();

    try {
        const data = await App.api("/api/persona/generate", { method: "POST" });
        if (data.error) { textarea.value = "エラー: " + data.error; return; }
        textarea.value = data.generated_text;
        // テキストに合わせてテキストエリアを自動リサイズ
        App.autoResize(textarea);
        App.toast("🧠 ペルソナ生成完了 → 保存してください");
    } catch (e) {
        textarea.value = "エラー: " + e.message;
    }
};

App.settings.suggestKeywords = async function () {
    const container = document.getElementById("keyword-suggest-list");
    if (!container) { App.toast("❌ 表示エリアが見つかりません"); return; }
    container.innerHTML = '<div class="loading-placeholder">🔑 キーワードを提案中...</div>';
    container.style.display = "block";

    try {
        const data = await App.api("/api/persona/suggest-keywords", { method: "POST" });
        if (data.error) { container.innerHTML = '<div class="loading-placeholder" style="color:var(--accent-red)">' + App.escapeHtml(data.error) + '</div>'; return; }
        const keywords = data.keywords || [];
        if (keywords.length === 0) { container.innerHTML = '<div class="loading-placeholder">キーワードが見つかりません</div>'; return; }

        let html = '<div class="keyword-suggest-items">';
        keywords.forEach(function (kw) {
            html += '<label class="keyword-suggest-item"><input type="checkbox" checked value="' + App.escapeHtml(kw) + '"><span>' + App.escapeHtml(kw) + '</span></label>';
        });
        html += '</div>';
        html += '<button class="btn btn-primary btn-sm" onclick="App.settings.registerKeywords()" style="margin-top:10px">✅ 選択したキーワードを登録</button>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<div class="loading-placeholder" style="color:var(--accent-red)">' + e.message + '</div>';
    }
};

App.settings.registerKeywords = async function () {
    const container = document.getElementById("keyword-suggest-list");
    const checked = container.querySelectorAll('input[type="checkbox"]:checked');
    const keywords = Array.from(checked).map(function (cb) { return cb.value; });
    if (keywords.length === 0) { App.toast("⚠️ キーワードを選択してください"); return; }

    // キーワードを Google News RSS URL に変換
    try {
        const data = await App.api("/api/keywords-to-rss", {
            method: "POST",
            body: JSON.stringify({ keywords: keywords }),
        });
        const urls = data.urls || [];
        if (urls.length === 0) { App.toast("❌ RSS URL を生成できませんでした"); return; }

        // rss_sources に追加
        const c = App.config;
        c.sources = c.sources || {};
        c.sources.rss_sources = c.sources.rss_sources || [];
        var added = 0;
        keywords.forEach(function (kw, i) {
            var url = urls[i] || "";
            if (!url) return;
            // 重複チェック
            var exists = c.sources.rss_sources.some(function (s) { return s.url === url; });
            if (!exists) {
                c.sources.rss_sources.push({ keyword: kw, url: url });
                added++;
            }
        });

        // 自動保存 & UI更新
        App.settings.renderSourceList();
        await App.settings.saveSources();
        container.style.display = "none";
        App.toast('🔑 ' + added + '件のRSSを登録しました');

        // トレンドを自動更新
        App.trends.refresh();
    } catch (e) {
        App.toast("❌ " + e.message);
    }
};

App.settings.renderSourceList = function () {
    const container = document.getElementById("rss-source-list");
    if (!container) return;
    const c = App.config;
    const sources = (c.sources || {}).rss_sources || [];

    // rss_urls からの移行: rss_sources が空で rss_urls があれば変換
    if (sources.length === 0 && (c.sources || {}).rss_urls && c.sources.rss_urls.length > 0) {
        c.sources.rss_sources = c.sources.rss_urls.map(function (url) {
            return { keyword: "", url: url };
        });
        App.settings.renderSourceList();
        return;
    }

    if (sources.length === 0) {
        container.innerHTML = '<div class="empty-state" style="padding:16px;text-align:center;color:var(--text-secondary);font-size:0.85rem;">📡 ソースが登録されていません<br>「🔑 ペルソナからキーワード提案」で追加できます</div>';
        return;
    }

    container.innerHTML = sources.map(function (s, i) {
        var kw = s.keyword || "(手動追加)";
        var url = s.url || "";
        return '<div class="rss-source-row">' +
            '<input type="checkbox" class="rss-source-check" data-index="' + i + '">' +
            '<span class="rss-source-keyword">' + App.escapeHtml(kw) + '</span>' +
            '<span class="rss-source-url">' + App.escapeHtml(url) + '</span>' +
            '</div>';
    }).join("");
};

App.settings.deleteSelectedSources = async function () {
    const checks = document.querySelectorAll(".rss-source-check:checked");
    if (checks.length === 0) { App.toast("⚠️ 削除するソースを選択してください"); return; }
    const indices = Array.from(checks).map(function (cb) { return parseInt(cb.dataset.index); }).sort(function (a, b) { return b - a; });
    const sources = App.config.sources.rss_sources || [];
    indices.forEach(function (i) { sources.splice(i, 1); });
    App.settings.renderSourceList();
    await App.settings.saveSources();
    App.toast('🗑️ ' + indices.length + '件削除しました');
};

App.settings.deleteAllSources = async function () {
    if (!confirm("全てのソースを削除しますか？")) return;
    App.config.sources = App.config.sources || {};
    App.config.sources.rss_sources = [];
    App.settings.renderSourceList();
    await App.settings.saveSources();
    App.toast('🗑️ 全ソースを削除しました');
};

App.settings.testConnections = async function () {
    const container = document.getElementById("api-test-result");
    container.innerHTML = '<div class="loading-placeholder">⏳ 接続テスト中...</div>';
    try {
        // テスト前に設定を保存
        await App.settings.save();
        const data = await App.api("/api/test-connections", { method: "POST" });
        const results = data.results || [];
        container.innerHTML = results.map(function (r) {
            const icon = r.service === 'gemini' ? '🤖' : r.service === 'x' ? '🐦' : '🧵';
            return '<div class="api-test-line ' + (r.ok ? 'success' : 'fail') + '">' + icon + ' ' + App.escapeHtml(r.message) + '</div>';
        }).join('');
    } catch (e) {
        container.innerHTML = '<div class="api-test-line fail">❌ テスト失敗: ' + e.message + '</div>';
    }
};

App.settings.refreshThreadsToken = async function () {
    const container = document.getElementById("api-test-result");
    container.innerHTML = '<div class="loading-placeholder">⏳ トークン更新中...</div>';
    try {
        const data = await App.api("/api/threads/refresh-token", { method: "POST" });
        if (data.error) {
            container.innerHTML = '<div class="api-test-line fail">❌ ' + App.escapeHtml(data.error) + '</div>';
            return;
        }
        container.innerHTML = '<div class="api-test-line success">' + App.escapeHtml(data.message) + '</div>';
        // トークン状態を更新
        App.settings.updateThreadsExpiry();
        // 設定をリロード
        await App.loadConfig();
        App.toast('✅ Threads トークンを更新しました');
    } catch (e) {
        container.innerHTML = '<div class="api-test-line fail">❌ ' + e.message + '</div>';
    }
};

App.settings.testThreads = async function () {
    const container = document.getElementById("api-test-result");
    container.innerHTML = '<div class="loading-placeholder">⏳ 接続テスト中...</div>';
    try {
        await App.settings.save();
        const data = await App.api("/api/test-connections", { method: "POST" });
        const results = data.results || [];
        const threads = results.find(function (r) { return r.service === 'threads'; });
        if (threads) {
            container.innerHTML = '<div class="api-test-line ' + (threads.ok ? 'success' : 'fail') + '">🧵 ' + App.escapeHtml(threads.message) + '</div>';
        }
    } catch (e) {
        container.innerHTML = '<div class="api-test-line fail">❌ ' + e.message + '</div>';
    }
};

App.settings.updateThreadsExpiry = function () {
    var containers = [
        document.getElementById("threads-token-status-api"),
    ];
    var sched = (App.config.schedule || {});
    var issued = sched.threads_token_issued || 0;
    var html, cls;
    if (!issued) {
        html = '⏳ トークン未発行（「🔄 トークン更新」で更新してください）';
        cls = 'threads-token-status status-warn';
    } else {
        var elapsed = (Date.now() / 1000) - issued;
        var remaining = 60 - Math.floor(elapsed / 86400);
        var issuedDate = new Date(issued * 1000);
        var dateStr = issuedDate.getFullYear() + '/' + (issuedDate.getMonth() + 1) + '/' + issuedDate.getDate();
        if (remaining <= 0) {
            html = '❌ トークン期限切れ（発行日: ' + dateStr + '）';
            cls = 'threads-token-status status-error';
        } else if (remaining <= 7) {
            html = '⚠️ 残り ' + remaining + ' 日（発行日: ' + dateStr + '）— まもなく期限切れ';
            cls = 'threads-token-status status-warn';
        } else {
            html = '✅ 残り ' + remaining + ' 日（発行日: ' + dateStr + '）';
            cls = 'threads-token-status status-ok';
        }
    }
    containers.forEach(function (c) {
        if (c) { c.innerHTML = html; c.className = cls; }
    });
};

App.settings.fetchNoteArticles = async function () {
    const noteUrl = document.getElementById("set-note-url").value;
    if (!noteUrl) { App.toast("⚠️ note URLを入力してください"); return; }

    const container = document.getElementById("note-articles-list");
    container.innerHTML = '<div class="loading-placeholder">記事を取得中...</div>';

    try {
        const data = await App.api("/api/note/fetch", {
            method: "POST",
            body: JSON.stringify({ note_url: noteUrl }),
        });
        if (data.error) {
            container.innerHTML = `<div class="loading-placeholder" style="color:var(--accent-red)">${App.escapeHtml(data.error)}</div>`;
            return;
        }
        const articles = data.articles || [];
        App.settings._renderNoteArticles(container, articles);
    } catch (e) {
        container.innerHTML = `<div class="loading-placeholder" style="color:var(--accent-red)">${e.message}</div>`;
    }
};

App.settings.loadNoteCache = async function () {
    const container = document.getElementById("note-articles-list");
    if (!container) return;
    try {
        const data = await App.api("/api/note/cache");
        const articles = data.articles || [];
        if (articles.length > 0) {
            App.settings._renderNoteArticles(container, articles);
        }
    } catch (e) {
        // キャッシュ未取得時は何もしない
    }
};

App.settings._renderNoteArticles = function (container, articles) {
    container.innerHTML = articles.map(function (a) {
        return '<div class="note-article-item">' +
            '<input type="checkbox" checked>' +
            '<span class="note-article-title">' + App.escapeHtml(a.title || a.url) + '</span>' +
            '</div>';
    }).join('') || '<div class="loading-placeholder">記事が見つかりません</div>';
};

// ==========================================================================
// ユーティリティ
// ==========================================================================

App.escapeHtml = function (str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
};

App.formatNumber = function (num) {
    if (num === undefined || num === null) return "0";
    num = Number(num);
    if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
    if (num >= 1000) return (num / 1000).toFixed(1) + "K";
    return String(num);
};

App.autoResize = function (textarea) {
    textarea.style.height = "auto";
    textarea.style.height = textarea.scrollHeight + "px";
};

// ==========================================================================
// 起動
// ==========================================================================

document.addEventListener("DOMContentLoaded", () => App.init());
