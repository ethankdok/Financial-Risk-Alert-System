/* Independent F4 evidence viewer. All external text is rendered as text nodes. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const allowedHosts = new Set(["mops.twse.com.tw", "mopsov.twse.com.tw",
    "www.twse.com.tw", "www.tpex.org.tw", "doc.twse.com.tw", "emops.twse.com.tw"]);
  function text(parent, tag, content) {
    const el = document.createElement(tag);
    el.textContent = content == null ? "—" : String(content);
    parent.appendChild(el);
    return el;
  }
  function line(parent, str) { return text(parent, "li", str); }
  function safeLink(parent, raw) {
    if (typeof raw !== "string") return;
    try {
      const u = new URL(raw);
      if (u.protocol !== "https:" || !allowedHosts.has(u.hostname) ||
          u.username || u.password || (u.port && u.port !== "443")) return;
      const a = text(parent, "a", "查看官方來源");
      a.href = raw; a.target = "_blank"; a.rel = "noopener noreferrer";
    } catch (_ignore) {}
  }
  async function companies() {
    try {
      const response = await fetch("/api/integrity/companies", {credentials: "same-origin"});
      const json = await response.json();
      if (!response.ok || json.success !== true || !Array.isArray(json.data.companies)) {
        throw new Error("cannot load company list");
      }
      const input = $("ticker"); input.replaceChildren();
      const placeholder = text(input, "option", "請選擇公司"); placeholder.value = "";
      json.data.companies.forEach(item => {
        if (!/^[0-9]{4,6}$/.test(item.ticker)) return;
        const opt = text(input, "option", item.ticker + " · " + item.name);
        opt.value = item.ticker;
      });
      $("status").textContent = "選擇公司後可查看完整的 F4 資料缺口。";
    } catch (_e) {
      $("status").textContent = "公司名錄無法載入，請確認服務。";
      $("status").className = "error";
    }
  }
  function render(body) {
    const result = (body.financial_findings || []).find(f => String(f.check_id).startsWith("F4"));
    const info = $("finding"), sources = $("sources"), limits = $("limits");
    [info, sources, limits].forEach(x => x.replaceChildren());
    if (!result) {
      text(info, "p", "沒有取得 F4 查核項目。");
      $("results").hidden = false;
      return;
    }
    text(info, "p", "公司：" + body.company + "（" + body.ticker + "）");
    text(info, "p", "狀態：" + result.status + "；期間：" + (result.period || "未取得"));
    text(info, "p", "方法版本：" + result.method_version + "；未校準、無舞弊分數。");
    text(info, "p", "公式：" + (result.formula || "無"));
    const vals = document.createElement("ul");
    Object.keys(result.computed || {}).forEach(key => {
      const value = result.computed[key];
      if (value !== null && typeof value !== "object") line(vals, key + "：" + value);
    });
    if (!vals.children.length) line(vals, "目前沒有可計算的成長率或成長差距。");
    info.appendChild(vals);

    const byId = new Map((body.evidence_records || []).map(rec => [rec.evidence_id, rec]));
    (result.evidence_ids || []).forEach(id => {
      const rec = byId.get(id);
      if (!rec) return;
      const section = document.createElement("div"); section.className = "item";
      text(section, "strong", rec.fiscal_period + " " + rec.concept + "：" + (rec.value_twd || "缺值") + " TWD");
      text(section, "p", "申報版本：" + (rec.filing_version || "未知"));
      text(section, "p", "原始文件 SHA-256：" + (rec.source_sha256 || "未驗證"));
      safeLink(section, rec.source_url);
      sources.appendChild(section);
    });
    const nfm = (result.inputs || {}).nfm_sources || [];
    if (Array.isArray(nfm)) {
      nfm.forEach(entry => {
        const section = document.createElement("div"); section.className = "item";
        text(section, "strong", entry.year + " 年非財務文件，單位：" + entry.unit);
        text(section, "p", "版本：" + (entry.filing_version_id || "未知"));
        text(section, "p", "SHA-256：" + (entry.source_sha256 || "未驗證") +
          "；公開時間：" + (entry.published_at || "未知"));
        safeLink(section, entry.source_url);
        sources.appendChild(section);
      });
    }
    if (!sources.children.length) text(sources, "p", "尚無可用的核准原始文件證據。");
    (result.reasons || []).forEach(reason => line(limits, "不可計算／資料缺口：" + reason));
    (result.limitations || []).forEach(item => line(limits, item));
    (body.disclaimers || []).forEach(item => line(limits, item));
    $("results").hidden = false;
  }
  $("run").addEventListener("click", async () => {
    const ticker = $("ticker").value;
    if (!/^[0-9]{4,6}$/.test(ticker)) return;
    const button = $("run"); button.disabled = true;
    $("results").hidden = true;
    $("status").textContent = "正在執行唯讀來源查核…"; $("status").className = "note";
    try {
      const response = await fetch("/api/integrity/assessments/preview", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ticker, sections: ["financial_checks"], persist: false})
      });
      const json = await response.json();
      if (!response.ok || json.success !== true || !json.data) throw new Error("API 目前不可用");
      render(json.data);
      $("status").textContent = "已完成來源檢視，未寫入任何查核資料。";
    } catch (_e) {
      $("status").textContent = "無法完成查核，請確認後端或來源發布檔設定。";
      $("status").className = "error";
    } finally {
      button.disabled = false;
    }
  });
  companies();
}());