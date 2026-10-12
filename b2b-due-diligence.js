/* Standalone B2B page. No localStorage, sessionStorage, eval or innerHTML. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const form = $("dossierForm");
  const submit = $("submit");
  const status = $("status");

  function write(parent, tag, label, cls) {
    const node = document.createElement(tag);
    node.textContent = label == null ? "—" : String(label);
    if (cls) node.className = cls;
    parent.appendChild(node);
    return node;
  }
  function clear(parent) { parent.replaceChildren(); }
  function line(list, value) { return write(list, "li", value); }
  function statistic(name, value) {
    const item = document.createElement("div");
    item.className = "stat";
    write(item, "span", name);
    write(item, "b", value);
    $("summary").appendChild(item);
  }
  async function loadCompanies() {
    try {
      const response = await fetch("/api/integrity/companies", {credentials: "same-origin"});
      const json = await response.json();
      if (!response.ok || json.success !== true || !Array.isArray(json.data.companies)) {
        throw new Error("無法取得公司清單。");
      }
      const select = $("ticker");
      clear(select);
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "請選擇公司";
      select.appendChild(placeholder);
      json.data.companies.forEach(function (company) {
        if (!/^[0-9]{4,6}$/.test(company.ticker)) return;
        const option = document.createElement("option");
        option.value = company.ticker;
        option.textContent = company.ticker + " · " + company.name;
        select.appendChild(option);
      });
      status.textContent = "選取公司與關係後，即可產生唯讀查核清單。";
    } catch (_error) {
      $("ticker").replaceChildren();
      status.textContent = "公司資料服務不可用，請稍後再試。";
      status.className = "error";
    }
  }
  function render(d) {
    const summary = $("summary"), requests = $("requests"), missing = $("missing"), limits = $("limits");
    [summary, requests, missing, limits].forEach(clear);
    statistic("公司", d.company + "（" + d.ticker + "）");
    statistic("合作身分", d.relationship.label + " · 未驗證");
    statistic("查核優先順序", d.investigation_queue.queue || "資料不足");
    statistic("最新財報年度", d.latest_fiscal_year ? d.latest_fiscal_year + "FY" : "未取得");
    statistic("證據群組數", d.cross_evidence.distinct_evidence_family_count);
    statistic("獨立第三方證據群組", d.cross_evidence.independent_third_party_family_count);
    if (!d.document_requests.length) {
      line(requests, "目前沒有可列出的具體補件項目。這不代表沒有風險。");
    } else {
      d.document_requests.forEach(function (r) {
        line(requests, (r.question || "建議補件") + " — " + r.requested_documents.join("、"));
      });
    }
    if (!d.missing_data.length) {
      line(missing, "這次查核沒有回傳缺漏清單，但仍須參考各項方法限制。");
    } else {
      d.missing_data.forEach(function (m) {
        line(missing, (m.item || m.section || "未分類") + "：" + (m.reasons || []).join("、"));
      });
    }
    if (d.stale_finding_ids.length) line(missing, "最新年度無法計算：" + d.stale_finding_ids.join("、"));
    (d.disclaimers || []).concat(d.cross_evidence.limitations || []).forEach(function (v) { line(limits, v); });
    $("results").classList.remove("hidden");
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const ticker = $("ticker").value, relation = $("relation").value;
    if (!/^[0-9]{4,6}$/.test(ticker)) return;
    submit.disabled = true;
    status.textContent = "正在取得唯讀查核結果…";
    status.className = "muted";
    $("results").classList.add("hidden");
    try {
      const response = await fetch("/api/b2b/dossiers/preview", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ticker: ticker, relationship_type: relation, persist: false})
      });
      const json = await response.json();
      if (!response.ok || json.success !== true || !json.data) {
        throw new Error((json && json.error) || "查核服務暫時無法使用。");
      }
      render(json.data);
      status.textContent = "查核完成（本次結果不會被儲存）。";
    } catch (error) {
      status.textContent = "無法完成查核：" + error.message;
      status.className = "error";
    } finally {
      submit.disabled = false;
    }
  });
  loadCompanies();
}());
