/* 片坞 Movie Dock 前端 */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  config: null,
  pendingDownload: null,
  lastResults: [],
  bestId: "",
  taskTimer: null,
  pollTimer: null,
  pollInterval: 1500,
  pollErrors: 0,
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || `请求失败 ${res.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function statusText(s) {
  const map = {
    queued: "排队中",
    active: "下载中",
    waiting: "等待中",
    paused: "已暂停",
    complete: "已完成",
    error: "失败",
    interrupted: "已中断",
    removed: "已移除",
  };
  return map[s] || s || "未知";
}

function subtitleText(s) {
  const map = {
    done: "字幕已配好",
    searching: "字幕匹配中",
    failed: "未匹配到字幕",
    skipped: "未启用字幕",
  };
  return map[s] || "";
}

function showToast(msg, type = "info") {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.style.cssText =
      "position:fixed;right:16px;bottom:16px;z-index:99;padding:10px 14px;border-radius:10px;font-size:13px;max-width:320px;box-shadow:0 8px 24px rgba(0,0,0,.3);";
    document.body.appendChild(el);
  }
  const colors = {
    info: ["#1a222d", "#e8eef6", "#2c3848"],
    ok: ["rgba(62,207,142,.15)", "#3ecf8e", "rgba(62,207,142,.35)"],
    err: ["rgba(240,113,120,.15)", "#f07178", "rgba(240,113,120,.35)"],
  };
  const c = colors[type] || colors.info;
  el.style.background = c[0];
  el.style.color = c[1];
  el.style.border = `1px solid ${c[2]}`;
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.hidden = true; }, 3200);
}

const PROVIDER_LABELS = {
  builtin: "内置索引",
  demo: "演示数据",
  llm: "大模型检索",
  qbittorrent: "qBittorrent 搜索",
  custom_api: "自定义索引",
};

async function loadConfig() {
  const cfg = await api("/api/config");
  state.config = cfg;
  $("#cfg-base-url").value = cfg.llm.base_url || "";
  $("#cfg-api-key").value = cfg.llm.api_key || "";
  $("#cfg-model").value = cfg.llm.model || "";
  const org = cfg.organize || {};
  $("#cfg-dir-template").value = org.movie_dir_template || "{title} ({year})";
  $("#cfg-file-template").value = org.file_name_template || "{title} ({year}) - {quality}";
  $("#cfg-series-dir-template").value = org.series_dir_template || "{title} ({year})/Season {season}";
  $("#cfg-series-file-template").value = org.series_file_template || "{title} ({year}) - S{season}E{episode} - {quality}";
  $("#cfg-library-root").value = org.library_root || "";
  $("#cfg-org-mode").value = org.mode || "move";
  $("#org-enabled").checked = org.enabled !== false;

  const sub = cfg.subtitle || {};
  $("#cfg-sub-enabled").checked = sub.enabled !== false;
  $("#cfg-sub-bilingual").checked = sub.prefer_bilingual !== false;
  $("#cfg-sub-keywords").value = (sub.extra_keywords || []).join("、");
  $("#sub-enabled").checked = sub.enabled !== false;

  const net = cfg.network || {};
  $("#cfg-proxy").value = net.proxy || "";

  $("#download-root").textContent = `下载根目录：${cfg.download_root || "-"}`;
  $("#cfg-env").textContent =
    `下载根目录：${cfg.download_root || "-"} · 资料库：${org.library_root || "（同下载根目录）"} · aria2 RPC：${cfg.aria2_rpc_url || "-"}`;

  const box = $("#cfg-providers");
  box.innerHTML = "";
  (cfg.search_providers || []).forEach((p, idx) => {
    const row = document.createElement("div");
    row.className = "provider";
    const typeLabel = PROVIDER_LABELS[p.type] || p.type;
    const opts = p.options || {};
    let extra = "";
    if (p.type === "builtin") {
      extra = `
        <label class="field" style="margin-top:8px">
          <span>启用的源（逗号分隔：tpb / yts / dmhy）</span>
          <input type="text" data-provider-opt="${idx}" data-opt-key="sources" value="${escapeHtml(opts.sources || "tpb,yts,dmhy")}" placeholder="tpb,yts,dmhy" />
        </label>
      `;
    } else if (p.type === "custom_api") {
      extra = `
        <label class="field" style="margin-top:8px">
          <span>名称</span>
          <input type="text" data-provider-name="${idx}" value="${escapeHtml(p.name || "")}" placeholder="自定义索引" />
        </label>
        <label class="field" style="margin-top:8px">
          <span>接口 URL</span>
          <input type="text" data-provider-url="${idx}" value="${escapeHtml(p.url || "")}" placeholder="https://... 或 http://NAS:port/search" />
        </label>
        <label class="field" style="margin-top:8px">
          <span>请求方法</span>
          <select data-provider-method="${idx}">
            <option value="GET" ${String(p.method || "GET").toUpperCase() === "GET" ? "selected" : ""}>GET</option>
            <option value="POST" ${String(p.method || "GET").toUpperCase() === "POST" ? "selected" : ""}>POST</option>
          </select>
        </label>
      `;
    } else if (p.type === "qbittorrent") {
      extra = `
        <label class="field" style="margin-top:8px">
          <span>WebUI 地址</span>
          <input type="text" data-provider-url="${idx}" value="${escapeHtml(p.url || "")}" placeholder="http://127.0.0.1:8085" />
        </label>
        <label class="field" style="margin-top:8px">
          <span>用户名</span>
          <input type="text" data-qbt-opt="${idx}" data-opt-key="username" value="${escapeHtml(opts.username || "")}" placeholder="admin" />
        </label>
        <label class="field" style="margin-top:8px">
          <span>密码</span>
          <input type="password" data-qbt-opt="${idx}" data-opt-key="password" value="${escapeHtml(opts.password || "")}" autocomplete="off" />
        </label>
        <label class="field" style="margin-top:8px">
          <span>插件（逗号分隔，留空=全部；建议固定几个快的）</span>
          <input type="text" data-qbt-opt="${idx}" data-opt-key="plugins" value="${escapeHtml(opts.plugins || "")}"
                 placeholder="yts,bt4g,kickass_torrent,limetorrents" />
        </label>
      `;
    }
    row.innerHTML = `
      <div style="flex:1">
        <div class="name">${escapeHtml(p.name || typeLabel)}</div>
        <div class="type">类型：${escapeHtml(typeLabel)}（${escapeHtml(p.type)}）</div>
        ${extra}
      </div>
      <label class="check"><input type="checkbox" data-provider-idx="${idx}" ${p.enabled ? "checked" : ""}/> 启用</label>
    `;
    box.appendChild(row);
  });
}

async function checkDownloader() {
  try {
    const st = await api("/api/downloader/status");
    const badge = $("#aria2-badge");
    if (st.available) {
      badge.textContent = `aria2 就绪${st.version ? " · " + st.version : ""}`;
      badge.className = "badge ok";
    } else {
      badge.textContent = "aria2 未连接（磁力/种子需 Docker 内引擎）";
      badge.className = "badge warn";
    }
  } catch {
    const badge = $("#aria2-badge");
    badge.textContent = "下载引擎状态未知";
    badge.className = "badge err";
  }
}

async function refreshOrganizePreview() {
  const title = $("#query").value.trim();
  if (!title) {
    $("#org-preview").value = "";
    return;
  }
  try {
    const year = $("#year").value ? Number($("#year").value) : null;
    const quality = $("#quality").value || "";
    const data = await api("/api/organize/preview", {
      method: "POST",
      body: JSON.stringify({
        title,
        year,
        quality,
        movie_dir_template: $("#cfg-dir-template").value || undefined,
        file_name_template: $("#cfg-file-template").value || undefined,
      }),
    });
    if (data.ok) $("#org-preview").value = data.preview_path || "";
  } catch {
    /* ignore preview errors */
  }
}

function renderResults(items, warnings, providers, bestId) {
  const warnBox = $("#search-warnings");
  const meta = $("#search-meta");
  const box = $("#results");
  state.lastResults = items || [];
  state.bestId = bestId || "";

  if (warnings && warnings.length) {
    warnBox.hidden = false;
    warnBox.innerHTML = warnings.map((w) => `<div>${escapeHtml(w)}</div>`).join("");
  } else {
    warnBox.hidden = true;
    warnBox.innerHTML = "";
  }

  meta.hidden = false;
  meta.textContent = `共 ${items.length} 条候选（按评分排序）· 来源：${(providers || []).join("、") || "无"}`;

  if (!items.length) {
    box.innerHTML = `<div class="empty">
      没有检索到候选。<br/>
      ① 检查「设置 → 检索源」里<b>内置索引</b>是否勾选（源：tpb/yts/dmhy）；境外源需在「网络（代理）」里填代理；
      ② 或直接用「粘贴磁力/直链」下载（不依赖任何检索源）。
      <div style="margin-top:10px"><button class="btn primary btn-paste-inline" type="button">粘贴磁力/直链</button></div>
    </div>`;
    return;
  }

  box.innerHTML = items.map((it) => {
    const tags = [];
    tags.push(`<span class="tag">${escapeHtml(it.quality || "未知")}</span>`);
    (it.tags || []).forEach((t) => tags.push(`<span class="tag feat">${escapeHtml(t)}</span>`));
    if (it.size) tags.push(`<span class="tag gray">${escapeHtml(it.size)}</span>`);
    if (it.seeds != null) tags.push(`<span class="tag green">做种 ${escapeHtml(it.seeds)}</span>`);
    if (it.peers != null) tags.push(`<span class="tag gray">同伴 ${escapeHtml(it.peers)}</span>`);
    if (it.score) tags.push(`<span class="tag score">评分 ${escapeHtml(it.score)}</span>`);
    tags.push(`<span class="tag gray">${escapeHtml(it.url_type || "unknown")}</span>`);
    tags.push(`<span class="tag gray">${escapeHtml(it.source || "")}</span>`);
    return `
      <article class="result ${it.id === state.bestId ? "result-best" : ""}" data-id="${escapeHtml(it.id)}">
        <div class="result-top">
          <div class="result-title">${escapeHtml(it.title)}${
            it.id === state.bestId ? ` <span class="best-flag">推荐</span>` : ""
          }</div>
        </div>
        <div class="tags">${tags.join("")}</div>
        ${it.note ? `<div class="result-note">${escapeHtml(it.note)}</div>` : ""}
        <div class="result-url">${escapeHtml(it.url)}</div>
        <div class="result-actions">
          <button class="btn primary btn-pick" type="button"
            data-title="${escapeHtml(it.title)}"
            data-quality="${escapeHtml(it.quality || "")}"
            data-url="${escapeHtml(it.url)}"
            data-source="${escapeHtml(it.source || "")}"
          >选择并下载</button>
        </div>
      </article>
    `;
  }).join("");
}

function guessYearFromTitle(title) {
  const m = String(title || "").match(/(19|20)\d{2}/);
  return m ? Number(m[0]) : ($("#year").value ? Number($("#year").value) : null);
}

/** 从磁力 dn= 里提取片名/年份（用于自动填“用于整理的片名”） */
function parseMagnetName(url) {
  if (!/^magnet:/i.test(url || "")) return null;
  const m = String(url).match(/[?&]dn=([^&]+)/i);
  if (!m) return null;
  let name = "";
  try { name = decodeURIComponent(m[1].replace(/\+/g, " ")); } catch { name = m[1].replace(/\+/g, " "); }
  name = name.replace(/\.(mkv|mp4|avi|ts|m2ts)$/i, "");
  const year = (name.match(/(19|20)\d{2}/) || [null])[0];
  const clean = name
    .replace(/\b(bluray|blu-ray|bdremux|remux|web-dl|webdl|webrip|hdtv|hdrip|brrip|dvdrip)\b/gi, " ")
    .replace(/\b(2160p|1080p|720p|480p|4k|uhd|hdr10\+|hdr10|hdr|dovi|dv|10bit|8bit)\b/gi, " ")
    .replace(/\b(x264|x265|h264|h265|hevc|avc|av1|aac|ac3|dts-hd|dts|truehd|atmos|ddp)\b/gi, " ")
    .replace(/\b(repack|proper|internal|multi|dual|remastered|criterion|imax)\b/gi, " ")
    .replace(/\b(19|20)\d{2}\b/g, " ")
    .replace(/[-_.]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return { title: clean || null, year: year ? Number(year) : null };
}

/** 打开“粘贴磁力/直链”弹框（链接为空、可编辑、自动识别磁力里的片名） */
function openPasteModal(prefill) {
  openDownloadModal({
    title: (prefill && prefill.title) || $("#query").value.trim() || "",
    quality: (prefill && prefill.quality) || $("#quality").value || "",
    url: (prefill && prefill.url) || "",
    source: "手动粘贴",
  });
  const el = $("#dl-url");
  el.readOnly = false;
  el.focus();
  if (el.value) autoFillFromUrl();
}

/** 粘完磁力自动补片名/年份（用户已填的不覆盖） */
function autoFillFromUrl() {
  const url = $("#dl-url").value.trim();
  const parsed = parseMagnetName(url);
  if (!parsed) return;
  const titleEl = $("#dl-title");
  const yearEl = $("#dl-year");
  if (!titleEl.value.trim() && parsed.title) titleEl.value = parsed.title;
  if (!yearEl.value && parsed.year) yearEl.value = parsed.year;
}

function openDownloadModal(payload) {
  state.pendingDownload = payload;
  $("#dl-summary").innerHTML = `
    <div class="t">${escapeHtml(payload.title || "未命名")}</div>
    <div class="s">来源：${escapeHtml(payload.source || "手动")} · 类型提示：${escapeHtml(payload.quality || "未知")}</div>
  `;
  $("#dl-title").value = (payload.title || "").replace(/\s*-\s*(1080p|720p|2160p|480p|4K).*$/i, "") || payload.title || "";
  // 尝试去掉年份便于模板重组
  const rawTitle = $("#dl-title").value.replace(/\((19|20)\d{2}\)/g, "").trim() || payload.title;
  $("#dl-title").value = rawTitle;
  $("#dl-year").value = guessYearFromTitle(payload.title) || "";
  $("#dl-quality").value = payload.quality || "";
  const urlEl = $("#dl-url");
  urlEl.value = payload.url || "";
  // 候选来的链接只读；手工粘贴时可编辑
  urlEl.readOnly = Boolean(payload.url);
  $("#dl-organize").checked = $("#org-enabled").checked;
  $("#dl-subtitle").checked = $("#sub-enabled").checked;
  $("#modal-download").hidden = false;
}

async function doSearch(ev) {
  ev.preventDefault();
  const query = $("#query").value.trim();
  if (!query) return;
  const btn = $("#btn-search");
  btn.disabled = true;
  btn.textContent = "检索中…";
  $("#results").innerHTML = `<div class="empty">正在检索，请稍候…</div>`;
  try {
    const body = {
      query,
      year: $("#year").value ? Number($("#year").value) : null,
      quality: $("#quality").value || null,
    };
    const data = await api("/api/search", { method: "POST", body: JSON.stringify(body) });
    renderResults(data.items || [], data.warnings || [], data.providers || [], data.best_id || "");
  } catch (err) {
    showToast(err.message || "检索失败", "err");
    $("#results").innerHTML = `<div class="empty">检索失败：${escapeHtml(err.message || "")}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "搜索";
  }
}

function pickBest() {
  const items = state.lastResults || [];
  if (!items.length) {
    showToast("还没有检索结果", "err");
    return;
  }
  const best = items.find((i) => i.id === state.bestId) ||
    items.slice().sort((a, b) => (b.score || 0) - (a.score || 0))[0];
  openDownloadModal({
    title: best.title || "",
    quality: best.quality || "",
    url: best.url || "",
    source: best.source || "",
    id: best.id || "",
  });
}

async function startDownload() {
  const url = $("#dl-url").value.trim();
  if (!url) {
    showToast("缺少下载链接", "err");
    return;
  }
  const title = $("#dl-title").value.trim() || "未命名任务";
  const year = $("#dl-year").value ? Number($("#dl-year").value) : null;
  const quality = $("#dl-quality").value.trim();
  const enabled = $("#dl-organize").checked;
  const body = {
    url,
    title,
    year,
    quality,
    source_id: (state.pendingDownload && state.pendingDownload.id) || "",
    fetch_subtitle: $("#dl-subtitle").checked,
    organize: {
      title,
      year,
      quality,
      enabled,
      movie_dir_template: $("#cfg-dir-template").value || undefined,
      file_name_template: $("#cfg-file-template").value || undefined,
      series_dir_template: $("#cfg-series-dir-template").value || undefined,
      series_file_template: $("#cfg-series-file-template").value || undefined,
      library_root: $("#cfg-library-root").value.trim(),
      mode: $("#cfg-org-mode").value || undefined,
    },
  };
  try {
    await api("/api/download", { method: "POST", body: JSON.stringify(body) });
    showToast("任务已创建", "ok");
    $("#modal-download").hidden = true;
    await loadTasks();
  } catch (err) {
    showToast(err.message || "创建任务失败", "err");
  }
}

function taskSubtitleHtml(t) {
  if (!t.subtitle_status) return "";
  const label = subtitleText(t.subtitle_status);
  if (!label) return "";
  const cls = t.subtitle_status === "done" ? "ok" : (t.subtitle_status === "failed" ? "err" : "neutral");
  const path = t.subtitle_path ? ` · ${escapeHtml(t.subtitle_path)}` : "";
  const note = t.subtitle_note ? `<div class="path neutral">${escapeHtml(t.subtitle_note)}</div>` : "";
  const retry = t.status === "complete" && t.subtitle_status !== "done"
    ? `<button class="btn ghost btn-retry-sub" type="button" data-task="${escapeHtml(t.task_id)}">重试字幕</button>`
    : "";
  return `<div class="path ${cls}">${escapeHtml(label)}${path}</div>${note}${retry}`;
}

function renderTasks(tasks) {
  const box = $("#tasks");
  if (!tasks || !tasks.length) {
    box.innerHTML = `<div class="empty">暂无任务。检索后选择一条片源开始下载。</div>`;
    return;
  }
  box.innerHTML = tasks.map((t) => {
    const path = t.organized_path || t.saved_path || "";
    const pathHtml = path
      ? `<div class="path">输出路径：${escapeHtml(path)}</div>`
      : (t.status === "complete" ? `<div class="path neutral">已完成，但未记录输出路径</div>` : "");
    const errHtml = t.error ? `<div class="path err">${escapeHtml(t.error)}</div>` : "";
    const tags = (t.tags || []).map((x) => `<span class="tag feat">${escapeHtml(x)}</span>`).join("");
    return `
      <article class="task">
        <div class="task-head">
          <div class="task-title">${escapeHtml(t.title || "未命名")}</div>
          <span class="status ${escapeHtml(t.status)}">${escapeHtml(statusText(t.status))}</span>
        </div>
        <div class="bar"><i style="width:${Number(t.progress || 0)}%"></i></div>
        <div class="task-meta">
          <span>${Number(t.progress || 0).toFixed(1)}%</span>
          ${t.download_speed ? `<span>${escapeHtml(t.download_speed)}</span>` : ""}
          ${t.completed_length ? `<span>${escapeHtml(t.completed_length)}</span>` : ""}
          ${t.total_length ? `<span>/ ${escapeHtml(t.total_length)}</span>` : ""}
          ${t.quality ? `<span>${escapeHtml(t.quality)}</span>` : ""}
          ${t.episode ? `<span>${escapeHtml(t.episode)}</span>` : ""}
          ${t.engine ? `<span>${escapeHtml(t.engine)}</span>` : ""}
        </div>
        ${tags ? `<div class="tags">${tags}</div>` : ""}
        ${pathHtml}
        ${errHtml}
        ${taskSubtitleHtml(t)}
      </article>
    `;
  }).join("");
}

async function loadTasks() {
  const live = document.getElementById("task-live");
  try {
    const tasks = await api("/api/tasks");
    state.lastResults = state.lastResults || [];
    renderTasks(tasks);
    state.pollErrors = 0;
    if (live) {
      const now = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      live.textContent = `更新于 ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
      live.style.color = "";
    }
    // 有活动任务就快刷，空闲时慢刷
    const busy = tasks.some((t) => ["active", "queued", "waiting", "paused", "interrupted", "searching"].includes(t.status)
      || t.subtitle_status === "searching");
    state.pollInterval = busy ? 1500 : 4000;
  } catch (err) {
    state.pollErrors = (state.pollErrors || 0) + 1;
    if (live) {
      live.textContent = `⚠︎ 状态更新失败（第${state.pollErrors}次），请刷新页面`;
      live.style.color = "var(--danger)";
    }
    state.pollInterval = Math.min(15000, (state.pollInterval || 4000) * 2);
  } finally {
    scheduleTaskPoll();
  }
}

function scheduleTaskPoll() {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(loadTasks, state.pollInterval || 2500);
}

async function saveConfig() {
  const providers = (state.config && state.config.search_providers
    ? state.config.search_providers.map((p) => ({ ...p, headers: { ...(p.headers || {}) }, options: { ...(p.options || {}) } }))
    : []);
  $$("#cfg-providers input[data-provider-idx]").forEach((input) => {
    const idx = Number(input.getAttribute("data-provider-idx"));
    if (providers[idx]) providers[idx].enabled = input.checked;
  });
  $$("#cfg-providers [data-provider-name]").forEach((input) => {
    const idx = Number(input.getAttribute("data-provider-name"));
    if (providers[idx]) providers[idx].name = input.value.trim();
  });
  $$("#cfg-providers [data-provider-url]").forEach((input) => {
    const idx = Number(input.getAttribute("data-provider-url"));
    if (providers[idx]) providers[idx].url = input.value.trim();
  });
  $$("#cfg-providers [data-provider-method]").forEach((input) => {
    const idx = Number(input.getAttribute("data-provider-method"));
    if (providers[idx]) providers[idx].method = (input.value || "GET").toUpperCase();
  });
  $$("#cfg-providers [data-qbt-opt]").forEach((input) => {
    const idx = Number(input.getAttribute("data-qbt-opt"));
    const key = input.getAttribute("data-opt-key");
    if (providers[idx] && key) {
      providers[idx].options = providers[idx].options || {};
      providers[idx].options[key] = input.value.trim();
    }
  });
  $$("#cfg-providers [data-provider-opt]").forEach((input) => {
    const idx = Number(input.getAttribute("data-provider-opt"));
    const key = input.getAttribute("data-opt-key");
    if (providers[idx] && key) {
      providers[idx].options = providers[idx].options || {};
      providers[idx].options[key] = input.value.trim();
    }
  });
  const body = {
    llm: {
      base_url: $("#cfg-base-url").value.trim(),
      api_key: $("#cfg-api-key").value.trim(),
      model: $("#cfg-model").value.trim(),
      timeout_seconds: (state.config && state.config.llm && state.config.llm.timeout_seconds) || 60,
    },
    organize: {
      movie_dir_template: $("#cfg-dir-template").value.trim() || "{title} ({year})",
      file_name_template: $("#cfg-file-template").value.trim() || "{title} ({year}) - {quality}",
      series_dir_template: $("#cfg-series-dir-template").value.trim() || "{title} ({year})/Season {season}",
      series_file_template: $("#cfg-series-file-template").value.trim() || "{title} ({year}) - S{season}E{episode} - {quality}",
      library_root: $("#cfg-library-root").value.trim(),
      mode: $("#cfg-org-mode").value || "move",
      enabled: $("#org-enabled").checked,
      unknown_year: (state.config && state.config.organize && state.config.organize.unknown_year) || "未知年份",
    },
    subtitle: {
      enabled: $("#cfg-sub-enabled").checked,
      prefer_bilingual: $("#cfg-sub-bilingual").checked,
      extra_keywords: $("#cfg-sub-keywords").value
        .split(/[,，、\s]+/)
        .map((s) => s.trim())
        .filter(Boolean),
    },
    network: {
      proxy: $("#cfg-proxy").value.trim(),
      timeout_seconds: (state.config && state.config.network && state.config.network.timeout_seconds) || 20,
    },
    search_providers: providers,
  };
  try {
    await api("/api/config", { method: "PUT", body: JSON.stringify(body) });
    showToast("设置已保存", "ok");
    await loadConfig();
    await refreshOrganizePreview();
  } catch (err) {
    showToast(err.message || "保存失败", "err");
  }
}

async function testLLM() {
  const btn = $("#btn-test-llm");
  const result = $("#llm-test-result");
  btn.disabled = true;
  result.textContent = "测试中…";
  try {
    const data = await api("/api/llm/test", {
      method: "POST",
      body: JSON.stringify({
        base_url: $("#cfg-base-url").value.trim(),
        api_key: $("#cfg-api-key").value.trim(),
        model: $("#cfg-model").value.trim(),
        timeout_seconds: 60,
      }),
    });
    result.textContent = data.ok
      ? `✓ ${data.message}（模型：${data.model || "-"}）${data.detail ? " · " + data.detail : ""}`
      : `✗ ${data.message}`;
    result.style.color = data.ok ? "var(--ok)" : "var(--danger)";
  } catch (err) {
    result.textContent = `✗ ${err.message}`;
    result.style.color = "var(--danger)";
  } finally {
    btn.disabled = false;
  }
}

function bindEvents() {
  const on = (sel, ev, fn) => {
    const el = document.querySelector(sel);
    if (!el) { console.warn("[片坞] 找不到元素，跳过绑定:", sel); return; }
    el.addEventListener(ev, fn);
  };
  on("#search-form", "submit", doSearch);
  on("#btn-best", "click", pickBest);
  on("#btn-paste", "click", () => openPasteModal());
  on("#dl-url", "input", autoFillFromUrl);
  on("#btn-settings", "click", () => { $("#modal-settings").hidden = false; });
  $$("[data-close-settings]").forEach((b) => b.addEventListener("click", () => { $("#modal-settings").hidden = true; }));
  $$("[data-close-download]").forEach((b) => b.addEventListener("click", () => { $("#modal-download").hidden = true; }));
  on("#btn-save-config", "click", saveConfig);
  on("#btn-test-llm", "click", testLLM);
  on("#btn-start-download", "click", startDownload);
  on("#btn-refresh-tasks", "click", () => { state.pollInterval = 1500; loadTasks(); });
  on("#query", "input", () => { clearTimeout(window._pt); window._pt = setTimeout(refreshOrganizePreview, 400); });
  on("#year", "change", refreshOrganizePreview);
  on("#quality", "change", refreshOrganizePreview);

  // 页面从缓存/后台恢复时（bfcache、切回标签页），定时器可能被冻结 → 立即补一次刷新并恢复轮询
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      state.pollInterval = 1500;
      loadTasks();
      checkDownloader();
    }
  });
  window.addEventListener("pageshow", () => { state.pollInterval = 1500; loadTasks(); });

  on("#tasks", "click", async (e) => {
    const btn = e.target.closest(".btn-retry-sub");
    if (!btn) return;
    const id = btn.getAttribute("data-task");
    btn.disabled = true;
    btn.textContent = "匹配中…";
    try {
      const data = await api(`/api/tasks/${encodeURIComponent(id)}/subtitle`, { method: "POST" });
      showToast(data.ok ? "字幕已配好" : (data.message || "未匹配到字幕"), data.ok ? "ok" : "err");
    } catch (err) {
      showToast(err.message || "字幕匹配失败", "err");
    } finally {
      await loadTasks();
    }
  });

  on("#results", "click", (e) => {
    const pasteBtn = e.target.closest(".btn-paste-inline");
    if (pasteBtn) { openPasteModal(); return; }
    const btn = e.target.closest(".btn-pick");
    if (!btn) return;
    openDownloadModal({
      title: btn.getAttribute("data-title") || "",
      quality: btn.getAttribute("data-quality") || "",
      url: btn.getAttribute("data-url") || "",
      source: btn.getAttribute("data-source") || "",
      id: "",
    });
  });

  // 支持在结果区空白处快速手动粘贴链接（双击结果区）
  on("#results", "dblclick", () => {
    const url = prompt("粘贴磁力链接 / 种子 URL / HTTP 直链：");
    if (!url) return;
    openDownloadModal({
      title: $("#query").value.trim() || "手动任务",
      quality: $("#quality").value || "",
      url: url.trim(),
      source: "手动粘贴",
    });
  });
}

async function init() {
  try {
    bindEvents();
  } catch (err) {
    console.error("[片坞] 事件绑定失败:", err);
    showToast("界面初始化异常：" + (err.message || err), "err");
  }
  // 未搜索前的占位（明确给出入口，不再靠“双击空白处”）
  const box = $("#results");
  if (box && !box.innerHTML.trim()) {
    box.innerHTML = `<div class="empty">
      <b>还没检索</b><br/>
      ① 点下方按钮直接粘贴磁力/直链下载（不需要任何检索源）<br/>
      ② 或在「设置 → 检索源」配置后搜索片名
      <div style="margin-top:10px"><button class="btn primary btn-paste-inline" type="button">粘贴磁力/直链</button></div>
    </div>`;
  }
  try {
    await loadConfig();
  } catch (err) {
    showToast(err.message || "加载配置失败", "err");
  }
  await checkDownloader();
  state.pollInterval = 1500;
  await loadTasks();
  setInterval(checkDownloader, 15000);
}

init();
