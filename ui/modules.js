// 路远桌面端 · modules.js v20
// 记账 / 课程 / 收件夹待确认 / 人脉 / 日记 / AI 抽屉 / 设置抽屉 / 手势 / 弹层
// 由 app.js（v39）加载；注册 RENDERERS / TOOLBARS 并提供 openDatePop / loadDigest / closeCtDetail
"use strict";
/* A5（2026-09-14）：独立版本号——必须与本文件头部 ?v= 严格同步；
   app.js 的 checkVer 会 no-store 探测这个常量，发现磁盘更新就自动刷页面。 */
window.MODULES_VER = 65;

/* ============ 记账 + 收件夹待确认 ============ */
let inboxCache = { items: [], vl_model: "" };
async function loadInboxCount() {
  try {
    const r = await api("/api/inbox/pending");
    inboxCache = r;
    const n = (r.items || []).length;
    const btn = document.querySelector('.module-btn[data-mod="ledger"]');
    let b = btn.querySelector(".bdg");
    if (n > 0) { if (!b) { b = document.createElement("span"); b.className = "bdg"; btn.appendChild(b); } b.textContent = n; }
    else if (b) b.remove();
  } catch {}
}
TOOLBARS.ledger = function () {
  modToolbar.innerHTML = `
    <span class="count" id="modCount"></span>
    <span class="spacer"></span>
    <button class="tool-btn" id="expImportBtn">⤓ 导入账单</button>
    <button class="tool-btn" id="expAddBtn">＋ 记一笔</button>`;
  /* 2026-10-30 通宵批：原来点「＋ 记一笔」只是把表单从 display:none 放开，
     而表单在统计卡下面那屏、页面还停在顶部 —— 点了像没反应。现在展开后滚过去并聚焦金额。 */
  $("#expAddBtn").addEventListener("click", () => {
    const f = $("#expForm");
    if (!f) return;
    const open = f.style.display === "none";
    f.style.display = open ? "flex" : "none";
    if (open) {
      f.scrollIntoView({ block: "center", behavior: REDUCED.matches ? "auto" : "smooth" });
      const amt = $("#exp-amt");
      if (amt) setTimeout(() => amt.focus(), 60);
    }
  });
  $("#expImportBtn").addEventListener("click", () => {
    const p = $("#expImportPanel");
    if (p) p.style.display = p.style.display === "none" ? "block" : "none";
  });
  // 导入流程（事件委托挂在 moduleList，账单面板随渲染重建）
  // 🐛 2026-10-30 修：这段原来直接写在本函数体内，而本函数每次进入记账页都会被
  // renderToolbar 调一次 → 每进一次就多叠一个监听 → 点一次「解析」会发 N 次
  // POST /api/expenses/import（重复导入账单）。加 dataset 守卫，全生命周期只绑一次。
  if (!moduleList.dataset.expImportBound) {
    moduleList.dataset.expImportBound = "1";
    moduleList.addEventListener("click", async e => {
      const parse = e.target.closest("#expParseBtn");
      if (parse) {
        const txt = ($("#expImportText") || {}).value || "";
        if (!txt.trim()) { $("#expImportInfo").textContent = "先粘贴账单 CSV 内容"; return; }
        const info = $("#expImportInfo");
        info.textContent = "解析中…";
        parse.disabled = true;
        try {
          const rr = await api("/api/expenses/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: txt, source: "bill" }) });
          info.textContent = "导入 " + rr.imported + " 笔支出，跳过 " + rr.skipped + " 笔" + (rr.errors && rr.errors.length ? "（" + rr.errors[0] + "）" : "");
          if (rr.imported) { RENDERERS.ledger(false); loadInboxCount && loadInboxCount(); }
        } catch (err) { info.textContent = "导入失败：" + err.message; }
        parse.disabled = false;
      }
    });
  }
};
RENDERERS.ledger = async function (animate) {
  const hito = $("#hitokoto"); hito.style.display = "none";
  try {
    const [r, ib] = await Promise.all([api("/api/expenses"), api("/api/inbox/pending")]);
    inboxCache = ib;
    const st = r.stats || {};
    const max = Math.max(1, ...(st.categories || []).map(c => c.amount));
    const cats = (st.categories || []).map(c =>
      `<div class="catbar"><span style="width:40px">${escapeHtml(c.category)}</span><span class="bar"><i style="width:${Math.round(c.amount / max * 100)}%"></i></span><span>¥${c.amount}</span></div>`).join("")
      || `<div class="hint">本月还没有分类数据</div>`;
    const rows = (r.items || []).map(e =>
      `<div class="xrow" data-id="${e.id}"><input type="checkbox" class="xcheck" data-id="${e.id}" ${state.selected.has("ledger:"+e.id) ? "checked" : ""}/><span>${fmtTime(e.spent_at)}</span><span>${escapeHtml(e.item)}</span>
       <span class="xcat">${escapeHtml(e.category || "其他")}</span>
       ${e.image ? `<a href="/api/shots?rel=${encodeURIComponent(e.image)}" target="_blank" style="font-size:12px">原图</a>` : ""}
       <span class="xamt">¥${e.amount}</span>
       <button class="xdel" data-xdel="${e.id}">删</button></div>`).join("")
      || `<div class="empty" style="padding:26px 0">这个月还一笔没记。右上「＋ 记一笔」，或直接在上面输入框说「午饭 15」。<div class="empty-acts"><button class="tool-btn pri" id="expAddEmpty">＋ 记一笔</button></div></div>`;
    const inboxHtml = renderInboxItems(ib);
    if (state.module !== "ledger") return;   // 切走了，迟到结果丢弃
    moduleList.innerHTML = `
      <div class="ledger-stat"><span class="ls-label">本月支出</span><span class="ls-num" id="lsNum">¥0</span>
        <span class="ls-sub">${st.count ?? 0} 笔 · 收入未记</span></div>${cats}
      <div class="mform" id="expForm" style="display:none">
        <input id="exp-amt" style="width:84px" placeholder="金额" inputmode="decimal">元
        <input id="exp-item" style="width:150px" placeholder="名目（如 午饭）">
        <button class="add2" id="exp-add">记一笔</button>
        <span class="hint" style="padding:0">手机付款截图会自动进这里的「待确认」</span>
      </div>
      <div id="expImportPanel" style="display:none" class="mu-import">
        <div class="hint">把微信/支付宝导出的账单 CSV 用记事本打开，全选复制粘贴到下面（自动只导「支出」，重复导入自动跳过）：</div>
        <textarea id="expImportText" rows="7" style="width:100%;margin-top:6px" placeholder="交易时间,交易类型,交易对方,商品,收/支,金额(元)…"></textarea>
        <div style="display:flex;gap:8px;margin-top:6px;align-items:center">
          <button class="tool-btn" id="expParseBtn">解析并导入</button>
          <span id="expImportInfo" class="hint"></span>
        </div>
      </div>
      <div style="margin-top:6px">${inboxHtml}${rows}</div>`;
    const nEl = $("#lsNum");
    if (nEl) countUp(nEl, st.total ?? 0, "¥");
    const c = $("#modCount"); if (c) c.textContent = `共 ${st.count ?? 0} 笔`;
    loadInboxCount();
  } catch { moduleList.innerHTML = failState("账本没加载出来。", "ledger"); }
};
function renderInboxItems(ib) {
  const items = (ib && ib.items) || [];
  if (!items.length) return "";
  const head = `<div class="sect">待确认（${items.length}）· 识别模型 ${escapeHtml(ib.vl_model || "?")} · 确认后才入账</div>`;
  const body = items.map(it => {
    let fields = "";
    if (it.type === "expense") {
      const d = it.data || {};
      fields = `<div class="mform">
        <input id="pe-${it.id}-amount" style="width:84px" value="${escapeHtml(String(d.amount ?? ""))}" title="金额">元
        <input id="pe-${it.id}-item" style="width:140px" value="${escapeHtml(String(d.item ?? ""))}" title="名目">
        <select id="pe-${it.id}-category">${["餐饮", "交通", "学习", "生活", "娱乐", "其他"].map(c => `<option ${c === (d.category || "其他") ? "selected" : ""}>${c}</option>`).join("")}</select>
        <input id="pe-${it.id}-spent_at" style="width:158px" value="${escapeHtml(String((d.spent_at || "").slice(0, 16)))}" title="时间">
      </div>`;
    } else if (it.type === "courses") {
      const cs = (it.data && it.data.courses) || [];
      fields = cs.map((c, i) =>
        `<div class="srow">
         <input id="pc-${it.id}-${i}-name" style="width:100px" value="${escapeHtml(String(c.name ?? ""))}">
         <input id="pc-${it.id}-${i}-teacher" style="width:72px" value="${escapeHtml(String(c.teacher ?? ""))}" placeholder="老师">
         <input id="pc-${it.id}-${i}-place" style="width:88px" value="${escapeHtml(String(c.place ?? ""))}" placeholder="教室">
         <input id="pc-${it.id}-${i}-weekday" style="width:40px" value="${escapeHtml(String(c.weekday ?? ""))}" title="1=周一…7=周日">
         <input id="pc-${it.id}-${i}-start" style="width:64px" value="${escapeHtml(String(c.start ?? ""))}">
         <input id="pc-${it.id}-${i}-end" style="width:64px" value="${escapeHtml(String(c.end ?? ""))}">
         <input id="pc-${it.id}-${i}-weeks" style="width:64px" value="${escapeHtml(String(c.weeks ?? "1-16"))}"></div>`).join("")
        || `<div class="hint">没解析出课程</div>`;
    } else fields = `<div class="hint">没认出来这是什么，建议忽略</div>`;
    const img = it.type === "expense" && it.data && it.data.image ? `<img class="pimg" src="/api/shots?rel=${encodeURIComponent(it.data.image)}" onerror="this.remove()">` : "";
    return `<div class="pitem"><div class="item-meta">${escapeHtml(it.type || "?")} · ${fmtTime(it.created_at)} · ${escapeHtml(it.file || "")}</div>${img}${fields}
      <div class="pbtns"><button class="pok" data-pin="${it.id}">✓ 确认入账</button>
      <button class="pno" data-preject="${it.id}">忽略</button></div></div>`;
  }).join("");
  return head + body;
}
moduleList.addEventListener("click", async e => {
  /* 空态里的「＋ 记一笔」（2026-10-30）：跳到表单并聚焦，别让用户自己找 */
  if (e.target.closest("#expAddEmpty")) {
    const f = $("#expForm");
    if (f) {
      f.style.display = "flex";
      f.scrollIntoView({ block: "center", behavior: REDUCED.matches ? "auto" : "smooth" });
      const a = $("#exp-amt");
      if (a) setTimeout(() => a.focus(), 60);
    }
    return;
  }
  if (e.target.id === "exp-add") {
    const amt = parseFloat($("#exp-amt").value);
    const item = $("#exp-item").value.trim();
    if (!amt || !item) { setStatus("金额和名目都要填。"); return; }
    try {
      await api("/api/expenses", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ amount: amt, item, source: "manual" }) });
      setStatus("已记好。");
      RENDERERS.ledger(false);
    } catch (err) { setStatus("记账失败：" + err.message); }
  }
  const del = e.target.closest("[data-xdel]");
  if (del) {
    // 红线：物理删除必过确认卡（2026-09-14 夜 UI 统一班）；openBatchConfirm 为 app.js 全局
    if (typeof openBatchConfirm === "function") { openBatchConfirm([del.dataset.xdel]); }
    else { try { await api("/api/expenses/" + del.dataset.xdel, { method: "DELETE" }); } catch {} RENDERERS.ledger(false); }
    return;
  }
  const ok = e.target.closest("[data-pin]");
  const no = e.target.closest("[data-preject]");
  if (ok) {
    const id = ok.dataset.pin;
    const edits = {};
    const num = document.getElementById(`pe-${id}-amount`);
    if (num) {
      edits.amount = parseFloat(num.value);
      edits.item = (document.getElementById(`pe-${id}-item`) || {}).value;
      edits.category = (document.getElementById(`pe-${id}-category`) || {}).value;
      edits.spent_at = (document.getElementById(`pe-${id}-spent_at`) || {}).value;
    } else {
      const cf = {};
      document.querySelectorAll(`[id^="pc-${id}-"]`).forEach(inp => {
        const parts = inp.id.split("-");
        cf[parts[parts.length - 1]] = inp.value;
      });
      edits.course_fields = cf;
    }
    ok.disabled = true;
    try { await api(`/api/inbox/${id}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(edits) }); setStatus("已确认入账。"); }
    catch (err) { setStatus("确认失败：" + err.message); }
    RENDERERS.ledger(false); loadInboxCount();
  } else if (no) {
    try { await api(`/api/inbox/${no.dataset.preject}/reject`, { method: "POST" }); } catch {}
    RENDERERS.ledger(false); loadInboxCount();
  }
});

/* ============ 课程 ============ */
TOOLBARS._courseLocal = function () {
  modToolbar.innerHTML = `
    <span class="count" id="modCount"></span>
    <span class="spacer"></span>
    <button class="tool-btn" id="coImportBtn">⤓ 导入课表</button>
    <button class="tool-btn" id="coAddBtn">＋ 加课</button>`;
  $("#coAddBtn").addEventListener("click", () => {
    const f = $("#coForm");
    if (f) f.style.display = f.style.display === "none" ? "flex" : "none";
  });
  $("#coImportBtn").addEventListener("click", () => {
    const p = $("#muImport");
    if (p) p.style.display = p.style.display === "none" ? "block" : "none";
  });
};
/* 木案课程表第四版（2026-09-14「完全照搬 muan-workbench 功能与 UI」）：
   节次×星期网格 + rowspan 连堂合并 + 分类体系（自动分类/图例筛选）+ 周次切换 +
   导入课表（Excel 粘贴/CSV，宽表·长表·研究生节次表三种格式，解析器照搬 muan）。
   数据=路远 courses 条目（name/teacher/place/weekday/start/end/weeks/cat）。 */
const COURSE_CATS=[
  {key:'广告',color:'#c9a227',kw:['广告','品牌','营销','consumer','marketing','brand']},
  {key:'传播',color:'#2f6db5',kw:['传播','communication','媒介','media','舆情','舆论','受众']},
  {key:'新闻',color:'#b5533c',kw:['新闻','journalism','采写','报道','编辑出版','出版']},
  {key:'研究方法',color:'#6a4fb0',kw:['研究方法','质性','量化','统计','spss','问卷','田野','ethnography','内容分析','扎根','interview']},
  {key:'外语',color:'#2f8f6b',kw:['英语','日语','外语','english','japanese','法语','德语','french']},
  {key:'政治',color:'#c0556b',kw:['政治','马克思主义','马克思','马原','毛概','思修','概论','思政','近代史']},
  {key:'公选/通识',color:'#7a8a99',kw:['心理','教育','法律','公选','通识','计算机','体育','健康','哲学','文学','历史','经济','管理']},
  {key:'其他',color:'#9aa0a6',kw:[]}];
function getCourseCat(o){ if(o&&o.cat)return o.cat; const hay=(((o||{}).title||(o&&o.name)||'')+' '+((o||{}).teacher||'')+' '+((o||{}).note||'')).toLowerCase();
  for(let i=0;i<COURSE_CATS.length-1;i++){const c=COURSE_CATS[i];for(const k of c.kw){ if(/[一-龥]/.test(k)){ if(hay.indexOf(k)>=0)return c.key; } } }
  return '其他'; }
function catChip(key){const c=COURSE_CATS.find(x=>x.key===key)||COURSE_CATS[COURSE_CATS.length-1];return '<span class="cat-mini" style="background:'+c.color+'22;color:'+c.color+'">'+c.key+'</span>';}
function catColor(key){const c=COURSE_CATS.find(x=>x.key===key)||COURSE_CATS[COURSE_CATS.length-1];return c.color;}
const MU_STATE = { week: 0, filter: "", base: new Date(2026, 8, 14) };  // 周锚点=新生 2026-09-14

function csuLocalWeek() {
  const diff = Math.floor((Date.now() - MU_STATE.base.getTime()) / 86400000);
  return diff < 0 ? 1 : Math.floor(diff / 7) + 1;
}
function muWeeksHit(weeks, wk) {
  const s = String(weeks || "1-16");
  for (const part of s.split(",")) {
    const m = part.match(/^(\d+)\s*-\s*(\d+)$/) || part.match(/^(\d+)$/);
    if (m && wk >= +m[1] && wk <= +(m[2] || m[1])) return true;
  }
  return false;
}
/* —— 导入解析器（照搬 muan parseCourseTable 全家）—— */
function muWdIndex(tok){ if(!tok)return -1; const s=tok.toLowerCase();
  const map=[['周一','星期一','星期1','周1','一','mon','monday'],['周二','星期二','星期2','周2','二','tue','tuesday'],['周三','星期三','星期3','周3','三','wed','wednesday'],['周四','星期四','星期4','周4','四','thu','thursday'],['周五','星期五','星期5','周5','五','fri','friday'],['周六','星期六','星期6','周6','六','sat','saturday'],['周日','星期日','星期天','周7','日','sun','sunday']];
  for(let i=0;i<map.length;i++){for(const m of map[i]){ if(s.indexOf(m)>=0)return i; }} return -1; }
function muSplitCell(s){ s=(s||'').trim(); if(!s)return null; const lines=s.split(/\n+/).map(x=>x.trim()).filter(Boolean);
  if(lines.length===1)return {title:s};
  const title=lines[0]; let teacher='',room='';
  lines.slice(1).forEach(l=>{ if(/室|楼|教|栋|Room|room|机房|^[A-Za-z]?\d/.test(l)||/\d{2,}/.test(l)) room=room?room+' '+l:l; else teacher=teacher?teacher+' '+l:l; });
  return {title,teacher,room}; }
const MU_ROOT_RE=/(外国语|传播|新闻|出版|广告|研究|理论|方法|原理|概论|导论|主义|思想|史|经济|写作|英语|德语|日语|法语|政治|马克思|思政|体育|心理|法律|计算机|健康|文学|历史|哲学|管理|统计|数学|数据|艺术|教育|专题|基础|分析|设计|媒介)/;
const muIsWeeksCell=s=>/周\s*[（(]\s*\d+\s*-\s*\d+\s*节/.test(s)||(/^\d+\s*-\s*\d+\s*周/.test(s)&&/节/.test(s));
const muIsRoomCell=s=>s.length<=12&&/(教学楼|楼|室|校区|研究院|中心|机房|图书馆|馆)/.test(s);
const muIsClassCell=s=>/(新传|出版|班|级|学硕|硕士|研究生|（.*班）|级\d|选修)/.test(s);
const muIsPeriodCell=s=>/第\d+节课/.test(s)||/\d{1,2}:\d{2}\s*[~～-]/.test(s);
function muIsTitleCell(s){ if(!s)return false; if(/(必修|限选|任选)/.test(s))return true; if(muIsWeeksCell(s))return false;
  const cn=(s.match(/[一-龥]/g)||[]).length; const hasCourseWord=MU_ROOT_RE.test(s);
  // 09-15 修：单行混排格（"大学英语(1) 李四 外语楼210"）含"楼"曾被 muIsRoomCell 整格误杀。
  // 长串（≥8 字符）+课程词+足够汉字 → 先判 title；短串才走 教室/班级/节次 排除。
  if(hasCourseWord&&cn>=4&&s.length>=8) return true;
  if(muIsClassCell(s)||muIsRoomCell(s)||muIsPeriodCell(s))return false;
  return cn>=4&&hasCourseWord; }
function muIsGradTimetable(M){ if(!M||!M.length)return false; let hdr=-1; for(let r=0;r<M.length&&r<8;r++){let c=0;M[r].forEach(cell=>{if(muWdIndex(cell)>=0)c++;});if(c>=3){hdr=r;break;}} if(hdr<0)return false; let sig=false; for(let r=0;r<M.length;r++){for(const cell of M[r]){if(/第\d+节课/.test(cell)||/周[（(]\s*\d+\s*-\s*\d+\s*节/.test(cell)||/\d{1,2}:\d{2}\s*[~～-]\s*\d{1,2}:\d{2}/.test(cell)){sig=true;break;}}if(sig)break;} return sig; }
function muParseGradTimetable(M){
  const NR=M.length,NC=Math.max.apply(null,M.map(r=>r.length).concat([0]));
  const grid=M.map(r=>{const a=new Array(NC).fill('');for(let c=0;c<NC;c++)a[c]=(r[c]==null?'':String(r[c])).trim();return a;});
  const T=c=>(c==null?'':String(c)).trim();
  let headerRow=-1,wdCols={};
  for(let r=0;r<NR&&r<8;r++){const map={};grid[r].forEach((cell,c)=>{const wi=muWdIndex(cell);if(wi>=0)map[c]=wi;});if(Object.keys(map).length>=3){headerRow=r;wdCols=map;break;}}
  if(headerRow<0)return {count:0};
  let timeCol=-1;
  for(let c=0;c<NC;c++){if(String(c) in wdCols)continue;const colTxt=grid.map(row=>row[c]).join(' ');if(/第\d+节课/.test(colTxt)||/\d{1,2}:\d{2}\s*[~～-]\s*\d{1,2}:\d{2}/.test(colTxt)){timeCol=c;break;}}
  const timeRe=/(\d{1,2}):(\d{2})\s*[~～-]\s*\d{1,2}:\d{2}/;
  const periodStart={};let lastN=0;const perNums=[];
  if(timeCol>=0){for(let r=0;r<NR;r++){const cell=grid[r][timeCol];const mN=cell.match(/第(\d+)节课/);if(mN){const n=+mN[1];lastN=n;if(perNums.indexOf(n)<0)perNums.push(n);let t=cell.match(timeRe);if(!t&&r+1<NR)t=grid[r+1][timeCol].match(timeRe);if(t)periodStart[n]=t[1].padStart(2,'0')+':'+t[2];}else{const t=cell.match(timeRe);if(t&&lastN&&!periodStart[lastN])periodStart[lastN]=t[1].padStart(2,'0')+':'+t[2];}}}
  const STD=['08:00','08:50','09:55','10:45','11:35','13:30','14:20','15:25','16:15','17:05'];
  const maxP=perNums.length?Math.max.apply(null,perNums):10;
  const periods=[];for(let n=1;n<=maxP;n++)periods.push(periodStart[n]||STD[n-1]||('P'+n));
  const cells=[];
  Object.keys(wdCols).forEach(ci=>{const wi=wdCols[ci];let r=headerRow+1;
    while(r<NR){const cell=T(grid[r][ci]);
      if(muIsTitleCell(cell)){const title=cell;let teacher='',room='',weeks='',sp=1,ep=1,gotRange=false,wkStart=null,wkEnd=null;let rr=r+1;
        while(rr<NR){const c2=T(grid[rr][ci]);
          if(c2){if(muIsTitleCell(c2))break;
            if(muIsWeeksCell(c2)){const m=c2.match(/(\d+)\s*-\s*(\d+)\s*周[（(]\s*(\d+)\s*-\s*(\d+)\s*节/)||c2.match(/周[（(]\s*(\d+)\s*-\s*(\d+)\s*节/);if(m){const a=m.length>=5?[+m[3],+m[4]]:[+m[1],+m[2]];sp=Math.min(a[0],a[1]);ep=Math.max(a[0],a[1]);gotRange=true;const wm=c2.match(/(\d+)\s*-\s*(\d+)\s*周/);if(wm){weeks=wm[0];wkStart=+wm[1];wkEnd=+wm[2];}}}
            else if(muIsRoomCell(c2)){room=room?room+' '+c2:c2;}
            else {teacher=teacher?teacher+' '+c2:c2;}}
          else {if(gotRange)break;}
          rr++;}
        if(!gotRange){sp=1;ep=1;}
        for(let p=sp;p<=ep;p++){const pi=p-1;if(pi<0||pi>=periods.length)continue;cells.push({pIndex:pi,ci:wi,title:title,teacher:teacher,room:room,wkStart:wkStart,wkEnd:wkEnd});}
        r=rr;continue;}
      r++;}
  });
  let semesterStart=null;
  for(let r=0;r<NR;r++){for(let c2=0;c2<NC;c2++){const t2=T(grid[r][c2]);const md=t2.match(/(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日/);if(md){semesterStart=md[1]+'-'+String(md[2]).padStart(2,'0')+'-'+String(md[3]).padStart(2,'0');break;}}if(semesterStart)break;}
  return {count:cells.length,periods,cells,semesterStart};
}
function muParseCourseTable(text){
  const matrix=text.replace(/\r/g,'').split('\n').map(l=>l.split('\t').map(c=>c.trim()));
  if(muIsGradTimetable(matrix)) return muParseGradTimetable(matrix);
  const raw=text.replace(/\r/g,'').split('\n').filter(l=>l.trim()!=='');
  if(!raw.length)return {count:0};
  const rows=raw.map(l=>{ const t=l.includes('\t'); const parts=t?l.split('\t'):(l.includes(',')&&!l.includes('，')?l.split(','):[l]); return parts.map(p=>p.trim()); });
  const wdCols={}; rows[0].forEach((cell,ci)=>{const wi=muWdIndex(cell); if(wi>=0)wdCols[ci]=wi;});
  if(Object.keys(wdCols).length>=3){
    const periods=[]; const cells=[];
    for(let r=1;r<rows.length;r++){ const row=rows[r]; const lbl=row[0]||('第'+r+'节'); const pi=periods.indexOf(lbl); const pIndex=pi<0?(periods.push(lbl)-1):pi;
      Object.keys(wdCols).forEach(ci=>{ const wi=wdCols[ci]; const cell=row[ci]; if(cell&&cell.trim()){ const sp=muSplitCell(cell); cells.push({pIndex,ci:wi,title:sp.title,teacher:sp.teacher||'',room:sp.room||''}); } }); }
    return {count:cells.length,periods,cells};
  }
  const head=rows[0].map(c=>c.toLowerCase());
  const colOf=(keys)=>{ for(let i=0;i<head.length;i++){ for(const k of keys){ if(head[i].indexOf(k)>=0)return i; } } return -1; };
  const cDay=colOf(['星期','周','day','日期']), cPer=colOf(['节次','节','period','时间','节数']), cTitle=colOf(['课程','课名','科目','title','course','名称']), cTea=colOf(['教师','老师','teacher','授课']), cRoom=colOf(['地点','教室','room','楼']), cNote=colOf(['备注','note','说明']);
  if(cTitle>=0){
    const periods=[]; const cells=[];
    for(let r=1;r<rows.length;r++){ const row=rows[r]; if(!row[cTitle]||!row[cTitle].trim())continue; const di=cDay>=0?muWdIndex(row[cDay]):muWdIndex(row[0]); if(di<0)continue;
      const pl=cPer>=0?row[cPer].trim():('第'+r+'节'); const pi=periods.indexOf(pl); const pIndex=pi<0?(periods.push(pl)-1):pi;
      cells.push({pIndex,ci:di,title:row[cTitle].trim(),teacher:cTea>=0?(row[cTea]||'').trim():'',room:cRoom>=0?(row[cRoom]||'').trim():'',note:cNote>=0?(row[cNote]||'').trim():''}); }
    return {count:cells.length,periods,cells};
  }
  return {count:0};
}
/* 解析结果 → 路远课程条目（bulk 用）。periods 元素是开始时间或 "HH:MM-HH:MM" 标签。 */
function muCellsToItems(res){
  return (res.cells||[]).map(c=>{
    const lbl=(res.periods&&res.periods[c.pIndex])||'08:00';
    let start=lbl, end='';
    const mm=lbl.match(/(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})/);
    if(mm){ start=mm[1].padStart(2,'0')+':'+mm[2]; end=mm[3].padStart(2,'0')+':'+mm[4]; }
    else { const hh=parseInt(lbl)||8; end=String(hh)+':45'; }
    // 单行混排拆分："高等数学A(1) 张三 教三205" → 课名/教师/教室（尾部回溯）
    let name=c.title, teacher=c.teacher||'', place=c.room||'';
    if (name === c.title || !teacher) {
      const words = c.title.split(/\s+/).filter(Boolean);
      if (words.length >= 2) {
        const wLast = words[words.length-1], wPrev = words[words.length-2] || "";
        const isRoom = w => (/(?:楼|室|馆|区|厅)\s*[0-9A-Za-z]*$/.test(w) || (/^\S{1,4}\d{2,4}$/.test(w) && /[\u4e00-\u9fa5]/.test(w))) && /\d/.test(w);
        const isTeacher = w => /^[一-龥]{2,4}$/.test(w) && !/\d/.test(w);
        let consumed = 0;
        if (isRoom(wLast)) { place = wLast; consumed++; }
        const wT = words[words.length-1-consumed];
        if (wT && isTeacher(wT) && !isRoom(wT)) { teacher = teacher || wT; consumed++; }
        if (consumed) name = words.slice(0, words.length-consumed).join(" ");
      }
    }
    return { name:name, teacher:teacher, place:place, weekday:(c.ci||0)+1,
             start:start, end:end,
             weeks:(c.wkStart!=null? c.wkStart+'-'+c.wkEnd : '1-16'),
             cat: getCourseCat({title:c.title,teacher:teacher,note:''}) };
  }).filter(x=>x.name);
}
RENDERERS._courseLocal = async function (animate) {
  $("#hitokoto").style.display = "none";
  try {
    const r = await api("/api/courses");
    const all = r.courses || [];
    if (!MU_STATE.week) MU_STATE.week = csuLocalWeek();
    renderMuanGrid(all, r.next || null);
  } catch { moduleList.innerHTML = `<div class="empty">课表没加载出来，稍等一下再点一次课程。</div>`; }
};
function muanHomeworkCard(all){
  // 木案「课程作业」卡：聚合当前笔记里带「作业」标签且未完成的待办（与待办单向联动）
  try {
    const list = (currentNotes || []).filter(n =>
      !n.deleted && ((n.tags||[]).some(t => /作业|homework/i.test(t)) || /作业/.test(n.text||'')));
    if(!list.length) return '';
    const rows = list.slice(0,8).map(n =>
      '<div class="item" style="padding:6px 0;border-top:1px dashed var(--line-1)"><div class="item-body"><div class="item-content" style="font-size:13px">'+escapeHtml(n.text)+'</div></div></div>').join('');
    return '<div class="load" style="margin-top:10px"><h4>课程作业（来自待办）</h4>'+rows+'</div>';
  } catch(e){ return ''; }
}
function renderMuanGrid(all, next) {
  const wk = MU_STATE.week, todayDow = new Date().getDay() || 7;
  const nextBar = next
    ? `<div class="nextbar">下一节 <b>${escapeHtml(next.course.name)}</b>${next.course.place ? " @" + escapeHtml(next.course.place) : ""} · ${escapeHtml(String(next.at).replace("T", " ").slice(5, 16))}（还有 ${next.minutes_away} 分钟）</div>`
    : "";
  const inWeek = all.filter(c => muWeeksHit(c.weeks, wk));
  const visible = MU_STATE.filter ? inWeek.filter(c => getCourseCat(c) === MU_STATE.filter) : inWeek;
  // 空态三问（v2 规范 §4.5）：什么情况/放什么/点哪
  if (!all.length) {
    moduleList.innerHTML = `
      <div class="cc-empty-guide">
        <div class="eg-sticker">📚</div>
        <div class="eg-title">课表还是空的</div>
        <div class="eg-sub">从教务系统/课表 App 复制课程表格，粘进「⤓ 导入课表」自动生成；
           或者点下面的「＋ 加课」手动加。</div>
        <div style="display:flex;gap:8px;justify-content:center;margin-top:12px">
          <button class="tool-btn" id="egImport">⤓ 导入课表</button>
          <button class="tool-btn" id="egAdd">＋ 手动加课</button>
        </div>
      </div>
      <div id="csuCalCard" class="load"><h4>📌 近期校历 · 学业节点</h4><div id="csuCalList" class="hint">加载中…</div></div>`;
    const imp = document.getElementById("egImport");
    if (imp) imp.addEventListener("click", () => { RENDERERS.course(false); const p = $("#muImport"); if (p) p.style.display = "block"; const t = $("#muImportText"); if (t) t.focus(); });
    const add = document.getElementById("egAdd");
    if (add) add.addEventListener("click", () => { RENDERERS.course(false); const p = $("#coForm"); if (p) { p.style.display = "flex"; $("#co-name").focus(); } });
    const c = $("#modCount"); if (c) c.textContent = "还没有课";
    loadCsuCalendarCard();
    return;
  }
  const starts = [...new Set(all.map(c => c.start))].sort();
  const rows = starts.map((s, i) => ({ i, label: s }));
  const endOf = (c) => c.end || c.start;
  const grid = {};
  visible.forEach(c => {
    const ri = starts.indexOf(c.start);
    const k = Math.max(0, ri) + ":" + (c.weekday || 1);
    (grid[k] = grid[k] || []).push(c);
  });
  const names = { 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日" };
  const head = `<tr><th style="width:44px"></th>` + [1, 2, 3, 4, 5, 6, 7].map(d =>
    `<th class="${d === todayDow ? "today" : ""}">${names[d]}${d === todayDow ? " ✓" : ""}</th>`).join("") + `</tr>`;
  const merged = {};
  let body = "";
  rows.forEach(({ i: ri, label }) => {
    let row = `<tr><td><b>${ri + 1}</b>${label}</td>`;
    [1, 2, 3, 4, 5, 6, 7].forEach(d => {
      const key = ri + ":" + d;
      if (merged[key]) { row += ""; return; }
      const list = grid[key] || [];
      const todayCls = d === todayDow ? " today-col" : "";
      if (!list.length) {
        row += `<td class="${todayCls}"><div class="cc empty mu-add" data-d="${d}" data-start="${label}" title="点这里加课">＋</div></td>`;
        return;
      }
      let html = "";
      list.forEach(c => {
        let span = 1, endRow = ri, endCourse = c;
        const id = (c.name || "") + "|" + (c.teacher || "");
        for (let r2 = ri + 1; r2 < rows.length; r2++) {
          const v2 = (grid[r2 + ":" + d] || []).find(x => ((x.name || "") + "|" + (x.teacher || "")) === id && muWeeksHit(x.weeks, wk));
          if (v2) { span++; endRow = r2; endCourse = v2; merged[r2 + ":" + d] = true; }
          else break;
        }
        const cat = getCourseCat(c);
        const col = catColor(cat);
        const dim = (MU_STATE.filter && MU_STATE.filter !== cat) ? " course-dim" : "";
        const spanTime = span > 1 ? (label + "-" + endOf(endCourse)) : (c.start + "-" + endOf(c));
        html += `<div class="cc ${dim}" style="--cc:${col};--ccbg:${col}1a" data-edit="${c.id}" title="点击编辑">
          <div class="t">${escapeHtml(c.name)}</div>${catChip(cat)}
          <div class="m">${c.teacher ? escapeHtml(c.teacher) : ""}</div>
          <div class="m">${c.place ? "@" + escapeHtml(c.place) : ""}</div>
          <div class="m">${escapeHtml(spanTime)}</div>
          <button class="sdel" data-cdel="${c.id}" title="删">×</button></div>`;
      });
      row += `<td class="${todayCls}">${html}</td>`;
    });
    row += "</tr>";
    body += row;
  });
  const cats = [...new Set(inWeek.map(c => getCourseCat(c)))];
  const legend = cats.map(k =>
    `<span class="lchip mu-leg ${MU_STATE.filter === k ? "on" : ""}" data-leg="${escapeHtml(k)}"
       style="border-color:${catColor(k)};color:${MU_STATE.filter === k ? 'var(--text-4)' : catColor(k)}">● ${escapeHtml(k)}</span>`).join("");
  const perDay = [1, 2, 3, 4, 5, 6, 7].map(d => visible.filter(c => (c.weekday || 1) === d).length);
  const mx = Math.max(1, ...perDay);
  const bars = [1, 2, 3, 4, 5, 6, 7].map((d, i) =>
    `<span class="b"><span class="bar ${d === todayDow ? "hi" : ""}" style="height:${Math.round(perDay[i] / mx * 100)}%"></span><span class="n">${names[d]} ${perDay[i]}</span></span>`).join("");
  moduleList.innerHTML = `
    ${nextBar}
    <div class="wkbar">
      <span class="ar mu-nav" data-d="-1">◀</span><span class="cur">第 ${wk} 周</span><span class="ar mu-nav" data-d="1">▶</span>
      <span class="back mu-nav" data-d="0">本周</span>
      <span class="cnt">共 20 周 · 本表 ${inWeek.length} 门</span>
    </div>
    <div class="mform" id="coForm" style="display:none">
      <input id="co-name" style="width:104px" placeholder="课名">
      <input id="co-teacher" style="width:72px" placeholder="老师">
      <input id="co-place" style="width:92px" placeholder="教室">
      <select id="co-weekday">${[1,2,3,4,5,6,7].map(k => `<option value="${k}">${names[k]}</option>`).join("")}</select>
      <input id="co-start" style="width:64px" placeholder="08:00">
      <input id="co-end" style="width:64px" placeholder="09:40">
      <input id="co-weeks" style="width:80px" placeholder="周次 1-16">
      <button class="add2" id="co-add">加课</button>
    </div>
    <div id="muImport" style="display:none" class="mu-import">
      <div class="hint">从教务系统/课表 App 复制表格粘贴到下面（支持 宽表·长表·研究生节次表 三种格式，CSV/Tab 均可）：</div>
      <textarea id="muImportText" rows="7" style="width:100%;margin-top:6px" placeholder="周一	周二	周三…（或 节次	周一	…）"></textarea>
      <div style="display:flex;gap:8px;margin-top:6px;align-items:center">
        <button class="tool-btn" id="muParseBtn">解析预览</button>
        <span id="muParseInfo" class="hint"></span>
      </div>
    </div>
    <table class="cgrid">${head}${body}</table>
    <div class="legend">${legend}</div>
    <div class="load"><h4>本周课程负荷 · 各天门数</h4><div class="bars">${bars}</div></div>
    ${muanHomeworkCard(all)}
    <div id="csuCalCard" class="load"><h4>📌 近期校历 · 学业节点</h4><div id="csuCalList" class="hint">加载中…</div></div>`;
  const c = $("#modCount"); if (c) c.textContent = `第 ${wk} 周 · ${inWeek.length} 门课`;
  bindMuanEvents(all);
  loadCsuCalendarCard();
}
/* 自提案（已自批）：课表页近期校历卡——数据源 /api/csu/overview。只读展示；
   接口 404（旧进程）或无事件时无痕降级。 */
async function loadCsuCalendarCard() {
  const list = document.getElementById("csuCalList");
  if (!list) return;
  try {
    const r = await api("/api/csu/overview");
    const today = new Date();
    const evs = (r.events || []).filter(e => {
      const end = e.end || e.date;
      return new Date(end + "T23:59:59") >= today;
    }).slice(0, 6);
    if (!evs.length) { list.textContent = "近期没有校历事件。"; return; }
    list.innerHTML = evs.map(e => {
      const end = e.end || e.date;
      const days = Math.round((new Date(end + "T23:59:59") - today) / 86400000);
      const when = e.end && e.end !== e.date ? e.date.slice(5) + " ~ " + e.end.slice(5) : e.date.slice(5);
      const urgent = days <= 3 && /截止|报资助|评议|考试/.test(e.name);
      return `<div class="cal-row${urgent ? " cal-urgent" : ""}">
        <span class="cal-date">${when}</span>
        <span class="cal-name">${escapeHtml(e.name)}</span>
        <span class="cal-tag">${e.type || ""}</span>
        <span class="cal-left">${days < 0 ? "进行中" : days === 0 ? "今天" : "还有 " + days + " 天"}</span></div>`;
    }).join("");
  } catch (e) {
    const card = document.getElementById("csuCalCard");
    if (card) card.style.display = "none";
  }
}
function bindMuanEvents(all) {
  moduleList.querySelectorAll(".mu-nav").forEach(b => b.addEventListener("click", () => {
    const d = +b.dataset.d;
    MU_STATE.week = d === 0 ? csuLocalWeek() : Math.max(1, MU_STATE.week + d);
    renderMuanGrid(all);
  }));
  moduleList.querySelectorAll(".mu-leg").forEach(b => b.addEventListener("click", () => {
    MU_STATE.filter = (MU_STATE.filter === b.dataset.leg) ? "" : b.dataset.leg;
    renderMuanGrid(all);
  }));
  moduleList.querySelectorAll(".mu-add").forEach(b => b.addEventListener("click", () => {
    const f = $("#coForm");
    if (!f) return;
    f.style.display = "flex";
    $("#co-weekday").value = b.dataset.d;
    $("#co-start").value = b.dataset.start || "08:00";
    $("#co-name").focus();
  }));
  moduleList.querySelectorAll('.cc[data-edit]').forEach(el => el.addEventListener("click", (ev) => {
    if (ev.target.closest(".sdel")) return;
    const course = all.find(x => x.id === el.dataset.edit);
    if (!course) return;
    const f = $("#coForm");
    if (!f) return;
    f.style.display = "flex";
    $("#co-name").value = course.name || "";
    $("#co-teacher").value = course.teacher || "";
    $("#co-place").value = course.place || "";
    $("#co-weekday").value = course.weekday || 1;
    $("#co-start").value = course.start || "";
    $("#co-end").value = course.end || "";
    $("#co-weeks").value = course.weeks || "1-16";
    $("#co-name").focus();
  }));
  const add = $("#co-add");
  if (add) add.addEventListener("click", async () => {
    const g = id => (document.getElementById(id) || {}).value;
    try {
      await api("/api/courses", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: (g("co-name") || "").trim(), teacher: (g("co-teacher") || "").trim(), place: (g("co-place") || "").trim(), weekday: parseInt(g("co-weekday")), start: (g("co-start") || "").trim(), end: (g("co-end") || "").trim(), weeks: (g("co-weeks") || "1-16").trim() }) });
      setStatus("课加好了。");
      RENDERERS.course(false);
    } catch (err) { setStatus("加课失败：" + err.message); }
  });
  moduleList.querySelectorAll("[data-cdel]").forEach(b => b.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    try { await api("/api/courses/" + b.dataset.cdel, { method: "DELETE" }); } catch {}
    RENDERERS.course(false);
  }));
  const pb = $("#muParseBtn");
  if (pb) pb.addEventListener("click", async () => {
    const txt = ($("#muImportText") || {}).value || "";
    if (!txt.trim()) { $("#muParseInfo").textContent = "先粘贴课表文本"; return; }
    const res = muParseCourseTable(txt);
    const items = muCellsToItems(res);
    const info = $("#muParseInfo");
    if (!items.length) { info.textContent = "没解析出课程——确认是表格复制（含星期列头）"; return; }
    info.textContent = "解析出 " + items.length + " 节课，再点一次确认导入";
    pb.textContent = "确认导入 " + items.length + " 节";
    const confirmBtn = pb.cloneNode(true);
    pb.replaceWith(confirmBtn);
    confirmBtn.addEventListener("click", async () => {
      try {
        const rr = await api("/api/courses/bulk", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }) });
        setStatus("导入完成：新增 " + rr.added + " 节，跳过重复 " + rr.skipped + " 节。");
        RENDERERS.course(false);
      } catch (err) {
        setStatus("导入失败：" + err.message);
      }
    });
  });
}



/* ============ 课程 ============ */
/* ============ 人脉 ============ */
let ctGroups = [];                 // [{name,count}] 后端返回的已有分组
function ctSortMode() {            // ""=自动 → 选了分组按学号，否则按拼音
  return state.ctSort || (state.ctGroup ? "sid" : "letter");
}
function ctSex(x) {                // 性别（老数据里性别存在 info 里）
  const info = (x.info || []).map(String);
  return info.find(s => s.trim() === "男" || s.trim() === "女") || info[0] || x.birthday || "";
}
function renderCtChips() {         // 分组 chips（与人脉页共用 #modChips）
  if (state.module !== "contact") return;
  const chips = [{ v: "", t: "全部" }]
    .concat((ctGroups || []).map(g => ({ v: g.name, t: `${g.name} ${g.count}` })));
  modChips.innerHTML = chips.map(c =>
    `<button class="chip ${(state.ctGroup || "") === c.v ? "active" : ""}" data-ctgroup="${escapeHtml(c.v)}">${escapeHtml(c.t)}</button>`).join("");
}
document.addEventListener("click", e => {
  const b = e.target.closest("#modChips .chip[data-ctgroup]");
  if (!b || state.module !== "contact") return;
  state.ctGroup = b.getAttribute("data-ctgroup") || "";
  state.ctSort = "";               // 回到自动：选组=按学号，全部=按拼音
  renderCtChips();
  loadContacts(false);
});
TOOLBARS.contact = function () {
  const bySid = ctSortMode() === "sid";
  modToolbar.innerHTML = `
    <div class="search">${ICONS.search}<input id="ct_search" placeholder="搜索联系人 / 信息 / 待办…" autocomplete="off"></div>
    <span class="count" id="modCount"></span>
    <span class="spacer"></span>
    <button class="tool-btn" id="ct_sort" title="切换排序方式">↕ ${bySid ? "按学号" : "按拼音"}</button>
    <input id="ct_add" placeholder="输入名字" style="width:110px;background:rgba(255,255,255,.9);border:1px solid var(--line-1);border-radius:8px;padding:6px 10px;font:inherit;font-size:12.5px;outline:none">
    <button class="tool-btn" id="ct_addbtn">＋ 添加</button>`;
  const s = $("#ct_search");
  s.addEventListener("input", () => { clearTimeout(s._t); s._t = setTimeout(loadContacts, 250); });
  $("#ct_addbtn").addEventListener("click", addContact);
  $("#ct_add").addEventListener("keydown", e => { if (e.key === "Enter") addContact(); });
  $("#ct_sort").addEventListener("click", () => {
    state.ctSort = ctSortMode() === "sid" ? "letter" : "sid";
    $("#ct_sort").textContent = "↕ " + (state.ctSort === "sid" ? "按学号" : "按拼音");
    loadContacts(false);
  });
};
async function addContact() {
  const addEl = $("#ct_add");
  const name = (addEl.value || "").trim();
  if (!name) return;
  try {
    await api("/api/contacts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, group: state.ctGroup || "" }) });
    addEl.value = "";
    setStatus("已添加 " + name + (state.ctGroup ? "（归入 " + state.ctGroup + "）" : ""));
    loadContacts();
  } catch (e) { setStatus("添加失败：" + e.message); }
}
async function loadContacts(animate) {
  if (state.module !== "contact") return;
  const s = $("#ct_search");
  try {
    const q = s ? s.value.trim() : "";
    const g = state.ctGroup || "";
    const r = await api(`/api/contacts?q=${encodeURIComponent(q)}&group=${encodeURIComponent(g)}&sort=${encodeURIComponent(ctSortMode())}`);
    currentContacts = r.contacts || [];
    ctGroups = r.groups || [];
    renderCtChips();
    // 排序按钮文案跟着「实际生效的排序」走（选了分组自动按学号，按钮别还写按拼音）
    const sb = $("#ct_sort");
    if (sb) sb.textContent = "↕ " + (ctSortMode() === "sid" ? "按学号" : "按拼音");
    renderContacts(animate);
  } catch (e) { setStatus("人脉加载失败：" + e.message); }
}
RENDERERS.contact = function (animate) { loadContacts(animate); };
function renderContacts(animate) {
  const c = $("#modCount"); if (c) c.textContent = `共 ${currentContacts.length} 位`;
  const hot = currentContacts.filter(x => (x.todos || []).some(t => !t.done));
  const pendingHtml = hot.length
    ? `<div class="sect">待办 · 有人等你</div>` + hot.map(x => `
      <div class="item ct-hot" data-cid="${x.id}">
        <div class="item-main"><div class="item-body">
          <div class="item-title" style="display:flex;align-items:center;gap:8px"><span class="reddot"></span>${escapeHtml(x.name)}</div>
          ${(x.todos || []).filter(t => !t.done).map(t => `
            <div class="cttodo"><input type="checkbox" data-cid="${x.id}" data-tid="${t.id}" />
            <span>${escapeHtml(t.text)}</span>${t.remind_at && !t.reminded ? `<span class="tremind">${ICONS.bell} ${fmtTime(t.remind_at)}</span>` : ""}</div>`).join("")}
        </div></div>
      </div>`).join("")
    : "";
  const rowOf = (x, delay) => `
      <div class="item" data-cid="${x.id}" style="animation-delay:${delay}ms">
        <div class="item-main"><div class="item-body">
          <div class="item-title" style="display:flex;align-items:center;gap:8px"><input type="checkbox" class="ccheck" data-id="${x.id}" ${state.selected.has("contact:"+x.id) ? "checked" : ""}/>${escapeHtml(x.name)}
            ${(x.todos || []).some(t => !t.done) ? '<span class="reddot"></span>' : ""}
            <span class="badge" ${ctSex(x) ? "" : 'style="display:none"'}>${escapeHtml(ctSex(x))}</span>
            ${x.sid ? `<span class="badge sid">${escapeHtml(x.sid)}</span>` : ""}</div>
        </div></div>
      </div>`;
  const bySid = ctSortMode() === "sid";
  let listHtml, letters = [];
  if (bySid) {
    // 按学号：后端已排好序 → 平铺，不加字母分组头（否则顺序看着矛盾）
    listHtml = currentContacts.length
      ? currentContacts.map((x, i) => rowOf(x, animate ? Math.min(i, 10) * 30 : 0)).join("")
      : `<div class="empty">这个分组还没有人。右上角输入名字就能添加，加了会按学号排进来。</div>`;
  } else {
    const groups = {};
    currentContacts.forEach(x => (groups[x.letter || "#"] = groups[x.letter || "#"] || []).push(x));
    letters = Object.keys(groups).sort();
    listHtml = letters.length ? letters.map(L => `
      <div class="ctletter">${L}</div>
      ${groups[L].map(x => rowOf(x, animate ? Math.min(letters.indexOf(L), 8) * 40 : 0)).join("")}`).join("")
      : `<div class="empty">还没有联系人。右上角输入名字添加。</div>`;
  }
  if (state.module !== "contact") return;   // 切走了，迟到结果丢弃
  moduleList.innerHTML = pendingHtml + `<div class="ctwrap"><div class="ctlistcol">${listHtml}</div>
    <div id="ct_index">${(!bySid && letters.length) ? letters.map(L => `<div class="ctix" data-letter="${L}">${L}</div>`).join("") : ""}</div></div>`;
}
moduleList.addEventListener("change", async e => {
  const cb = e.target;
  if (cb.classList && (cb.classList.contains("xcheck") || cb.classList.contains("scheck") || cb.classList.contains("ccheck"))) {
    const key = state.module + ":" + cb.dataset.id;
    if (cb.checked) state.selected.add(key); else state.selected.delete(key);
    updateBatchBar();
    return;
  }
  if (cb.matches && cb.matches("input[type=checkbox]") && cb.dataset.cid && cb.dataset.tid) {
    await api(`/api/contacts/${cb.dataset.cid}/todos/${cb.dataset.tid}/toggle`, { method: "POST" });
    loadContacts(false);
  }
});
moduleList.addEventListener("click", async e => {
  if (state.module !== "contact") return;
  const ix = e.target.closest(".ctix");
  if (ix) {
    const letters = [...moduleList.querySelectorAll(".ctletter")];
    const target = letters.find(l => l.textContent === ix.dataset.letter);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  const card = e.target.closest(".item[data-cid]");
  if (card && !e.target.matches("input[type=checkbox]")) {
    const x = currentContacts.find(c => c.id === card.dataset.cid);
    if (x) openCtDetail(x);
  }
});

/* 人脉详情弹层 */
function openCtDetail(x) {
  ctDetailId = x.id;
  const box = $("#ctdetail");
  const field = (label, key, attrs) => `
    <div class="ctfield"><label>${label}</label>
    <input data-field="${key}" value="${escapeHtml(x[key] || "")}" placeholder="未填" ${attrs || ""} /></div>`;
  const todoBits = (x.todos || []).map(t => `
      <div class="cttodo"><input type="checkbox" ${t.done ? "checked" : ""} data-cid="${x.id}" data-tid="${t.id}" />
        <span class="${t.done ? "donetext" : ""}">${escapeHtml(t.text)}</span>
        ${t.remind_at && !t.reminded && !t.done ? `<span class="tremind">${ICONS.bell} ${fmtTime(t.remind_at)}</span>` : ""}
        <button class="tool-btn td_del" data-cid="${x.id}" data-tid="${t.id}" style="margin-left:auto;padding:2px 8px;font-size:11px">删</button>
      </div>`).join("");
  box.innerHTML = `
    <div class="phead"><span class="ptitle">${escapeHtml(x.name)}</span><span style="flex:1"></span>
      <button class="tool-btn" id="ctd_close">✕</button></div>
    <div class="ctinfo">
      ${field("学号", "sid")}${field("分组", "group", 'list="ct_grouplist"')}
      ${field("生日", "birthday")}${field("电话", "phone")}${field("微信", "wechat")}${field("QQ", "qq")}
    </div>
    <datalist id="ct_grouplist">${(ctGroups || []).map(g => `<option value="${escapeHtml(g.name)}"></option>`).join("")}</datalist>
    <div class="ctactions">
      <button class="tool-btn" id="ctd_tel">打电话</button>
      <button class="tool-btn" id="ctd_wechat">微信</button>
      <button class="tool-btn" id="ctd_qq">QQ</button>
      <button class="tool-btn" id="ctd_saveinfo">保存资料</button>
    </div>
    <div class="sect">待办</div>
    ${todoBits || '<div class="hint">还没有跟 TA 相关的待办</div>'}
    <div class="mform"><input id="ctd_newtodo" placeholder="给 ${escapeHtml(x.name)} 加一条待办…" style="flex:1;min-width:120px" />
      <button class="add2" id="ctd_addtodo">加</button></div>
    <div class="sect">个人信息 <span class="hint" style="display:inline;padding:0">（主界面说「${escapeHtml(x.name)}的生日是…」会自动记到这里）</span></div>
    ${(x.info || []).map(i => `<div class="ctinfo-line">${escapeHtml(i)}</div>`).join("") || '<div class="hint">还没有个人信息</div>'}
    <button class="tool-btn" id="ctd_del" style="margin-top:12px;color:#b91c1c">删除联系人</button>`;
  box.classList.add("show");
}
function closeCtDetail() {
  ctDetailId = null;
  const box = $("#ctdetail");
  box && box.classList.remove("show");
}
$("#ctdetail").addEventListener("click", async e => {
  const cid = ctDetailId;
  const box = $("#ctdetail");
  if (e.target.id === "ctd_close") { closeCtDetail(); return; }
  if (e.target.id === "ctd_del") {
    if (!(await askConfirm(`删除「${(currentContacts.find(c => c.id === cid) || {}).name || "这个联系人"}」？`,
      "TA 名下所有待办会一起删掉，不进回收站。", "确认删除", true))) return;
    await api("/api/contacts/" + cid, { method: "DELETE" });
    closeCtDetail(); loadContacts(false);
    return;
  }
  if (e.target.id === "ctd_saveinfo") {
    const fields = {};
    box.querySelectorAll("input[data-field]").forEach(i => fields[i.dataset.field] = i.value.trim());
    await api("/api/contacts/" + cid, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields) });
    setStatus("资料已保存");
    loadContacts(false);
    return;
  }
  if (e.target.id === "ctd_tel") {
    const phone = box.querySelector('input[data-field="phone"]').value.trim();
    if (!phone) { setStatus("还没填电话号码"); return; }
    location.href = "tel:" + phone;
    return;
  }
  if (e.target.id === "ctd_wechat") {
    const wx = box.querySelector('input[data-field="wechat"]').value.trim();
    if (!wx) { setStatus("还没填微信号"); return; }
    try { await navigator.clipboard.writeText(wx); } catch {}
    location.href = "weixin://";
    setStatus("已复制微信号「" + wx + "」，在微信里搜索即可");
    return;
  }
  if (e.target.id === "ctd_qq") {
    const qq = box.querySelector('input[data-field="qq"]').value.trim();
    if (!qq) { setStatus("还没填 QQ 号"); return; }
    location.href = "tencent://message/?uin=" + qq;
    return;
  }
  if (e.target.id === "ctd_addtodo") {
    const input = box.querySelector("#ctd_newtodo");
    const text = input.value.trim();
    if (!text) return;
    await api(`/api/contacts/${cid}/todos`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    loadContacts(false);
    const fresh = currentContacts.find(c => c.id === cid);
    if (fresh) openCtDetail(fresh);
    return;
  }
  if (e.target.classList.contains("td_del")) {
    await api(`/api/contacts/${e.target.dataset.cid}/todos/${e.target.dataset.tid}`, { method: "DELETE" });
    loadContacts(false);
    return;
  }
  if (e.target.matches("input[type=checkbox]") && e.target.dataset.tid) {
    await api(`/api/contacts/${e.target.dataset.cid}/todos/${e.target.dataset.tid}/toggle`, { method: "POST" });
    loadContacts(false);
  }
});
/* 出框关闭 + 拖动守卫：从详情内拖选到外面、或按住拖动，都不该关闭 */
let _ctDown = null;
document.addEventListener("mousedown", e => {
  const box = $("#ctdetail");
  _ctDown = { x: e.clientX, y: e.clientY, inBox: !!(ctDetailId && box.classList.contains("show") && box.contains(e.target)) };
});
document.addEventListener("click", e => {
  const box = $("#ctdetail");
  if (ctDetailId && box.classList.contains("show") && !box.contains(e.target) && !e.target.closest(".item[data-cid]")) {
    if (_ctDown && (_ctDown.inBox || Math.abs(e.clientX - _ctDown.x) + Math.abs(e.clientY - _ctDown.y) > 6)) return;
    closeCtDetail();
  }
});

/* ============ 日记（负一屏 → 模块页） ============ */
TOOLBARS.journal = function () {
  // 09-15 路河：表情/图片不再挂顶部工具栏，跟「存」放同一排（见 RENDERERS.journal 的 .dtools）
  modToolbar.innerHTML = `
    <span class="count" id="modCount"></span>
    <span class="streak" id="diary_streak"></span>
    <span class="spacer"></span>`;
};
/** 卡片摘要：压掉换行、截断即可（3:2 卡里靠 CSS 再裁 4 行） */
function diaryBrief(text) {
  const s = (text || "").replace(/\s+/g, " ").trim();
  if (!s) return "（空）";
  return s.length > 68 ? s.slice(0, 68) + "…" : s;
}
// 拖选文字不算「点开」：记下按下的坐标，位移超 8px 就忽略这次 click
let _diaryDown = null;
document.addEventListener("mousedown", e => { _diaryDown = { x: e.clientX, y: e.clientY }; });

function updateJournalBadge(written) {
  const btn = document.querySelector('.module-btn[data-mod="journal"]');
  if (!btn) return;
  let d = btn.querySelector(".bdg-dot");
  if (!written) {
    if (!d) { d = document.createElement("span"); d.className = "bdg-dot"; btn.appendChild(d); }
  } else if (d) d.remove();
}
RENDERERS.journal = async function (animate) {
  $("#hitokoto").style.display = "none";
  try {
    const t = await api("/api/diary/today");
    updateJournalBadge(!!(t.note && (t.note.text || "").trim()));
    const stEl = $("#diary_streak");
    if (stEl) stEl.textContent = t.streak ? "连续 " + t.streak + " 天" : "";
    const c = $("#modCount");
    if (c) {
      // 2026-10-29 复查：原来是 toLocaleDateString 给的 "2026/10/29"，和别处中文写法不统一
      const _d = new Date();
      c.textContent = "今天 · " + (_d.getMonth() + 1) + "月" + _d.getDate() + "日";
    }
    state.diaryImages = (t.note && t.note.images) ? t.note.images.slice() : [];
    const r = await api("/api/diary/recent?limit=60");
    // 一次只展开一张（展开的那张盖住整片网格）
    const openId = ((r.notes || []).find(n => state.expanded.has(n.id)) || {}).id || null;
    const cards = (r.notes || []).map(n => {
      const open = !!openId && n.id === openId;
      const imgs = n.images || [];
      const thumbs = imgs.slice(0, 4).map(p => {
        const u = "/media/" + encodeURIComponent(String(p).split("/").pop());
        return `<img src="${u}" data-full="${u}" alt="配图" />`;
      }).join("");
      return `<div class="dcard ${open ? "dopen" : ""}" data-dcard="${n.id}">
        <div class="dc-date">${fmtTime(n.created_at)}${imgs.length > 4 ? " · " + imgs.length + " 图" : ""}</div>
        <div class="dc-sum">${open ? escapeHtml(n.text || "") : escapeHtml(diaryBrief(n.text))}</div>
        ${thumbs ? `<div class="dc-thumbs">${thumbs}</div>` : ""}
        ${open ? `<div class="dc-tools"><button class="item-action" data-dclose="${n.id}">收起</button>
          <button class="item-action danger jdel" data-id="${n.id}">删除</button></div>`
              /* 2026-10-30 通宵批：短文/没图时不再挂「点开看全文」——本来就没被截断，
                 挂着等于骗一次点击。 */
              : ((String(n.text || "").replace(/\s+/g, "").length > 56 || imgs.length) ? `<div class="dc-foot">点开看全文</div>` : "")}
      </div>`;
    }).join("") || `<div class="empty">还没有日记。上面写下第一篇。</div>`;
    if (state.module !== "journal") return;   // 切走了，迟到结果丢弃
    moduleList.innerHTML = `
      <div class="diary-editor">
        <textarea id="diary_text" placeholder="今天记点什么…（点「存」或 Ctrl+Enter）">${""}</textarea>
        <div class="dtools">
          <button class="add2" id="diary_save">存</button>
          <button class="tool-btn" id="emoji_btn">${ICONS.smile} 表情</button>
          <button class="tool-btn" id="img_btn">${ICONS.image} 图片</button>
          <input type="file" id="img_input" accept="image/*" multiple style="display:none" />
          <span class="hint">一天一篇，重复保存会更新今天这篇 · 日记不会出现在笔记主页</span>
        </div>
        <div class="imgrow" id="diary_imgs"></div>
      </div>
      <div class="sect">之前的日记</div>
      <div class="diary-grid ${openId ? "open" : ""}">${cards}</div>`;
    const ta = $("#diary_text");
    const serverText = (t.note && t.note.text) || "";
    // 草稿恢复：本地草稿与服务器内容不同 → 草稿优先（退出/切模块/崩溃都不丢）
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem(DIARY_DRAFT_KEY) || "null"); } catch (e) {}
    ta.value = (draft && typeof draft.text === "string" && draft.text !== serverText)
      ? draft.text : serverText;
    /* 2026-10-30 通宵批：草稿恢复原来是「悄悄生效」——打开日记看到一堆字，
       分不清这是已保存的日记还是上次没存上的草稿，也没有「我不想要它」的出口。 */
    if (draft && typeof draft.text === "string" && draft.text !== serverText) {
      const ed = document.querySelector(".diary-editor");
      if (ed) {
        const d = document.createElement("div");
        d.className = "draft-note";
        d.innerHTML = `已恢复上次没存上的草稿。<button class="tool-btn" id="diaryDropDraft" style="padding:2px 9px;font-size:11px;margin-left:6px">丢弃草稿</button>`;
        ed.insertBefore(d, ta.nextSibling);
        const b = d.querySelector("#diaryDropDraft");
        if (b) b.addEventListener("click", () => {
          try { localStorage.removeItem(DIARY_DRAFT_KEY); } catch (e) {}
          ta.value = serverText;
          d.remove();
          setStatus("已丢弃草稿，恢复成已保存的那篇。", 4000);
        });
      }
    }
    let dt = null;
    ta.addEventListener("input", () => {
      clearTimeout(dt);
      dt = setTimeout(() => diaryDraftSave(ta.value), 500);
    });
    ta.addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); saveDiary(); } });
    $("#diary_save").addEventListener("click", saveDiary);
    renderDiaryImages();
    // 卡片展开/收起：展开态下其余卡片 pointer-events:none，所以再点这张（或「收起」）即还原
    moduleList.querySelectorAll(".dcard").forEach(card => {
      card.addEventListener("click", ev => {
        /* 2026-10-30 通宵批：那个「收起」按钮以前没有任何监听（点它被 .dc-tools 的
           early-return 吃掉），只能靠 Esc 或再点一次卡片。现在它真的收。 */
        if (ev.target.closest("[data-dclose]")) {
          state.expanded.clear();
          RENDERERS.journal(false);
          return;
        }
        if (ev.target.closest(".dc-tools") || ev.target.closest(".dc-thumbs")) return;
        if (_diaryDown && Math.abs(ev.clientX - _diaryDown.x) + Math.abs(ev.clientY - _diaryDown.y) > 8) return;
        const id = card.getAttribute("data-dcard");
        state.expanded.clear();
        if (!card.classList.contains("dopen")) state.expanded.add(id);
        RENDERERS.journal(false);
      });
    });
    moduleList.querySelectorAll(".jdel").forEach(btn => {
      btn.addEventListener("click", async ev => {
        ev.stopPropagation();
        const id = btn.dataset.id;
        try {
          await api("/api/notes/delete_many", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: [id] }) });
          setStatus("已删除（可在回收站找回）。");
          RENDERERS.journal(false);
        } catch (err) { setStatus("删除失败：" + err.message); }
      });
    });
    moduleList.querySelectorAll("img[data-full]").forEach(img => {
      img.addEventListener("click", ev => { ev.stopPropagation(); window.open(img.dataset.full, "_blank"); });
      // 配图被删/没同步到：换成占位，别刷 404 破图（09-15 验收抓到 images/2d774e6a8060.jpg 丢失）
      img.addEventListener("error", () => {
        const ph = document.createElement("span");
        ph.className = "dc-lost";
        ph.textContent = "图已丢";
        img.replaceWith(ph);
      });
    });
  } catch (e) { setStatus("日记加载失败：" + e.message); }
};
/* 日记草稿自动保存（2026-09-10，任务单三.1）：输入落 localStorage，
   重进/切模块/崩溃都不丢；保存成功即清。 */
const DIARY_DRAFT_KEY = "luyuan_diary_draft";

function diaryDraftSave(text) {
  try { localStorage.setItem(DIARY_DRAFT_KEY, JSON.stringify({ text, ts: Date.now() })); } catch (e) {}
}

async function saveDiary() {
  const ta = $("#diary_text");
  if (!ta) return;
  const text = ta.value.trim();
  if (!text) return;
  try {
    const r = await api("/api/diary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, images: state.diaryImages || [] }) });
    try { localStorage.removeItem(DIARY_DRAFT_KEY); } catch (e) {}
    setStatus("日记已保存（连续 " + r.streak + " 天）", 4000);
    RENDERERS.journal(false);
  } catch (e) { setStatus("日记保存失败：" + e.message + "（内容还在编辑框里）"); }
}
function renderDiaryImages() {
  const box = $("#diary_imgs");
  if (!box) return;
  box.innerHTML = (state.diaryImages || []).map((p, i) => `
    <div class="ithumb"><img src="/media/${p.split("/")[1]}" data-full="/media/${p.split("/")[1]}" />
    <button class="ix" data-ix="${i}">✕</button></div>`).join("");
}
document.addEventListener("click", async e => {
  if (e.target.closest("#emoji_btn")) {
    const pop = $("#emojipopup");
    if (!pop.dataset.filled) {
      const EMOJIS = ("\u{1F600} \u{1F604} \u{1F605} \u{1F602} \u{1F923} \u{1F60A} \u{1F60D} \u{1F618} \u{1F61C} \u{1F92A} \u{1F914} \u{1F928} \u{1F610} \u{1F634} \u{1F924} \u{1F62A} \u{1F971} \u{1F60F} \u{1F612} \u{1F97A} \u{1F622} \u{1F62D} \u{1F624} \u{1F621} \u{1F92C} \u{1F92F} \u{1F633} \u{1F975} \u{1F976} \u{1F631} \u{1F628} \u{1F630} \u{1F625} \u{1F613} \u{1F917} \u{1F92D} \u{1F92B} \u{1F925} \u{1F636} \u{1F62C} \u{1F644} \u{1F62F} \u{1F626} \u{1F627} \u{1F62E} \u{1F632} \u{1F973} \u{1F635} \u{1F922} \u{1F92E} \u{1F915} \u{1F912} \u{1F927} \u{1F637} \u{1F974} \u{1F608} \u{1F47F} \u{1F480} \u{1F47B} \u{1F47D} \u{1F916} \u{1F4A9} \u{1F63A} \u{1F648} \u{1F649} \u{1F436} \u{1F431} \u{1F42D} \u{1F430} \u{1F98A} \u{1F43B} \u{1F43C} \u{1F428} \u{1F42F} \u{1F981} \u{1F42E} \u{1F437} \u{1F438} \u{1F414} \u{1F427} \u{1F984} \u{1F41D} \u{1F98B} \u{1F338} \u{1F339} \u{1F33B} \u{1F308} \u{2B50} \u{1F319} \u{2600}\u{FE0F} \u{26C5} \u{1F327}\u{FE0F} \u{2744}\u{FE0F} \u{1F525} \u{1F4A7} \u{1F389} \u{1F38A} \u{1F381} \u{1F382} \u{1F340} \u{1F330} \u{1F355} \u{1F354} \u{1F35C} \u{1F35A} \u{1F363} \u{1F370} \u{1F366} \u{2615} \u{1F37A} \u{1F377} \u{1F4AA} \u{1F44D} \u{1F44E} \u{1F44F} \u{1F64F} \u{2764}\u{FE0F} \u{1F494} \u{1F4AF} \u{26A1} \u{1F3B5} \u{1F3AE} \u{1F4A4} \u{1F4B0} \u{1F4DA} \u{270F}\u{FE0F} \u{1F3C3} \u{1F6B4}").split(" ");
      pop.innerHTML = EMOJIS.map(x => `<span>${x}</span>`).join("");
      pop.dataset.filled = "1";
    }
    pop.classList.toggle("show");
  } else if (e.target.closest("#img_btn")) {
    $("#img_input").click();
  } else if (e.target.id === "diary_save") { /* handled */ }
  if (e.target.closest("#emojipopup") && e.target.tagName === "SPAN") {
    const ta = $("#diary_text");
    if (ta) {
      const pos = ta.selectionStart || ta.value.length;
      ta.value = ta.value.slice(0, pos) + e.target.textContent + ta.value.slice(pos);
      $("#emojipopup").classList.remove("show");
      ta.focus();
    }
  } else if (e.target.id === "emojipopup") e.target.classList.remove("show");
  if (e.target.classList.contains("ix") && e.target.dataset.ix != null) {
    state.diaryImages.splice(+e.target.dataset.ix, 1);
    renderDiaryImages();
  }
});
/* #img_input 是日记面板渲染时才生成的动态元素，不能在模块顶层直接取；
   必须在 document 上做事件委托，否则元素不存在 → null.addEventListener 抛错
   → modules.js 从这里往下全部不执行（设置抽屉/手势/弹层/各模块渲染器全死）。
   这是 v20 起就潜伏的老 bug，v25 修复。 */
document.addEventListener("change", async (e) => {
  const input = e.target;
  if (!input || input.id !== "img_input") return;
  for (const f of input.files) {
    try {
      const dataUrl = await fileToCompressedDataUrl(f);
      const r = await api("/api/upload_image", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data: dataUrl }) });
      state.diaryImages.push(r.path);
      renderDiaryImages();
    } catch (err) { setStatus("图片上传失败：" + err.message); }
  }
  input.value = "";
});
async function fileToCompressedDataUrl(file, maxDim = 1600, q = 0.85) {
  const img = await createImageBitmap(file);
  const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", q);
}

/* ============ 日期弹层 / 回顾弹层 / 一言 ============ */
async function openDatePop() {
  try {
    const { dates } = await api("/api/note_dates");
    if (!dates.length) { setStatus("还没有任何笔记。"); return; }
    const pop = $("#datepop");
    pop.innerHTML = `<div class="hint" style="padding:2px 10px 6px">跳转到日期</div>` + dates.map(d => {
      const parts = d.date.split("-");
      const dt = new Date(d.date + "T00:00:00");
      const wk = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][dt.getDay()];
      return `<div class="drow" data-date="${d.date}"><span class="ddot"></span>${+parts[1]}月${+parts[2]}日 ${wk}<span class="dcount">${d.count} 条</span></div>`;
    }).join("");
    pop.classList.add("show");
  } catch (e) { setStatus("日期列表获取失败：" + e.message); }
}
$("#datepop").addEventListener("click", e => {
  const row = e.target.closest(".drow");
  const pop = $("#datepop");
  if (row) {
    const k = row.getAttribute("data-date");
    pop.classList.remove("show");
    state.selected.clear();
    if (currentNotes.some(n => dateKey(n.created_at) === k)) {
      state.jumpDate = null; state.collapsed.delete(k); renderNotes();
      const g = moduleList.querySelector(`.group[data-date="${k}"]`);
      if (g) g.scrollIntoView({ behavior: "smooth", block: "start" });
    } else { state.jumpDate = k; loadNotes(); }
  } else if (e.target === pop) pop.classList.remove("show");
});
document.addEventListener("click", e => {
  const p = $("#datepop");
  if (p.classList.contains("show") && !p.contains(e.target) && !e.target.closest("#datebtn")) p.classList.remove("show");
});
async function loadDigest(scope) {
  const body = $("#digestpop .dbody");
  body.textContent = "本地 AI 正在回顾…";
  try {
    const r = await api("/api/digest?scope=" + scope);
    body.textContent = r.digest + (r.count ? `\n\n（共揉了 ${r.count} 条记事）` : "\n\n（这段时间还没有记事）");
  } catch (e) {
    body.textContent = e.message.includes("ollama_off") ? "Ollama 没在运行，回顾用不了。点左下角徽标可尝试拉起。" : "回顾失败：" + e.message;
  }
}
$("#digestpop").addEventListener("click", e => {
  if (e.target.id === "dclose") { $("#digestpop").classList.remove("show"); return; }
  const tab = e.target.closest(".dtab");
  if (tab) {
    document.querySelectorAll("#digestpop .dtab").forEach(t => t.classList.toggle("on", t === tab));
    loadDigest(tab.getAttribute("data-scope"));
  }
});
document.addEventListener("click", e => {
  const p = $("#digestpop");
  if (p.classList.contains("show") && !p.contains(e.target) && !e.target.closest("#digestbtn")) p.classList.remove("show");
});
async function loadHitokoto(rotate) {
  const el = $("#hitokoto");
  try {
    const h = await api("/api/hitokoto" + (rotate ? "?rotate=1" : ""));
    el.textContent = "「" + (h.hitokoto || "") + "」—— " + (h.from || "一言");
  } catch { el.textContent = ""; }
}
let lastRotate = 0;
$("#hitokoto").addEventListener("click", () => {
  if (Date.now() - lastRotate < 3000) return;
  lastRotate = Date.now();
  loadHitokoto(true);
});

/* ============ AI 抽屉（问路远 + 识别记录 + 模型） ============ */
let openDrawerName = null;
function openDrawerByName(name) {
  closeAllDrawers();
  openDrawerName = name;
  document.getElementById(name + "Overlay").classList.add("open");
  document.getElementById(name + "Drawer").classList.add("open");
  if (name === "ai") buildAiDrawer();
  if (name === "set") buildSetDrawer();
}
function closeAllDrawers() {
  document.querySelectorAll(".drawer-overlay, .drawer").forEach(el => el.classList.remove("open"));
  openDrawerName = null;
  /* 2026-10-30 通宵批：设置是抽屉，点侧栏「设置」时导航高亮会跟过去；
     抽屉一关，高亮必须回到真正所在的页，否则侧栏一直显示「你在设置」。 */
  if (typeof markRailActive === "function") markRailActive(state.module);
  if (typeof syncRailSubs === "function") syncRailSubs();
}
$("#aiBtn").addEventListener("click", () => openDrawerByName("ai"));
$("#setBtn").addEventListener("click", () => openDrawerByName("set"));
["ai", "set"].forEach(name => {
  document.getElementById(name + "Overlay").addEventListener("click", closeAllDrawers);
  document.querySelector(`[data-close="${name}"]`).addEventListener("click", closeAllDrawers);
});
async function buildAiDrawer() {
  const body = $("#aiDrawerBody");
  let model = "qwen2.5:7b";
  try { const o = await api("/api/ollama"); if (o.running && o.model) model = o.model; } catch {}
  const localModel = localStorage.getItem("luyuan_model") || model;
  let log = [];
  try { log = JSON.parse(localStorage.getItem("luyuan_ai_log") || "[]"); } catch {}
  body.innerHTML = `
    <div class="drawer-section">
      <h4>当前模型</h4>
      <div class="drawer-row"><span>${escapeHtml(localModel)} · 本地优先</span><span class="badge manual">右下角可切</span></div>
      <div class="hint">长文本（&gt;80 字）自动建议 DeepSeek；私密标签笔记永不外发。</div>
    </div>
    <div class="drawer-section">
      <h4>问路远</h4>
      <div class="drawer-row"><label>跟笔记对话</label>
        <button class="batch-btn" id="aiGoAsk">去问路远页</button></div>
      <div class="hint">问答、历史都在左侧「问路远」那一页（原来抽屉里又有一份，是同一件事两个入口）。</div>
    </div>
    <div class="drawer-section">
      <h4>识别记录（本机）</h4>
      <div id="aiHistList">
      ${log.length ? log.map(l => `<div class="ai-item"><time>${escapeHtml(l.t)}</time>「${escapeHtml(l.text)}」→ ${escapeHtml(l.label)}</div>`).join("")
        : `<div class="hint">还没有记录。在输入框记一句就会出现在这里。</div>`}
      </div>
    </div>`;
  const goAsk = document.getElementById("aiGoAsk");
  if (goAsk) goAsk.addEventListener("click", () => { closeAllDrawers(); switchModule("ask"); });
  /* 识别记录：上面模板已用 log（localStorage）直接渲染完毕。
     历史上这里还有一段「拉真历史覆盖 DOM」的补丁，但它找的 #histList / #histSrc
     两个元素在 panel.html 里从来不存在 → list.innerHTML 抛
     "Cannot set properties of null" → 点 AI 助手就在控制台报错（v26 修复）。
     正确做法：给「识别记录」区块自己一个 id，有真历史就覆盖、没有就保留本地那份。 */
  (async () => {
    const list = $("#aiHistList");
    if (!list) return;            // 模板变了也不崩
    try {
      const h = await api("/api/terminal/history");
      const items = (h.items || []).slice(0, 15);
      if (!items.length) return;  // 没真历史就留着本地日志
      list.innerHTML = items.map(function (it) {
        const lbl = (it.actions && it.actions[0] && it.actions[0].label) || it.intent || "已处理";
        const t = it.ts ? new Date(it.ts * 1000).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
        return '<div class="ai-item"><time>' + escapeHtml(t) + '</time>「' + escapeHtml(it.text || "") + '」→ ' + escapeHtml(String(lbl)) + '</div>';
      }).join("");
    } catch (e) { /* 拿不到真历史：本地那份已经在上面渲染好了，什么都不用做 */ }
  })();
}

/* ============ 设置抽屉（可读写：API 配置 / 模型端点 / 开关） ============ */
async function buildSetDrawer() {
  const body = $("#setDrawerBody");
  let ver = "?", ollama = "未知", cfg = null;
  try { const h = await api("/api/health"); ver = h.ver; } catch {}
  try { const o = await api("/api/ollama"); ollama = o.running ? "运行中（" + (o.model || "") + "）" : "未运行"; } catch {}
  try { const c = await api("/api/config"); cfg = c.config || {}; } catch {}
  const ak = (cfg && cfg.askaway) || {};
  const ch = (cfg && cfg.chat) || {};
  const keyTail = ak.api_key_set ? (ak.api_key || "") : "";
  body.innerHTML = `
    <div class="drawer-section">
      <h4>服务</h4>
      <div class="drawer-row"><label>生产地址</label><input value="http://127.0.0.1:8777" disabled></div>
      <div class="drawer-row"><label>前端版本</label><span>v${escapeHtml((() => { const s = document.querySelector('script[src*="/app.js"]'); const m = s && s.src.match(/[?&]v=([^&]+)/); return m ? m[1] : '?'; })())}（服务端 ver ${escapeHtml(String(ver))}）</span></div>
      <div class="drawer-row"><label>Ollama</label><span>${escapeHtml(ollama)}</span></div>
    </div>
    <div class="drawer-section">
      <h4>模型 Key / 端点</h4>
      <div class="drawer-row"><label>DeepSeek Key</label>
        <input id="cfgKey" type="password" placeholder="${ak.api_key_set ? escapeHtml(keyTail) + "（已配置，留空不改）" : "未配置，粘贴你的 Key"}" autocomplete="off"></div>
      <div class="drawer-row"><label>云端模型</label>
        <input id="cfgModel" value="${escapeHtml(ak.model || "deepseek-v4-flash")}"></div>
      <div class="drawer-row"><label>Cloud Base</label>
        <input id="cfgBase" value="${escapeHtml(ak.base_url || "https://api.deepseek.com")}"></div>
      <div class="drawer-row"><label>Ollama 端点</label>
        <input id="cfgOllama" value="${escapeHtml((cfg && cfg.stt && cfg.stt.correct && cfg.stt.correct.endpoint) || "http://localhost:11434")}"></div>
      <div class="drawer-actions"><button class="batch-btn" id="cfgSave">保存</button></div>
      <div class="hint">Key 只存本机 config.json，前端只显示掩码、永不回显明文（隐私红线）。</div>
    </div>
    <div class="drawer-section">
      <h4>外观</h4>
      <div class="drawer-row"><label>主题</label>
        <span style="font-size:12.5px;color:var(--ink-soft)">当前：${document.body.classList.contains("dark") ? "夜色" : "白天"}</span></div>
      <div class="drawer-row"><label>深色主题</label>
        <button class="batch-btn" id="darkToggle">切到${document.body.classList.contains("dark") ? "白天" : "夜色"}</button></div>
    </div>
    <div class="drawer-section">
      <h4>同步</h4>
      <div class="drawer-row"><label>Syncthing</label><span>data/notes 双向同步</span></div>
    </div>
    <div class="drawer-section">
      <h4>快捷键</h4>
      <div class="drawer-row"><label>全部快捷键</label>
        <button class="batch-btn" id="openKeyHelp">查看</button></div>
      <div class="hint">最常用的四个：<b>F10</b> 说话 · <b>/</b> 搜当前页 · <b>Ctrl+K</b> 跳转任何地方 · <b>Esc</b> 逐层退出</div>
    </div>
    <div class="drawer-section" id="conflictSection" style="display:none">
      <h4>同步冲突 · 二选一</h4>
      <div id="conflictList"></div>
      <div class="hint">败者挪进 data/conflict_trash/ 隔离区（不删），选错可从那里找回。</div>
    </div>`;
  /* A8（2026-09-14）：同步冲突二选一（SYNC_FORMAT §10.5）。没有冲突时整块不出现，不占地方。 */
  (async () => {
    let cs = [];
    try { cs = (await api("/api/conflicts")).conflicts || []; } catch { return; }
    if (!cs.length) return;
    const sec = document.getElementById("conflictSection"), list = document.getElementById("conflictList");
    if (!sec || !list) return;
    sec.style.display = "";
    const prev = (o) => { const t = o && (o.text || o.item || o.name || ""); return t ? escapeHtml(String(t).slice(0, 40)) : "（非文本条目）"; };
    const when = (s) => escapeHtml(String(s || "").replace("T", " ").slice(5, 16));
    list.innerHTML = cs.map(c => {
      const btns = c.orphan
        ? `<button class="batch-btn cf-act" data-cf="${escapeHtml(c.conflict)}" data-keep="conflict">收养转正</button>
           <button class="batch-btn danger cf-act" data-cf="${escapeHtml(c.conflict)}" data-keep="discard">隔离丢弃</button>`
        : `<button class="batch-btn cf-act" data-cf="${escapeHtml(c.conflict)}" data-keep="base">留本机</button>
           <button class="batch-btn cf-act" data-cf="${escapeHtml(c.conflict)}" data-keep="conflict">留副本</button>`;
      return `<div class="cf-item">
        <div class="cf-row"><span class="badge">本机</span><span class="cf-text">${prev(c.base_json)}</span><span class="cf-time">${when(c.base_mtime)}</span></div>
        <div class="cf-row"><span class="badge tag">${c.orphan ? "孤儿副本" : "副本"}</span><span class="cf-text">${prev(c.conflict_json)}</span><span class="cf-time">${when(c.conflict_mtime)}</span></div>
        <div class="cf-btns">${btns}</div>
      </div>`;
    }).join("");
    list.querySelectorAll(".cf-act").forEach(b => b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        await api("/api/conflicts/resolve", { method: "POST", body: JSON.stringify({ conflict: b.dataset.cf, keep: b.dataset.keep }) });
        showToast("已裁决（败者在 data/conflict_trash/ 可找回）", "green");
        buildSetDrawer();
      } catch (e) { setStatus("裁决失败：" + e.message); b.disabled = false; }
    }));
  })();
  setTimeout(function () {
    var dt = document.getElementById("darkToggle");
    if (dt) dt.addEventListener("click", function () {
      document.body.classList.toggle("dark");
      localStorage.setItem("luyuan_dark", document.body.classList.contains("dark") ? "1" : "");
      try { buildSetDrawer(); } catch (e) {}   // 让「当前：夜色/白天」这一行跟着变
    });
    /* 2026-10-30 通宵批：抽屉里原来把那串快捷键说明整段摊开（跟 ? 帮助卡两处维护、两处不一致）。
       现在只留四个最常用的，其余点「查看」开官方那张表。 */
    var kh = document.getElementById("openKeyHelp");
    if (kh) kh.addEventListener("click", function () {
      closeAllDrawers();
      document.getElementById("helpPop").classList.add("show");
    });
    var sv = document.getElementById("cfgSave");
    if (sv) sv.addEventListener("click", async function () {
      var patch = {};
      var kv = document.getElementById("cfgKey").value.trim();
      if (kv && kv.indexOf("••••") !== 0) patch["askaway.api_key"] = kv;
      var mv = document.getElementById("cfgModel").value.trim();
      if (mv) patch["askaway.model"] = mv;
      var bv = document.getElementById("cfgBase").value.trim();
      if (bv) patch["askaway.base_url"] = bv;
      var ov = document.getElementById("cfgOllama").value.trim();
      if (ov) patch["stt.correct.endpoint"] = ov;
      if (!Object.keys(patch).length) { setStatus("没有改动。"); return; }
      sv.disabled = true; sv.textContent = "保存中…";
      try {
        var r = await api("/api/config", { method: "PUT", body: JSON.stringify({ patch: patch }) });
        setStatus("已保存 " + (r.changed ? r.changed.length : 0) + " 项，即时生效。");
        showToast("设置已保存", "green");
        if (patch["askaway.api_key"]) { try { buildSetDrawer(); } catch (e) {} }
      } catch (e) {
        setStatus("保存失败：" + e.message);
      } finally {
        sv.disabled = false; sv.textContent = "保存";
      }
    });
  }, 0);
}

/* ============ 触控手势：左滑快捷操作 + 长按多选（v15） ============ */
const SWIPE_W = 150;
let lp = null;
function closeOpenSwipe(except) {
  moduleList.querySelectorAll('.item[data-swipe="open"]').forEach(it => {
    if (it === except) return;
    it.removeAttribute("data-swipe");
    it.classList.remove("swipe-show");
    const m = it.querySelector(".item-main");
    if (m) m.style.transform = "";
  });
}
moduleList.addEventListener("touchstart", e => {
  const item = e.target.closest(".item");
  closeOpenSwipe(item);
  if (!item || !item.querySelector(".swipe-actions")) { lp = null; return; }
  lp = { item, main: item.querySelector(".item-main"), x0: e.touches[0].clientX, y0: e.touches[0].clientY, dx: 0, mode: "undecided", wasOpen: item.dataset.swipe === "open" };
  item.classList.add("pressing");
  lp.timer = setTimeout(() => {
    if (lp && lp.mode === "undecided") {
      lp.item.classList.remove("pressing");
      lp.mode = "done";
      const cb = lp.item.querySelector('input[type=checkbox].ncheck, .cttodo input[type=checkbox]');
      if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event("change", { bubbles: true })); }
    }
  }, 550);
}, { passive: true });
moduleList.addEventListener("touchmove", e => {
  if (!lp || lp.mode === "done") return;
  const dx = e.touches[0].clientX - lp.x0, dy = e.touches[0].clientY - lp.y0;
  if (lp.mode === "undecided") {
    if (Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy) * 1.4) { lp.mode = "swipe"; clearTimeout(lp.timer); lp.item.classList.remove("pressing"); }
    else if (Math.abs(dy) > 12) { lp.mode = "scroll"; clearTimeout(lp.timer); lp.item.classList.remove("pressing"); }
  }
  if (lp.mode === "swipe") {
    lp.dx = Math.max(-SWIPE_W - 30, Math.min(0, (lp.wasOpen ? -SWIPE_W : 0) + dx));
    lp.main.style.transition = "none";
    lp.main.style.transform = `translateX(${lp.dx}px)`;
    lp.item.classList.toggle("swipe-show", lp.dx < -30);
  }
}, { passive: true });
moduleList.addEventListener("touchend", () => {
  if (!lp) return;
  clearTimeout(lp.timer);
  lp.item.classList.remove("pressing");
  if (lp.mode === "swipe") {
    const open = lp.dx < -SWIPE_W * 0.45;
    lp.main.style.transition = "";
    lp.main.style.transform = open ? `translateX(${-SWIPE_W}px)` : "";
    if (open) lp.item.dataset.swipe = "open"; else lp.item.removeAttribute("data-swipe");
    lp.item.classList.toggle("swipe-show", open);
  }
  lp = null;
}, { passive: true });
moduleList.addEventListener("touchcancel", () => {
  if (lp) { clearTimeout(lp.timer); lp.item.classList.remove("pressing"); lp = null; }
}, { passive: true });
moduleList.addEventListener("contextmenu", e => { if (e.target.closest(".item")) e.preventDefault(); });
document.addEventListener("click", e => { if (!e.target.closest(".item")) closeOpenSwipe(null); });

/* ============ 启动追加 ============ */
loadHitokoto(false);
loadInboxCount();
setInterval(loadInboxCount, 90000);
/* 一言只在打开面板与点击时刷新（2026-09-14 修复：原来 setInterval(fn,0) 会被浏览器钳到
   ~4ms，等于每秒轰炸 /api/hitokoto 两百多次）。 */

/* ============ 学业（CSU，2026-09-14 夜 UI 席位）：校历周次 + 事件 + 奖学金/竞赛/综测速查 ============
   2026-10-30 通宵批：与「课务」（8790 iframe）两个顶层入口点下去像同一页 —— 两边都有校历、都有
   「成绩·学业」。分工定死：课务=上课这件事（课表/作业/成绩），学业=校历/速查/综测台账。
   课务的子项里已摘掉「校历·提醒」，「成绩·学业」改名「成绩」；两页顶部各给一句分工 + 一个互跳口。 */
TOOLBARS.csu = function () {
  modToolbar.innerHTML = `
    <span class="count" id="modCount"></span>
    <span class="spacer"></span>
    <button class="tool-btn" id="csu_to_course" title="课表、作业、成绩在「课务」里">去课务看课表</button>
    <a class="tool-btn" href="http://csu.yjs.net.cn" target="_blank" rel="noopener">研究生院</a>`;
  const b = document.getElementById("csu_to_course");
  if (b) b.addEventListener("click", () => switchModule("course"));
};
RENDERERS.csu = async function (animate) {
  moduleList.innerHTML = `<div class="empty">正在翻校历…</div>`;
  let ov = null;
  try { ov = await api("/api/csu/overview"); } catch (e) {
    moduleList.innerHTML = failState("学业服务这会儿没连上。", "csu") +
      `<div class="hint" style="text-align:center;max-width:460px;margin:0 auto">速查也可以直接在终端里问路远。</div>`;
    return;
  }
  const w = ov.week || {};
  const events = (ov.events || []).filter(ev => ev.end >= new Date().toISOString().slice(0, 10));
  if (state.module !== "csu") return;   // 切走了，迟到结果丢弃
  moduleList.innerHTML = `
    <div class="ledger-stat"><span class="ls-label">${w.semester || "本学期"}</span>
      <span class="ls-num">第 ${w.week || "?"} 周</span>
      <span class="ls-sub">${w.week_day || ""} · 开学锚点 ${w.anchor || "—"}${w.anchor_kind === "freshman" ? "（新生历）" : ""}</span></div>
    <div class="hint" style="padding:2px 4px 10px">这页管校历 / 速查 / 综测台账；课表、作业、成绩在「课务」。
      <button class="tool-btn" id="csu_to_course2" style="padding:2px 10px;font-size:11.5px;margin-left:4px">去课务</button></div>
    <div class="sect">接下来（校历 · 自动提醒已进待办）</div>
    <div id="csuEvents">${events.length ? events.map(ev => `
      <div class="xrow"><span class="xcat">${ev.type || "校历"}</span>
        <span style="flex:1;min-width:0">${escapeHtml(ev.name || "")}</span>
        <span class="stime">${ev.date}${ev.end && ev.end !== ev.date ? " ~ " + ev.end : ""}</span></div>`).join("")
      : `<div class="empty">未来 120 天没有校历事件了，安心上课。</div>`}</div>
    <div class="sect">一句话速查</div>
    <div class="jumpbar"><input class="dtin" id="csuQ" placeholder="如：奖学金 / 竞赛 / 综测 / 推免…"
      style="flex:1;min-width:0;font-size:13.5px;padding:8px 12px">
      <button class="tool-btn" id="csuQBtn">查</button></div>
    <div id="csuRes"></div>
    <div class="sect">待核实事项 <span class="hint" style="font-weight:400">（整理时存疑的条目，找学院/教务确认后划掉）</span></div>
    <div id="csuPending" style="margin-top:6px"></div>
    <div class="sect">综测加分台账 <span class="hint" style="font-weight:400">（规则：综合素质总加分 ≤3 分，明细见速查）</span></div>
    <div class="jumpbar"><input class="dtin" id="csuLedgerIn" placeholder="如：+1.5 竞赛 校赛二等 前端项目"
      style="flex:1;min-width:0;font-size:13px;padding:8px 12px"><button class="tool-btn" id="csuLedgerAdd">记</button></div>
    <div id="csuLedgerList" style="margin-top:8px"></div>`;
  $("#modCount").textContent = `${events.length} 件校历节点`;
  const toCourse = document.getElementById("csu_to_course2");
  if (toCourse) toCourse.addEventListener("click", () => switchModule("course"));
  const run = async () => {
    const q = ($("#csuQ").value || "").trim();
    if (!q) return;
    $("#csuRes").innerHTML = `<div class="empty">查问中…</div>`;
    try {
      const r = await api("/api/csu/quick?q=" + encodeURIComponent(q));
      // 🔴 /api/csu/quick 返回分组结构 {scholarships/competitions/bonuses/pending}（各为字符串数组），
      //   原代码按 r.items 数组解——永远空。按分组渲染并带组名标签。
      const groups = [["奖学金", r.scholarships], ["竞赛", r.competitions],
                      ["综测加分", r.bonuses], ["待核实", r.pending]];
      const total = groups.reduce((n, [, arr]) => n + ((arr || []).length), 0);
      $("#csuRes").innerHTML = total
        ? groups.map(([label, arr]) => (arr || []).length
            ? `<div class="sect">${label} · ${arr.length} 条</div>` + arr.map(i =>
                `<div class="item"><div class="item-body"><div class="item-content">${escapeHtml(String(i))}</div></div></div>`).join("")
            : "").join("")
        : `<div class="empty">没有查到「${escapeHtml(q)}」相关的条目，换个说法试试。</div>`;
    } catch (e) { $("#csuRes").innerHTML = `<div class="empty">速查没连上：${escapeHtml(e.message)}</div>`; }
  };
  $("#csuQBtn").addEventListener("click", run);
  $("#csuQ").addEventListener("keydown", ev => { if (ev.key === "Enter") run(); });

  /* 待核实事项（折叠，点开看全部；数据源 csu_luyuan_data.json pending_verification） */
  const pendBox = document.getElementById("csuPending");
  if (pendBox) {
    fetch("/api/csu/pending").then(r => r.json()).then(items => {
      if (!items || !items.length) { pendBox.innerHTML = `<div class="hint">没有待核实条目。</div>`; return; }
      pendBox.innerHTML = `<details class="mu-pending"><summary>共 ${items.length} 条存疑，点开逐条核对</summary>
        ${items.map((t, i) => `<div class="cal-row"><span class="cal-date">${i + 1}</span><span class="cal-name">${escapeHtml(t)}</span></div>`).join("")}
      </details>`;
    }).catch(() => { pendBox.innerHTML = `<div class="hint">待核实清单加载失败。</div>`; });
  }

  /* 综测台账（自提案 B）：条目存 notes（tag=综测台账，text="+1.5 说明"），纯前端累计。 */
  const renderLedger = async () => {
    const box = document.getElementById("csuLedgerList");
    if (!box) return;
    const { notes } = await api("/api/notes?limit=100&tag=" + encodeURIComponent("综测台账"));
    let total = 0;
    const rows = (notes || []).map(n => {
      const m = (n.text || "").match(/^([+-]?\d+(?:\.\d+)?)\s*分?\s*(.*)$/);
      const v = m ? parseFloat(m[1]) : 0;
      total += v;
      return `<div class="xrow"><span class="stime">${fmtTime(n.created_at)}</span>
        <span style="flex:1;min-width:0">${escapeHtml(m ? m[2] || "（未写说明）" : n.text)}</span>
        <b style="color:${v >= 0 ? "var(--green-700)" : "var(--red)"}">${v >= 0 ? "+" : ""}${v}</b>
        <button class="sdel" data-tdel="${n.id}">删</button></div>`;
    }).join("");
    const over = total > 3 ? ` <span class="tag red">超 3 分上限，按 3 计</span>` : "";
    box.innerHTML = (notes || []).length
      ? rows + `<div class="hint" style="text-align:right">合计 <b style="color:var(--accent)">${total.toFixed(2)}</b> 分${over}（数据同步到手机）</div>`
      : `<div class="hint">还没有记录。格式：<b>+1.5 说明</b>（如 +1.5 竞赛 校赛二等）</div>`;
    box.querySelectorAll("[data-tdel]").forEach(b => b.addEventListener("click", async () => {
      try { await api("/api/notes/" + b.dataset.tdel, { method: "DELETE" }); renderLedger(); } catch {}
    }));
  };
  renderLedger();
  const la = $("#csuLedgerAdd");
  if (la) la.addEventListener("click", async () => {
    const inp = $("#csuLedgerIn");
    const v = (inp.value || "").trim();
    if (!v) return;
    try {
      await api("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: v, source: "manual", tags: ["综测台账"] }) });
      inp.value = "";
      setStatus("已记入综测台账。");
      renderLedger();
    } catch (err) { setStatus("台账记入失败：" + err.message); }
  });
  $("#csuLedgerIn").addEventListener("keydown", ev => { if (ev.key === "Enter") $("#csuLedgerAdd").click(); });
};

/* ============ 待办页（2026-09-15 IA 重排：消息待办从笔记页升级为一级入口） ============ */
TOOLBARS.todo = function () {
  /* 2026-10-29 体检批：把常驻的一整句同步说明收成一个小标签 + 悬浮提示，工具栏回归一行一个计数 */
  modToolbar.innerHTML = `<span class="count" id="modCount"></span><span class="spacer"></span>
    <span class="hint" style="padding:0;cursor:help" title="手机「✓ 收下」的待办会自动同步到这里，电脑不用再点一次；电脑点「完成」也会同步回手机。">与手机同步</span>`;
};
RENDERERS.todo = async function (animate) {
  moduleList.innerHTML = `<div class="empty">翻待办…</div>`;
  let t;
  try { t = await api("/api/todos"); } catch (e) {
    moduleList.innerHTML = failState("待办服务没连上。") +
      `<div class="hint" style="text-align:center;max-width:440px;margin:0 auto">可以先去看笔记页，待办数据都在同一个服务里，回来再试一次。</div>`;
    return;
  }
  const all = t.todos || [], done = t.done_today || [];
  updateTodoBadge(all.length);
  // 日期彩签（借鉴课务系统 rem-item 2026-09-15）：今天/尽快=琥珀、明天=金、其余=灰
  /* 2026-10-30 通宵批：这一格原先「没有截止时间」时也会塞一个 created_at（如 10/29），
     摆在行首读起来像「这事 10/29 要办」—— 天天误读。现在只显示真正的截止/说法，
     真没有就摆一个淡的「—」，收录时间挪到 tooltip。 */
  const ddchip = (x) => {
    const w = x.when_text || "";
    if (/今天|马上|尽快|现在|赶紧/.test(w)) return `<span class="ddchip soon" title="${escapeHtml(w)}">今天</span>`;
    if (/明天/.test(w)) return `<span class="ddchip mid" title="${escapeHtml(w)}">明天</span>`;
    const wm = w.match(/^(\d{1,2})[-月](\d{1,2})/);
    if (wm) return `<span class="ddchip" title="${escapeHtml(w)}">${wm[1]}/${wm[2]}</span>`;
    if (x.due_at && !isNaN(new Date(x.due_at))) {
      const d = new Date(x.due_at);
      return `<span class="ddchip ${d < new Date() ? "soon" : ""}" title="截止 ${fmtTime(x.due_at)}">${d.getMonth() + 1}/${d.getDate()}</span>`;
    }
    return `<span class="ddchip" style="opacity:.5" title="${x.created_at ? "收录于 " + fmtTime(x.created_at) : "没写什么时候办"}">—</span>`;
  };
  /* 2026-10-29 体检批：206 条平铺 = 没有优先级。三桶——今天及以后（展开）、已逾期（折叠）、
     没截止（折叠）。首屏只看到真正还来得及的，历史陈账收进一行摘要，点开仍在。 */
  const hasDue = (x) => x.due_at && !isNaN(new Date(x.due_at));
  const nowMs = Date.now();
  const upcoming = all.filter(x => hasDue(x) && new Date(x.due_at) >= nowMs)
    .sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
  const overdue = all.filter(x => hasDue(x) && new Date(x.due_at) < nowMs)
    .sort((a, b) => new Date(b.due_at) - new Date(a.due_at));
  const noDue = all.filter(x => !hasDue(x));
  const rowHtml = (x) => `
      <div class="item todo-row"><div class="item-main">${ddchip(x)}<div class="item-body">
        <div class="item-meta"><span class="badge">${x.source === "wechat" ? "微信" : x.source === "qq" ? "QQ" : "手动"}${x.who ? " · " + escapeHtml(x.who) : ""}</span>
          ${x.topic ? `<span class="badge tag">〔${escapeHtml(x.topic)}〕</span>` : ""}
          ${x.when_text ? `<span class="badge tag">${escapeHtml(x.when_text)}</span>` : ""}
          <span>${x.created_at ? fmtClock(x.created_at) : ""}</span></div>
        <div class="item-title">${escapeHtml(x.text)}</div>
        ${x.raw ? `<div class="item-content folded todo-raw" title="原始消息（完整内容点卡片展开）">${escapeHtml(x.raw)}</div>` : ""}
        <div class="item-actions">
          <button class="tool-btn mtdone" data-tid="${x.id}" title="办完销账（done 同步回手机，手机侧随之消失）">✓ 完成</button>
          <button class="tool-btn mtdrop" data-tid="${x.id}">✗ 不要</button>
        </div>
      </div></div></div>`;
  // 消息采集卡已随 msgdigest 下线（2026-09-18 路河拍板）；消息待办页本体保留
  const fold = (n, title, body) => n
    ? `<details class="tset"><summary>${title} <span class="tset-n">${n}</span></summary>${body}</details>` : "";
  // 2026-10-29 体检批：await 回来时人可能已经切走——迟到结果不许画到别人页面上
  if (state.module !== "todo") return;
  moduleList.innerHTML = `
    <div class="todo-sum">
      ${overdue.length ? `<span class="ts-warn">逾期 <b>${overdue.length}</b></span><span>·</span>` : ""}
      <span>近期待办 ${upcoming.length} 件</span>
      <span style="flex:1"></span>
      <span style="cursor:help" title="微信/QQ 私聊自动抽取；手机「✓ 收下」即入列">来源：微信 / QQ / 手动</span></div>
    ${all.length
      ? (upcoming.length ? `<div class="sect">今天及以后</div>` + upcoming.map(rowHtml).join("") : "")
        + fold(overdue.length, "已逾期（点开）", overdue.map(rowHtml).join(""))
        + fold(noDue.length, "没写截止时间", noDue.map(rowHtml).join(""))
      : `<div class="empty">眼下没有要办的。<br>手机上收到微信/QQ 里「像任务」的消息，收下后会同步到这里。</div>`}
    ${done.length ? `<div class="sect">今天已办完</div>` + done.map(x => `
      <div class="xrow"><span class="badge">已办</span><span style="flex:1;min-width:0">${escapeHtml(x.text)}</span>
        <button class="tool-btn mtundone" data-tid="${x.id}" title="勾错了？翻回未办（同步回手机）">取消完成</button></div>`).join("") : ""}`;
  $("#modCount").textContent = `${all.length} 件待办 · 已办 ${done.length}`;
};

/* ============ 路远远页（2026-10-19 批：QQ 播报退役，路远远的汇报改走工作台数据，SYNC_FORMAT §10.6） ============
   晨报/新收录/提醒/管家讲解/群简报都落 report_*.json，这里只管呈现：未读在上，点行展开全文顺手标已读。 */
TOOLBARS.report = function () {
  modToolbar.innerHTML = `<span class="count" id="modCount"></span><span class="spacer"></span>
    <button class="tool-btn" id="repOrganize" title="让路远远把待办按主题归组（写进本页汇报）">整理待办</button>
    <button class="tool-btn" id="repPanel" title="打开路远远自己的管理面板（人设 / 记忆库 / QQ 桥 / 订阅 / 主动性，3927 端口那套）">路远远面板 ↗</button>
    <button class="tool-btn" id="repReadAll">全部已读</button>`;
  $("#repOrganize").addEventListener("click", async () => {
    try {
      const r = await fetch("http://127.0.0.1:3927/api/organizer/run", { method: "POST" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      showToast("🫡 路远远开始整理了，等它写汇报", "blue");
    } catch (err) {
      setStatus("路远远没在跑（3927 没开），整理不了。");
    }
  });
  /* 2026-10-30：路远远的管理面板（public/index.html，九个设置页签：人设/记忆库/QQ桥/订阅/主动性/
     工具箱/收件箱/相处统计/App桥接）一直是个独立网页，工作台里从来没有入口——路河问"弄到哪去了"。
     现在挂在「汇报」页工具栏：优先让桌面壳用系统默认浏览器打开（8781/openurl，只放行回环地址），
     壳没在跑（纯浏览器访问工作台）就退化成 window.open。 */
  $("#repPanel").addEventListener("click", async () => {
    const url = "http://127.0.0.1:3927/";
    try {
      const r = await fetch("http://127.0.0.1:8781/openurl?u=" + encodeURIComponent(url));
      const j = await r.json();
      if (!j.ok) throw new Error(j.err || "壳拒绝");
      setStatus("路远远面板已在浏览器打开（人设 / 记忆库 / QQ 桥都在里面）。");
    } catch (e) {
      try { window.open(url, "_blank"); } catch (_) { setStatus("打不开：" + url); }
    }
  });
  $("#repReadAll").addEventListener("click", async () => {
    try { const r = await api("/api/reports/read_all", { method: "POST" }); setStatus(`已标 ${r.read} 条为已读。`); }
    catch (e) { setStatus("失败：" + e.message); }
    RENDERERS.report(false);
  });
};
RENDERERS.report = async function (animate) {
  moduleList.innerHTML = `<div class="empty">翻汇报…</div>`;
  let o;
  try { o = await api("/api/reports"); } catch (e) {
    moduleList.innerHTML = failState("汇报服务没连上。") +
      `<div class="hint" style="text-align:center;max-width:440px;margin:0 auto">路远远在跑的时候会自己写进来，晚点再回来看。</div>`;
    return;
  }
  const all = o.reports || [];
  const unread = all.filter(r => !r.read), read = all.filter(r => r.read);
  updateReportBadge(unread.length);
  const CATS = { "晨报": "mid", "新收录": "soon", "提醒": "soon", "管家": "", "简报": "", "来件": "", "整理": "deep" };
  // A 方案（2026-10-20 路河拍板）：列表只露 分类签+标题+一行摘要+时间；点开才看正文
  /* 2026-10-29 复查：摘要位常出现「没说利害」「通知没写利害」这类自我说明——那是机器的备忘，
     不是给人的信息。命中就退回正文首句，正文也没有才用一句中性话兜底。 */
  const META_SUM = /^(没说|没提|通知没写|原文没写|原文没提|未提及|不清楚|不详|未知)/;
  /* 只去「列表编号」，不能连正文开头的数字一起吃掉——
     旧写法 /^[①-⑮0-9一二三四五六七八九十、.·\s]+/ 会把「28号晚上七点」的 28 也删掉。 */
  const stripMark = (s) => String(s || "")
    .replace(/^[①-⑮]\s*/, "")
    .replace(/^\d{1,2}\s*[、.．]\s*/, "")
    .replace(/^[一二三四五六七八九十]{1,3}\s*、\s*/, "")
    .trim();
  const sumOf = (r) => {
    let s = stripMark(r.summary);
    if (!s || META_SUM.test(s)) {
      const first = stripMark(String(r.text || "").trim().split("\n")[0]);
      s = META_SUM.test(first) ? "" : first;
    }
    return s.slice(0, 60) || "原文没写影响，点开看正文";
  };
  /* 分类签已经写了「提醒」，标题再顶一个「提醒：」是重复；急标保留。 */
  const titleOf = (r) => {
    let t = String(r.title || "（无题）").trim();
    const urgent = /^【?(急|重要)】?/.test(t);
    t = t.replace(/^【?(急|重要)】?\s*/, "").replace(/^(提醒|晨报|简报|来件|通知|管家)\s*[:：]\s*/, "");
    return (urgent ? "【急】" : "") + t;
  };
  /* 正文清洗（2026-10-29 复查）：
     ①「①没说利害」这类整行自我说明直接删掉并重新编号——它不是给他的信息；
     ②完全相同的整行只留一次（142 条逾期里有重复抽出的同一条待办）。 */
  const MARKS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];
  const cleanBody = (t) => {
    const seen = new Set();
    const kept = [];
    for (const raw of String(t || "").split("\n")) {
      const line = raw.trimEnd();
      if (!line.trim()) { kept.push(""); continue; }
      const m = line.match(/^\s*(?:[①-⑩]|\d+[、.．])\s*(.+)$/);
      if (m && META_SUM.test(m[1].trim())) continue;      // 元话行整行丢弃
      if (seen.has(line)) continue;                        // 重复行丢弃
      seen.add(line);
      kept.push(line);
    }
    let n = 0;
    return kept.map((line) => {
      const m = line.match(/^\s*(?:[①-⑩]|\d+[、.．])\s*(.+)$/);
      if (!m) return line;
      const mark = MARKS[n] || `${n + 1}、`;
      n++;
      return mark + " " + m[1];
    }).join("\n").trim();
  };
  const rowHtml = (r, unreadRow, idx) => `
    <div class="item rep-row" data-rid="${r.id}" data-unread="${unreadRow ? 1 : 0}" style="animation-delay:${animate && idx < 8 ? idx * 55 : 0}ms">
      <div class="item-main"><span class="ddchip ${CATS[r.category] != null ? CATS[r.category] : ""}">${escapeHtml(r.category || "汇报")}</span>
        <div class="item-body">
          <div class="rep-title${unreadRow ? " rep-strong" : ""}">${escapeHtml(titleOf(r))}</div>
          <div class="rep-sum">${escapeHtml(sumOf(r))}</div>
          <div class="rep-full">${escapeHtml(cleanBody(r.text))}</div>
          <div class="rep-time">${r.created_at ? fmtTime(r.created_at) : ""}</div>
          <div class="item-actions">
            <button class="tool-btn rep-toggle" data-rid="${r.id}" data-to="${unreadRow ? "read" : "unread"}">${unreadRow ? "✓ 看过了" : "标未读"}</button>
            <button class="tool-btn rep-del" data-rid="${r.id}">✗ 删掉</button>
          </div>
        </div></div></div>`;
  if (state.module !== "report") return;   // 切走了，迟到结果丢弃
  moduleList.innerHTML = `${((unread.length ? `<div class="sect">未读</div>` + unread.map((r, i) => rowHtml(r, true, i)).join("") : "")
      + (read.length ? `<div class="sect">已看过</div>` + read.map((r, i) => rowHtml(r, false, i)).join("") : ""))
      || `<div class="empty">还没有汇报。路远远有话要说时写在这里，不再发 QQ。</div>`}`;
  $("#modCount").textContent = `未读 ${unread.length} · 共 ${all.length}`;
  const rerender = () => RENDERERS.report(false);
  moduleList.querySelectorAll(".rep-row").forEach(row => {
    row.addEventListener("click", async (e) => {
      if (e.target.closest(".tool-btn")) return;
      const opening = !row.classList.contains("open");
      row.classList.toggle("open");                     // 点行=摘要↔正文切换
      if (opening && row.dataset.unread === "1") {      // 点开=读过：本地更新，不整页重绘
        row.dataset.unread = "0";
        const dot = row.querySelector(".rep-dot"); if (dot) dot.remove();
        const btn = row.querySelector(".rep-toggle"); if (btn) { btn.dataset.to = "unread"; btn.textContent = "标未读"; }
        api(`/api/reports/${row.dataset.rid}/read`, { method: "POST" }).catch(() => {});
      }
    });
  });
  moduleList.querySelectorAll(".rep-toggle").forEach(b => b.addEventListener("click", async () => {
    try { await api(`/api/reports/${b.dataset.rid}/${b.dataset.to}`, { method: "POST" }); } catch {}
    rerender();
  }));
  moduleList.querySelectorAll(".rep-del").forEach(b => b.addEventListener("click", async (e) => {
    e.stopPropagation();
    try { await api(`/api/reports/${b.dataset.rid}`, { method: "DELETE" }); } catch (err) { setStatus("删除失败：" + err.message); }
    rerender();
  }));
};

/* ============ 问路远页（从右上小图标升级为一级入口；接口与 AI 抽屉同源） ============ */
TOOLBARS.ask = function () {
  modToolbar.innerHTML = `<span class="count">翻你的笔记回答 · 私密标签默认不外发</span><span class="spacer"></span>
    <button class="tool-btn" id="pAskClear">清空对话</button>`;
  const c = document.getElementById("pAskClear");
  if (c) c.addEventListener("click", async () => {
    try { await api("/api/ask/clear", { method: "POST" }); const l = document.getElementById("pAskLog"); if (l) l.innerHTML = ""; setStatus("问路远的对话已清空。"); } catch (e) { setStatus("清空失败：" + e.message); }
  });
};
RENDERERS.ask = async function (animate) {
  moduleList.innerHTML = `
    <div class="chat-wrap">
      <div class="asklog" id="pAskLog" style="max-height:none;flex:1;min-height:0;overflow:auto"><div class="empty">问点什么，路远去翻你的笔记作答。<br>例：「上周记过什么」「谢凤林的待办还有哪些」</div></div>
      <div class="askrow" style="padding-top:12px;border-top:1px solid var(--line)">
        <input id="pAskIn" placeholder="问点什么…（检索你的笔记作答）" autocomplete="off">
        <button class="sendq" id="pAskSend">问</button>
      </div>
    </div>`;
  const log = document.getElementById("pAskLog");
  try {
    /* 2026-10-30 通宵批：历史接口两种返回形状都有过（数组 / {history:[...]}），
       原来只认数组，抽屉那边只认对象 —— 同一份数据两处一半能显示一半不能。两种都接。 */
    const h = await api("/api/ask/history");
    const arr = Array.isArray(h) ? h : (h && h.history) || [];
    if (arr.length) log.innerHTML = arr.map(x =>
      `<div class="q">${escapeHtml(x.q || x.question || x.content || "")}</div><div class="a">${escapeHtml(x.a || x.answer || "")}</div>`).join("");
  } catch {}
  log.scrollTop = log.scrollHeight;
  const run = async () => {
    const inp = document.getElementById("pAskIn");
    const q = (inp.value || "").trim();
    if (!q) return;
    inp.value = "";
    log.insertAdjacentHTML("beforeend", `<div class="q">${escapeHtml(q)}</div><div class="a">…翻笔记中</div>`);
    log.scrollTop = log.scrollHeight;
    try {
      const r = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) });
      const ans = (log.lastElementChild);
      ans.classList.remove("a"); ans.classList.add("a");
      ans.textContent = r.answer || r.reply || JSON.stringify(r);
    } catch (e) {
      log.lastElementChild.textContent = "没答上来：" + e.message + "（断网或没配 Key 会自动降级本地模型）";
    }
    log.scrollTop = log.scrollHeight;
  };
  document.getElementById("pAskSend").addEventListener("click", run);
  document.getElementById("pAskIn").addEventListener("keydown", ev => { if (ev.key === "Enter") run(); });
};

/* ============ 课务（2026-09-15 路河：接入独立课务系统，直接替换原课程表） ============
   路远只当外壳：iframe 装 http://127.0.0.1:8790（带 ?embed=1，那边自己收起左侧栏），
   子页切换与深浅色都走 postMessage，不重载页面。
   原课程表渲染器没删，改名 RENDERERS._courseLocal / TOOLBARS._courseLocal：
   想退回旧课表，把下面两个注册名改回 course 即可（路远自己的 course_*.json 数据一直都在）。
   注意：旧渲染器自己那几处「改完课重画」的调用（共 5 个 RENDERERS.course(false)，在
   renderMuanGrid / 加课 / 删课 / 导入课表 里）没跟着改名，退回时要一并改回 _courseLocal，
   否则那几处会去刷新课务 iframe —— 不报错，只是刷不动旧课表。 */
const KEIWU_ORIGIN = "http://127.0.0.1:8790";
const KEIWU_VIEW_DEFAULT = "timetable";
let keiwuFrame = null, keiwuBooted = false;

function keiwuDark() { return document.body.classList.contains("dark") ? 1 : 0; }
function keiwuView() {
  if (state.keiwuView) return state.keiwuView;
  try { return localStorage.getItem("luyuan_keiwu_view") || KEIWU_VIEW_DEFAULT; } catch (e) { return KEIWU_VIEW_DEFAULT; }
}
function keiwuSrc() { return KEIWU_ORIGIN + "/?embed=1&dark=" + keiwuDark() + "#" + keiwuView(); }

/* 切子页：能用 postMessage 就不重载页面（重载会把那边的状态全丢掉） */
function keiwuGo(view) {
  state.keiwuView = view;
  try { localStorage.setItem("luyuan_keiwu_view", view); } catch (e) {}
  const w = keiwuFrame && keiwuFrame.contentWindow;
  if (w) { try { w.postMessage({ type: "keiwu:go", mod: view }, "*"); } catch (e) {} }
  if (typeof markKeiwuSub === "function") markKeiwuSub();
}
/* 把当前视图 + 主题推过去（iframe 刚加载完、或路远切深浅色时各推一次） */
function keiwuPush() {
  const w = keiwuFrame && keiwuFrame.contentWindow;
  if (!w) return;
  try {
    w.postMessage({ type: "keiwu:theme", dark: !!keiwuDark() }, "*");
    w.postMessage({ type: "keiwu:go", mod: keiwuView() }, "*");
  } catch (e) {}
}
function keiwuReload() {
  if (!keiwuFrame) return;
  keiwuFrame.src = keiwuSrc();
  keiwuCheck();
}

/* 探活：跨端口读不到响应体，但「连不上」一定 reject，拿它当 TCP 探针够用 */
async function keiwuProbe() {
  try { await fetch(KEIWU_ORIGIN + "/api/state", { mode: "no-cors", cache: "no-store" }); return true; }
  catch (e) { return false; }
}
async function keiwuCheck() {
  const up = await keiwuProbe();
  const c = $("#modCount");
  if (c) c.textContent = up ? "课务系统 · 127.0.0.1:8790" : "课务系统未连接";
  const off = $("#keiwuOff");
  if (off) off.hidden = up;
  return up;
}

function keiwuMount() {
  const host = $("#keiwuHost");
  if (!host) return;
  if (keiwuFrame) return;                       // 只建一次；之后切模块只是 CSS 藏起来
  keiwuFrame = document.createElement("iframe");
  keiwuFrame.className = "keiwu-frame";
  keiwuFrame.id = "keiwuFrame";
  keiwuFrame.setAttribute("title", "课务系统");
  keiwuFrame.setAttribute("allow", "fullscreen");
  keiwuFrame.src = keiwuSrc();
  keiwuFrame.addEventListener("load", () => { keiwuPush(); keiwuCheck(); });
  host.appendChild(keiwuFrame);

  const off = document.createElement("div");
  off.className = "keiwu-off";
  off.id = "keiwuOff";
  off.hidden = true;
  off.innerHTML = `<div class="kt">课务系统现在没在跑</div>
    <div class="ks">它是本机一个独立小服务（<code>127.0.0.1:8790</code>），课表、校历、成绩、综测都在里面；路远只负责把它装进这一页。没跑就点「启动它」，或自己双击 <code>课务系统\启动课务系统.bat</code>。</div>
    <div class="krow"><button class="tool-btn" id="kwEnsure">启动它</button><button class="tool-btn" id="kwRetry">我已启动，重试</button></div>`;
  host.appendChild(off);

  off.querySelector("#kwRetry").addEventListener("click", async () => {
    if (await keiwuCheck()) keiwuReload();      // 探到了就重新拉一次页面（之前那次连接是失败的）
    else setStatus("还是连不上 8790——确认课务系统的 server.py 起来了再说。");
  });
  off.querySelector("#kwEnsure").addEventListener("click", async () => {
    setStatus("正在拉起课务系统…");
    let r = null;
    try { r = await api("/api/keiwu/ensure", { method: "POST" }); }
    catch (e) { setStatus("路远后端还没有自动拉起接口（重启一次路远即可用上）；先手动双击 启动课务系统.bat。"); }
    if (r && r.running) { await new Promise(res => setTimeout(res, 300)); keiwuReload(); setStatus("课务系统已就绪。"); }
    else if (r && r.error) setStatus(r.error);
  });

  if (!keiwuBooted) {
    keiwuBooted = true;
    /* 那边切了页（含它自己内部改 hash）就把子项高亮跟过来 */
    window.addEventListener("message", (e) => {
      const d = e.data || {};
      if ((e.origin || "").indexOf(KEIWU_ORIGIN) !== 0) return;
      if (d.type === "keiwu:view" && d.mod) { state.keiwuView = d.mod; if (typeof markKeiwuSub === "function") markKeiwuSub(); }
    });
  }
  keiwuCheck();
}

TOOLBARS.course = function () {
  /* 2026-10-30：课表页主入口改回**本地课表**。
     旧版把这一页做成 iframe 指向课务系统 127.0.0.1:8790，而那个服务经常没在跑
     —— 点进去就是一片白，用户以为"课表坏了"。8790 降级成工具栏里的后门。 */
  modToolbar.innerHTML = `<span class="count" id="modCount">课表</span>
    <span class="spacer"></span>
    <button class="tool-btn" id="kwImport" title="从教务系统/课表 App 粘贴表格导入">⤓ 导入课表</button>
    <button class="tool-btn" id="kwAdd" title="手动加一门课">＋ 加课</button>
    <button class="tool-btn" id="kw_csu" title="校历、奖学金/竞赛/综测速查在「学业」里">学业速查</button>
    <button class="tool-btn" id="kwOpen" title="课务系统（8790）没跑时会是空白，仅留作后门">↗ 课务系统</button>`;
  const cs = document.getElementById("kw_csu");
  if (cs) cs.addEventListener("click", () => switchModule("csu"));
  const bi = $("#kwImport");
  if (bi) bi.addEventListener("click", () => {
    const p = $("#muImport");
    if (!p) { setStatus("先让课表渲染出来。"); return; }
    p.style.display = "block";
    p.scrollIntoView({ block: "center", behavior: REDUCED.matches ? "auto" : "smooth" });
    const t = $("#muImportText"); if (t) t.focus();
  });
  const ba = $("#kwAdd");
  if (ba) ba.addEventListener("click", () => {
    const f = $("#coForm");
    if (!f) { setStatus("先让课表渲染出来。"); return; }
    f.style.display = "flex";
    f.scrollIntoView({ block: "center", behavior: REDUCED.matches ? "auto" : "smooth" });
    const n = $("#co-name"); if (n) n.focus();
  });
  const bo = $("#kwOpen");
  if (bo) bo.addEventListener("click", () => window.open(KEIWU_ORIGIN + "/", "_blank"));
};
RENDERERS.course = function (animate) {
  // 本地课表：含「下一节」条、周次切换、分类筛选、加课/导入、本周负荷、近期校历
  $("#hitokoto").style.display = "none";
  return RENDERERS._courseLocal(animate);
};
