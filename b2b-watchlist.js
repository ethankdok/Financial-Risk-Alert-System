/* Independent multi-company preview. Safe DOM APIs only; no browser storage. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const companies = [];
  const relations = [
    ["potential_counterparty", "潛在交易對手"],
    ["supplier", "自述供應商"],
    ["customer", "自述客戶"],
    ["partner", "自述合作夥伴"]
  ];
  function text(node, tag, content) {
    const el = document.createElement(tag);
    el.textContent = content == null ? "—" : String(content);
    node.appendChild(el);
    return el;
  }
  function select(options, name) {
    const element = document.createElement("select");
    element.setAttribute("aria-label", name);
    options.forEach(pair => {
      const o = document.createElement("option");
      o.value = pair[0]; o.textContent = pair[1];
      element.appendChild(o);
    });
    return element;
  }
  function addEntry() {
    if ($("entries").children.length >= 5) return;
    const row = document.createElement("div");
    row.className = "entry";
    const tickers = select([["", "請選擇公司"]].concat(companies.map(c => [c.ticker, c.ticker + " · " + c.name])), "公司");
    const type = select(relations, "合作關係");
    const remove = document.createElement("button");
    remove.type = "button"; remove.className = "ghost"; remove.textContent = "移除";
    remove.addEventListener("click", () => {
      row.remove();
      if (!$("entries").children.length) addEntry();
      $("add").disabled = $("entries").children.length >= 5;
    });
    row.append(tickers, type, remove);
    $("entries").appendChild(row);
    $("add").disabled = $("entries").children.length >= 5;
  }
  async function load() {
    try {
      const response = await fetch("/api/integrity/companies", {credentials: "same-origin"});
      const payload = await response.json();
      if (!response.ok || payload.success !== true || !Array.isArray(payload.data.companies)) {
        throw new Error("公司清單載入失敗");
      }
      payload.data.companies.forEach(c => {
        if (/^[0-9]{4,6}$/.test(c.ticker)) companies.push(c);
      });
      addEntry();
      $("status").textContent = "可加入最多五家公司，系統不會儲存這份清單。";
    } catch (_error) {
      $("status").textContent = "公司名錄目前無法取得，請確認後端服務。";
      $("status").className = "error";
    }
  }
  function collect() {
    const rows = Array.from($("entries").children);
    const picked = rows.map(row => ({
      ticker: row.children[0].value,
      relationship_type: row.children[1].value
    }));
    if (picked.some(x => !/^[0-9]{4,6}$/.test(x.ticker))) throw new Error("請選擇每一家公司的代號");
    if (new Set(picked.map(x => x.ticker)).size !== picked.length) throw new Error("同一家公司不可重複");
    return picked;
  }
  function render(data) {
    const target = $("summary");
    target.replaceChildren();
    (data.dossiers || []).forEach((d, idx) => {
      const card = document.createElement("article");
      card.className = "report";
      text(card, "h3", (idx + 1) + ". " + d.company + "（" + d.ticker + "）");
      text(card, "p", d.relationship.label + " · 關係未驗證");
      text(card, "p", "查核優先順序：" + d.investigation_queue.queue + "（不是風險等級）");
      text(card, "p", "最新財報年度：" + (d.latest_fiscal_year || "缺少") +
        "；來源不足：" + d.missing_data.length + " 項");
      const list = document.createElement("ul");
      if (!d.document_requests.length) {
        text(list, "li", "沒有可列出的補件項目，不代表低風險。");
      }
      d.document_requests.forEach(entry => {
        text(list, "li", (entry.question || "建議查核") + "：" +
          (entry.requested_documents || []).join("、"));
      });
      card.appendChild(list);
      target.appendChild(card);
    });
    $("results").hidden = false;
  }
  $("add").addEventListener("click", addEntry);
  $("preview").addEventListener("click", async () => {
    let items;
    try {
      items = collect();
    } catch (e) {
      $("status").textContent = e.message;
      $("status").className = "error";
      return;
    }
    const button = $("preview");
    button.disabled = true;
    $("results").hidden = true;
    $("status").textContent = "正在整理唯讀查核結果…";
    $("status").className = "muted";
    try {
      const response = await fetch("/api/b2b/watchlists/preview", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({items, persist: false})
      });
      const payload = await response.json();
      if (!response.ok || payload.success !== true || !payload.data) {
        throw new Error(payload.error || "查核失敗");
      }
      render(payload.data);
      $("status").textContent = "已完成 " + payload.data.count + " 家公司查核，清單未儲存。";
    } catch (error) {
      $("status").textContent = "查核未完成：" + error.message;
      $("status").className = "error";
    } finally {
      button.disabled = false;
    }
  });
  load();
}());