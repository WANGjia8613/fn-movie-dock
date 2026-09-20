/* 片坞 Movie Dock 前端 */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  config: null,
  pendingDownload: null,
  taskTimer: null,
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
    removed: "已移除",
  };
  return map[s] || s || "未知";
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

async function loadConfig() {
  const cfg = await api("/api/config");
  state.config = cfg;
  $("#cfg-base-url").value = cfg.llm.base_url || "";
  $("#cfg-api-key").value = cfg.llm.api_key || "";
  $("#cfg-model").value = cfg.llm.model || "";
  $("#cfg-dir-template").value = cfg.organize.movie_dir_template || "{title} ({year})";
  $("#cfg-file-template").value = cfg.organize.file_name_template || "{title} ({year}) - {quality}";
  $("#cfg-org-mode").value = cfg.organize.mode || "move";
  $("#org-enabled").checked = cfg.organize.enabled !== false;
  $("#download-root").textContent = `下载根目录：${cfg.download_root || "-"}`;
  $("#cfg-env").textContent = `下载根目录：${cfg.download_root || "-"} · aria2 RPC：${cfg.aria2_rpc_url || "-"}`;

  const box = $("#cfg-providers");
  box.innerHTML = "";
  (cfg.search_providers || []).forEach((p, idx) => {
    const row = document.createElement("div");
    row.className = "provider";
    const typeLabel = { demo: "演示数据", llm: "大模型检索", custom_api: "自定义索引" }[p.type] || p.type;
    const extra = p.type === "custom_api"
      ? `
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
      `
      : "";
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

function renderResults(items, warnings, providers) {
  const warnBox = $("#search-warnings");
  const meta = $("#search-meta");
  const box = $("#results");

  if (warnings && warnings.length) {
    warnBox.hidden = false;
    warnBox.innerHTML = warnings.map((w) => `<div>${escapeHtml(w)}</div>`).join("");
  } else {
    warnBox.hidden = true;
    warnBox.innerHTML = "";
  }

  meta.hidden = false;
  meta.textContent = `共 ${items.length} 条候选 · 来源：${(providers || []).join("、") || "无"}`;

  if (!items.length) {
    box.innerHTML = `<div class="empty">没有检索到候选。可启用「演示数据」验证流程，或配置大模型 / 自定义索引 API，也可以在下载弹窗中手动粘贴磁力链接。</div>`;
    return;
  }

  box.innerHTML = items.map((it) => {
    const tags = [];
    tags.push(`<span class="tag">${escapeHtml(it.quality || "未知")}</span>`);
    if (it.size) tags.push(`<span class="tag gray">${escapeHtml(it.size)}</span>`);
    if (it.seeds != null) tags.push(`<span class="tag green">做种 ${escapeHtml(it.seeds)}</span>`);
    if (it.peers != null) tags.push(`<span class="tag gray">同伴 ${escapeHtml(it.peers)}</span>`);
    tags.push(`<span class="tag gray">${escapeHtml(it.url_type || "unknown")}</span>`);
    tags.push(`<span class="tag gray">${escapeHtml(it.source || "")}</span>`);
    return `
      <article class="result" data-id="${escapeHtml(it.id)}">
        <div class="result-top">
          <div class="result-title">${escapeHtml(it.title)}</div>
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
  $("#dl-url").value = payload.url || "";
  $("#dl-organize").checked = $("#org-enabled").checked;
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
    renderResults(data.items || [], data.warnings || [], data.providers || []);
  } catch (err) {
    showToast(err.message || "检索失败", "err");
    $("#results").innerHTML = `<div class="empty">检索失败：${escapeHtml(err.message || "")}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "搜索";
  }
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
    organize: {
      title,
      year,
      quality,
      enabled,
      movie_dir_template: $("#cfg-dir-template").value || undefined,
      file_name_template: $("#cfg-file-template").value || undefined,
      mode: $("#cfg-org-mode").value || undefined,
    },
  };
  try {
    const data = await api("/api/download", { method: "POST", body: JSON.stringify(body) });
    showToast("任务已创建", "ok");
    $("#modal-download").hidden = true;
    await loadTasks();
  } catch (err) {
    showToast(err.message || "创建任务失败", "err");
  }
}

function renderTasks(tasks) {
  const box = $("#tasks");
  if (!tasks || !tasks.length) {
    box.innerHTML = `<div class="empty">暂无任务。检索后选择一条片源开始下载。</div>`;
    return;
  }
  box.innerHTML = tasks.map((t) => {
    const path = t.organized_path || t.saved_path || "";
    const pathHtml = t.status === "complete"
      ? (path
          ? `<div class="path">输出路径：${escapeHtml(path)}</div>`
          : `<div class="path neutral">已完成，但未记录输出路径</div>`)
      : (t.error ? `<div class="path err">${escapeHtml(t.error)}</div>` : "");
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
          ${t.engine ? `<span>${escapeHtml(t.engine)}</span>` : ""}
        </div>
        ${pathHtml}
      </article>
    `;
  }).join("");
}

async function loadTasks() {
  try {
    const tasks = await api("/api/tasks");
    renderTasks(tasks);
  } catch (err) {
    /* keep silent on poll errors */
  }
}

async function saveConfig() {
  const providers = (state.config && state.config.search_providers
    ? state.config.search_providers.map((p) => ({ ...p, headers: { ...(p.headers || {}) } }))
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
      mode: $("#cfg-org-mode").value || "move",
      enabled: $("#org-enabled").checked,
      unknown_year: (state.config && state.config.organize && state.config.organize.unknown_year) || "未知年份",
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
  $("#search-form").addEventListener("submit", doSearch);
  $("#btn-settings").addEventListener("click", () => { $("#modal-settings").hidden = false; });
  $$("[data-close-settings]").forEach((b) => b.addEventListener("click", () => { $("#modal-settings").hidden = true; }));
  $$("[data-close-download]").forEach((b) => b.addEventListener("click", () => { $("#modal-download").hidden = true; }));
  $("#btn-save-config").addEventListener("click", saveConfig);
  $("#btn-test-llm").addEventListener("click", testLLM);
  $("#btn-start-download").addEventListener("click", startDownload);
  $("#btn-refresh-tasks").addEventListener("click", loadTasks);
  $("#query").addEventListener("input", () => { clearTimeout(window._pt); window._pt = setTimeout(refreshOrganizePreview, 400); });
  $("#year").addEventListener("change", refreshOrganizePreview);
  $("#quality").addEventListener("change", refreshOrganizePreview);
  $("#org-enabled").addEventListener("change", () => {
    /* 仅影响后续下载弹窗默认值 */
  });

  $("#results").addEventListener("click", (e) => {
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
  $("#results").addEventListener("dblclick", () => {
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
  bindEvents();
  try {
    await loadConfig();
  } catch (err) {
    showToast(err.message || "加载配置失败", "err");
  }
  await checkDownloader();
  await loadTasks();
  state.taskTimer = setInterval(async () => {
    await loadTasks();
  }, 2500);
  setInterval(checkDownloader, 15000);
}

init();
