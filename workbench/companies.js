/* 企业追踪 · 投资论点。数据在 wb-data.companies，本机修改在 localStorage。 */
(function () {
  "use strict";
  const KEY = "joyce-podcast-companies-v1";
  const SCALE = ["活跃用户数", "交易/付费用户数", "订阅/交易金额", "企业收入", "企业利润"];
  let ctx = null;
  let store = { overrides: {}, added: [] };
  const state = { view: "overview", id: "", compare: [] };

  function loadStore() {
    try { store = JSON.parse(localStorage.getItem(KEY)) || {}; } catch { store = {}; }
    store.overrides ||= {};
    store.added ||= [];
  }
  function saveStore() {
    try { localStorage.setItem(KEY, JSON.stringify(store)); } catch { /* 隐私模式 */ }
  }
  function esc(s) { return ctx.esc(s); }

  function deepMerge(a, b) {
    if (Array.isArray(b)) return b.slice();
    if (b && typeof b === "object" && a && typeof a === "object" && !Array.isArray(a)) {
      const out = Object.assign({}, a);
      Object.keys(b).forEach(k => { out[k] = deepMerge(a[k], b[k]); });
      return out;
    }
    return b === undefined ? a : b;
  }

  function baseList() {
    return ((ctx.D.companies || {}).list) || [];
  }
  function companies() {
    const merged = baseList().map(c => store.overrides[c.id] ? deepMerge(c, store.overrides[c.id]) : c);
    (store.added || []).forEach(c => merged.push(c));
    return merged;
  }
  function byId(id) { return companies().find(c => c.id === id); }

  function patch(id, partial) {
    const added = (store.added || []).find(c => c.id === id);
    if (added) {
      Object.assign(added, deepMerge(added, partial));
    } else {
      store.overrides[id] = deepMerge(store.overrides[id] || {}, partial);
    }
    saveStore();
    render();
  }

  function parseAsOf(value) {
    if (!value) return null;
    const m = String(value).match(/^(\d{4})-(\d{2})(?:-(\d{2}))?$/);
    if (!m) return null;
    const y = +m[1], mo = +m[2];
    const d = m[3] ? +m[3] : new Date(y, mo, 0).getDate();
    return new Date(y, mo - 1, d);
  }
  function isStale(value) {
    const dt = parseAsOf(value);
    if (!dt) return false;
    const days = (Date.now() - dt.getTime()) / 864e5;
    return days > ((ctx.D.companies || {}).staleDays || 90);
  }
  function asOfOf(f) { return f.asOf || (f.source && f.source.asOf) || ""; }

  function factBits(f) {
    if (!f) return "";
    if (f.status === "未公开") {
      return `<span class="pill miss">未公开</span>${f.note ? `<span class="dim"> ${esc(f.note)}</span>` : ""}`;
    }
    const when = asOfOf(f);
    const old = isStale(when);
    const label = [f.value, f.unit].filter(x => x !== undefined && x !== null && x !== "").join(" ");
    const href = f.sourceUrl || (f.source && f.source.sourceUrl) || "";
    const title = f.sourceTitle || (f.source && f.source.sourceTitle) || "来源";
    const type = f.type || (f.source && f.source.type) || "";
    const ep = f.episodeId || (f.source && f.source.episodeId);
    return `<div class="fact${old ? " is-stale" : ""}">
      <b>${esc(label || f.text || f.name || "")}</b>
      ${type ? `<span class="pill">${esc(type)}</span>` : ""}
      ${f.forecast ? `<span class="pill">预测</span>` : ""}
      ${old ? `<span class="pill bad">超过 90 天</span>` : ""}
      <span class="dim">${esc(f.period || "")}${when ? " · " + esc(when) : ""}</span>
      ${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(title)}</a>` : ""}
      ${ep ? `<a href="../${esc(ep)}.html">${esc(ep)}</a>` : ""}
      ${f.note ? `<div class="dim">${esc(f.note)}</div>` : ""}
    </div>`;
  }

  function nodeFacts(node) {
    if (!node) return [];
    if (node.status === "未公开") return [node];
    if (Array.isArray(node.facts)) return node.facts;
    return [];
  }
  function refsHtml(co, refs) {
    if (!refs || !refs.length) return "";
    const blocks = refs.map(ref => {
      let node = co;
      String(ref).split(".").forEach(k => { node = node ? node[k] : null; });
      const facts = nodeFacts(node);
      if (!facts.length && node && node.text) return "";
      return facts.map(factBits).join("") || `<span class="dim">${esc(ref)}</span>`;
    }).join("");
    return blocks ? `<div class="ev">${blocks}</div>` : "";
  }

  function episodesHtml(co) {
    const rows = co.episodes || [];
    if (!rows.length) return `<p class="dim">没有挂上节目。</p>`;
    const prim = rows.filter(e => e.role === "主线");
    const ment = rows.filter(e => e.role !== "主线");
    const chip = e => `<a class="tag hue" href="../${esc(e.id)}.html">${e.publicNo ? "EP " + String(e.publicNo).padStart(2, "0") : esc(e.id)} · ${esc(e.role)}</a>`;
    return `<div class="tags">${prim.map(chip).join("")}</div>
      ${ment.length ? `<details class="co-more"><summary>提及 ${ment.length} 期</summary><div class="tags">${ment.map(chip).join("")}</div></details>` : ""}`;
  }

  function judgmentSelect(co) {
    const cur = (co.thesis && co.thesis.judgment) || "观察中";
    const opts = ((ctx.D.companies || {}).judgments) || ["看多", "中性", "看空", "观察中"];
    return `<select class="sel jsel" data-id="${esc(co.id)}">${opts.map(j => `<option ${j === cur ? "selected" : ""}>${esc(j)}</option>`).join("")}</select>`;
  }

  function draftBadge(node) {
    if (!node || node.draft === false) return `<span class="pill ok">已改</span>`;
    return `<span class="pill draft">AI草稿</span>`;
  }

  function renderOverview(root, rows) {
    const head = `<table class="ov"><thead><tr>
      <th>公司</th><th>判断</th><th>一句话论点</th><th>未公开</th><th>过期</th><th>第一条风险</th><th>主线</th>
    </tr></thead><tbody>`;
    const body = rows.map(co => {
      const cov = co.coverage || {};
      const risk = (co.risks && co.risks[0] && co.risks[0].text) || "—";
      const prim = (co.episodes || []).filter(e => e.role === "主线").map(e => e.publicNo ? "EP " + String(e.publicNo).padStart(2, "0") : e.id).join("、");
      const stale = cov.staleCount > 0;
      return `<tr class="${stale ? "is-stale" : ""}" data-open="${esc(co.id)}">
        <td><b>${esc(co.name)}</b><div class="dim">${esc(co.listing || "")}${co.ticker ? " · " + esc(co.ticker) : ""}</div></td>
        <td>${judgmentSelect(co)} ${draftBadge(co.thesis)}</td>
        <td>${esc((co.thesis && co.thesis.oneLiner) || "")}</td>
        <td>${cov.undisclosedCount ?? "—"}</td>
        <td>${stale ? `<span class="pill bad">${cov.staleCount}</span>` : "0"}</td>
        <td>${esc(risk)}</td>
        <td>${esc(prim || "—")}</td>
      </tr>`;
    }).join("");
    const omitted = ((ctx.D.companies || {}).omitted) || [];
    root.innerHTML = head + body + `</tbody></table>
      <div class="panel glass" style="margin-top:14px">
        <h3>没有单列的名字</h3>
        <p class="sub">仓库里对不上单一公司，或根本没有这一期。</p>
        <ul class="clean">${omitted.map(o => `<li><span>${esc(o.name)}</span><span>${esc(o.why)}</span></li>`).join("")}</ul>
        <p class="dim" style="margin-top:8px">${esc((((ctx.D.companies || {}).pendingTopics) || []).join(" "))}</p>
      </div>`;
    root.querySelectorAll("[data-open]").forEach(tr => {
      tr.addEventListener("click", ev => {
        if (ev.target.closest("select")) return;
        open(tr.dataset.open);
      });
    });
    bindJudgment(root);
  }

  function bindJudgment(scope) {
    scope.querySelectorAll(".jsel").forEach(sel => {
      sel.onchange = () => patch(sel.dataset.id, { thesis: { judgment: sel.value } });
    });
  }

  function kpiTable(co) {
    const rows = SCALE.map(key => {
      const node = (co.scale || {})[key] || { status: "未公开", note: "" };
      return `<tr><th>${esc(key)}</th><td>${nodeFacts(node).map(factBits).join("") || factBits(node)}</td></tr>`;
    });
    rows.push(`<tr><th>增速及预测</th><td>${nodeFacts(co.growth).map(factBits).join("") || factBits(co.growth)}</td></tr>`);
    return `<table class="kpi">${rows.join("")}</table>`;
  }

  function listBlock(title, items, renderItem) {
    return `<div class="dr-sec"><h4>${esc(title)}</h4>${(items || []).map(renderItem).join("") || "<p class='dim'>—</p>"}</div>`;
  }

  function renderDetail(root, co) {
    if (!co) { root.innerHTML = `<p class="dim">没有这家公司。</p>`; return; }
    const th = co.thesis || {};
    root.innerHTML = `
      <button class="btn" id="coBack" type="button">← 论点总览</button>
      <div class="panel glass thesis-hero" style="margin-top:12px">
        <div class="co-bar">
          <h2 style="margin:0">${esc(co.name)}</h2>
          <span class="dim">${esc(co.listing || "")}${co.ticker ? " · " + esc(co.ticker) : ""}</span>
          ${judgmentSelect(co)}
          ${draftBadge(th)}
          <span class="dim">${esc((co.derive || {}).role || "")}</span>
        </div>
        <p class="one-liner" id="oneLiner">${esc(th.oneLiner || "")}</p>
        <label class="dim">改一句话（保存在这台浏览器）</label>
        <textarea class="note" id="oneEdit">${esc(th.oneLiner || "")}</textarea>
        <div class="hero-actions">
          <button class="btn pri" id="oneSave" type="button">保存这句话</button>
          <button class="btn" id="markMine" type="button">${th.draft === false ? "仍标成 AI草稿" : "这句我改过了，去掉 AI草稿"}</button>
          <button class="btn" id="mdOne" type="button">导出 Markdown</button>
        </div>
        <p class="dim">${esc((co.derive || {}).how || "")}</p>
        ${episodesHtml(co)}
      </div>
      ${section("为什么是现在", draftBadge(co.whyNow) + `<p>${esc((co.whyNow && co.whyNow.text) || "")}</p>` + refsHtml(co, co.whyNow && co.whyNow.refs))}
      ${section("核心驱动", (co.drivers || []).map((d, i) => `<div class="issue"><span class="lv info"></span><div><b>${i + 1}.</b> ${draftBadge(d)} ${esc(d.text)}${refsHtml(co, d.refs)}</div></div>`).join(""))}
      ${section("护城河与竞争格局", draftBadge(co.moat) + `<p>${esc((co.moat && co.moat.text) || "")}</p>`)}
      ${section("商业模式与单位经济", draftBadge(co.model) + `<p>${esc((co.model && co.model.text) || "")}</p><p class="dim">${esc((co.model && co.model.unitEconomics) || "")}</p>` + refsHtml(co, co.model && co.model.refs))}
      ${section("规模与增速", kpiTable(co) + `<p class="dim">主营：${esc((co.business && co.business.text) || "")}</p>`)}
      ${section("市场空间与代表用户", `<p>${esc((co.market && co.market.text) || "")}</p>` + (co.customers && co.customers.items ? co.customers.items.map(it => factBits(it)).join("") : factBits(co.customers)))}
      ${section("产品矩阵", (co.products && co.products.items || []).map(it => `<div class="fact"><b>${esc(it.name)}</b> <span class="dim">${esc(it.note || "")}</span>${factBits({ source: it.source })}</div>`).join("") || "<p class='dim'>—</p>")}
      ${section("产品迭代", (co.iterations && co.iterations.items || []).map(it => `<div class="fact${isStale(it.date) ? " is-stale" : ""}"><b>${esc(it.date)}</b> ${esc(it.text)} ${isStale(it.date) ? `<span class="pill bad">超过 90 天</span>` : ""}<div>${factBits({ source: it.source })}</div></div>`).join(""))}
      ${section("估值参考", `${nodeFacts(co.valuation).map(factBits).join("") || factBits(co.valuation)}
        ${co.valuation && co.valuation.multiples ? factBits(co.valuation.multiples) : ""}
        ${co.market && co.market.tam ? `<div style="margin-top:8px"><span class="dim">市场空间 </span>${factBits(co.market.tam)}</div>` : ""}`)}
      ${section("主要风险", (co.risks || []).map(r => `<div class="issue"><span class="lv warn"></span><div>${draftBadge(r)} ${esc(r.text)}</div></div>`).join(""))}
      ${section("证伪信号", (co.falsify || []).map(r => `<div class="issue"><span class="lv error"></span><div>${draftBadge(r)} ${esc(r.text)}</div></div>`).join(""))}
      ${section("关键跟踪指标", (co.watch || []).map(w => `<div class="issue"><span class="lv info"></span><div>${draftBadge(w)} <b>${esc(w.kpi)}</b> · ${esc(w.why || "")}</div></div>`).join(""))}
      ${section("催化剂", factBits(co.catalysts))}
      ${section("相关节目与选题", episodesHtml(co) + (co.topics || []).map(t => `<p>${draftBadge(t)} ${esc(t.text)}</p>`).join(""))}
      <details class="panel glass" style="margin-top:14px" open>
        <summary>证据底稿 · 字段覆盖 未公开 ${esc((co.coverage || {}).undisclosedCount ?? "")} / ${esc((co.coverage || {}).leaves ?? "")}</summary>
        <p class="dim">${esc(((co.coverage || {}).undisclosed || []).join("、"))}</p>
        ${kpiTable(co)}
      </details>`;
    // 估值节在上面 kpi 里已经有一行，这里再单独放是重复。去掉空的占位 section 已用估值 panel。
    $("#coBack").onclick = () => { state.view = "overview"; state.id = ""; render(); };
    bindJudgment(root);
    $("#oneSave").onclick = () => patch(co.id, { thesis: { oneLiner: $("#oneEdit").value.trim() } });
    $("#markMine").onclick = () => patch(co.id, { thesis: { draft: th.draft === false } });
    $("#mdOne").onclick = () => download(co.name + "-投资论点.md", markdown(co));
  }

  function section(title, html) {
    return `<div class="panel glass" style="margin-top:14px"><h3>${esc(title)}</h3>${html}</div>`;
  }
  function $(s, el) { return (el || document).querySelector(s); }

  function renderMatrix(root, rows) {
    const links = ((ctx.D.companies || {}).rivalries) || [];
    const ids = [];
    links.forEach(r => { if (!ids.includes(r.a)) ids.push(r.a); if (!ids.includes(r.b)) ids.push(r.b); });
    const name = id => (rows.find(c => c.id === id) || {}).name || id;
    let html = `<table class="matrix"><thead><tr><th></th>${ids.map(id => `<th>${esc(name(id))}</th>`).join("")}</tr></thead><tbody>`;
    ids.forEach(a => {
      html += `<tr><th>${esc(name(a))}</th>`;
      ids.forEach(b => {
        if (a === b) { html += `<td class="dim">—</td>`; return; }
        const hit = links.find(r => (r.a === a && r.b === b) || (r.a === b && r.b === a));
        html += hit ? `<td><b>${esc(hit.axis)}</b><div class="dim">${esc(hit.note)}</div><a href="${esc(hit.sourceUrl)}" target="_blank" rel="noopener">${esc(hit.type)} · ${esc(hit.asOf)}</a></td>` : `<td></td>`;
      });
      html += `</tr>`;
    });
    html += `</tbody></table><p class="dim">没有格子的两家，是这批材料里没有写过的对照，不补份额。</p>`;
    root.innerHTML = html;
  }

  function renderCompare(root, rows) {
    const ids = state.compare.slice(0, 3);
    while (ids.length < 2) ids.push("");
    const opts = [`<option value="">选择公司</option>`].concat(rows.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`)).join("");
    const picks = ids.map((id, i) => `<select class="sel cmp" data-i="${i}">${opts}</select>`).join("");
    let table = "";
    const chosen = ids.map(byId).filter(Boolean);
    if (chosen.length >= 2) {
      const keys = SCALE.concat(["增速及预测"]);
      table = `<table class="kpi"><thead><tr><th>指标</th>${chosen.map(c => `<th>${esc(c.name)}</th>`).join("")}</tr></thead><tbody>`;
      keys.forEach(key => {
        table += `<tr><th>${esc(key)}</th>`;
        chosen.forEach(c => {
          const node = key === "增速及预测" ? c.growth : (c.scale || {})[key];
          table += `<td>${nodeFacts(node).map(factBits).join("") || factBits(node)}</td>`;
        });
        table += `</tr>`;
      });
      table += `<tr><th>一句话</th>${chosen.map(c => `<td>${draftBadge(c.thesis)} ${esc((c.thesis || {}).oneLiner || "")}</td>`).join("")}</tr>`;
      table += `</tbody></table>`;
    }
    root.innerHTML = `<div class="co-bar">${picks}</div>${table || `<p class="dim">选两家或三家。</p>`}`;
    root.querySelectorAll(".cmp").forEach(sel => {
      if (ids[+sel.dataset.i]) sel.value = ids[+sel.dataset.i];
      sel.onchange = () => {
        state.compare[+sel.dataset.i] = sel.value;
        render();
      };
    });
  }

  function markdown(co) {
    const th = co.thesis || {};
    const lines = [];
    const pack = ctx.D.companies || {};
    lines.push(`# ${co.name} · 投资论点`);
    lines.push("");
    lines.push(`> ${pack.disclaimer || "非投资建议。"}`);
    lines.push("");
    lines.push(`判断：**${th.judgment || "观察中"}** · ${th.draft === false ? "已由 Joyce 修改" : "AI草稿"}`);
    lines.push("");
    lines.push(`## 一句话论点`);
    lines.push(th.oneLiner || "");
    lines.push("");
    lines.push(`## 为什么是现在`);
    lines.push((co.whyNow && co.whyNow.text) || "");
    lines.push("");
    lines.push(`## 核心驱动`);
    (co.drivers || []).forEach((d, i) => lines.push(`${i + 1}. ${d.text}`));
    lines.push("");
    lines.push(`## 护城河与竞争格局`);
    lines.push((co.moat && co.moat.text) || "");
    lines.push("");
    lines.push(`## 商业模式与单位经济`);
    lines.push((co.model && co.model.text) || "");
    lines.push((co.model && co.model.unitEconomics) || "");
    lines.push("");
    lines.push(`## 规模与增速`);
    lines.push(`| 指标 | 内容 |`);
    lines.push(`| --- | --- |`);
    const pushNode = (name, node) => {
      const facts = nodeFacts(node);
      if (!facts.length) facts.push(node || { status: "未公开" });
      facts.forEach(f => {
        if (f.status === "未公开") lines.push(`| ${name} | 未公开。${(f.note || "").replace(/\|/g, "/")} |`);
        else lines.push(`| ${name} | ${f.value || ""} ${f.unit || ""}；${f.period || ""}；${asOfOf(f)}；${f.type || ""}；${f.sourceTitle || ""} ${f.sourceUrl || ""} |`);
      });
    };
    SCALE.forEach(k => pushNode(k, (co.scale || {})[k]));
    pushNode("增速及预测", co.growth);
    lines.push("");
    lines.push(`## 市场空间与代表用户`);
    lines.push((co.market && co.market.text) || "");
    pushNode("市场空间", co.market && co.market.tam);
    if (co.customers && co.customers.items) co.customers.items.forEach(it => lines.push(`- ${it.name}：${it.note || ""}`));
    else lines.push(co.customers && co.customers.status === "未公开" ? `代表用户：未公开。${co.customers.note || ""}` : "");
    lines.push("");
    lines.push(`## 产品与迭代`);
    (co.products && co.products.items || []).forEach(it => lines.push(`- ${it.name}：${it.note || ""}`));
    (co.iterations && co.iterations.items || []).forEach(it => lines.push(`- ${it.date} ${it.text}`));
    lines.push("");
    lines.push(`## 估值参考`);
    pushNode("估值", co.valuation);
    if (co.valuation && co.valuation.multiples) pushNode("倍数", co.valuation.multiples);
    lines.push("");
    lines.push(`## 主要风险`);
    (co.risks || []).forEach(r => lines.push(`- ${r.text}`));
    lines.push("");
    lines.push(`## 证伪信号`);
    (co.falsify || []).forEach(r => lines.push(`- ${r.text}`));
    lines.push("");
    lines.push(`## 跟踪与催化剂`);
    (co.watch || []).forEach(w => lines.push(`- ${w.kpi}：${w.why || ""}`));
    if (co.catalysts && co.catalysts.status === "未公开") lines.push(`- 催化剂：未公开。${co.catalysts.note || ""}`);
    lines.push("");
    lines.push(`## 相关节目与选题`);
    (co.episodes || []).forEach(e => lines.push(`- ${e.role} ${e.id} ${e.title}`));
    (co.topics || []).forEach(t => lines.push(`- 选题（AI草稿）：${t.text}`));
    lines.push("");
    return lines.join("\n");
  }

  function download(name, text) {
    const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
    ctx.toast("已导出 " + name);
  }

  function exportJson() {
    const payload = {
      app: "joyce-podcast-companies",
      exportedAt: new Date().toISOString(),
      disclaimer: (ctx.D.companies || {}).disclaimer || "",
      companies: companies(),
      overrides: store.overrides,
      added: store.added,
    };
    download("companies-export.json", JSON.stringify(payload, null, 1));
  }

  function onImport(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(String(reader.result || ""));
        if (data.overrides) store.overrides = data.overrides;
        if (data.added) store.added = data.added;
        if (!data.overrides && Array.isArray(data.companies)) {
          data.companies.forEach(c => {
            if (baseList().some(b => b.id === c.id)) store.overrides[c.id] = c;
            else store.added.push(c);
          });
        }
        saveStore();
        ctx.toast("已导入到本机");
        render();
      } catch {
        ctx.toast("这份 JSON 读不了");
      }
    };
    reader.readAsText(file);
  }

  function addCompany() {
    const name = ($("#coNewName").value || "").trim();
    if (!name) { $("#coNewName").focus(); return; }
    const id = "local-" + Date.now().toString(36);
    const scale = {};
    SCALE.forEach(k => { scale[k] = { status: "未公开", note: "手工新增，尚未填写。" }; });
    store.added.push({
      id, name, listing: "手工", ticker: "",
      derive: { role: "手工添加", how: "工作台里新增，不从节目自动挂。" },
      thesis: { judgment: "观察中", draft: true, label: "AI草稿", oneLiner: ($("#coNewLine").value || "").trim() },
      whyNow: { draft: true, text: "" },
      drivers: [], moat: { draft: true, text: "" }, model: { draft: true, text: "", unitEconomics: "" },
      business: { text: "" }, scale, growth: { status: "未公开", note: "" },
      market: { draft: true, text: "", tam: { status: "未公开", note: "" } },
      customers: { status: "未公开", note: "" },
      products: { items: [] }, iterations: { items: [] },
      valuation: { status: "未公开", note: "" },
      risks: [], falsify: [], watch: [], catalysts: { status: "未公开", note: "" }, topics: [],
      episodes: [], coverage: { undisclosedCount: 14, undisclosed: [], staleCount: 0, leaves: 14 },
    });
    saveStore();
    $("#coModal").classList.remove("on");
    open(id);
    ctx.toast("已加到本机");
  }

  function render() {
    const root = document.getElementById("coStage");
    if (!root || !ctx) return;
    const rows = companies();
    const bar = document.getElementById("coBar");
    if (bar) {
      bar.querySelectorAll("[data-cv]").forEach(btn => btn.classList.toggle("on", btn.dataset.cv === state.view && state.view !== "detail"));
    }
    if (state.view === "detail") renderDetail(root, byId(state.id));
    else if (state.view === "matrix") renderMatrix(root, rows);
    else if (state.view === "compare") renderCompare(root, rows);
    else renderOverview(root, rows);
  }

  function open(id) {
    state.view = "detail";
    state.id = id;
    if (location.hash !== "#companies") history.replaceState(null, "", "#companies");
    if (ctx.switchView) ctx.switchView("companies");
    render();
  }

  function mount(next) {
    ctx = next;
    loadStore();
    const bar = document.getElementById("coBar");
    if (bar && !bar.dataset.bound) {
      bar.dataset.bound = "1";
      bar.addEventListener("click", ev => {
        const btn = ev.target.closest("[data-cv]");
        if (!btn) return;
        state.view = btn.dataset.cv;
        state.id = "";
        render();
      });
      document.getElementById("coExport").onclick = exportJson;
      document.getElementById("coImport").onclick = () => document.getElementById("coFile").click();
      document.getElementById("coFile").onchange = ev => {
        const file = ev.target.files && ev.target.files[0];
        if (file) onImport(file);
        ev.target.value = "";
      };
      document.getElementById("coAdd").onclick = () => document.getElementById("coModal").classList.add("on");
      document.getElementById("coReset").onclick = () => {
        if (!confirm("清除这台浏览器里对企业卡的修改？仓库里的 companies.json 不会变。")) return;
        store = { overrides: {}, added: [] };
        saveStore();
        ctx.toast("已回到仓库里的底稿");
        render();
      };
      document.getElementById("coNewCancel").onclick = () => document.getElementById("coModal").classList.remove("on");
      document.getElementById("coNewOk").onclick = addCompany;
    }
    const note = document.getElementById("coDisclaimer");
    if (note) note.textContent = (ctx.D.companies && ctx.D.companies.disclaimer) || "";
  }

  window.WBCompanies = { mount, render, open };
})();
