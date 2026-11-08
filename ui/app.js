// 路远桌面端 · 新版面板 v20 · 超级终端 + 模块分页（v15 设计落地）
// 结构合同：路远桌面端_v14_实现说明.md + _drafts/ui-redesign-v15.html（UI 会话 2026-09-08 夜）
// 本文件：helpers + 全局状态 + 壳（rail/预览/终端/录音/键盘/版本自检）+ 笔记模块 + 回收站
// 记账/课程/收件夹/人脉/日记/抽屉/终端路由在 /ui/modules.js
"use strict";
const $ = (s) => document.querySelector(s);
/* URL 参数读取（2026-10-30）：只认白名单里的几个（embed / dark / entry），其余一律忽略。
   桌面壳内嵌与截图验收都用它，不写任何状态、不影响正常使用。 */
function urlParam(k) {
  try { return new URLSearchParams(location.search).get(k) || ""; } catch (e) { return ""; }
}

/* ---------------- 图标（木案风线条 SVG，stroke 1.6） ---------------- */
const ICONS = {
  note: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="3.5" width="15" height="15" rx="2"/><path d="M6.5 8h9M6.5 11.5h9M6.5 15h6"/></svg>',
  ledger: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 7v9a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7"/><path d="M3.5 7l1.6-3h12l1.6 3"/><circle cx="8.2" cy="12.5" r="1.4"/><circle cx="13.8" cy="12.5" r="1.4"/></svg>',
  course: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4.5" width="15" height="14" rx="2"/><path d="M7 2.8v3M15 2.8v3M3.5 9.5h15"/><path d="M7 13h2.5M7 15.8h2.5M12.5 13h2.5"/></svg>',
  contact: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="8.6" cy="7.6" r="2.8"/><path d="M3.5 17.5a5.1 5.1 0 0 1 10.2 0"/><circle cx="15.6" cy="9" r="2.2"/><path d="M14.6 13.6a4.4 4.4 0 0 1 4 4.4"/></svg>',
  journal: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 3.5h9.5a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5.5a1.6 1.6 0 0 1-1.6-1.6V5.1a1.6 1.6 0 0 1 1.6-1.6z"/><path d="M7 2.5v17"/></svg>',
  chat: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M11 3.5c4.7 0 8.5 3 8.5 6.8s-3.8 6.8-8.5 6.8c-.9 0-1.8-.1-2.6-.3L4.2 18.5l.8-3.4C3.4 13.9 2.5 12.2 2.5 10.3 2.5 6.5 6.3 3.5 11 3.5z"/><path d="M7.5 9.2h.01M11 9.2h.01M14.5 9.2h.01"/></svg>',
  todo: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="3.5" width="15" height="15" rx="3"/><path d="M7 11.2l2.6 2.6L15 8.4"/></svg>',
  report: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M18.5 10.3c0 3.8-3.4 6.8-7.5 6.8-.9 0-1.8-.1-2.6-.4l-4 1.8.8-3.3c-1.5-1.2-2.2-3-2.2-4.9 0-3.8 3.4-6.8 7.5-6.8s8 3 8 6.8z"/><path d="M7.5 8.6h7M7.5 11.6h4.5"/></svg>',
  ask: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="5.5"/><path d="M14.2 14.2L18 18"/><path d="M8.2 8.6a1.9 1.9 0 0 1 3.7.6c0 1.2-1.8 1.4-1.8 2.6"/><path d="M10.1 13.6h.01"/></svg>',
  settings: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="2.6"/><path d="M11 3.2v2.2M11 16.6v2.2M18.8 11h-2.2M5.4 11H3.2M16.8 5.2l-1.6 1.6M6.8 15.2l-1.6 1.6M16.8 16.8l-1.6-1.6M6.8 6.8L5.2 5.2"/></svg>',
  csu: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4L2.8 8.2 11 12.4l8.2-4.2L11 4z"/><path d="M6.2 10.4v4.1c0 1.3 2.1 2.6 4.8 2.6s4.8-1.3 4.8-2.6v-4.1"/><path d="M19.2 8.8v4.7"/></svg>',
  spark: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;vertical-align:-2px"><path d="M11 2.8l1.9 5 5 1.9-5 1.9-1.9 5-1.9-5-5-1.9 5-1.9 1.9-5z"/><path d="M17.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2z"/></svg>',
  bell: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;vertical-align:-2px"><path d="M11 3.2a5 5 0 0 1 5 5v3.3l1.4 2.5a.7.7 0 0 1-.6 1H5.2a.7.7 0 0 1-.6-1L6 11.5V8.2a5 5 0 0 1 5-5z"/><path d="M9.3 17.8a1.8 1.8 0 0 0 3.4 0"/></svg>',
  trash: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 6.5h13M8.5 6.5V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 13.5 5v1.5"/><path d="M6.5 6.5l.9 10a1.5 1.5 0 0 0 1.5 1.4h4.2a1.5 1.5 0 0 0 1.5-1.4l.9-10"/></svg>',
  search: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="10" cy="10" r="5.5"/><path d="M14.2 14.2L18 18"/></svg>',
  cal: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><rect x="3.5" y="4.5" width="15" height="14" rx="2"/><path d="M7 2.8v3M15 2.8v3M3.5 9.5h15"/></svg>',
  book: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5.5C9.5 4 7.5 3.5 4 3.5v13c3.5 0 5.5.5 7 2 1.5-1.5 3.5-2 7-2v-13c-3.5 0-5.5.5-7 2z"/><path d="M11 5.5v15"/></svg>',
  plus: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M11 5v12M5 11h12"/></svg>',
  image: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4.5" width="15" height="13" rx="2"/><circle cx="8.3" cy="9" r="1.4"/><path d="M4.5 15.5l4.2-4 3.3 3 2.5-2.3 3 2.8"/></svg>',
  trashs: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4.5 6.5h13M9 6.5V5.2A1.2 1.2 0 0 1 10.2 4h1.6A1.2 1.2 0 0 1 13 5.2v1.3"/><path d="M6.5 6.5l.8 10h7.4l.8-10"/></svg>',
  smile: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7.5"/><path d="M8.2 13.2a3.6 3.6 0 0 0 5.6 0"/><path d="M8.3 9h.01M13.7 9h.01"/></svg>',
  inbox: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 12.5h4l1.5 2.5h4l1.5-2.5h4"/><path d="M5.5 4.5h11l2 8v4a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5v-4z"/></svg>',
  filter: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3.6 5.2h14.8l-5.7 6.7v4.6l-3.5 1.7v-6.3z"/></svg>',
};

/* ---------------- 基础 helpers（沿用旧面板战斗验证过的） ---------------- */
const statusEl = $("#status");
let statusExpiry = 0;
function setStatus(msg, ttl) {
  statusEl.textContent = msg || "";
  statusEl.title = msg || "";   // 2026-10-30：状态栏固定一行省略号，完整句子靠悬停
  statusExpiry = msg ? Date.now() + (ttl || 6000) : 0;
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(await humanError(r));
  return r.json();
}
async function humanError(r) {
  let code = "", msg = "";
  try {
    const data = JSON.parse(await r.text());
    if (data && typeof data === "object") { code = data.error || ""; msg = typeof data.msg === "string" ? data.msg : ""; }
  } catch {}
  const byCode = {
    "empty": "内容是空的，先写点什么。",
    "not_found": "要找的东西不存在（可能已被删除）。",
    "bad time": "时间格式没认出来，换个写法试试。",
    "bad list": "没认出要处理哪些条目。",
    "ollama_off": "智能功能没开（Ollama 未运行，点左下角徽标可拉起）。"
  };
  const byStatus = { 400: "请求不对，没存上。", 404: "要找的东西不存在（可能已被删除）。", 500: "路远服务内部出错，稍后再试。", 502: "服务暂时不可用，稍后再试。", 503: "服务暂时不可用，稍后再试。" };
  return msg || byCode[code] || byStatus[r.status] || ("操作失败（错误码 " + r.status + "）。");
}
window.addEventListener("unhandledrejection", (e) => {
  setStatus("出了点小问题：" + (e.reason && e.reason.message ? e.reason.message : e.reason));
});
function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function hi(text) {
  const esc = escapeHtml(text);
  const q = state.query && state.module === "note" ? escapeHtml(state.query) : "";
  return q ? esc.split(q).join("<mark>" + q + "</mark>") : esc;
}
/* 2026-10-29 复查：全站时间口径统一成微信式（今天只给时:分 / 昨天 / M月D日 / 往年带年）。
   原先是 toLocaleString，卡片上是「10/11 18:56」、组头是「2026.10.11」、日记是「2026/10/29」，
   同一屏三种写法。 */
function fmtClock(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function fmtTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return String(iso || "");
  const now = new Date();
  const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const hm = fmtClock(iso);
  if (sameDay(d, now)) return hm;
  if (sameDay(d, new Date(now.getTime() - 86400000))) return "昨天 " + hm;
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}
function dateKey(iso) {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function relDateLabel(key) {
  const now = new Date();
  const t = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yst = new Date(t.getTime() - 86400000);
  if (key === dateKey(t)) return "今天";
  if (key === dateKey(yst)) return "昨天";
  const d = new Date(key + "T00:00:00");
  const days7 = new Date(t.getTime() - 6 * 86400000);
  if (d >= days7 && d < t) return ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][d.getDay()];
  // 2026-10-29 复查：原来是 "2026.10.11" 这种点分隔，和其他位置的中文写法两套
  if (d.getFullYear() === t.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日`;
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}
function firstSentence(text) { return (text.split(/[。！？!?\n]/)[0] || text).trim(); }
function noteTitle(text) { const s = firstSentence(text); return s.length > 14 ? s.slice(0, 14) + "…" : (s || "（无标题）"); }
function noteSummary(text) {
  const s = firstSentence(text);
  const rest = text.slice(s.length).replace(/^[。！？!?\n\s]+/, "").trim();
  if (!rest) return "";
  return rest.length > 42 ? rest.slice(0, 42) + "…" : rest;
}
function toLocalISO(d) {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const pad = n => String(Math.abs(n)).padStart(2, "0");
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":00" + sign + pad(off / 60) + ":" + pad(off % 60);
}
function presetISO(kind) {
  const d = new Date();
  if (kind === "1h") d.setHours(d.getHours() + 1);
  else if (kind === "3h") d.setHours(d.getHours() + 3);
  else if (kind === "tm9") { d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); }
  d.setSeconds(0, 0);
  return toLocalISO(d);
}
/* 心情字形是「用户笔记正文里的标记」，不是 UI 图标——A4 红线（2026-09-14）要求 UI 源码不出现
   emoji 本体，这里用 \u 转义保持功能不变（匹配逻辑与渲染色完全一致）。 */
const MOODS = { "\u{1F60A}": "#46d39a", "\u{1F621}": "#ff6b6b", "\u{1F62E}": "#5a96ff", "\u{1F614}": "#9d7bd8", "\u{1F630}": "#ffce5a", "\u{1F922}": "#7bc86c" };
const MOOD_RE = /[\u{1F60A}\u{1F621}\u{1F62E}\u{1F614}\u{1F630}\u{1F922}]/gu;
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");

/* ---------------- 全局状态 ---------------- */
const state = {
  module: "note",       // note|ledger|course|contact|journal|trash
  selected: new Set(),
  collapsed: new Set(),
  expanded: new Set(),
  query: "",
  tag: "",
  src: "",
  pickerId: null,
  jumpDate: null,
  flashId: null,
  pending: null,
  organizing: null,
  categories: null,
  diaryImages: [],
  workspaceExpanded: true,   // v42 木案式固定工作台：始终展开
  ctGroup: "",          // 人脉页：当前分组（""=全部）
  ctSort: "",           // 人脉页排序：""=自动 / "sid"=学号 / "letter"=拼音
};
let currentNotes = [];
let editing = false;
let ctDetailId = null;
let currentContacts = [];

const CATEGORIES_FALLBACK = ["待办", "购物", "想法", "日常", "写作素材"];

/* 内建确认卡（2026-10-30 通宵批）：全站的 window.confirm 全部换掉。
   ①原生 confirm 样式跟整站全不相干（系统灰框），和「瓷片纸面」不是一个世界；
   ②桌面壳层要注入禁用浏览器对话框/右键，一旦被拦，用户看到的就是「点了没反应」。
   这里用项目自己的 #modalWrap + #modalCard，返回 Promise<boolean>，点遮罩 = 取消。 */
let _acToken = 0;
function askConfirm(title, detail, okText, danger) {
  return new Promise(resolve => {
    const wrap = $("#modalWrap"), card = $("#modalCard");
    if (!wrap || !card) { resolve(true); return; }      // 极端情况别把主流程卡死
    const tok = ++_acToken;
    card.innerHTML = `<div class="mc-title">${escapeHtml(title)}</div>
      ${detail ? `<div class="hint" style="padding:0 0 12px">${escapeHtml(detail)}</div>` : ""}
      <div class="mc-btns"><button class="tool-btn" id="acNo">取消</button>
      <button class="${danger ? "batch-btn danger" : "batch-btn"}" id="acYes">${escapeHtml(okText || "确认")}</button></div>`;
    wrap.classList.add("show");
    const done = v => {
      if (tok !== _acToken) return;                     // 旧对话框的残留回调，直接哑掉
      _acToken++;
      wrap.classList.remove("show");
      document.removeEventListener("keydown", onKey, true);
      resolve(v);
    };
    const onKey = e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(false); } };
    document.addEventListener("keydown", onKey, true);
    const yes = $("#acYes"), no = $("#acNo");
    if (yes) yes.addEventListener("click", () => done(true), { once: true });
    if (no) no.addEventListener("click", () => done(false), { once: true });
    wrap.addEventListener("click", e => { if (e.target === wrap) done(false); });
  });
}
/* 统一失败态：一句人话 + 重试（原来各页失败就一行灰字，只能靠自己切走再切回来） */
function failState(msg, mod) {
  return `<div class="fail">${escapeHtml(msg)}<div class="fail-act"><button class="tool-btn" data-retry="${escapeHtml(mod || state.module)}">重试</button></div></div>`;
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-retry]");
  if (b) {
    const mod = b.getAttribute("data-retry");
    if (RENDERERS[mod]) RENDERERS[mod](false);
    return;
  }
  /* 空态里的动作（2026-10-30 通宵批）：清除搜索 / 聚焦录入 / 回到最新 / 跳到某页 */
  if (e.target.closest("[data-clearq]")) {
    state.query = "";
    const inp = $("#modSearch") || $("#trashSearch");
    if (inp) inp.value = "";
    if (state.module === "trash") renderTrashList(false); else loadNotes();
    return;
  }
  if (e.target.closest("[data-focus-quick]")) {
    expandWorkspace();
    const q = $("#quick");
    if (q) { q.focus(); setStatus("想记什么？直接打，回车归类。", 4000); }
    return;
  }
  if (e.target.closest("[data-backlatest]")) { state.jumpDate = null; loadNotes(); return; }
  const g = e.target.closest("[data-goto]");
  if (g) { switchModule(g.getAttribute("data-goto")); return; }
});

/* toast */
function showToast(msg, color = "green") {
  const t = document.createElement("div");
  t.className = "toast";
  t.innerHTML = `<span class="check ${color}">✓</span><span>${escapeHtml(msg)}</span>`;
  $("#toastBox").appendChild(t);
  requestAnimationFrame(() => t.classList.add("show"));
  setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.remove(), 400); }, 2600);
}
/* g03 数字增长 */
function countUp(el, target, prefix = "", dur = 650) {
  if (REDUCED.matches) { el.textContent = prefix + Math.round(target); return; }
  const t0 = performance.now();
  (function step(t) {
    const p = Math.min(1, (t - t0) / dur);
    el.textContent = prefix + Math.round(target * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(step);
  })(t0);
}

/* ---------------- 壳：rail / 模块切换 / 展开收起 ---------------- */
/* 2026-10-30 通宵批：顺序 = 侧栏从上到下的视觉顺序。
   原来数组是 journal→note→todo→report→contact→ledger→course→…，和左侧导航
   「笔记/日记/待办/记账/课务/人脉/学业/对话/路远远/问路远」完全对不上，
   连按 ←/→ 切页时跳的顺序和眼睛看到的都是两码事。现在按分组一一对应。 */
const MODULES = [
  { id: "note", label: "笔记" },
  { id: "journal", label: "日记" },
  { id: "todo", label: "待办" },
  { id: "ledger", label: "记账" },
  /* 「课务」= 8790 那套教务系统（课表/作业/成绩）；「学业」= 校历·速查·综测台账。
     两边原来都挂着「校历」「成绩·学业」，两个顶层入口点下去像同一页。
     分工：课务只管上课这件事，校历归学业；「成绩·学业」改名「成绩」，别再跟「学业」撞名。 */
  { id: "course", label: "课务", children: [
    { id: "today", label: "今日" },
    { id: "timetable", label: "课表" },
    { id: "homework", label: "作业" },
    { id: "grades", label: "成绩" },
  ] },
  { id: "contact", label: "人脉" },
  { id: "csu", label: "学业" },
  /* 2026-10-30 双入口批：这三个原来跟笔记待办并列挂在「智能」分组里（还撞名：路远/路远远/问路远）。
     现在归到「路远」这个平级大入口下，作为它的三个视图：对话=主视图、汇报=汇报史、问答=问答。
     模块本体与 switchModule 完全复用，只换归属与叫法。 */
  { id: "chat", label: "对话" },
  { id: "report", label: "汇报" },
  { id: "ask", label: "问答" },
  { id: "trash", label: "回收站" },
  { id: "settings", label: "设置" },
];
const MOD_LABEL = { note: "笔记", ledger: "记账", course: "课务", contact: "人脉", journal: "日记", trash: "回收站", chat: "对话", csu: "学业", todo: "待办", report: "汇报", ask: "问答", settings: "设置" };
const rail = $("#rail"), railIndicator = $("#railIndicator"), panelContent = $("#panelContent");
const moduleList = $("#moduleList"), modToolbar = $("#modToolbar"), modChips = $("#modChips");
const batchBar = $("#batchBar"), batchCount = $("#batchCount");
const batchDeleteBtn = $("#batchDelete"), batchRestoreBtn = $("#batchRestore");
const batchCopyBtn = $("#batchCopy"), batchExportBtn = $("#batchExport");

MODULES.forEach(m => {
  const b = document.createElement("button");
  b.className = "module-btn" + (m.id === state.module ? " active" : "") + (m.children ? " has-sub" : "");
  b.dataset.mod = m.id;
  b.innerHTML = ICONS[m.id] + `<span>${m.label}</span>` + (m.children ? `<i class="caret"></i>` : "");
  const host = [...rail.querySelectorAll(".nav-items")]
    .find(el => (el.dataset.mods || "").split(",").includes(m.id));
  (host || rail).appendChild(b);
  if (m.children) {   // 子界面栏（目前只有「课务」用得上）
    const sub = document.createElement("div");
    sub.className = "nav-sub";
    sub.dataset.subOf = m.id;
    sub.innerHTML = m.children.map(c =>
      `<button class="nav-subitem" data-mod="${m.id}" data-view="${c.id}"><span>${c.label}</span></button>`).join("");
    (host || rail).appendChild(sub);
  }
});
/* 子项栏跟着父项走：父项是当前模块才展开；「课务」再高亮当前子页 */
function syncRailSubs() {
  rail.querySelectorAll(".module-btn.has-sub").forEach(b => {
    const on = b.dataset.mod === state.module;
    b.classList.toggle("open", on);
    const s = rail.querySelector('.nav-sub[data-sub-of="' + b.dataset.mod + '"]');
    if (s) s.classList.toggle("show", on);
  });
  markKeiwuSub();
  updateRailIndicator();
}
function markKeiwuSub() {
  const v = (typeof keiwuView === "function") ? keiwuView() : null;
  rail.querySelectorAll(".nav-subitem").forEach(s =>
    s.classList.toggle("on", state.module === "course" && s.dataset.view === v));
}
function updateRailIndicator() {
  const active = rail.querySelector(".module-btn.active");
  if (!active) return;
  const h = active.offsetHeight;
  const ih = Math.min(30, h - 6);
  railIndicator.style.height = ih + "px";
  railIndicator.style.top = (active.offsetTop + (h - ih) / 2) + "px";
}
/* 各模块渲染器注册表（modules.js 注册） */
const RENDERERS = {};   // id -> async () => 渲染列表
const TOOLBARS = {};    // id -> () => 渲染工具栏

/* ---------------- 双入口：路远（AI） / 工作台（2026-10-30 双入口批） ----------------
   路河拍板：「路远 AI 应该和工作台是两个并行等级的大入口，而不是 AI 被归入工作台里面」。
   这里只做「归属与切换」——RENDERERS / TOOLBARS / switchModule / MODULES 全部复用，
   模块内部逻辑一个字没改；本段只负责 ①两套导航分区显隐 ②入口按钮选中态
   ③跨入口时落到该入口的默认页（路远→对话，工作台→笔记）。 */
const AI_MODULES = ["chat", "report", "ask"];
const ENTRY_DEFAULT = { ai: "chat", work: "note" };
let ENTRY = "work";
function entryOf(mod) { return AI_MODULES.includes(mod) ? "ai" : "work"; }
function paintEntry(entry) {
  ENTRY = entry === "ai" ? "ai" : "work";
  document.body.classList.toggle("entry-ai", ENTRY === "ai");
  document.body.classList.toggle("entry-work", ENTRY === "work");
  document.querySelectorAll("#entrySwitch .entry-btn").forEach(b => {
    const on = b.dataset.entry === ENTRY;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  const bar = document.getElementById("aiStatusBar");
  if (bar) bar.hidden = ENTRY !== "ai";
  if (ENTRY === "ai") pollAiStatus();
  if (typeof updateRailIndicator === "function") setTimeout(updateRailIndicator, 0);
}
function setEntry(entry) {
  const want = entry === "ai" ? "ai" : "work";
  if (entryOf(state.module) !== want) {
    switchModule(ENTRY_DEFAULT[want], { force: true });   // switchModule 内部会 paintEntry
    return;
  }
  paintEntry(want);   // 已经在正确的入口里：只更新选中态，不打断眼前这页
}
(function bindEntrySwitch() {
  const box = document.getElementById("entrySwitch");
  if (!box) return;
  box.addEventListener("click", e => {
    const b = e.target.closest(".entry-btn");
    if (b) setEntry(b.dataset.entry);
  });
})();
/* 路远在线状态（3927）：没跑就灰点 + 一句人话，别让人对着空白页猜 */
let _aiAlive = null;
async function pollAiStatus() {
  const bar = document.getElementById("aiStatusBar");
  if (!bar) return;
  const stEl = bar.querySelector(".as-state");
  const metaEl = document.getElementById("aiStatusMeta");
  let alive = false;
  try {
    await fetch("http://127.0.0.1:3927/", { mode: "no-cors", cache: "no-store" });
    alive = true;
  } catch (e) { alive = false; }   // 连接被拒 = 没在跑
  _aiAlive = alive;
  bar.classList.toggle("on", alive);
  if (stEl) stEl.textContent = alive ? "· 在线" : "· 没在跑";
  if (metaEl) {
    let unread = null;
    try { unread = (await api("/api/reports/badge")).unread; } catch (e) {}
    metaEl.textContent = alive
      ? ((unread != null ? "未读汇报 " + unread + " · " : "") + "汇报 / 整理 / 提醒都在跑")
      : "3927 没起来：汇报暂停，对话和问答照常用";
  }
}

let _switchTimer = null;
/* 侧栏选中态只在这一处改（2026-10-30 通宵批）：设置是「抽屉型」页面，
   点侧栏「设置」时抽屉从右边滑出、但导航高亮原来还停在上一页 —— 看起来像没反应。
   现在高亮跟着走，抽屉关掉再回到真正所在的模块。 */
function markRailActive(mod) {
  document.querySelectorAll(".module-btn").forEach(b => b.classList.toggle("active", b.dataset.mod === mod));
}
function switchModule(mod, opts = {}) {
  if (!MOD_LABEL[mod]) return;
  if (mod === "settings") {
    /* typeof 守卫是必须的：modules.js 在本文件之后才加载，而带 #page= 的深链会在启动阶段
       就走到这里 —— 原来直接写 `openDrawerByName && openDrawerByName(...)`，读的是裸标识符，
       未定义时抛 ReferenceError（2026-10-30 实测：冷启动带 #page=diary 时整段启动被截断，
       今日卡/轮询全没跑起来）。 */
    if (typeof openDrawerByName === "function") openDrawerByName("set");
    markRailActive("settings");
    syncRailSubs();
    paintEntry("work");   // 设置属工作台，AI 入口下打开抽屉也要把分区切回来
    return;
  }
  if (mod === "ask") { /* 问路远页 */ }
  if (mod === state.module && !opts.force) return;
  if (typeof closeCtDetail === "function") closeCtDetail();
  const from = MODULES.findIndex(m => m.id === state.module), to = MODULES.findIndex(m => m.id === mod);
  if (to !== from) panelContent.style.setProperty("--dir", to > from ? 1 : -1);
  state.module = mod;
  state.selected.clear();
  markRailActive(mod);
  syncRailSubs();
  paintEntry(entryOf(mod));   // 双入口：跟着模块走（对话/汇报/问答 → 路远，其余 → 工作台）
  panelContent.classList.add("switch-out");
  /* 2026-10-29 体检批：连点页签原先会叠加多个 setTimeout，先发起的页面数据晚到、
     把眼前这页盖掉（实测：点人脉后立刻点记账，记账页里躺着人脉名单）。
     现在只留一个待执行定时器，且执行时再确认「还是不是当前页」。 */
  if (_switchTimer) { clearTimeout(_switchTimer); _switchTimer = null; }
  _switchTimer = setTimeout(() => {
    _switchTimer = null;
    if (state.module !== mod) return;   // 已被后来的切换取代，这次渲染作废
    renderModule(mod, true);
    panelContent.classList.remove("switch-out");
    panelContent.classList.add("switch-in");
    setTimeout(() => panelContent.classList.remove("switch-in"), 340);
  }, REDUCED.matches ? 0 : 170);
}
function renderToolbar(mod) {
  // chips 行：2026-09-15 起笔记页不再常驻（筛选搬进工具栏「筛选」弹层），这条栏只剩人脉分组用
  modChips.classList.toggle("hidden", mod !== "contact");
  if (mod === "contact" && typeof renderCtChips === "function") renderCtChips();
  $("#hitokoto").style.display = "none";
  if (TOOLBARS[mod]) { TOOLBARS[mod](); return; }
  modToolbar.innerHTML = `<div class="search">${ICONS.search}<input id="modSearch" placeholder="搜索…" autocomplete="off"></div><span class="count" id="modCount"></span><span class="spacer"></span>`;
  const s = $("#modSearch");
  s && s.addEventListener("input", () => { state.query = s.value.trim(); clearTimeout(s._t); s._t = setTimeout(() => renderModule(mod, false), 250); });
}
function renderModule(mod, animate = true) {
  // 日记页不放超级终端卡（09-15 路河实测：日记自己有输入框，两个输入框叠着是打架）。
  // 只藏不删——#quick 一直在 DOM 里，语音/回车那套逻辑不受影响，切回来即恢复。
  const tc = document.getElementById("terminalCard");
  // 课务页也藏（09-15 实测后加）：那边是内嵌课表，一屏要竖着排下一周的课，
  // 上面压一条超级终端卡就少掉一大截。跟日记页一样只藏不删，#quick 还在 DOM 里。
  if (tc) tc.hidden = mod === "journal" || mod === "course";
  // 消息待办条整体搬去「待办」页了（09-15 路河：待办已单开一页，笔记页就别再放）；
  // 冲突横幅仍归笔记页。切走时清掉任何残留容器。
  for (const id of ["msgTodoStrip", "cfBanner"]) {
    const el = document.getElementById(id);
    if (el && !(id === "cfBanner" && mod === "note")) el.remove();
  }
  renderToolbar(mod);
  // 批量条并入工具栏同一行（09-15 路河）：工具栏每次重写 innerHTML，所以渲染完把 #batchBar 挂回末尾
  if (batchBar.parentNode !== modToolbar) modToolbar.appendChild(batchBar);
  // 课务页显示课务系统 iframe；其它页藏起来（常驻 DOM，删了就等于让那边整页重载）
  /* 2026-10-30：课表页改为本地渲染，不再常驻 8790 的 iframe（那个服务经常没跑，点进去是空白）。keiwu* 函数保留，随时能改回去。 */
  document.body.classList.toggle("showing-keiwu", false);
  /* 2026-10-30 通宵批：对话/问路远是「撑满剩余高度」的页（输入框钉在底），
     交给外层 flex 撑，不再各处写死 calc(100vh - N)。 */
  moduleList.classList.toggle("fill", mod === "chat" || mod === "ask");
  updateBatchBar();
  if (RENDERERS[mod]) RENDERERS[mod](animate);
  else moduleList.innerHTML = "";
}
rail.addEventListener("click", e => {
  const sub = e.target.closest(".nav-subitem");
  if (sub) {
    if (typeof keiwuGo === "function") keiwuGo(sub.dataset.view);
    if (state.module !== sub.dataset.mod) switchModule(sub.dataset.mod);
    return;
  }
  const btn = e.target.closest(".module-btn");
  if (!btn) return;
  if (btn.dataset.mod === state.module && btn.classList.contains("has-sub")) {
    const open = !btn.classList.contains("open");           // 已在课务页：点父项就收起/展开
    btn.classList.toggle("open", open);
    const s = rail.querySelector('.nav-sub[data-sub-of="' + btn.dataset.mod + '"]');
    if (s) s.classList.toggle("show", open);
    updateRailIndicator();
    return;
  }
  switchModule(btn.dataset.mod);
});
function expandWorkspace() {
  if (state.workspaceExpanded) return;
  state.workspaceExpanded = true;
  document.body.classList.add("expanded");
  setTimeout(updateRailIndicator, 60);
}
function collapseWorkspace() {
  // v42：木案式固定工作台，不再收起；保留函数名供旧调用安全空转
  return;
}
$("#glassPreview")?.addEventListener("click", expandWorkspace);
$("#brandBtn")?.addEventListener("click", () => switchModule("note"));
/* 路远切深/浅色时把主题送进课务 iframe（那边只换令牌，不重载页面）。
   不再要求「此刻正看着课务页」：在笔记页切成夜色、回头进课务页也得是黑的。
   body 上别的 class（expanded / showing-keiwu）也在变，所以只在深色值真变的那一刻发一次。 */
let keiwuDarkSent = document.body.classList.contains("dark") ? 1 : 0;
new MutationObserver(() => {
  const d = document.body.classList.contains("dark") ? 1 : 0;
  if (d === keiwuDarkSent) return;
  keiwuDarkSent = d;
  if (typeof keiwuPush === "function") keiwuPush();
}).observe(document.body, { attributes: true, attributeFilter: ["class"] });
/* 覆盖层（AI/设置抽屉、详情弹窗、命令面板等）打开时，主界面手势应失效：
   子界面浮在主界面上方，双指滑动收起主界面属于误触 */
function anyOverlayOpen() {
  if (typeof openDrawerName !== "undefined" && openDrawerName) return true;
  if (typeof detailId !== "undefined" && detailId) return true;
  if (typeof ctDetailId !== "undefined" && ctDetailId) return true;
  return ["#modalWrap", "#detailModal", "#cmdk", "#helpPop", "#datepop", "#digestpop", "#filterpop"]
    .some(s => { const el = $(s); return el && el.classList.contains("show"); });
}
let wheelLock = false;
document.addEventListener("wheel", e => {
  if (wheelLock || anyOverlayOpen()) return;
  if (!state.workspaceExpanded) { if (e.deltaY > 12) { expandWorkspace(); wheelLock = true; setTimeout(() => wheelLock = false, 600); } }
  else if (moduleList.scrollTop <= 0 && e.deltaY < -12) { collapseWorkspace(); wheelLock = true; setTimeout(() => wheelLock = false, 600); }
}, { passive: true });
/* 触控上滑展开 / 下滑收起（列表在顶部时） */
let tsY = 0, tsT = 0;
$("#app").addEventListener("touchstart", e => { tsY = e.touches[0].clientY; tsT = Date.now(); }, { passive: true });
$("#app").addEventListener("touchend", e => {
  if (anyOverlayOpen()) return;
  const dy = tsY - e.changedTouches[0].clientY, dt = Date.now() - tsT;
  if (dt > 600) return;
  if (!state.workspaceExpanded && dy > 50) expandWorkspace();
  else if (state.workspaceExpanded && dy < -50 && moduleList.scrollTop <= 0) collapseWorkspace();
}, { passive: true });

/* ---------------- 批量工具条 ---------------- */
function selectedInCurrentModule() { return [...state.selected].filter(k => k.startsWith(state.module + ":")); }
function updateBatchBar() {
  const n = selectedInCurrentModule().length;
  batchBar.classList.toggle("show", n > 0);
  if (batchCount) batchCount.textContent = "已选 " + n;
  /* 2026-10-30 通宵批：工具栏「清选」按选中态出现（没选中时它没有任何意义） */
  const sn = $("#selnone");
  if (sn) { sn.hidden = !n; sn.textContent = "清选 " + n; }
  const c0 = $("#modCount");
  if (c0 && state.module === "note") c0.textContent = `共 ${currentNotes.length} 条` + (n ? ` · 已选 ${n} 条` : "");
  const inTrash = state.module === "trash";
  const bOrg = $("#batchOrganize"); if (bOrg) bOrg.hidden = !(state.module === "note");
  // 「合并整理」：至少 2 条才亮，避免点了才被告知不够
  const bMerge = $("#batchMerge");
  if (bMerge) bMerge.hidden = !(state.module === "note" && n >= 2);
  batchRestoreBtn.hidden = !inTrash;
  // 复制/导出只在笔记模块的多选态出现
  const inNotes = state.module === "note";
  batchCopyBtn.hidden = !inNotes;
  batchExportBtn.hidden = !inNotes;
  batchDeleteBtn.textContent = inTrash ? "彻底删除" : (state.module === "note" ? "移入回收站" : "删除");
}

/* ---------------- 笔记 / 回收站数据与渲染 ---------------- */
/* ---------------- 笔记筛选（2026-09-15 路河：常驻 chips 行 → 工具栏「筛选」弹层） ----------------
   筛选状态仍用 state.src（voice|manual|""）与 state.tag（分类名），后端接口一个没动。
   #modChips 那条栏从此只服务人脉页的分组 chips。 */
function filterLabel() {
  const parts = [];
  if (state.src) parts.push(state.src === "voice" ? "语音" : "手动");
  if (state.tag) parts.push("#" + state.tag);
  return parts.join(" · ");
}
function renderFilterBtn() {
  const b = $("#filterbtn");
  if (!b) return;
  const on = !!(state.src || state.tag);
  b.classList.toggle("on", on);
  b.innerHTML = ICONS.filter + " 筛选" + (on ? " · " + escapeHtml(filterLabel()) : "");
}
function renderFilterPop() {
  const pop = $("#filterpop");
  if (!pop) return;
  const cats = state.categories || CATEGORIES_FALLBACK;
  const srcs = [["", "全部"], ["voice", "语音"], ["manual", "手动"]];
  pop.innerHTML = `<div class="phead"><span class="ptitle">筛选笔记</span></div>
    <div class="fp-sect">来源</div>
    <div class="fp-chips">` + srcs.map(([v, t]) =>
      `<button class="chip ${state.src === v ? "on" : ""}" data-fsrc="${v}">${t}</button>`).join("") + `</div>
    <div class="fp-sect">分类</div>
    <div class="fp-chips"><button class="chip ${state.tag === "" ? "on" : ""}" data-ftag="">全部</button>` +
    cats.map(c => `<button class="chip ${state.tag === c ? "on" : ""}" data-ftag="${escapeHtml(c)}">#${escapeHtml(c)}</button>`).join("") + `</div>
    <div class="fp-foot"><span class="fp-now">${escapeHtml(filterLabel() || "未筛选 · 显示全部")}</span>
      <button class="tool-btn" id="fclear">清除筛选</button></div>`;
}
/* 「筛选」按钮与弹层统一在 document 上委托：modToolbar 每次切模块都重写 innerHTML，
   弹层内容也是动态生成的，逐个绑定时机不可靠（v42 全模块炸就是这类 null 引发的）。 */
document.addEventListener("click", e => {
  const pop = $("#filterpop");
  if (!pop) return;
  const filterBtn = e.target.closest("#filterbtn");
  if (filterBtn) {
    e.stopPropagation();
    if (pop.classList.contains("show")) pop.classList.remove("show");
    else {
      renderFilterPop(); pop.classList.add("show");
      // 贴着按钮开（v44 遗留呈现问题 09-16 修：原固定右上角，离按钮远）；窄窗贴右缘兜底
      const r = filterBtn.getBoundingClientRect();
      pop.style.top = Math.round(r.bottom + 8) + "px";
      pop.style.right = Math.max(10, Math.round(window.innerWidth - r.right)) + "px";
      pop.style.left = "auto";
    }
  } else if (e.target.closest("#fclear")) {
    state.src = ""; state.tag = ""; renderFilterPop(); renderFilterBtn(); refreshToolbar("note"); loadNotes();
  } else if (e.target.closest("#filterpop .chip")) {
    const chip = e.target.closest("#filterpop .chip");
    if (chip.hasAttribute("data-fsrc")) state.src = chip.getAttribute("data-fsrc");
    else if (chip.hasAttribute("data-ftag")) state.tag = chip.getAttribute("data-ftag");
    else return;
    renderFilterPop(); renderFilterBtn(); refreshToolbar("note"); loadNotes();
  } else if (pop.classList.contains("show")) pop.classList.remove("show");
});

async function loadCategories() {
  try {
    const cached = localStorage.getItem("luyuan_cats");
    if (cached) { state.categories = JSON.parse(cached); renderFilterBtn(); }
    const { categories } = await api("/api/categories");
    state.categories = categories;
    localStorage.setItem("luyuan_cats", JSON.stringify(categories));
    renderFilterBtn();
  } catch {}
}
let _notesSig = null, _notesSigMod = null;   // 上次渲染的数据指纹（防 4s 轮询无谓重绘闪屏）
async function loadNotes(animate = false) {
  if (editing || state.pickerId || state.pending) return;
  try {
    let url;
    if (state.module === "trash") url = "/api/notes?trash=1&limit=200";
    else if (state.jumpDate) url = "/api/notes?limit=200&ondate=" + encodeURIComponent(state.jumpDate);
    else if (state.query) { url = "/api/search?q=" + encodeURIComponent(state.query); if (state.tag) url += "&tag=" + encodeURIComponent(state.tag); }
    else url = "/api/notes?limit=200" + (state.tag ? "&tag=" + encodeURIComponent(state.tag) : "");
    const { notes } = await api(url);
    currentNotes = (state.src && state.module === "note" && !state.jumpDate) ? notes.filter(n => n.source === state.src) : notes;
    // 数据指纹：内容没变就不重绘（轮询静默跳过，不闪屏、不打断选字）
    const sig = currentNotes.map(n =>
      n.id + ":" + (n.updated_at || n.created_at || "") + ":" + (n.deleted ? 1 : 0) + ":" +
      n.text.length + ":" + (n.remind_at || "") + ":" + JSON.stringify(n.tags || [])
    ).join("|");
    if (!animate && state.module === _notesSigMod && sig === _notesSig) return;
    _notesSig = sig; _notesSigMod = state.module;
    renderCurrentList(animate);
    renderPreview();
    if (state.module === "note") maybeConflictBanner();
  } catch { setStatus("无法连接路远服务（桌面程序是否运行？）"); }
}

/* 自提案三（2026-09-14 批复）：同步冲突一次性提示——只提示不自动裁决（红线）。
   2026-10-30 通宵批：这个数字曾经以整条黄横幅 / 状态栏长句的形式常驻首屏，23 处冲突天天顶在
   第一行视线里，看完也不动手。现在只在侧栏「设置」上挂一个数字小角标（点它=打开设置抽屉），
   状态栏一个字节都不占；冲突清零时角标自然消失。 */
let _conflictBannerShown = false;
async function maybeConflictBanner() {
  if (_conflictBannerShown) return;
  let cs = [];
  try { cs = (await api("/api/conflicts")).conflicts || []; } catch { return; }
  if (!cs.length) return;
  _conflictBannerShown = true;
  const paint = () => {
    const btn = document.querySelector('.module-btn[data-mod="settings"]');
    if (!btn) return false;
    btn.querySelectorAll(".bdg-dot,.bdg").forEach(el => el.remove());
    const b = document.createElement("span");
    b.className = "bdg";
    b.textContent = cs.length > 99 ? "99+" : String(cs.length);
    b.title = cs.length + " 处同步冲突待裁决 · 点这里去设置里处理";
    btn.appendChild(b);
    return true;
  };
  if (!paint()) setTimeout(paint, 800);
}
function renderCurrentList(animate) {
  /* 2026-10-29 体检批：笔记列表的刷新可能晚于用户切页（搜索防抖/拉盘回来），
     加模块判断，别让笔记覆盖眼前的记账/人脉页。 */
  if (state.module === "trash") renderTrashList(animate);
  else if (state.module === "note") renderNotesList(animate);
}
function dayMoods(notes) {
  const cnt = {};
  for (const n of notes) {
    if (n.source !== "voice") continue;
    for (const e of (n.text.match(MOOD_RE) || [])) cnt[e] = (cnt[e] || 0) + 1;
  }
  return cnt;
}
function noteHtml(n) {
  const sel = state.selected.has(state.module + ":" + n.id) ? "checked" : "";
  const src = n.source === "voice" ? '<span class="badge voice">语音</span>' : '<span class="badge manual">手动</span>';
  /* 2026-10-29 体检批：转写失败/未识别人声/录音抢救这类"半成品"不再占一张大卡。
     它们仍是完整记录（原声、可点详情、可编辑、可删），只是首屏让位给真内容。 */
  const _t0 = String(n.text || "").trim();
  if (!_t0 || /^（?(未识别到人声|语音待转写|录音中断)/.test(_t0)) {
    const label = /未识别到人声/.test(_t0) ? "语音没听清 · 点详情可听原声"
      : /录音中断/.test(_t0) ? "录音中断，原声已保留 · 等电脑转写"
      : /语音待转写/.test(_t0) ? "语音待转写 · 电脑在转"
      : "空记录";
    return `<div class="item is-pending" data-id="${n.id}">
      <div class="item-main">
        <div class="item-check"><input type="checkbox" class="ncheck" data-id="${n.id}" ${sel}/></div>
        <div class="item-body">
          <div class="n-top"><span class="n-title pending-line">${label}</span>
            <span class="n-side">${src}<span class="n-time">${fmtClock(n.created_at)}</span></span></div>
          <div class="item-actions">
            <button class="item-action dtlbtn" data-id="${n.id}">${ICONS.book} 详情</button>
            <button class="item-action edit" data-id="${n.id}">编辑</button>
            <button class="item-action danger del" data-id="${n.id}">删除</button>
          </div>
        </div>
      </div>
    </div>`;
  }
  const sem = n._semantic ? '<span class="badge sem">相近</span>' : "";
  // 分类左色条（借鉴课务系统行卡 2026-09-15）：按标签映射语义色
  const _t = n.tags || [];
  const catCls = _t.includes("待办") ? " cat-todo" : _t.includes("记账") ? " cat-expense"
    : _t.includes("日记") ? " cat-diary" : (_t.includes("人脉") || _t.includes("联系人")) ? " cat-contact"
    : _t.includes("提醒") ? " cat-remind" : "";
  const tags = _t.map(t => `<span class="badge tag">#${escapeHtml(t)}</span>`).join("");
  const organizing = state.organizing === n.id;
  let remBadge = "", due = false;
  if (n.remind_at) {
    due = !n.remind_fired && (new Date(n.remind_at) <= new Date());
    remBadge = `<span class="badge rem ${n.remind_fired ? "done" : ""}">${ICONS.bell} ${fmtTime(n.remind_at)}${n.remind_fired ? " 已响" : ""}</span>`;
  }
  /* 2026-10-29 下午·笔记卡紧凑重排：原来一条卡＝meta 一行＋标题＋两行摘要＋操作行，
     一条近 100px，一屏只看五六条。改成「标题+右侧徽章时间」一行、「摘要+标签」一行，约 56px。 */
  const sideHtml = `<span class="n-side">${src}${sem}${remBadge}${(n.images && n.images.length) ? `<span class="badge pic">图 ×${n.images.length}</span>` : ""}<span class="n-time">${fmtClock(n.created_at)}</span></span>`;
  const headHtml = `<div class="n-top"><span class="n-title">${hi(noteTitle(n.text))}</span>${sideHtml}</div>`;
  let contentHtml;
  if (state.expanded.has(n.id)) {
    // 配图（SYNC_FORMAT images 字段；App 端图片速记同源，/media 服务出图）
    const imgs = (n.images || []).map(p => {
      const fname = encodeURIComponent(String(p).split("/").pop());
      return `<a class="note-img-link" href="/media/${fname}" target="_blank" rel="noopener">` +
             `<img class="note-img" src="/media/${fname}" alt="配图" loading="lazy"/></a>`;
    }).join("");
    contentHtml = headHtml + `<div class="item-content" data-full="${escapeHtml(n.text)}">${hi(n.text)}</div>` +
      (imgs ? `<div class="note-imgs">${imgs}</div>` : "");
  } else {
    const sum = noteSummary(n.text);
    // 列表里不再挂 #标签——左侧色条已经用颜色标了分类，标签只留详情页看，这一行才挤得开
    contentHtml = headHtml +
      `<div class="n-bottom"><div class="item-content folded" data-full="${escapeHtml(n.text)}">${sum ? `<span>${hi(sum)}</span>` : ""}</div></div>`;
  }
  const fading = state.pending && state.pending.ids.has(n.id);
  const undo = fading
    ? `<div class="undobar"><button class="undo" data-undo="1">撤回</button><span class="cd">${state.pending.seconds}s 后删除</span><button class="delnow" data-delnow="1">立即删除</button></div>` : "";
  const picker = state.pickerId === n.id ? pickerHtml(n) : "";
  const flash = state.flashId === n.id ? " flash" : "";
  const isOpen = state.expanded.has(n.id);
  return `<div class="item${catCls}${fading ? " fading" : ""}${flash}${isOpen ? " expanded" : ""}" data-id="${n.id}" style="animation-delay:0ms;${due ? "border-color:var(--amber);box-shadow:0 0 0 1px var(--amber) inset" : ""}">
    <div class="item-main">
      <div class="item-check"><input type="checkbox" class="ncheck" data-id="${n.id}" ${sel}/></div>
      <div class="item-body">
        ${contentHtml}
        <div class="item-actions">
          <button class="item-action dtlbtn" data-id="${n.id}" title="查看完整内容 / 改提醒时间">${ICONS.book} 详情</button>
          <button class="item-action orgbtn ${organizing ? "organizing" : ""}" data-id="${n.id}" title="让 AI 把口语原文整理成要点/疑问">${ICONS.spark} 整理</button>
          <button class="item-action rembtn" data-id="${n.id}">${ICONS.bell} 提醒</button>
          <button class="item-action cpbtn" data-id="${n.id}" title="复制全文到剪贴板">复制</button>
          <button class="item-action edit" data-id="${n.id}">编辑</button>
          <button class="item-action danger del" data-id="${n.id}">删除</button>
        </div>
      </div>
    </div>
    <div class="swipe-actions"><button class="item-action danger del" data-id="${n.id}">删除</button></div>
    ${picker}${undo}
  </div>`;
}
function trashNoteHtml(n) {
  const src = n.source === "voice" ? '<span class="badge voice">语音</span>' : '<span class="badge manual">手动</span>';
  return `<div class="item" data-id="${n.id}">
    <div class="item-main">
      <div class="item-check"><input type="checkbox" class="ncheck" data-id="${n.id}" ${state.selected.has(state.module + ":" + n.id) ? "checked" : ""}/></div>
      <div class="item-body">
        <div class="item-meta">${src} <span>${fmtTime(n.created_at)}</span><span class="badge">已软删</span></div>
        <div class="item-content">${escapeHtml(n.text)}</div>
        <div class="item-actions">
          <button class="item-action trestore" data-id="${n.id}">恢复</button>
          <button class="item-action danger tpurge" data-id="${n.id}">彻底删除</button>
        </div>
      </div>
    </div>
    <div class="swipe-actions">
      <button class="item-action trestore" data-id="${n.id}">恢复</button>
      <button class="item-action danger tpurge" data-id="${n.id}">彻底删除</button>
    </div>
  </div>`;
}
function pickerHtml(n) {
  let dt = "";
  if (n.remind_at) {
    const d = new Date(n.remind_at);
    const pad = x => String(x).padStart(2, "0");
    dt = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  return `<div class="pickerbar">
    <button class="tool-btn pv" data-pv="1h">+1小时</button>
    <button class="tool-btn pv" data-pv="3h">+3小时</button>
    <button class="tool-btn pv" data-pv="tm9">明早9点</button>
    <input type="datetime-local" class="dtin" value="${dt}" />
    <button class="tool-btn pok">定时</button>
    ${n.remind_at ? '<button class="tool-btn prmcancel">取消提醒</button>' : ""}
  </div>`;
}

/* ---------------- 笔记详情弹层 ----------------
   点笔记正文（非复选框/非按钮）打开，一屏看全：全文 / 标签 / 图片 / 提醒（可回填修改）/ 操作。
   进入弹层时 Esc 先关弹层（见键盘处理），符合「逐层退出」。 */
let detailId = null;

function dtLocalValue(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const pad = x => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function openDetail(id) {
  const n = currentNotes.find(x => x.id === id);
  if (!n) { setStatus("这条笔记不在当前列表（可能已删除或在更早日期）。"); return; }
  detailId = id;
  const src = n.source === "voice" ? "语音" : (n.source === "merge" ? "合并" : "手动");
  const tags = (n.tags || []).map(t => `<span class="badge tag">${escapeHtml(t)}</span>`).join(" ");
  const imgs = (n.images || []).map(p => {
    const f = encodeURIComponent(String(p).split("/").pop());
    return `<a class="note-img-link" href="/media/${f}" target="_blank" rel="noopener"><img class="note-img" src="/media/${f}" alt="配图" loading="lazy"/></a>`;
  }).join("");
  const remLine = n.remind_at
    ? `<span class="badge rem ${n.remind_fired ? "done" : ""}">${ICONS.bell} ${fmtTime(n.remind_at)}${n.remind_fired ? " 已响" : ""}</span>`
    : "";
  $("#detailTitle").textContent = noteTitle(n.text) || "笔记详情";
  $("#detailBody").innerHTML = `
    <div class="detail-meta"><span>${src}</span><span>${fmtTime(n.created_at)}</span>${remLine}${tags}</div>
    <div class="detail-text">${escapeHtml(n.text)}</div>
    ${imgs ? `<div class="detail-section-title">配图</div><div class="note-imgs">${imgs}</div>` : ""}
    <div class="detail-section-title">提醒</div>
    <div class="pickerbar" id="detailPicker">
      <button class="tool-btn pv" data-pv="1h">+1小时</button>
      <button class="tool-btn pv" data-pv="3h">+3小时</button>
      <button class="tool-btn pv" data-pv="tm9">明早9点</button>
      <input type="datetime-local" class="dtin" value="${dtLocalValue(n.remind_at)}" />
      <button class="tool-btn pok">定时</button>
      ${n.remind_at ? '<button class="tool-btn prmcancel">取消提醒</button>' : ""}
    </div>
    <div class="detail-actions">
      <button class="tool-btn" id="detailOrganize">${ICONS.spark} 整理</button>
      <button class="tool-btn" id="detailEdit">编辑</button>
      <button class="tool-btn" id="detailCopy">复制</button>
      <button class="tool-btn" id="detailDelete" style="color:var(--red)">删除</button>
    </div>`;
  $("#detailModal").classList.add("show");
  $("#detailOverlay").classList.add("show");
  const p = $("#detailPicker");
  if (p) p.dataset.id = id;   // 让既有 picker 事件委托能认到这条
}

function closeDetail() {
  detailId = null;
  const m = $("#detailModal"), o = $("#detailOverlay");
  if (m) m.classList.remove("show");
  if (o) o.classList.remove("show");
}

/* 详情弹层里 ←/→ 翻上一条 / 下一条（2026-10-30 通宵批） */
function stepDetail(dir) {
  const idx = currentNotes.findIndex(n => n.id === detailId);
  if (idx < 0) return;
  const next = currentNotes[idx + dir];
  if (!next) { setStatus(dir > 0 ? "已经是最后一条了。" : "已经是第一条了。", 3000); return; }
  state.expanded.add(next.id);
  openDetail(next.id);
  const el = moduleList.querySelector(`.item[data-id="${next.id}"]`);
  if (el) el.scrollIntoView({ block: "center" });
}

function bindDetail() {
  const close = $("#detailClose");
  if (close) close.addEventListener("click", closeDetail);
  const ov = $("#detailOverlay");
  if (ov) {
    /* 拖动守卫：只有"按下和松开都在遮罩上、且没怎么动"才算点击关闭。
       从弹窗内拖出、或在遮罩上拖选，都不该把详情收起。 */
    let ovDown = null;
    ov.addEventListener("mousedown", e => { ovDown = { x: e.clientX, y: e.clientY }; });
    ov.addEventListener("click", e => {
      if (!ovDown) return;   // mousedown 不在遮罩上（如从弹窗内拖出）→ 不关
      const moved = Math.abs(e.clientX - ovDown.x) + Math.abs(e.clientY - ovDown.y);
      ovDown = null;
      if (moved > 6) return; // 移动超过 6px = 拖动，不是点击
      closeDetail();
    });
  }
  const body = $("#detailBody");
  if (!body) return;
  body.addEventListener("click", async e => {
    const id = detailId;
    if (!id) return;
    // 提醒选择器（弹层不在 moduleList 内，须单独接一套，逻辑与列表一致）
    // 改完先刷新列表数据再重开弹层，否则回填的是旧时间
    if (e.target.classList.contains("pv")) {
      await setReminder(id, presetISO(e.target.getAttribute("data-pv")));
      await loadNotes(); openDetail(id);
      return;
    }
    if (e.target.classList.contains("pok")) {
      const v = e.target.closest(".pickerbar").querySelector(".dtin").value;
      if (!v) { setStatus("请先选时间。"); return; }
      await setReminder(id, toLocalISO(new Date(v)));
      await loadNotes(); openDetail(id);
      return;
    }
    if (e.target.classList.contains("prmcancel")) {
      await setReminder(id, null);
      await loadNotes(); openDetail(id);
      return;
    }
    if (e.target.closest("#detailOrganize")) {
      closeDetail();
      await doOrganize(id);
      return;
    }
    if (e.target.closest("#detailCopy")) {
      const n = currentNotes.find(x => x.id === id);
      if (n) {
        try { await navigator.clipboard.writeText(n.text); showToast("已复制到剪贴板", "green"); }
        catch (err) { setStatus("复制失败：" + err.message); }
      }
      return;
    }
    if (e.target.closest("#detailDelete")) {
      closeDetail();
      if (state.module === "trash") {
        if (!(await askConfirm("彻底删除这条？", "这条已经在回收站里，再删就是物理删除，不可恢复。", "确认删除", true))) return;
        try { await api("/api/notes/" + id + "/purge", { method: "POST" }); setStatus("已彻底删除。"); }
        catch (err) { setStatus("删除失败：" + err.message); }
        await loadNotes();
      } else {
        startPending([id]);
      }
      return;
    }
    if (e.target.closest("#detailEdit")) {
      closeDetail();
      state.editing = id;
      renderNotes();
      setTimeout(() => {
        const el = moduleList.querySelector(`.item[data-id="${id}"] textarea.editbox`);
        if (el) { el.focus(); el.scrollIntoView({ behavior: "smooth", block: "center" }); }
      }, 120);
      return;
    }
  });
}
bindDetail();

RENDERERS.note = function (animate) { loadNotes(animate); };
RENDERERS.trash = function (animate) { loadNotes(animate); };
/* 日记模块渲染器与草稿自动保存在 ui/modules.js（DIARY_DRAFT_KEY 也定义在那边） */

/* ---------------- 「路远」对话模块（U1：像微信聊天，不像客服窗） ----------------
   后端 POST /api/chat（chat.py：人格+三层记忆）。UI 历史存 localStorage；
   「清屏」只清界面显示——记忆在路远脑子里（后端 memory），不在此处清除。 */
const CHAT_HIST_KEY = "luyuan_chat_ui_hist";
const CHAT_WELCOME = "来了？有话就说。";

function chatHist() {
  try {
    const v = JSON.parse(localStorage.getItem(CHAT_HIST_KEY) || "null");
    if (Array.isArray(v)) return v.slice(-80);
  } catch (e) {}
  return [];
}
function chatHistPush(role, text) {
  const h = chatHist();
  h.push({ role, text, ts: Date.now() });
  try { localStorage.setItem(CHAT_HIST_KEY, JSON.stringify(h.slice(-80))); } catch (e) {}
}
function chatBubbleHtml(role, text) {
  const cls = role === "user" ? "me" : "yuan";
  return `<div class="chat-row ${cls}"><div class="bubble">${escapeHtml(text)}</div></div>`;
}
RENDERERS.chat = function () {
  $("#hitokoto").style.display = "none";
  const hist = chatHist();
  const msgs = hist.length
    ? hist.map(m => chatBubbleHtml(m.role, m.text)).join("")
    : chatBubbleHtml("yuan", CHAT_WELCOME);
  moduleList.innerHTML = `
    <div class="chat-wrap">
      <div class="chat-msgs" id="chatMsgs">${msgs}</div>
      <div class="chat-inputbar">
        <textarea id="chatInput" rows="1" placeholder="跟路远说点什么…（Enter 发送，Shift+Enter 换行）"></textarea>
        <button id="chatSend" title="发送">${ICONS.search.replace('stroke-width="1.8"', 'stroke-width="2"')}</button>
      </div>
    </div>`;
  const box = $("#chatMsgs"), ta = $("#chatInput"), send = $("#chatSend");
  box.scrollTop = box.scrollHeight;
  async function doSend() {
    const text = ta.value.trim();
    if (!text) return;
    ta.value = "";
    ta.style.height = "auto";
    chatHistPush("user", text);
    box.insertAdjacentHTML("beforeend", chatBubbleHtml("user", text));
    const typing = document.createElement("div");
    typing.className = "chat-row yuan typing";
    typing.innerHTML = '<div class="bubble">…</div>';
    box.appendChild(typing);
    box.scrollTop = box.scrollHeight;
    send.disabled = true;
    try {
      const r = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text }) });
      typing.remove();
      const reply = (r && r.reply) || "（它走了下神，再说一遍？）";
      chatHistPush("yuan", reply);
      box.insertAdjacentHTML("beforeend", chatBubbleHtml("yuan", reply));
    } catch (e) {
      typing.remove();
      const msg = humanError({ status: e.status || 0, data: e.data || null }) || e.message;
      box.insertAdjacentHTML("beforeend", `<div class="chat-row yuan"><div class="bubble err">${escapeHtml(msg)}</div></div>`);
    }
    send.disabled = false;
    box.scrollTop = box.scrollHeight;
    ta.focus();
  }
  send.addEventListener("click", doSend);
  ta.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); }
  });
  ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(120, ta.scrollHeight) + "px"; });
  ta.focus();
};
TOOLBARS.chat = function () {
  modToolbar.innerHTML = `
    <span class="count" id="modCount"></span>
    <span class="spacer"></span>
    <button class="tool-btn" id="chatclear">清屏</button>`;
  const c = $("#modCount"); if (c) c.textContent = "和路远的对话 · 记忆在它脑子里";
  $("#chatclear").addEventListener("click", () => {
    try { localStorage.removeItem(CHAT_HIST_KEY); } catch (e) {}
    RENDERERS.chat();
    setStatus("已清屏（路远还是记得你们的）。");
  });
};
function renderNotesList(animate) {
  $("#hitokoto").style.display = "";
  if (!currentNotes.length) {
    /* 2026-10-30 通宵批：空态从「一句灰话」升级为「一句话 + 下一步点哪」
       —— 搜不到时有「清除搜索」，跳日空了有「返回最新」，真没笔记时直接聚焦输入框。 */
    moduleList.innerHTML = (state.jumpDate
      ? `<div class="jumpbar">正在只看 ${relDateLabel(state.jumpDate)}（${state.jumpDate}）的笔记 <button class="tool-btn" id="backlatest">返回最新</button></div>
         <div class="empty">这一天还没有记事。<div class="empty-acts"><button class="tool-btn" id="backlatest2" data-backlatest="1">回到最新</button></div></div>`
      : (state.query
        ? `<div class="empty">没有匹配「${escapeHtml(state.query)}」的记事。<div class="empty-acts"><button class="tool-btn pri" data-clearq="1">清除搜索</button><button class="tool-btn" data-focus-quick="1">换一句记</button></div></div>`
        : `<div class="empty">还没有记事。<br>在上面输入框打一句回车，或按 F10 说话。<div class="empty-acts"><button class="tool-btn pri" data-focus-quick="1">现在写第一条</button></div></div>`));
    updateCount(); pollTodos(); return;
  }
  const banner = state.jumpDate ? `<div class="jumpbar">正在只看 ${relDateLabel(state.jumpDate)}（${state.jumpDate}）的笔记 <button class="tool-btn" id="backlatest">返回最新</button></div>` : "";
  const groups = {};
  for (const n of currentNotes) (groups[dateKey(n.created_at)] = groups[dateKey(n.created_at)] || []).push(n);
  const keys = Object.keys(groups).sort().reverse();
  let idx = 0;
  moduleList.innerHTML = banner + keys.map(k => {
    const arr = groups[k];
    const collapsed = state.collapsed.has(k);
    const allSel = arr.every(n => state.selected.has(state.module + ":" + n.id));
    const mc = dayMoods(arr);
    const mo = Object.keys(mc).map(e => `<span style="color:${MOODS[e]}">${e}×${mc[e]}</span>`).join(" ");
    const itemsHtml = collapsed ? "" : arr.map(n => {
      const el = noteHtml(n).replace('style="animation-delay:0ms;', `style="animation-delay:${animate && idx < 8 ? idx++ * 55 : 0};`);
      return el;
    }).join("");
    return `<div class="group ${collapsed ? "collapsed" : ""}" data-date="${k}">
      <div class="gdate-head" data-date="${k}">
        <input type="checkbox" class="gcheck" data-daysel="${k}" ${allSel ? "checked" : ""} title="选中/取消这一天的全部笔记" />
        <span class="caret">▾</span>
        <span class="gdate-title">${relDateLabel(k)}</span>
        <span class="gdate-count">${arr.length} 条</span>
        <span style="font-size:11px">${mo}</span>
        <button class="day-organize tool-btn" data-dayorg="${k}" title="把这一天的笔记整理成一条要点">${ICONS.spark} 整理这天</button>
      </div>${itemsHtml}</div>`;
  }).join("");
  updateCount();
  pollTodos();   // 顺带刷一次待办：只更新红点与 toast，笔记页不画任何待办条
}

/* ---------------- 消息待办轮询（2026-09-15 路河：待办已单开一页，笔记页不再画待办条） ---------
   只管三件事：侧栏「待办」红点、新待办到达 toast+语音、待办页自动刷新。
   SYNC_FORMAT §10.4：手机端点「✓ 收下」后才落盘 → 出现在同步根目录即已确认，
   PC 端绝不再要求二次「收下」，只提供「✓ 完成」（写 done/done_at，同步回手机）与「✗ 不要」。 */
let _todoSig = "";
let _msgTodoMax = null;     // 新待办 toast 的基线（首轮不提醒，避免一开面板就弹历史）
async function pollTodos() {
  let t;
  try { t = await api("/api/todos"); } catch { return; }
  const all = t.todos || [];
  const n = all.length;
  updateTodoBadge(n);
  if (_msgTodoMax != null && n > _msgTodoMax && typeof showToast === "function") {
    const newest = all[0] || {};
    const msg = "新的消息待办：" + (newest.text || "").slice(0, 30) + (n > _msgTodoMax + 1 ? "（共 " + n + " 条）" : "");
    showToast("📬 " + msg, "blue");
    fetch("/api/announce", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: msg }) }).catch(() => {});
  }
  _msgTodoMax = Math.max(_msgTodoMax ?? 0, n);
  const sig = JSON.stringify([t.todos, t.done_today]);
  if (sig !== _todoSig) {
    _todoSig = sig;
    if (state.module === "todo" && RENDERERS.todo) RENDERERS.todo(false);   // 人在待办页就即时重绘
  }
}

/* 未确认消息待办 → 侧栏「待办」红点（独立函数：待办页/笔记页都能调用） */
function updateTodoBadge(n) {
  const todoBtn = rail.querySelector('.module-btn[data-mod="todo"]');
  if (!todoBtn) return;
  let dot = todoBtn.querySelector(".bdg-dot");
  const want = n > 0 && state.module !== "todo";
  if (want && !dot) { dot = document.createElement("i"); dot.className = "bdg-dot"; todoBtn.appendChild(dot); }
  if (!want && dot) dot.remove();
}

/* ---------------- 路远远汇报轮询（2026-10-19 批）：侧栏红点 + 新汇报 toast + 页签自动刷新 ----------------
   QQ 播报已撤（路河拍板：QQ 不留），路远远的晨报/提醒/管家讲解全落 report_*.json，这里只管呈现。 */
let _repSig = "";
let _repMax = null;   // 新汇报 toast 基线（首轮不提醒，防一开面板弹历史）
async function pollReports() {
  let b;
  try { b = await api("/api/reports/badge"); } catch { return; }
  updateReportBadge(b.unread || 0);
  // 人在页签上才拉全文做增量重绘；别处只动红点
  if (state.module === "report" && RENDERERS.report) {
    try {
      const o = await api("/api/reports");
      const sig = JSON.stringify((o.reports || []).map(r => r.id));   // 只看增删：已读变化不整体重绘（防展开中的行被收起）
      if (sig !== _repSig) { _repSig = sig; RENDERERS.report(false); }
    } catch {}
  }
}
function updateReportBadge(n) {
  const btn = rail.querySelector('.module-btn[data-mod="report"]');
  if (!btn) return;
  let dot = btn.querySelector(".bdg-dot");
  const want = n > 0 && state.module !== "report";
  if (want && !dot) { dot = document.createElement("i"); dot.className = "bdg-dot"; btn.appendChild(dot); }
  if (!want && dot) dot.remove();
}
function renderTrashList(animate) {
  $("#hitokoto").style.display = "none";
  let idx = 0;
  /* 2026-10-30 通宵批：回收站按搜索词过滤（纯前端，不新增接口）；空态给「回笔记」出口。 */
  const q = (state.query || "").toLowerCase();
  const rows = q ? currentNotes.filter(n => String(n.text || "").toLowerCase().includes(q)) : currentNotes;
  moduleList.innerHTML = rows.length
    ? rows.map(n => trashNoteHtml(n).replace('class="item"', `class="item" style="animation-delay:${animate && idx < 8 ? idx++ * 55 : 0}ms"`)).join("")
    : (q
      ? `<div class="empty">回收站里没有含「${escapeHtml(state.query)}」的记事。<div class="empty-acts"><button class="tool-btn pri" data-clearq="1">清除搜索</button></div></div>`
      : `<div class="empty">回收站是空的。删掉的记事在这里躺 30 天，随时可恢复。<div class="empty-acts"><button class="tool-btn pri" data-goto="note">回笔记</button></div></div>`);
  updateCount();
};
function updateCount() {
  const c = $("#modCount");
  if (!c) return;
  if (state.module === "trash") { c.textContent = `回收站 ${currentNotes.length} 条`; return; }
  const sel = state.selected.size;
  c.textContent = `共 ${currentNotes.length} 条` + (sel ? ` · 已选 ${sel} 条` : "");
}
RENDERERS._notesRefresh = loadNotes;

/* 笔记工具栏（2026-10-30 通宵批）
   原来是「全选 / 清选 / 筛选 / 日 / 回顾」五个常驻按钮挤在搜索框右边：一屏里最响的是工具，
   而其中四个绝大多数时间用不上。现在只留 计数 + （有选中时的）清选 + 一个「⋯」；
   全选/筛选/按日期/回顾/导出全部收进 ⋯ 菜单，且「正在筛选」以一行小字挂在搜索框旁，
   状态可见（原来筛选生效了只能靠按钮上的长文案猜）。 */
TOOLBARS.note = function () {
  const n = selectedInCurrentModule().length;
  const fl = filterLabel();
  modToolbar.innerHTML = `
    <div class="search">${ICONS.search}<input id="modSearch" placeholder="搜索记事 / 标签…（按 / 聚焦）" autocomplete="off"></div>
    <span class="count" id="modCount"></span>
    ${fl ? `<span class="count" id="filterOn" style="color:var(--accent)">筛选 · ${escapeHtml(fl)}</span>` : ""}
    <span class="spacer"></span>
    ${n ? `<button class="tool-btn" id="selnone">清选 ${n}</button>` : `<button class="tool-btn" id="selnone" hidden>清选</button>`}
    <button class="tool-btn" id="morebtn" title="更多操作（全选 / 筛选 / 按日期 / 回顾 / 导出）">⋯</button>`;
  const s = $("#modSearch");
  s.value = state.query;
  s.addEventListener("input", () => { state.query = s.value.trim(); clearTimeout(s._t); s._t = setTimeout(loadNotes, 250); });
  const sn = $("#selnone");
  if (sn) sn.addEventListener("click", () => { state.selected.clear(); renderNotes(); updateBatchBar(); });
};
/* 工具栏重画的安全版：renderToolbar 会重写 modToolbar.innerHTML（连带把 batchBar 从 DOM 上摘掉），
   所以要把批量条重新挂回去，否则选完东西批量按钮就凭空消失。 */
function refreshToolbar(mod) {
  renderToolbar(mod || state.module);
  if (batchBar.parentNode !== modToolbar) modToolbar.appendChild(batchBar);
  updateBatchBar();
}
/* ⋯ 菜单内容 */
function renderMorePop() {
  const pop = $("#morepop");
  if (!pop) return;
  const fl = filterLabel();
  pop.innerHTML = `
    <div class="more-item" data-more="all">全选这 ${currentNotes.length} 条<span class="mi-k">Ctrl+A</span></div>
    <div class="more-item ${fl ? "on" : ""}" data-more="filter">筛选${fl ? " · " + escapeHtml(fl) : "（来源 / 分类）"}</div>
    <div class="more-item" data-more="date">按日期跳转</div>
    <div class="more-item" data-more="digest">回顾（今天 / 本周）</div>
    <div class="more-sep"></div>
    <div class="more-item" data-more="export">导出 Markdown<span class="mi-k">所选优先</span></div>
    <div class="more-item" data-more="refresh">刷新列表</div>`;
}
document.addEventListener("click", e => {
  const pop = $("#morepop");
  if (!pop) return;
  const btn = e.target.closest("#morebtn");
  if (btn) {
    e.stopPropagation();
    if (pop.classList.contains("show")) { pop.classList.remove("show"); return; }
    renderMorePop();
    pop.classList.add("show");
    const r = btn.getBoundingClientRect();
    pop.style.top = Math.round(r.bottom + 8) + "px";
    pop.style.right = Math.max(10, Math.round(window.innerWidth - r.right)) + "px";
    pop.style.left = "auto";
    return;
  }
  const item = e.target.closest("#morepop .more-item");
  if (item) {
    const k = item.getAttribute("data-more");
    pop.classList.remove("show");
    if (k === "all") {
      currentNotes.forEach(n => state.selected.add(state.module + ":" + n.id));
      renderNotes(); updateBatchBar();
      if (currentNotes.length) showToast(`已选 ${currentNotes.length} 条`, "green");
    } else if (k === "filter") {
      renderFilterPop();
      $("#filterpop").classList.add("show");
      const r = $("#morebtn").getBoundingClientRect();
      $("#filterpop").style.top = Math.round(r.bottom + 8) + "px";
      $("#filterpop").style.right = Math.max(10, Math.round(window.innerWidth - r.right)) + "px";
      $("#filterpop").style.left = "auto";
    } else if (k === "date") {
      if (typeof openDatePop === "function") openDatePop();
    } else if (k === "digest") {
      $("#digestpop").classList.add("show");
      if (typeof loadDigest === "function") loadDigest("day");
    } else if (k === "export") { exportMd(); }
    else if (k === "refresh") { loadNotes(); showToast("已刷新", "green"); }
    return;
  }
  if (pop.classList.contains("show")) pop.classList.remove("show");
});
TOOLBARS.trash = function () {
  modToolbar.innerHTML = `
    <div class="search">${ICONS.search}<input id="trashSearch" placeholder="在回收站里搜…" autocomplete="off"></div>
    <span class="count" id="modCount"></span>
    <span class="spacer"></span>
    <button class="tool-btn" id="emptybtn" ${currentNotes.length ? "" : "disabled"}>清空回收站</button>`;
  const ts = $("#trashSearch");
  ts.value = state.query;
  /* 2026-10-30 通宵批：回收站原来没有搜索，软删攒到 200 条只能拿滚轮找。
     数据本来就在前端手上（loadNotes 拉 trash=1），直接内存过滤，不新增接口。 */
  ts.addEventListener("input", () => {
    state.query = ts.value.trim();
    clearTimeout(ts._t);
    ts._t = setTimeout(() => renderTrashList(false), 180);
  });
  $("#emptybtn").addEventListener("click", async () => {
    if (!(await askConfirm("彻底清空回收站？", "回收站里的条目会被物理删除，不进撤销流、不可恢复。", "确认清空", true))) return;
    try { const r = await api("/api/notes/trash/empty", { method: "POST" }); setStatus(`已彻底清除 ${r.purged} 条。`); }
    catch (err) { setStatus("清空失败：" + err.message); }
    loadNotes();
  });
};
function renderNotes() { renderCurrentList(); }

/* 导出 */
function exportMd() {
  const arr = exportArr();
  if (!arr.length) { setStatus("没有可导出的记事。"); return; }
  const lines = [`# 路远导出 · ${new Date().toLocaleDateString("zh-CN")}（共 ${arr.length} 条）`, ""];
  for (const n of arr) {
    const src = n.source === "voice" ? "语音" : "手动";
    lines.push(`## ${fmtTime(n.created_at)} · ${src}`, "", n.text);
    if ((n.tags || []).length) lines.push("", n.tags.map(t => "#" + t).join(" "));
    lines.push("", "---", "");
  }
  const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "路远导出_" + new Date().toISOString().slice(0, 10) + ".md";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  setStatus(`已导出 ${arr.length} 条记事（Markdown 已下载）。`);
}
/* 选中内容拼纯文本（导出与复制共用；无选中=全部） */
function exportArr() {
  const sel = currentNotes.filter(n => state.selected.has(state.module + ":" + n.id));
  return sel.length ? sel : currentNotes;
}
function copyNotes() {
  const arr = exportArr();
  if (!arr.length) { setStatus("没有可复制的记事。"); return; }
  const lines = [];
  for (const n of arr) {
    lines.push(`【${fmtTime(n.created_at)}${n.source === "voice" ? " · 语音" : ""}】${n.text}`);
    if ((n.tags || []).length) lines.push(n.tags.map(t => "#" + t).join(" "));
    lines.push("");
  }
  navigator.clipboard.writeText(lines.join("\n")).then(
    () => setStatus(`已复制 ${arr.length} 条到剪贴板。`),
    () => setStatus("复制失败：浏览器没给剪贴板权限（点一下页面再试）。"));
}
/* 提醒 */
async function setReminder(id, isoOrNull) {
  try {
    await api("/api/notes/" + id + "/reminder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ remind_at: isoOrNull }) });
    state.pickerId = null;
    await loadNotes();
    if (isoOrNull) setStatus("提醒已设好，到点会弹 Windows 通知。");
  } catch (e) { setStatus("设置提醒失败：" + e.message); }
}
/* 删除撤回流（无确认，5 秒可撤回） */
function commitPending() {
  if (!state.pending) return;
  const ids = [...state.pending.ids];
  clearInterval(state.pending.timer);
  state.pending = null;
  const idset = new Set(ids);
  currentNotes = currentNotes.filter(n => !idset.has(n.id));
  ids.forEach(id => { state.selected.delete(state.module + ":" + id); state.expanded.delete(id); });
  renderNotes();
  (async () => {
    try {
      await api("/api/notes/delete_many", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }) });
      ids.forEach(id => state.selected.delete(state.module + ":" + id));
      setStatus(`已删除 ${ids.length} 条（可在回收站找回）。`);
    } catch (e) { setStatus("删除失败：" + e.message); }
    await loadNotes();
  })();
}
function startPending(ids) {
  if (state.pending) commitPending();
  state.pending = { ids: new Set(ids), seconds: 5, timer: null };
  state.pending.timer = setInterval(() => {
    if (!state.pending) return;
    state.pending.seconds -= 1;
    if (state.pending.seconds <= 0) commitPending();
    else {
      const cd = moduleList.querySelector(".cd");
      if (cd) cd.textContent = state.pending.seconds + "s 后删除";
    }
  }, 1000);
  renderNotes();
}
function cancelPending() {
  if (!state.pending) return;
  clearInterval(state.pending.timer);
  state.pending = null;
  renderNotes();
}
/* 整理 */

/* 一键整理：多条笔记逐个调 Ollama 整理（串行，避免本地模型并发崩） */
async function batchOrganize(ids) {
  const list = (ids || []).filter(Boolean);
  if (!list.length) { setStatus("先勾选要整理的笔记，或用「整理这天」。"); return; }
  if (!(await askConfirm(`用本地 AI 整理这 ${list.length} 条？`, "原文一个字不改，要点追加在原文后面；要几分钟，逐条排队。", "开始整理"))) return;
  let ok = 0, fail = [];
  setStatus(`整理中 0/${list.length}…`);
  for (let i = 0; i < list.length; i++) {
    setStatus(`整理中 ${i + 1}/${list.length}…`);
    try { await api("/api/notes/" + list[i] + "/organize", { method: "POST" }); ok++; }
    catch (e) { fail.push(list[i]); }
  }
  state.expanded = new Set([...state.expanded, ...list]);
  await loadNotes();
  if (fail.length) setStatus(`整理完成 ${ok} 条，${fail.length} 条失败（多为 Ollama 未开）。`, 8000);
  else showToast(`已整理 ${ok} 条笔记`, "green");
}

/* 一键合并整理：多条零散笔记 → 一条汇总笔记；原文归档进回收站（可整体恢复）。
   不做 confirm 弹窗式拦截，改用一条可撤销的提示，符合「能一步就不要两步」。 */
async function mergeOrganize(ids) {
  const list = (ids || []).filter(Boolean);
  if (list.length < 2) { setStatus("至少勾选 2 条笔记才能合并。"); return; }
  const btn = $("#batchMerge");
  if (btn) { btn.disabled = true; btn.textContent = "合并中…"; }
  setStatus(`正在把 ${list.length} 条笔记合并成一条…`);
  try {
    const r = await api("/api/notes/merge-organize", {
      method: "POST", body: JSON.stringify({ ids: list, archive: true })
    });
    state.selected.clear();
    updateBatchBar();
    await loadNotes();
    showToast(`已合并 ${r.count} 条 → 1 条，原文已归档到回收站`, "green");
    setStatus(`合并完成：${r.count} 条原文已打「已合并」标签并移入回收站，可整体恢复。`, 8000);
    if (r.note && r.note.id) {
      state.expanded = new Set([...state.expanded, r.note.id]);
      renderNotes();
    }
  } catch (e) {
    setStatus("合并失败：" + e.message + "（笔记原样未动）", 8000);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = ICONS.spark + " 合并整理"; }
  }
}

async function doOrganize(id) {
  if (state.organizing) return;
  state.organizing = id;
  renderNotes();
  try {
    await api("/api/notes/" + id + "/organize", { method: "POST" });
    state.organizing = null;
    state.expanded.add(id);
    await loadNotes();
    setStatus("已整理（原文保留，整理块追加在后面）。");
    setTimeout(() => {
      const el = moduleList.querySelector(`.item[data-id="${id}"]`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 100);
  } catch (e) {
    state.organizing = null; renderNotes();
    setStatus(e.message.includes("ollama_off") ? "Ollama 没在运行，整理用不了（记事不受影响）。点左下角徽标可拉起。" : "整理失败：" + e.message);
  }
}
function startEdit(id, item) {
  const textEl = item.querySelector(".item-content");
  if (!textEl || item.querySelector(".editbox")) return;
  editing = true;
  /* 2026-10-30 通宵批：编辑态把原来的操作行藏掉，只留「保存 / 取消」。
     原来两套 .item-actions 都是绝对定位，直接叠在同一处，点哪个全看运气。 */
  item.classList.add("editing");
  const box = document.createElement("textarea");
  box.className = "editbox";
  box.value = textEl.getAttribute("data-full") || textEl.textContent;
  textEl.replaceWith(box);
  const bar = document.createElement("div");
  bar.className = "item-actions";
  bar.innerHTML = '<button class="tool-btn save" data-id="' + id + '">保存</button><button class="tool-btn cancel" data-id="' + id + '">取消</button>';
  item.querySelector(".item-body").appendChild(bar);
  box.focus();
  box.setSelectionRange(box.value.length, box.value.length);
}

/* ---------------- 列表事件（委托） ---------------- */
moduleList.addEventListener("click", async (e) => {
  if (e.target.classList.contains("undo")) { cancelPending(); return; }
  if (e.target.hasAttribute("data-delnow")) { commitPending(); return; }
  if (e.target.id === "backlatest") { state.jumpDate = null; await loadNotes(); return; }
  const mtd = e.target.closest(".mtdone, .mtdrop, .mtundone");
  if (mtd) {
    const drop = mtd.classList.contains("mtdrop");
    const undone = mtd.classList.contains("mtundone");
    mtd.disabled = true;
    try {
      await api("/api/todos/" + mtd.dataset.tid + (undone ? "/undone" : drop ? "/discard" : "/done"), { method: "POST" });
      showToast(undone ? "已翻回未办（已同步回手机）" : drop ? "已丢弃" : "已完成（已同步回手机）", "green");
    } catch (err) { setStatus((undone ? "取消完成" : drop ? "丢弃" : "完成") + "失败：" + err.message); }
    _todoSig = "";
    if (state.module === "todo") RENDERERS.todo && RENDERERS.todo(false);
    else pollTodos();
    return;
  }
  const tid = e.target.getAttribute("data-id");
  if (tid && e.target.classList.contains("trestore")) {
    await api("/api/notes/" + tid + "/restore", { method: "POST" });
    setStatus("已恢复 1 条，回到「笔记」。");
    switchModule("note"); return;
  }
  if (tid && e.target.classList.contains("tpurge")) {
    if (!(await askConfirm("彻底删除这条？", "物理删除，不进撤销流，不可恢复。", "确认删除", true))) return;
    await api("/api/notes/" + tid + "/purge", { method: "POST" });
    await loadNotes(); return;
  }
  const ghead = e.target.closest(".gdate-head");
  if (ghead) {
    // 「全选当天」复选框：切换该日全选，不触发折叠
    const dayBtn = e.target.closest(".gcheck");
    if (dayBtn) {
      e.stopPropagation();
      const k = dayBtn.getAttribute("data-daysel");
      const dayNotes = currentNotes.filter(n => dateKey(n.created_at) === k);
      const allSelNow = dayNotes.every(n => state.selected.has(state.module + ":" + n.id));
      if (allSelNow) dayNotes.forEach(n => state.selected.delete(state.module + ":" + n.id));
      else dayNotes.forEach(n => state.selected.add(state.module + ":" + n.id));
      updateBatchBar();
      renderNotes();
      return;
    }
    // 「整理这天」：把当天全部笔记整理成要点（排队，逐个调）
    const orgBtn = e.target.closest(".day-organize");
    if (orgBtn) {
      e.stopPropagation();
      const k = orgBtn.getAttribute("data-dayorg");
      const dayNotes = currentNotes.filter(n => dateKey(n.created_at) === k);
      batchOrganize(dayNotes.map(n => n.id));
      return;
    }
    const k = ghead.getAttribute("data-date");
    if (state.collapsed.has(k)) state.collapsed.delete(k); else state.collapsed.add(k);
    renderNotes(); return;
  }
  /* 2026-10-30 通宵批：点开/收起的热区从「摘要那一行字」扩到整张卡。
     原来点标题、点空白、点右侧徽章全都没反应，只有摘要那 30 来个字可点。 */
  const cardEl = e.target.closest(".item");
  if (cardEl && state.module === "note" &&
      !e.target.closest("input,button,a,textarea,select,.pickerbar,.undobar,.item-actions")) {
    const cid = cardEl.getAttribute("data-id");
    if (cid) {
      if (state.expanded.has(cid)) state.expanded.delete(cid); else state.expanded.add(cid);
      renderNotes(); return;
    }
  }
  const id = e.target.getAttribute("data-id") || (e.target.closest(".item") ? e.target.closest(".item").getAttribute("data-id") : null);
  if (!id) return;
  if (e.target.classList.contains("cpbtn")) {
    // 自提案 B：单条复制全文（2026-09-15 UI席位自审）
    const cn = currentNotes.find(x => x.id === id);
    const txt = cn ? cn.text : "";
    if (navigator.clipboard && txt) navigator.clipboard.writeText(txt).then(() => showToast("已复制全文", "green"));
    else setStatus(txt ? "浏览器不支持一键复制，请在详情里手动复制。" : "这条找不到了，刷新一下。");
    return;
  }
  if (e.target.classList.contains("dtlbtn")) { openDetail(id); return; }
  if (e.target.classList.contains("del")) startPending([id]);
  else if (e.target.classList.contains("edit")) { if (!editing) startEdit(id, e.target.closest(".item")); }
  else if (e.target.classList.contains("save")) {
    const item = e.target.closest(".item");
    const text = item.querySelector(".editbox").value.trim();
    if (!text) return;
    await api("/api/notes/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    editing = false;
    await loadNotes();
  } else if (e.target.classList.contains("cancel")) { editing = false; await loadNotes(); }
  else if (e.target.classList.contains("rembtn")) { state.pickerId = (state.pickerId === id) ? null : id; renderNotes(); }
  else if (e.target.classList.contains("orgbtn")) await doOrganize(id);
  else if (e.target.classList.contains("pv")) await setReminder(id, presetISO(e.target.getAttribute("data-pv")));
  else if (e.target.classList.contains("pok")) {
    const v = e.target.closest(".pickerbar").querySelector(".dtin").value;
    if (!v) { setStatus("请先选时间。"); return; }
    await setReminder(id, toLocalISO(new Date(v)));
  }
  else if (e.target.classList.contains("prmcancel")) await setReminder(id, null);
});
moduleList.addEventListener("change", (e) => {
  const cb = e.target;
  if (cb.classList && cb.classList.contains("ncheck")) {
    const id = cb.getAttribute("data-id");
    if (cb.checked) state.selected.add(state.module + ":" + id); else state.selected.delete(state.module + ":" + id);
    updateBatchBar();
    const c = $("#modCount");
    if (c) c.textContent = (state.module === "trash" ? `回收站 ${currentNotes.length} 条` : `共 ${currentNotes.length} 条`) + (state.selected.size ? ` · 已选 ${state.selected.size} 条` : "");
  }
});
const batchOrganizeBtn = $("#batchOrganize");
if (batchOrganizeBtn) batchOrganizeBtn.addEventListener("click", () => {
  batchOrganize(selectedInCurrentModule().map(k => k.split(":")[1]));
});
const batchMergeBtn = $("#batchMerge");
if (batchMergeBtn) batchMergeBtn.addEventListener("click", () => {
  mergeOrganize(selectedInCurrentModule().map(k => k.split(":")[1]));
});
batchDeleteBtn.addEventListener("click", () => {
  const ids = selectedInCurrentModule().map(k => k.split(":")[1]);
  if (!ids.length) return;
  if (state.module === "trash") {
    // 红线补卡（2026-09-14 夜 UI 统一班）：批量彻底删除也必须过确认卡
    const wrap = $("#modalWrap"), card = $("#modalCard");
    card.innerHTML = `<div class="mc-title">彻底删除选中的 ${ids.length} 条？</div>
      <div class="mc-list">${ids.length > 8 ? ids.slice(0, 8).map(() => "· …").join("<br>") + "<br>· …" : ids.map(() => "· 已选笔记").join("<br>")}</div>
      <div class="hint" style="padding:0 0 10px">笔记已删过一次，此步彻底清除，不可恢复。</div>
      <div class="mc-btns"><button class="tool-btn" id="mcCancel">取消</button>
      <button class="batch-btn danger" id="mcYes">确认彻底删除</button></div>`;
    wrap.classList.add("show");
    $("#mcCancel").addEventListener("click", () => wrap.classList.remove("show"));
    $("#mcYes").addEventListener("click", async () => {
      wrap.classList.remove("show");
      let okN = 0;
      for (const id of ids) { try { await api("/api/notes/" + id + "/purge", { method: "POST" }); okN++; } catch {} }
      state.selected.clear();
      setStatus(`已彻底删除 ${okN} 条。`);
      loadNotes();
      updateBatchBar();
    });
  } else if (state.module === "note") {
    startPending(ids);   // 撤回流，不要 confirm
  } else {
    openBatchConfirm(ids);   // 记账/课程/人脉：物理删除，过确认卡
  }
});
batchRestoreBtn.addEventListener("click", async () => {
  const ids = selectedInCurrentModule().map(k => k.split(":")[1]);
  if (!ids.length) return;
  let ok = 0;
  for (const id of ids) { try { await api("/api/notes/" + id + "/restore", { method: "POST" }); ok++; } catch {} }
  state.selected.clear();
  setStatus(`已批量恢复 ${ok} 条，回到「笔记」。`);
  switchModule("note");
});
batchCopyBtn.addEventListener("click", () => { copyNotes(); });
batchExportBtn.addEventListener("click", () => { exportMd(); });

/* ---------------- 超级终端：意图提示 + 提交（协议冻结前回退普通记事） ---------------- */
const quickEl = $("#quick"), intentTag = $("#intentTag");
function detectIntent(text) {
  const t = text.trim();
  if (!t) return null;
  if (/(认识了|遇到|见到|加了个?好友?)/.test(t) || /叫\s*[\u4e00-\u9fa5]{2,4}/.test(t)) return { label: "联系人", color: "amber" };
  if (/(花了|支出|记账|￥|\d+\s*元|开支|消费)/.test(t)) return { label: "记账", color: "amber" };
  if (/(课|上课|课程|第\d+节|教室|课表)/.test(t)) return { label: "课程", color: "purple" };
  if (/(提醒我|待办|todo)/i.test(t) || /(明早|明天下午|明天|周[一二三四五六日])\s*(\d+|\d+点)/.test(t)) return { label: "待办", color: "amber" };
  if (/(买|购|下单|加购|想入手)/.test(t)) return { label: "购物", color: "pink" };
  if (/(我觉得|想法|思考|考虑|要不要|纠结|忽然想到)/.test(t)) return { label: "想法", color: "blue" };
  if (/(金句|摘抄|文章|句子|语录|文案)/.test(t)) return { label: "写作素材", color: "purple" };
  return { label: "笔记", color: "green" };
}
quickEl.addEventListener("input", () => {
  const text = quickEl.value;
  const intent = detectIntent(text);
  if (intent) {
    intentTag.textContent = "→ " + intent.label;
    intentTag.classList.add("show");
  } else intentTag.classList.remove("show");
  // setModelDot(text.length > 80 ? "deepseek" : (localStorage.getItem("luyuan_model") || "qwen2.5:7b"));
});
quickEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && quickEl.value.trim()) { e.preventDefault(); terminalSubmit(); return; }
  if (e.key === "ArrowUp" && !e.shiftKey) {
    // ↑ 翻最近提交（连续记录时找回上一句）
    const hist = getTermHistory();
    if (!hist.length) return;
    e.preventDefault();
    if (termHistIdx === -1) { termHistDraft = quickEl.value; termHistIdx = 0; }
    else if (termHistIdx < hist.length - 1) termHistIdx++;
    quickEl.value = hist[termHistIdx];
    setIntent(quickEl.value);
  } else if (e.key === "ArrowDown" && termHistIdx !== -1) {
    const hist = getTermHistory();
    e.preventDefault();
    termHistIdx--;
    if (termHistIdx < 0) { termHistIdx = -1; quickEl.value = termHistDraft; }
    else quickEl.value = hist[termHistIdx];
    setIntent(quickEl.value);
  }
});
let termHistIdx = -1, termHistDraft = "";
function getTermHistory() {
  try { return JSON.parse(localStorage.getItem("luyuan_term_hist") || "[]"); } catch { return []; }
}
function setIntent(text) {
  const intent = detectIntent(text);
  if (intent) { intentTag.textContent = "→ " + intent.label; intentTag.classList.add("show"); }
  else intentTag.classList.remove("show");
}
quickEl.addEventListener("input", () => {
  quickEl.style.height = "auto";
});
async function terminalSubmit() {
  const text = quickEl.value.trim();
  if (!text) return;
  const intent = detectIntent(text);
  quickEl.value = "";
  try {
    const h = getTermHistory();
    if (h[0] !== text) { h.unshift(text); localStorage.setItem("luyuan_term_hist", JSON.stringify(h.slice(0, 30))); }
    termHistIdx = -1;
  } catch {}
  intentTag.classList.remove("show");
  try {
    const r = await fetch("/api/terminal", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, source: "panel" }) });
    if (r.ok) {
      const data = await r.json();
      handleTerminalActions(data, text);
      return;
    }
    if (r.status >= 500) setStatus("智能路由暂时出错，已按普通记事保存（问题已上报）。", 8000);
    else if (r.status !== 404) setStatus("智能路由未处理这条，已按普通记事保存。", 8000);
  } catch {
    setStatus("智能路由未响应，已按普通记事保存。", 8000);
  }
  // 回退：普通记事（路由未接入时的诚实行为——不谎称走了云端）
  try {
    const r2 = await api("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, source: "manual" }) });
    if (r2 && r2.note) { state.flashId = r2.note.id; setTimeout(() => { state.flashId = null; }, 2000); }
    showToast("已记下 → 笔记", "green");
    logAiHistory(text, "笔记");
    if (text.length > 80) setStatus("已按普通记事保存（智能路由未响应；路由上线后长文会自动归入日记）。", 8000);
    expandWorkspace();
    if (state.module === "note") await loadNotes(); else switchModule("note");
  } catch (e) { setStatus("保存失败：" + e.message); }
}
function handleTerminalActions(data, text) {
  const actions = data.actions || [];
  logAiHistory(text, (actions[0] && actions[0].label) || "已处理");
  let deferred = 0;
  actions.forEach((a, i) => {
    if (a.status === "clarify") { setTimeout(() => queueClarify(a), i * 380); deferred++; }
    else if (a.personal_fact && a.fields && a.fields.note_id) { setTimeout(() => queuePersonalFact(a), i * 380); deferred++; }
    else if (a.confirm) { setTimeout(() => queueConfirm(a), i * 380); deferred++; }
    else setTimeout(() => showToast(a.label || a.action, "green"), i * 380);
  });
  if (data.model) setTimeout(() => showToast("本次由 " + (data.model === "voice_split" ? "语音拆句" : data.model) + " 处理", "blue"), Math.max(actions.length, 1) * 380 + 120);
  expandWorkspace();
  const first = actions[0];
  if (first && (first.confirm || first.status === "clarify")) setStatus("有 " + deferred + " 项待你拍板（左下角卡片），选好才会生效。", 8000);
  else if (first && MOD_LABEL[first.module]) switchModule(first.module);
}
/* 低置信确认卡：模型拿不准意图时显式问用户，拍板后带 force_intent 重发 */
const INTENT_LBL = { note: "笔记", todo: "待办", expense: "记账", diary: "日记", read_later: "稍后读" };
function queueClarify(action) {
  const stack = $("#confirmStack");
  const card = document.createElement("div");
  card.className = "confirm-card";
  const opts = (action.fields && action.fields.candidates) || ["note", "todo"];
  const orig = (action.fields && action.fields.orig_text) || "";
  card.innerHTML = `<div class="cc-title">这条拿不准，你说了算</div>
    <div class="cc-sub">${escapeHtml(orig)}</div>
    <div class="cc-btns">${opts.map(o => `<button class="cc-yes" data-intent="${o}">${INTENT_LBL[o] || o}</button>`).join("")}</div>`;
  card.querySelectorAll("button").forEach(b => b.addEventListener("click", async () => {
    card.remove();
    try {
      const r = await fetch("/api/terminal", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: orig, source: "panel", force_intent: b.dataset.intent }) });
      if (r.ok) { const d = await r.json(); handleTerminalActions(d, orig); return; }
    } catch {}
    setStatus("没保存上，再输一次吧。");
  }));
  stack.appendChild(card);
}
/* 终端 confirm 动作：AI 只建议、用户点头才生效 */
function queueConfirm(action) {
  const stack = $("#confirmStack");
  const card = document.createElement("div");
  card.className = "confirm-card";
  card.innerHTML = `<div class="cc-title">${escapeHtml(action.label || action.action)}</div>
    <div class="cc-sub">AI 建议的动作 · 确认后才会生效</div>
    <div class="cc-btns"><button class="cc-yes">确认</button><button class="cc-no">放弃</button></div>`;
  card.querySelector(".cc-yes").addEventListener("click", async () => {
    card.remove();
    try { await applyTerminalAction(action); showToast("已确认：" + (action.label || action.action), "green"); }
    catch (e) { showToast("执行失败：" + e.message, "red"); }
  });
  card.querySelector(".cc-no").addEventListener("click", () => { card.remove(); setStatus("已放弃该建议。"); });
  stack.appendChild(card);
}
/* 个人信息询问卡：已存为个人信息（带标签），可选从笔记流移除（软删→回收站 30 天可找回） */
function queuePersonalFact(action) {
  const stack = $("#confirmStack");
  const card = document.createElement("div");
  card.className = "confirm-card";
  const snippet = String((action.fields || {}).text || "").slice(0, 30);
  card.innerHTML = `<div class="cc-title">${escapeHtml(action.label || "已记入个人信息")}</div>
    <div class="cc-sub">${escapeHtml(snippet)} · 从笔记列表移除吗？（回收站 30 天内可找回）</div>
    <div class="cc-btns"><button class="cc-yes">移除</button><button class="cc-no">保留</button></div>`;
  let closed = false;
  const close = () => { closed = true; card.remove(); };
  card.querySelector(".cc-yes").addEventListener("click", async () => {
    close();
    try {
      await api("/api/notes/delete_many", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: [action.fields.note_id] }) });
      showToast("已移入回收站，30 天内可找回", "green");
      if (state.module === "note" || state.module === "trash") await loadNotes();
    } catch (e) { showToast("移除失败：" + e.message, "red"); }
  });
  card.querySelector(".cc-no").addEventListener("click", close);
  stack.appendChild(card);
  setTimeout(() => { if (!closed && card.isConnected) card.remove(); }, 12000);
}
async function applyTerminalAction(a) {
  const f = a.fields || {};
  if (a.action === "create_contact") {
    await api("/api/contacts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) });
    switchModule("contact");
  } else if (a.action === "create_expense") {
    await api("/api/expenses", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) });
    switchModule("ledger");
  } else if (a.action === "create_journal") {
    await api("/api/diary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: f.text || "" }) });
    switchModule("journal");
  } else {
    await api("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: f.text || "", source: "manual" }) });
    switchModule(a.module || "note");
  }
}
/* 危险批量删除的确认卡（记账/课程/人脉：物理删除，必须过卡） */
function openBatchConfirm(ids) {
  const mod = state.module;
  const names = ids.map(id => {
    let el = null;
    if (mod === "ledger") el = moduleList.querySelector(`.xrow[data-id="${id}"]`);
    else if (mod === "course") el = moduleList.querySelector(`.srow[data-id="${id}"]`);
    else if (mod === "contact") el = moduleList.querySelector(`.item[data-cid="${id}"] .item-title`);
    return el ? el.textContent.replace(/\s+/g, " ").trim().slice(0, 40) : id;
  });
  const wrap = $("#modalWrap"), card = $("#modalCard");
  card.innerHTML = `<div class="mc-title">彻底删除选中的 ${ids.length} 项？</div>
    <div class="mc-list">${names.map(n => "· " + escapeHtml(n)).join("<br>")}</div>
    <div class="hint" style="padding:0 0 10px">此类记录不进回收站，删除不可恢复。</div>
    <div class="mc-btns"><button class="tool-btn" id="mcCancel">取消</button>
    <button class="batch-btn danger" id="mcYes">确认删除</button></div>`;
  wrap.classList.add("show");
  $("#mcCancel").addEventListener("click", () => wrap.classList.remove("show"));
  $("#mcYes").addEventListener("click", async () => {
    const base = mod === "ledger" ? "/api/expenses/" : mod === "course" ? "/api/courses/" : "/api/contacts/";
    let okN = 0;
    for (const id of ids) { try { await api(base + id, { method: "DELETE" }); okN++; } catch {} }
    ids.forEach(id => state.selected.delete(mod + ":" + id));
    wrap.classList.remove("show");
    setStatus(`已删除 ${okN} 项。`);
    if (RENDERERS[mod]) RENDERERS[mod](false);
    updateBatchBar();
  });
}
/* 识别记录（本地留痕，未拍板自提案） */
function logAiHistory(text, label) {
  try {
    const arr = JSON.parse(localStorage.getItem("luyuan_ai_log") || "[]");
    arr.unshift({ t: fmtTime(new Date().toISOString()), text: text.slice(0, 60), label });
    localStorage.setItem("luyuan_ai_log", JSON.stringify(arr.slice(0, 30)));
  } catch {}
}

/* ---------------- 录音（F10 / 点麦克风） ---------------- */
const capBtn = $("#capture"), micIcon = $("#micIcon"), micTimer = $("#micTimer");
let listenStart = 0;
async function doCaptureClick() {
  if (capBtn.dataset.mode === "stop") {
    try { await api("/api/capture/stop", { method: "POST" }); } catch {}
    capBtn.dataset.mode = "transcribing";
    micIcon.textContent = "…";
    return;
  }
  try {
    const r = await api("/api/capture", { method: "POST" });
    if (!r.triggered) setStatus("未触发（可能正在记录中，或程序未就绪）。");
  } catch (e) { setStatus("发送失败：" + e.message); }
}
capBtn.addEventListener("click", doCaptureClick);
async function syncBtn() {
  try {
    const st = await api("/api/status");
    if (st.state === "listening") {
      if (capBtn.dataset.mode !== "stop") { capBtn.dataset.mode = "stop"; capBtn.classList.add("recording"); listenStart = Date.now(); }
      const el = Math.floor((Date.now() - listenStart) / 1000);
      micTimer.textContent = String(Math.floor(el / 60)).padStart(2, "0") + ":" + String(el % 60).padStart(2, "0");
      setStatus("");
    } else if (st.state === "transcribing") {
      if (capBtn.dataset.mode === "stop") { capBtn.dataset.mode = "transcribing"; capBtn.classList.remove("recording"); micIcon.textContent = "…"; }
      setStatus("");
    } else {
      if (capBtn.dataset.mode !== "idle") {
        capBtn.dataset.mode = "idle";
        capBtn.classList.remove("recording");
        micIcon.innerHTML = '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="3" width="6" height="10" rx="3"/><path d="M5.5 11a5.5 5.5 0 0 0 11 0M11 16.5V19"/></svg>';
        if (state.module === "note" || state.module === "trash") await loadNotes();
      }
      if (st.state === "idle" && st.error) setStatus("注意：" + st.error);
      else if (st.state === "idle" && Date.now() > statusExpiry) setStatus("");
    }
  } catch {}
}

/* ---------------- Ollama 徽标 ---------------- */
async function pollOllama() {
  const b = $("#ollamabadge");
  try {
    const r = await api("/api/ollama");
    b.classList.toggle("on", !!r.running);
    b.textContent = r.running ? `智能 · 开（${r.model || ""}）` : "智能 · 关";
    b.title = r.running ? "归类/整理/回顾已就绪" : "Ollama 未运行，智能功能暂不可用；记事等主流程不受影响。点我尝试拉起。";
  } catch { b.textContent = "…"; }
}
$("#ollamabadge").addEventListener("click", async () => {
  const b = $("#ollamabadge");
  b.textContent = "正在拉起…";
  try {
    const r = await api("/api/ollama/wake", { method: "POST" });
    setStatus(r.running ? "Ollama 已就绪，智能功能可用。" : "没拉起来：请从开始菜单手动打开 Ollama，再点一次徽标。");
  } catch (e) { setStatus("拉起失败：" + e.message); }
  pollOllama();
});

/* ---------------- 键盘 ---------------- */
document.addEventListener("keydown", (e) => {
  const inField = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
  // Esc 优先于一切：弹层/抽屉开着时，即便焦点在输入框也必须能关掉（否则用户只能去点×）
  // 注意：openDrawerName 在 modules.js 里声明，用 typeof 兜底防止加载顺序变化时 ReferenceError
  const _drawerOpen = (typeof openDrawerName !== "undefined") && openDrawerName;
  if (e.key === "Escape" && (_drawerOpen || detailId || ctDetailId)) {
    e.preventDefault();
    if (_drawerOpen) { closeAllDrawers(); return; }
    if (detailId) { closeDetail(); return; }
    if (ctDetailId && typeof closeCtDetail === "function") { closeCtDetail(); return; }
  }
  /* 日记「看全文」那张纸也吃 Esc（2026-10-30）：它是浮在整页上的层，Esc 该先关它 */
  if (e.key === "Escape" && state.module === "journal" && state.expanded.size && !_drawerOpen && !detailId && !ctDetailId) {
    e.preventDefault();
    state.expanded.clear();
    if (RENDERERS.journal) RENDERERS.journal(false);
    return;
  }
  /* 2026-10-30 通宵批：补三个天天用得上、却一直没有的键 ——
     Ctrl+S 存日记（在日记框里顺手就有「保存」的肌肉记忆）、Ctrl+A 全选当前列表、
     详情弹层里 ←/→ 翻上一条/下一条（原来看完一条要关掉再重新找地方点）。 */
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === "s" || e.key === "S") && state.module === "journal") {
    e.preventDefault();
    if (typeof saveDiary === "function") saveDiary();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === "a" || e.key === "A") && !inField && state.module === "note") {
    e.preventDefault();
    currentNotes.forEach(n => state.selected.add("note:" + n.id));
    renderNotes(); updateBatchBar();
    setStatus(`已全选 ${currentNotes.length} 条（点「清选」或 Esc 取消勾选）`, 5000);
    return;
  }
  if (detailId && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
    e.preventDefault();
    stepDetail(e.key === "ArrowRight" ? 1 : -1);
    return;
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); openCmdk(); return; }
  if (e.key === "?" && !inField) { e.preventDefault(); $("#helpPop").classList.toggle("show"); return; }
  if (e.key === "/" && !inField) {
    e.preventDefault();
    const s = $("#modSearch");
    if (state.workspaceExpanded && s) s.focus();
    else expandWorkspace();
    return;
  }
  if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !inField && state.workspaceExpanded) {
    e.preventDefault();
    const idx = MODULES.findIndex(m => m.id === state.module);
    const next = idx + (e.key === "ArrowRight" ? 1 : -1);
    if (next >= 0 && next < MODULES.length) switchModule(MODULES[next].id);
    return;
  }
  if (e.key === "ArrowDown" && !inField) { e.preventDefault(); expandWorkspace(); return; }
  if ((e.key === "ArrowUp" || e.key === "Escape") && !inField) {
    e.preventDefault();
    if (openDrawerName) { closeAllDrawers(); return; }
    if (detailId) { closeDetail(); return; }
    if (editing) { editing = false; loadNotes(); return; }
    if (state.pickerId) { state.pickerId = null; renderNotes(); return; }
    if (ctDetailId && typeof closeCtDetail === "function") { closeCtDetail(); return; }
    if ($("#datepop").classList.contains("show")) { $("#datepop").classList.remove("show"); return; }
    if ($("#digestpop").classList.contains("show")) { $("#digestpop").classList.remove("show"); return; }
    if ($("#helpPop").classList.contains("show")) { $("#helpPop").classList.remove("show"); return; }
    if ($("#cmdk").classList.contains("show")) { $("#cmdk").classList.remove("show"); return; }
    if ($("#modalWrap").classList.contains("show")) { $("#modalWrap").classList.remove("show"); return; }
    if (document.activeElement === quickEl) { quickEl.blur(); return; }
    collapseWorkspace();
  }
});

/* ---------------- 快捷键帮助卡 + Ctrl+K 快速跳转 ---------------- */
$("#helpclose").addEventListener("click", () => $("#helpPop").classList.remove("show"));
document.addEventListener("click", (e) => {
  const p = $("#helpPop");
  if (p.classList.contains("show") && !p.contains(e.target) && e.key !== "?") p.classList.remove("show");
});
let cmdkItems = [], cmdkIdx = 0, cmdkT = null;
function openCmdk() {
  $("#cmdk").classList.add("show");
  const input = $("#cmdin");
  input.value = "";
  buildCmdk("");
  setTimeout(() => input.focus(), 30);
}
function buildCmdk(q) {
  const res = [];
  MODULES.forEach(m => { if (!q || m.label.includes(q)) res.push({ label: "跳到「" + m.label + "」", run: () => { expandWorkspace(); switchModule(m.id); } }); });
  /* 2026-10-30 双入口批：两个大入口也进 Ctrl+K，键盘党不用先去侧栏点 */
  if (!q) {
    res.push({ label: "去「路远」—— AI 入口（对话 / 汇报 / 问答）", run: () => setEntry("ai") });
    res.push({ label: "回「工作台」—— 笔记 / 待办 / 记账", run: () => setEntry("work") });
  }
  res.push({ label: "快捷键帮助", run: () => $("#helpPop").classList.add("show") });
  res.push({ label: state.module === "trash" ? "返回笔记" : "打开回收站", run: () => { expandWorkspace(); switchModule(state.module === "trash" ? "note" : "trash"); } });
  cmdkItems = res;
  cmdkIdx = 0;
  renderCmdk();
  if (q) {
    clearTimeout(cmdkT);
    cmdkT = setTimeout(async () => {
      try {
        const { notes } = await api("/api/search?q=" + encodeURIComponent(q));
        const extra = (notes || []).slice(0, 5).map(n => ({
          label: "笔记 · " + noteTitle(n.text),
          run: () => {
            expandWorkspace(); switchModule("note"); state.expanded.add(n.id);
            setTimeout(() => {
              const el = moduleList.querySelector('.item[data-id="' + n.id + '"]');
              if (el) { el.scrollIntoView({ block: "center" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600); }
            }, 450);
          }
        }));
        cmdkItems = res.concat(extra);
        renderCmdk();
      } catch {}
    }, 200);
  }
}
function renderCmdk() {
  $("#cmdres").innerHTML = cmdkItems.map((it, i) =>
    `<div class="drow${i === cmdkIdx ? " sel" : ""}" data-i="${i}">${escapeHtml(it.label)}${i === cmdkIdx ? '<span style="margin-left:auto;color:var(--ink-faint);font-size:11px">⏎</span>' : ""}</div>`).join("")
    || `<div class="hint">没有匹配项</div>`;
}
$("#cmdin").addEventListener("input", e => buildCmdk(e.target.value.trim()));
$("#cmdin").addEventListener("keydown", e => {
  if (e.key === "ArrowDown") { e.preventDefault(); cmdkIdx = Math.min(cmdkIdx + 1, cmdkItems.length - 1); renderCmdk(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); cmdkIdx = Math.max(cmdkIdx - 1, 0); renderCmdk(); }
  else if (e.key === "Enter") { e.preventDefault(); const it = cmdkItems[cmdkIdx]; $("#cmdk").classList.remove("show"); it && it.run(); }
  else if (e.key === "Escape") { $("#cmdk").classList.remove("show"); }
});
$("#cmdres").addEventListener("click", e => {
  const r = e.target.closest(".drow");
  if (r) { const it = cmdkItems[+r.dataset.i]; $("#cmdk").classList.remove("show"); it && it.run(); }
});
document.addEventListener("click", e => {
  const p = $("#cmdk");
  if (p.classList.contains("show") && !p.contains(e.target)) p.classList.remove("show");
});
$("#modalWrap").addEventListener("click", e => { if (e.target.id === "modalWrap") e.target.classList.remove("show"); });

/* ---------------- 通知锚点（沿用旧链接格式） ---------------- */
const PAGE_MAP = { notes: "note", diary: "journal", contacts: "contact" };
function handleHash() {
  /* 2026-10-30：原来只认 notes/diary/contacts 三个深链，别的模块（course/todo/…）
     写了 #page=xxx 会静默不跳，看着像"打开就是错的页"。改成认所有模块 id。 */
  const pm = (location.hash || "").match(/#page=([\w-]+)/);
  if (pm) {
    const target = PAGE_MAP[pm[1]] || (MODULES.some(m => m.id === pm[1]) ? pm[1] : null);
    if (target) {
      history.replaceState(null, "", location.pathname);
      expandWorkspace();
      switchModule(target);
      return;
    }
  }
  const dm = (location.hash || "").match(/#ctdone=([^/]+)\/([\w-]+)/);
  if (dm) {
    history.replaceState(null, "", location.pathname);
    api("/api/contacts/" + dm[1] + "/todos/" + dm[2] + "/toggle", { method: "POST" })
      .then(() => setStatus("待办已完成", 4000))
      .catch((e) => setStatus("完成失败：" + e.message));
    expandWorkspace(); switchModule("contact");
    return;
  }
  const sm = (location.hash || "").match(/#ctsnooze=([^/]+)\/([\w-]+)\/(\d+)/);
  if (sm) {
    history.replaceState(null, "", location.pathname);
    api("/api/contacts/" + sm[1] + "/todos/" + sm[2] + "/snooze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hours: +sm[3] }) })
      .then(() => setStatus("好，" + sm[3] + " 小时后再提醒你", 4000))
      .catch((e) => setStatus("贪睡失败：" + e.message));
    expandWorkspace(); switchModule("contact");
    return;
  }
  const m = (location.hash || "").match(/#n=([0-9a-f-]+)/);
  if (!m) return;
  const id = m[1];
  history.replaceState(null, "", location.pathname);
  expandWorkspace();
  switchModule("note");
  state.expanded.add(id);
  state.jumpDate = null;
  setTimeout(() => {
    const el = moduleList.querySelector(`.item[data-id="${id}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("flash");
      setTimeout(() => el.classList.remove("flash"), 2000);
    } else setStatus("提醒的这条笔记不在当前列表（可能已删除或在更早日期）。");
  }, 400);
}
window.addEventListener("hashchange", handleHash);

/* ---------------- 玻璃预览（真实最近 3 条） ---------------- */
function renderPreview() {
  const stack = $("#previewStack");
  const latest = currentNotes.filter(n => !n.deleted).slice(0, 3);
  if (!latest.length) { stack.innerHTML = ""; return; }
  stack.innerHTML = latest.map(n => {
    const src = n.source === "voice" ? "语音" : "手动";
    const tag = (n.tags || [])[0] ? `#${n.tags[0]}` : "";
    return `<div class="preview-card">
      <div class="preview-meta"><span>${src}</span><span>${fmtTime(n.created_at)}</span><span>${escapeHtml(tag)}</span></div>
      <div class="preview-title">${escapeHtml(noteTitle(n.text))}</div>
    </div>`;
  }).join("");
}

/* ---------------- 版本自检 ----------------
   只在「服务端比页面新」时强制刷新（防旧页面静默失效）；
   页面比服务端新 = UI 已落地、后端 APP_VER 待 PC 会话同步，属协调过渡态，静默放行。
   A5（2026-09-14）：以前只比服务端 ver——改了 modules.js 忘同步 ?v= 时，旧文件会静默失效且毫无提示。
   现在额外用 no-store 探测磁盘上两份文件的真实版本号，谁比当前页面新就刷一次（每会话最多一次）。 */
const MY_VER = 62;
async function checkVer() {
  try {
    const h = await api("/api/health");
    let diskApp = 0, diskMod = 0;
    try {
      const t = await fetch("app.js?_vprobe=" + Date.now(), { cache: "no-store" }).then(r => r.text());
      diskApp = +(((t.match(/MY_VER\s*=\s*(\d+)/) || [])[1]) || 0);
    } catch {}
    try {
      const t = await fetch("ui/modules.js?_vprobe=" + Date.now(), { cache: "no-store" }).then(r => r.text());
      diskMod = +(((t.match(/MODULES_VER\s*=\s*(\d+)/) || [])[1]) || 0);
    } catch {}
    const stale = (diskApp && diskApp > MY_VER) ||
                  (diskMod && window.MODULES_VER && diskMod > window.MODULES_VER);
    if ((h.ver && h.ver > MY_VER) || stale) {
      if (sessionStorage.getItem("ver_reload")) { setStatus("页面版本与服务端不一致，请手动 Ctrl+F5 刷新", 30000); return; }
      sessionStorage.setItem("ver_reload", "1");
      setStatus("路远更新了，正在刷新页面…", 30000);
      setTimeout(() => location.reload(), 1200);
    } else sessionStorage.removeItem("ver_reload");
  } catch {}
}

/* ---------------- 问候语 ---------------- */
(function greet() {
  const h = new Date().getHours();
  const g = h < 5 ? "夜深了" : h < 9 ? "早上好" : h < 12 ? "上午好" : h < 14 ? "中午好" : h < 18 ? "下午好" : "晚上好";
  $("#greet").textContent = g + "，想记点什么？";
})();

/* 自提案 A（2026-09-15·UI席位自审）：深色=手动开关在顶栏，无手动记录时首次跟随系统 */
(function initDark(){
  /* 2026-10-30 通宵批：读 URL 上的少量参数，供桌面壳层 / 截图验收用。
     ?embed=1  桌面壳层内嵌（收窄外边距、隐藏问候语，给独立窗口留位置）
     ?dark=1|0 强制主题（不写 localStorage，纯当次会话）
     认不出的参数一律忽略，不报错、不影响任何逻辑。 */
  let q = null;
  try { q = new URLSearchParams(location.search); } catch (e) { q = null; }
  const param = k => (q && q.get(k)) || "";
  if (param("embed") === "1") document.body.classList.add("embed");
  const forcedDark = param("dark");
  const saved = localStorage.getItem("luyuan_dark");
  if (forcedDark === "1" || forcedDark === "0") {
    document.body.classList.toggle("dark", forcedDark === "1");
  } else if (saved === "1" || (saved === null && matchMedia("(prefers-color-scheme: dark)").matches)) {
    document.body.classList.add("dark");
  }
  const btn = document.getElementById("darkBtn");
  btn && btn.addEventListener("click", () => {
    const dark = document.body.classList.toggle("dark");
    localStorage.setItem("luyuan_dark", dark ? "1" : "0");
    showToast && showToast(dark ? "夜色模式，护眼" : "白天模式");
  });
})();

/* ---------------- 布局自适应（2026-10-30 通宵批）----------------
   桌面壳层窗口 1477×880 时卡片右边缘被窗口切掉：外壳把整页做了 CSS 缩放，
   而 media query 读到的仍是缩放前的假宽度（1477），于是「宽屏布局 + 缩放渲染」
   = 内容横向溢出，被 body 的 overflow:hidden 裁掉。
   这里不再问 media query，直接量 body 的真实渲染宽度（缩放后会明显小于 innerWidth），
   由它决定 ①侧栏是否收成图标条 ②内容列最宽多少，写进 --content-max。
   窗口从 1100 到 1920 全程自适应，缩放后同样成立。 */
function fitLayout() {
  /* 关键：量 body.clientWidth 而不是 innerWidth。
     外壳缩放时 innerWidth 还是窗口的 1477，但 body 的真实排版宽度只有 821 ——
     拿 innerWidth 判断就会得出「我是宽屏」，于是按宽布局画、画完被裁。
     clientWidth 是缩放后的真实可用宽度（不缩放时两者相同）。 */
  let bodyW = 0;
  try { bodyW = document.body.clientWidth; } catch (e) {}
  if (!bodyW) { try { bodyW = parseFloat(getComputedStyle(document.body).width) || 0; } catch (e) {} }
  if (!bodyW) bodyW = window.innerWidth;
  const compact = bodyW < 940;
  document.body.classList.toggle("compact", compact);
  const sidebar = compact ? 68 : 214;
  const main = Math.max(300, bodyW - sidebar);
  const gutters = main < 900 ? 24 : 52;         // 内容列左右内边距合计
  const maxW = Math.max(300, Math.min(1240, main - gutters));
  document.documentElement.style.setProperty("--content-max", Math.round(maxW) + "px");
  if (typeof updateRailIndicator === "function") updateRailIndicator();
}
window.addEventListener("resize", fitLayout);
if (window.ResizeObserver) {
  try {
    let raf = 0;
    new ResizeObserver(() => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; fitLayout(); });   // 合并成帧回调，避免观察-改写循环
    }).observe(document.body);
  } catch (e) {}
}

/* ---------------- 启动 ---------------- */
window.addEventListener("resize", updateRailIndicator);
fitLayout();                 // 2026-10-30：先按真实渲染宽度定好布局，再画内容
paintEntry("work");          // 双入口：默认落「工作台」，但「路远」入口就在品牌区正下方一眼看见
/* ?entry=ai 直接落路远入口（壳内嵌 / 截图验收用；默认仍是工作台） */
if (urlParam("entry") === "ai") { paintEntry("ai"); switchModule("chat", { force: true }); }
loadNotes();
renderToolbar(state.module);   // 2026-09-14：启动直接渲染工具栏（原来要等第一次切模块才出现）
loadCategories();
pollOllama();
setInterval(pollOllama, 20000);
handleHash(); window.__qaReady=true;
setInterval(() => { if (state.module === "note" || state.module === "trash") loadNotes(); }, 4000);
setInterval(syncBtn, 700);
syncBtn();
/* 待办独立轮询（09-15）：待办条从笔记页搬走后，红点 / 新待办 toast / 待办页刷新
   全靠这条轮询驱动，与当前停在哪个模块无关。 */
setInterval(pollTodos, 6000);
setInterval(pollReports, 8000);
pollTodos();
/* 自提案 A（09-15 自批）：每日晨报条——今日概览一眼看全（周次/待办/校历节点/今日提醒）。
   数据全走现成接口；任一接口失败对应段静默消失；关闭状态存 localStorage（当天不再弹）。 */
async function renderDayBrief() {
  // hero 大日期（借鉴课务系统 nextcard 2026-09-15）
  const hd = document.getElementById("heroDate");
  if (hd) { const _w = "日一二三四五六", _d = new Date(); hd.textContent = `${_d.getMonth() + 1}月${_d.getDate()}日 · 周${_w[_d.getDay()]}`; }
  const el = document.getElementById("dayBrief");
  if (!el) return;
  const today = new Date().toISOString().slice(0, 10);
  if (localStorage.getItem("daybriefHide") === today) { el.hidden = true; return; }
  const [csu, todos, notes, badge] = await Promise.all([
    fetch("/api/csu/overview").then(r => r.json()).catch(() => null),
    fetch("/api/todos").then(r => r.json()).catch(() => null),
    fetch("/api/notes?limit=200").then(r => r.json()).catch(() => null),
    fetch("/api/reports/badge").then(r => r.json()).catch(() => null),
  ]);
  /* 2026-10-29 体检批：横条 → 「今天」卡。四格只回答一个问题——今天有什么卡着我。
     口径：逾期=截止时间已过；今天到期=截止在今日 23:59 前且未过；今天提醒=当天要响的提醒；新汇报=路远远未读。 */
  const all = (todos && todos.todos) || [];
  const now = new Date();
  const endOfToday = new Date(today + "T23:59:59");
  let overdue = 0, dueToday = 0;
  for (const t of all) {
    if (!t.due_at) continue;
    const d = new Date(t.due_at);
    if (isNaN(d)) continue;
    if (d < now) overdue++;
    else if (d <= endOfToday) dueToday++;
  }
  let remindToday = 0;
  if (notes && notes.notes) {
    remindToday = notes.notes.filter(n => !n.remind_fired && (n.remind_at || "").slice(0, 10) === today).length;
  }
  const unreadRep = (badge && badge.unread) || 0;
  const weekLabel = (csu && csu.week && csu.week.label) || "本周";
  const _w2 = "日一二三四五六", _d2 = new Date();
  const dateLabel = `${_d2.getMonth() + 1}月${_d2.getDate()}日`;
  const cell = (n, label, cls, goto) =>
    `<button class="db-item${n ? " " + cls : " zero"}" data-goto="${goto}"><b>${n}</b><span>${label}</span></button>`;
  let calSoon = 0;
  if (csu && csu.events) {
    for (const e of csu.events) {
      const end = new Date((e.end || e.date) + "T23:59:59");
      if (end >= now) calSoon++;
    }
  }
  el.hidden = false;
  el.innerHTML =
    `<div class="tb-week"><b>${escapeHtml(weekLabel)}</b><span>${dateLabel}${calSoon ? " · 学业节点 " + calSoon + " 项" : ""}</span></div>
     <div class="tb-grid">
       ${cell(dueToday, "今天到期", "warn", "todo")}
       ${cell(remindToday, "今天提醒", "gold", "note")}
       ${cell(overdue, "已逾期", "", "todo")}
       ${cell(unreadRep, "新汇报", "info", "report")}
     </div>
     <span class="db-x" id="dbX" title="今天不再显示">✕</span>`;
  el.querySelectorAll(".db-item").forEach(s => s.addEventListener("click", () => {
    const m = s.dataset.goto;
    if (m && typeof switchModule === "function") switchModule(m, { force: true });
  }));
  // 自提案 C：校历截止提醒——≤2 天的截止/评议类事件弹 toast（本会话一次）
  if (csu && csu.events && !window._calToastShown) {
    const now = new Date();
    const urgent = csu.events.filter(e => {
      if (!/截止|评议|报资助/.test(e.name)) return false;
      const end = new Date((e.end || e.date) + "T23:59:59");
      const days = Math.round((end - now) / 86400000);
      return days >= 0 && days <= 2;
    });
    if (urgent.length) {
      window._calToastShown = true;
      setTimeout(() => showToast("⏰ 学业提醒：" + urgent[0].name + (urgent.length > 1 ? " 等 " + urgent.length + " 项即将截止" : " 即将截止"), "amber"), 1800);
    }
  }
  const x = document.getElementById("dbX");
  if (x) x.addEventListener("click", () => {
    localStorage.setItem("daybriefHide", today);
    el.hidden = true;
  });
}
/* 09-15 防御补丁：v42 新版 panel 移除了 modCount 计数位，但各 TOOLBARS 仍直接
   $("#modCount").textContent = ... → 全模块渲染炸（Cannot set properties of null）。
   注入隐藏占位恢复兼容；实装会话若要真计数器，替换此占位即可。 */
if (!document.getElementById("modCount")) {
  const _mc = document.createElement("span");
  _mc.id = "modCount";
  _mc.style.display = "none";
  (document.querySelector(".topbar") || document.body).appendChild(_mc);
}
checkVer();
renderDayBrief();
setInterval(checkVer, 60000);
/* 2026-10-30 通宵批：今日卡原来只在启动那一次算，「今天到期」放一下午还是早上的数；
   现在 90 秒静默重算一次（四个接口都轻，失败各自静默）。 */
setInterval(renderDayBrief, 90000);
/* 路远（3927）在线状态：只在「路远」入口里轮询，30 秒一次，走开就不打扰 */
setInterval(() => { if (ENTRY === "ai") pollAiStatus(); }, 30000);
quickEl.focus();
