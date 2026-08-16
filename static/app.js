/* 墨笔 · 小说创作 Agent 前端 */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  settings: null,
  projects: [],
  project: null,
  view: "premise",
  chapterIndex: null,
  streaming: false,
  snapshot: null, // AI 替换类操作前的正文快照,用于撤销
  dirty: false,
  editingChar: -1,
};

/* ---------------- 基础工具 ---------------- */
async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!resp.ok) {
    let msg = `${resp.status}`;
    try {
      const d = await resp.json();
      msg = d.detail || JSON.stringify(d);
    } catch {}
    throw new Error(msg);
  }
  return resp.json();
}

async function streamNDJSON(path, body, { onDelta, onStatus } = {}) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!resp.ok) {
    let msg = `${resp.status}`;
    try { msg = (await resp.text()).slice(0, 300) || msg; } catch {}
    throw new Error(msg);
  }
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "", done = null;
  while (true) {
    const { value, done: rd } = await reader.read();
    if (rd) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      const ev = JSON.parse(line);
      if (ev.type === "delta") onDelta && onDelta(ev.text);
      else if (ev.type === "status") onStatus && onStatus(ev.text);
      else if (ev.type === "error") throw new Error(ev.message);
      else if (ev.type === "done") done = ev.project;
    }
  }
  return done;
}

function toast(msg, type = "") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("#toast-wrap").appendChild(el);
  setTimeout(() => el.remove(), type === "error" ? 6000 : 2600);
}

function setStreaming(on, btn) {
  state.streaming = on;
  if (btn && on) {
    btn.dataset.orig = btn.innerHTML;
    btn.innerHTML = '<span class="spin"></span>生成中…';
    btn.disabled = true;
  } else if (btn && btn.dataset.orig) {
    btn.innerHTML = btn.dataset.orig;
    btn.disabled = false;
  }
}

function guard(btn) {
  if (state.streaming) {
    toast("请等待当前生成完成", "muted");
    return true;
  }
  if (btn) setStreaming(true, btn);
  return false;
}

const fmtTime = (ts) => {
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

/* ---------------- 初始化 ---------------- */
async function init() {
  try {
    state.settings = await api("/api/settings");
  } catch (e) {
    toast("读取设置失败:" + e.message, "error");
  }
  await refreshProjects();
  updateBadge();
  bindGlobal();
}

async function refreshProjects() {
  state.projects = await api("/api/projects");
  renderSidebar();
}

function updateBadge() {
  const s = state.settings || {};
  $("#llm-badge").textContent = `${s.provider} · ${s.model || "(未配置模型)"}`;
}

async function openProject(id) {
  if (state.dirty && !confirm("当前章节有未保存的修改,确定切换吗?")) return;
  state.project = await api(`/api/projects/${id}`);
  state.chapterIndex = null;
  state.dirty = false;
  state.snapshot = null;
  state.view = "premise";
  renderAll();
}

function setView(v, chapterIndex) {
  if (state.dirty && state.view === "chapters" && (v !== "chapters" || chapterIndex !== state.chapterIndex)) {
    if (!confirm("当前章节有未保存的修改,确定离开吗?")) return;
    state.dirty = false;
  }
  state.view = v;
  if (chapterIndex !== undefined) state.chapterIndex = chapterIndex;
  state.snapshot = null;
  renderAll();
}

/* ---------------- 渲染 ---------------- */
function renderAll() {
  renderSidebar();
  renderMain();
}

function renderSidebar() {
  const ul = $("#project-list");
  ul.innerHTML =
    state.projects
      .map(
        (p) => `<li data-id="${p.id}" class="${state.project?.id === p.id ? "active" : ""}">
          <span class="pt">${esc(p.title)}</span>
          <span class="del" data-action="del-project" data-id="${p.id}" title="删除项目">×</span>
        </li>`
      )
      .join("") || `<li style="color:var(--muted);cursor:default">还没有作品</li>`;

  const has = !!state.project;
  $("#steps-section").hidden = !has;
  if (has) {
    const items = [
      ["premise", "① 故事设定"],
      ["characters", "② 角色卡"],
      ["outline", "③ 章节大纲"],
      ["chapters", "④ 章节写作"],
    ];
    $("#steps").innerHTML = items
      .map(([v, t]) => `<li data-view="${v}" class="${state.view === v ? "active" : ""}">${t}</li>`)
      .join("");
  }
}

function renderMain() {
  const main = $("#main");
  if (!state.project) {
    main.innerHTML = `<div class="empty"><div class="big">✒️</div>点击右上角「＋ 新建小说」开始创作<br>Agent 会依次完成:故事圣经 → 角色卡 → 分章大纲 → 逐章写作</div>`;
    return;
  }
  switch (state.view) {
    case "premise": return renderPremise(main);
    case "characters": return renderCharacters(main);
    case "outline": return renderOutline(main);
    case "chapters": return renderChapters(main);
  }
}

/* ---------------- 视图:故事设定 ---------------- */
function renderPremise(main) {
  const p = state.project;
  main.innerHTML = `<div class="view">
    <h2>故事设定</h2>
    <p class="sub">先用一两句话写下灵感,由 Agent 生成完整的「故事圣经」:世界观、核心冲突、主线梗概与文风。</p>
    <div class="panel">
      <label>书名</label><input id="p-title" value="${esc(p.title)}">
      <label>创作意向 / 灵感</label><textarea id="p-idea" rows="3" placeholder="例:一个能听见器物之声的古籍修复师,在修复一册禁书时被卷入百年前的冤案">${esc(p.idea)}</textarea>
      <label>类型</label><input id="p-genre" value="${esc(p.genre)}" placeholder="如:悬疑 / 东方玄幻 / 都市情感 / 科幻">
      <div class="row">
        <button class="btn primary" data-action="gen-premise" ${state.streaming ? "disabled" : ""}>✨ 生成故事圣经</button>
        <button class="btn" data-action="save-meta">保存基本信息</button>
        <span class="status-line" id="premise-status"></span>
      </div>
    </div>
    <div class="panel">
      <div class="panel-head">故事圣经 <span class="hint">可直接编辑,保存后用于指导后续创作</span></div>
      <textarea id="p-premise" rows="18" class="prose" placeholder="尚未生成">${esc(p.premise)}</textarea>
      <div class="row"><button class="btn" data-action="save-premise">保存设定</button></div>
    </div>
    <pre class="gen-log" id="gen-log" hidden></pre>
  </div>`;
}

async function genPremise(btn) {
  const idea = $("#p-idea").value.trim();
  const genre = $("#p-genre").value.trim();
  if (!idea && !state.project.idea) return toast("请先填写创作意向", "error");
  const ta = $("#p-premise");
  const log = $("#gen-log");
  ta.value = "";
  log.hidden = false;
  log.textContent = "";
  try {
    const done = await streamNDJSON(`/api/projects/${state.project.id}/generate/premise`, { idea, genre }, {
      onDelta: (t) => { ta.value += t; ta.scrollTop = ta.scrollHeight; },
    });
    state.project = done;
    toast("故事圣经已生成并保存", "ok");
  } catch (e) {
    toast("生成失败:" + e.message, "error");
  }
  setStreaming(false, btn);
  renderSidebar();
}

/* ---------------- 视图:角色卡 ---------------- */
const CHAR_FIELDS = [
  ["name", "姓名"], ["role", "定位"], ["appearance", "外貌特征"], ["personality", "性格与说话风格"],
  ["background", "背景经历"], ["goal", "核心目标与动机"], ["arc", "成长弧线"], ["relationships", "人物关系"],
];

function renderCharacters(main) {
  const p = state.project;
  const cards = (p.characters || [])
    .map(
      (c, i) => `<div class="card">
        <div class="card-head"><span class="name">${esc(c.name)}</span><span class="role">${esc(c.role || "配角")}</span></div>
        <dl>
          ${CHAR_FIELDS.slice(2).map(([k, label]) => (c[k] ? `<div><dt>${label}</dt><dd>${esc(c[k])}</dd></div>` : "")).join("")}
        </dl>
        <div class="ops">
          <button class="btn" data-action="edit-character" data-index="${i}">编辑</button>
          <button class="btn danger" data-action="del-character" data-index="${i}">删除</button>
        </div>
      </div>`
    )
    .join("");
  main.innerHTML = `<div class="view">
    <h2>角色卡</h2>
    <p class="sub">基于故事圣经生成主要角色的设定卡,可编辑。写作时 Agent 会自动参考角色卡保持人设一致。</p>
    <div class="panel">
      <div class="row" style="margin-top:0">
        <input id="c-count" type="number" value="5" min="2" max="12" style="width:90px">
        <button class="btn primary" data-action="gen-characters" ${state.streaming ? "disabled" : ""}>✨ 生成角色卡</button>
        <button class="btn" data-action="add-character">＋ 手动新增</button>
        <span class="status-line" id="chars-status"></span>
      </div>
    </div>
    <div class="cards">${cards || '<div class="hint" style="grid-column:1/-1">尚未创建角色,点击上方按钮生成。</div>'}</div>
    <pre class="gen-log" id="gen-log" hidden></pre>
  </div>`;
}

async function genCharacters(btn) {
  const count = parseInt($("#c-count").value) || 5;
  const log = $("#gen-log");
  log.hidden = false;
  log.textContent = "";
  try {
    const done = await streamNDJSON(`/api/projects/${state.project.id}/generate/characters`, { count }, {
      onDelta: (t) => { log.textContent += t; log.scrollTop = log.scrollHeight; },
    });
    state.project = done;
    toast(`已生成 ${done.characters.length} 张角色卡`, "ok");
    renderMain();
  } catch (e) {
    toast("生成失败:" + e.message, "error");
  }
  setStreaming(false, btn);
}

function openCharacterModal(index) {
  state.editingChar = index;
  const c = index >= 0 ? state.project.characters[index] : {};
  $("#ch-modal-title").textContent = index >= 0 ? "编辑角色" : "新增角色";
  $("#character-form").innerHTML = CHAR_FIELDS.map(
    ([k, label]) => `<label>${label}</label><input id="cf-${k}" value="${esc(c[k] || "")}">`
  ).join("");
  $("#modal-character").hidden = false;
}

async function saveCharacterModal() {
  const c = {};
  CHAR_FIELDS.forEach(([k]) => (c[k] = $(`#cf-${k}`).value.trim()));
  if (!c.name) return toast("姓名不能为空", "error");
  const chars = [...(state.project.characters || [])];
  if (state.editingChar >= 0) chars[state.editingChar] = c;
  else chars.push(c);
  state.project = await api(`/api/projects/${state.project.id}`, { method: "PATCH", body: { characters: chars } });
  $("#modal-character").hidden = true;
  toast("角色已保存", "ok");
  renderMain();
}

async function delCharacter(index) {
  if (!confirm("确定删除该角色卡?")) return;
  const chars = state.project.characters.filter((_, i) => i !== index);
  state.project = await api(`/api/projects/${state.project.id}`, { method: "PATCH", body: { characters: chars } });
  renderMain();
}

/* ---------------- 视图:大纲 ---------------- */
function renderOutline(main) {
  const p = state.project;
  const items = (p.outline || [])
    .map(
      (o, i) => `<div class="outline-item" data-i="${i}">
        <div class="oi-head">
          <span class="idx">${esc(o.index)}</span>
          <input class="oi-title" value="${esc(o.title)}" placeholder="章节标题">
          <button class="btn" data-action="goto-write" data-index="${esc(o.index)}">写作 →</button>
        </div>
        <textarea class="oi-summary" rows="2" placeholder="本章情节概要">${esc(o.summary)}</textarea>
        <input class="oi-events" value="${esc(o.key_events || "")}" placeholder="关键事件,分号分隔" style="margin-top:6px">
      </div>`
    )
    .join("");
  main.innerHTML = `<div class="view">
    <h2>章节大纲</h2>
    <p class="sub">生成分章大纲后可自由编辑。写作每章时 Agent 会参考全书大纲与本章计划,保持情节推进不跑偏。</p>
    <div class="panel"><div class="row" style="margin-top:0">
      <input id="o-count" type="number" value="${(p.outline || []).length || 12}" min="3" max="100" style="width:90px">
      <button class="btn primary" data-action="gen-outline" ${state.streaming ? "disabled" : ""}>✨ 生成大纲</button>
      <button class="btn" data-action="save-outline">保存大纲修改</button>
      <span class="status-line" id="outline-status"></span>
    </div></div>
    ${items || '<div class="hint" style="padding:20px 4px">尚未生成大纲。</div>'}
    <pre class="gen-log" id="gen-log" hidden></pre>
  </div>`;
}

async function genOutline(btn) {
  const num = parseInt($("#o-count").value) || 12;
  const log = $("#gen-log");
  log.hidden = false;
  log.textContent = "";
  try {
    const done = await streamNDJSON(`/api/projects/${state.project.id}/generate/outline`, { num_chapters: num }, {
      onDelta: (t) => { log.textContent += t; log.scrollTop = log.scrollHeight; },
    });
    state.project = done;
    toast(`已生成 ${done.outline.length} 章大纲`, "ok");
    renderMain();
  } catch (e) {
    toast("生成失败:" + e.message, "error");
  }
  setStreaming(false, btn);
}

async function saveOutline() {
  const outline = $$(".outline-item").map((el, i) => ({
    index: parseInt($(".idx", el).textContent) || i + 1,
    title: $(".oi-title", el).value.trim(),
    summary: $(".oi-summary", el).value.trim(),
    key_events: $(".oi-events", el).value.trim(),
  }));
  state.project = await api(`/api/projects/${state.project.id}`, { method: "PATCH", body: { outline } });
  toast("大纲已保存", "ok");
  renderMain();
}

/* ---------------- 视图:章节写作 ---------------- */
function chapterEntries() {
  const p = state.project;
  const map = new Map();
  (p.outline || []).forEach((o) =>
    map.set(o.index, { index: o.index, title: o.title, written: false, summary: o.summary })
  );
  (p.chapters || []).forEach((c) => {
    const has = !!((c.content || "").trim());
    const prev = map.get(c.index);
    map.set(c.index, {
      index: c.index,
      title: c.title || prev?.title || `第${c.index}章`,
      written: has,
      summary: c.summary || prev?.summary || "",
      content: c.content || "",
    });
  });
  return [...map.values()].sort((a, b) => a.index - b.index);
}

function renderChapters(main) {
  const entries = chapterEntries();
  if (state.chapterIndex === null || !entries.find((e) => e.index === state.chapterIndex)) {
    state.chapterIndex = entries[0]?.index ?? null;
  }
  const cur = entries.find((e) => e.index === state.chapterIndex);
  const list = entries
    .map(
      (e) => `<li data-action="select-chapter" data-index="${e.index}" class="${e.index === state.chapterIndex ? "active" : ""}">
        <span class="ci">${e.index}</span><span class="ct">${esc(e.title || "未命名")}</span>
        <span class="pill ${e.written ? "done" : "todo"}">${e.written ? "已写" : "待写"}</span>
      </li>`
    )
    .join("");
  main.innerHTML = `<div class="chapters-layout">
    <div class="chapter-list panel">
      <div class="cl-title">章节 <span class="hint">(${entries.filter((e) => e.written).length}/${entries.length} 已写)</span></div>
      <ul>${list || ""}</ul>
      <div class="row"><button class="btn" data-action="add-chapter">＋ 新增章节</button></div>
    </div>
    <div class="editor panel">
      ${cur ? editorHTML(cur) : '<div class="empty"><div class="big">📖</div>请先生成大纲,或手动新增章节</div>'}
    </div>
  </div>`;
  bindEditor();
}

function editorHTML(cur) {
  const content = cur.content || "";
  const ch = (state.project.chapters || []).find((c) => c.index === cur.index) || {};
  return `
    <div class="editor-head">
      <input id="ch-title" value="${esc(cur.title)}">
      <span class="meta" id="ch-meta">约 ${content.length} 字${state.snapshot ? " · 可撤销" : ""}</span>
    </div>
    <textarea id="ch-content" rows="20" class="prose" placeholder="点击下方「AI 写作」,Agent 将根据故事圣经、角色卡、大纲与前文摘要写出本章…">${esc(content)}</textarea>
    <div class="summary-box">
      <label>本章摘要(写作下一章时自动作为前文记忆)</label>
      <textarea id="ch-summary" rows="3">${esc(ch.summary || "")}</textarea>
    </div>
    <div class="toolbar">
      <button class="btn primary" data-action="ch-write" ${state.streaming ? "disabled" : ""}>✍ AI 写作</button>
      <button class="btn" data-action="ch-continue" ${state.streaming ? "disabled" : ""}>➡ AI 续写</button>
      <button class="btn" data-action="ch-polish" ${state.streaming ? "disabled" : ""}>🪄 AI 润色</button>
      <button class="btn" data-action="ch-summary">📋 生成摘要</button>
      <span class="sep"></span>
      ${state.snapshot ? '<button class="btn danger" data-action="ch-undo">↩ 撤销上一次 AI 生成</button>' : ""}
      <button class="btn" data-action="ch-save">💾 保存</button>
      <button class="btn danger" data-action="del-chapter">删除本章</button>
    </div>
    <div class="row">
      <input id="ch-instruction" placeholder="可选:本轮 AI 的特别要求,如「加强打斗场面的细节」">
      <span class="status-line" id="ch-status"></span>
    </div>`;
}

function bindEditor() {
  const content = $("#ch-content");
  if (!content) return;
  content.addEventListener("input", () => {
    state.dirty = true;
    updateMeta();
  });
  $("#ch-title")?.addEventListener("input", () => (state.dirty = true));
  $("#ch-summary")?.addEventListener("input", () => (state.dirty = true));
}

function updateMeta() {
  const el = $("#ch-meta");
  if (el && $("#ch-content")) el.textContent = `约 ${$("#ch-content").value.length} 字${state.dirty ? " · 未保存" : ""}`;
}

async function editorStream(action, mode, btn) {
  const index = state.chapterIndex;
  const ta = $("#ch-content");
  const instruction = $("#ch-instruction")?.value.trim() || "";
  if (mode === "continue" && !ta.value.trim()) return toast("本章还没有正文,请先「AI 写作」", "error");
  if (mode !== "continue") state.snapshot = ta.value; // 可撤销
  if (mode === "continue" && ta.value.trim()) ta.value += "\n\n";
  else ta.value = "";
  state.dirty = true;
  try {
    const done = await streamNDJSON(`/api/projects/${state.project.id}/chapters/${index}/${action}`, { instruction }, {
      onDelta: (t) => { ta.value += t; ta.scrollTop = ta.scrollHeight; updateMeta(); },
      onStatus: (s) => { $("#ch-status").textContent = s; },
    });
    state.project = done;
    state.dirty = false;
    toast("本章已保存", "ok");
    renderMain();
  } catch (e) {
    toast("生成失败:" + e.message, "error");
    updateMeta();
  }
  setStreaming(false, btn);
  const st = $("#ch-status");
  if (st) st.textContent = "";
}

function undoSnapshot() {
  if (state.snapshot === null) return;
  $("#ch-content").value = state.snapshot;
  state.snapshot = null;
  state.dirty = true;
  renderMain();
}

/* ---------------- 全局事件 ---------------- */
function bindGlobal() {
  document.addEventListener("click", async (ev) => {
    const closeBtn = ev.target.closest("[data-close]");
    if (closeBtn) { $("#" + closeBtn.dataset.close).hidden = true; return; }
    if (ev.target.classList.contains("modal-backdrop")) { ev.target.hidden = true; return; }

    const projLi = ev.target.closest("#project-list li[data-id]");
    if (projLi && !ev.target.dataset.action) { openProject(projLi.dataset.id); return; }
    const stepLi = ev.target.closest("#steps li[data-view]");
    if (stepLi) { setView(stepLi.dataset.view); return; }

    const el = ev.target.closest("[data-action]");
    if (!el) return;
    const act = el.dataset.action;
    const idx = parseInt(el.dataset.index);
    try {
      switch (act) {
        case "del-project": {
          if (!confirm("确定删除整部小说?不可恢复!")) return;
          await api(`/api/projects/${el.dataset.id}`, { method: "DELETE" });
          if (state.project?.id === el.dataset.id) state.project = null;
          await refreshProjects();
          renderMain();
          toast("已删除", "ok");
          break;
        }
        case "gen-premise": if (!guard(el)) genPremise(el); break;
        case "save-meta": {
          state.project = await api(`/api/projects/${state.project.id}`, {
            method: "PATCH",
            body: { title: $("#p-title").value.trim() || "未命名小说", idea: $("#p-idea").value.trim(), genre: $("#p-genre").value.trim() },
          });
          toast("已保存", "ok"); await refreshProjects(); break;
        }
        case "save-premise": {
          state.project = await api(`/api/projects/${state.project.id}`, { method: "PATCH", body: { premise: $("#p-premise").value } });
          toast("设定已保存", "ok"); break;
        }
        case "gen-characters": if (!guard(el)) genCharacters(el); break;
        case "add-character": openCharacterModal(-1); break;
        case "edit-character": openCharacterModal(idx); break;
        case "del-character": delCharacter(idx); break;
        case "gen-outline": if (!guard(el)) genOutline(el); break;
        case "save-outline": saveOutline(); break;
        case "goto-write": setView("chapters", idx); break;
        case "select-chapter": setView("chapters", idx); break;
        case "add-chapter": {
          state.project = await api(`/api/projects/${state.project.id}/chapters`, { method: "POST", body: { title: "" } });
          state.chapterIndex = Math.max(...(state.project.chapters || [{ index: 0 }]).map((c) => c.index));
          renderMain(); break;
        }
        case "del-chapter": {
          if (!confirm("确定删除本章?")) return;
          state.project = await api(`/api/projects/${state.project.id}/chapters/${state.chapterIndex}`, { method: "DELETE" });
          state.chapterIndex = null; renderMain(); break;
        }
        case "ch-write": if (!guard(el)) editorStream("write", "write", el); break;
        case "ch-continue": if (!guard(el)) editorStream("continue", "continue", el); break;
        case "ch-polish": if (!guard(el)) editorStream("polish", "polish", el); break;
        case "ch-undo": undoSnapshot(); break;
        case "ch-save": {
          state.project = await api(`/api/projects/${state.project.id}/chapters/${state.chapterIndex}`, {
            method: "PUT",
            body: { title: $("#ch-title").value.trim(), content: $("#ch-content").value, summary: $("#ch-summary").value },
          });
          state.dirty = false; toast("已保存", "ok"); renderMain(); break;
        }
        case "ch-summary": {
          if (state.streaming) return toast("请等待当前生成完成", "muted");
          if (!$("#ch-content").value.trim()) return toast("本章还没有正文", "error");
          el.disabled = true; el.dataset.orig = el.innerHTML;
          el.innerHTML = '<span class="spin"></span>生成中…';
          try {
            state.project = await api(`/api/projects/${state.project.id}/chapters/${state.chapterIndex}/summary`, { method: "POST" });
            toast("摘要已生成", "ok"); renderMain();
          } catch (e) { toast("失败:" + e.message, "error"); }
          el.innerHTML = el.dataset.orig; el.disabled = false;
          break;
        }
      }
    } catch (e) {
      toast("操作失败:" + e.message, "error");
    }
  });

  $("#btn-new").addEventListener("click", () => {
    $("#wizard-steps").hidden = true;
    $("#wizard-steps").innerHTML = "";
    $("#wizard-log").hidden = true;
    $("#wizard-log").textContent = "";
    $("#btn-wizard-run").disabled = false;
    $("#modal-new").hidden = false;
  });

  $("#btn-settings").addEventListener("click", () => {
    const s = state.settings || {};
    $("#st-provider").value = s.provider || "openai";
    $("#st-model").value = s.model || "";
    $("#st-baseurl").value = s.base_url || "";
    $("#st-apikey").value = s.api_key || "";
    $("#st-words").value = s.chapter_words ?? 2500;
    $("#st-temp").value = s.temperature ?? 0.8;
    $("#modal-settings").hidden = false;
  });
  $("#llm-badge").addEventListener("click", () => $("#btn-settings").click());

  $("#btn-save-settings").addEventListener("click", async () => {
    try {
      state.settings = await api("/api/settings", {
        method: "PUT",
        body: {
          provider: $("#st-provider").value,
          model: $("#st-model").value.trim(),
          base_url: $("#st-baseurl").value.trim(),
          api_key: $("#st-apikey").value.trim(),
          chapter_words: parseInt($("#st-words").value) || 2500,
          temperature: parseFloat($("#st-temp").value) || 0.8,
        },
      });
      updateBadge();
      $("#modal-settings").hidden = true;
      toast("设置已保存", "ok");
    } catch (e) {
      toast("保存失败:" + e.message, "error");
    }
  });

  $("#btn-save-character").addEventListener("click", saveCharacterModal);
  $("#btn-wizard-run").addEventListener("click", runWizard);
  window.addEventListener("beforeunload", (e) => {
    if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
  });
}

/* ---------------- 创作向导 ---------------- */
async function runWizard() {
  const idea = $("#wz-idea").value.trim();
  if (!idea) return toast("请填写创作意向", "error");
  const title = $("#wz-title").value.trim() || "未命名小说";
  const genre = $("#wz-genre").value.trim();
  const count = parseInt($("#wz-chars").value) || 5;
  const num = parseInt($("#wz-outline").value) || 12;
  const auto = $("#wz-auto").checked;

  const steps = ["创建项目", "生成故事圣经", "生成角色卡", "生成分章大纲"];
  if (auto) steps.push("撰写第 1 章");
  const wsEl = $("#wizard-steps");
  wsEl.hidden = false;
  wsEl.innerHTML = steps.map((s, i) => `<div class="ws" id="ws-${i}"><span class="dot"></span>${esc(s)}</div>`).join("");
  const log = $("#wizard-log");
  log.hidden = false;
  log.textContent = "";
  const btn = $("#btn-wizard-run");
  btn.disabled = true;

  const setStep = (i, cls) => { const el = $(`#ws-${i}`); el.className = `ws ${cls}`; };
  const onDelta = (t) => { log.textContent += t; log.scrollTop = log.scrollHeight; };

  try {
    setStep(0, "run");
    let project = await api("/api/projects", { method: "POST", body: { title, idea, genre } });
    setStep(0, "ok");

    setStep(1, "run");
    project = await streamNDJSON(`/api/projects/${project.id}/generate/premise`, { idea, genre }, { onDelta });
    setStep(1, "ok");
    log.textContent += "\n\n—————\n\n";

    setStep(2, "run");
    project = await streamNDJSON(`/api/projects/${project.id}/generate/characters`, { count }, { onDelta });
    setStep(2, "ok");
    log.textContent += "\n\n—————\n\n";

    setStep(3, "run");
    project = await streamNDJSON(`/api/projects/${project.id}/generate/outline`, { num_chapters: num }, { onDelta });
    setStep(3, "ok");

    if (auto) {
      log.textContent += "\n\n—————\n\n";
      setStep(4, "run");
      project = await streamNDJSON(`/api/projects/${project.id}/chapters/1/write`, { instruction: "" }, {
        onDelta,
        onStatus: (s) => { log.textContent += `\n[${s}]\n`; },
      });
      setStep(4, "ok");
    }

    state.project = project;
    state.view = auto ? "chapters" : "premise";
    state.chapterIndex = auto ? 1 : null;
    await refreshProjects();
    $("#modal-new").hidden = true;
    renderAll();
    toast("开篇完成,开始你的长篇之旅吧!", "ok");
  } catch (e) {
    const running = $$("#wizard-steps .ws.run")[0];
    if (running) running.className = "ws err";
    toast("向导中断:" + e.message, "error");
  }
  btn.disabled = false;
}

init();
