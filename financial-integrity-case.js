/* 1785 retrospective case page (RETROSPECTIVE_CASE). Same-origin Flask proxy only; textContent / createElement only;
 * links only to the official regulator hosts. Nothing here is a current review or a pre-event prediction.
 */
(function () {
  "use strict";

  var OFFICIAL_HOSTS = ["mopsov.twse.com.tw", "mops.twse.com.tw", "doc.twse.com.tw", "www.twse.com.tw",
    "www.tpex.org.tw", "emops.twse.com.tw"];
  var STATUS_TEXT = {computed: "已計算", not_computable: "不可計算", source_unavailable: "來源不可用",
    insufficient_point_in_time_evidence: "截點前無可驗證資料"};
  var EVENT_STATUS = {
    verified_official_document: ["官方原文已驗證（E2）", "ok"],
    official_listing_only: ["僅官方清單（日期與標題，E1）", "listing"],
    needs_source_verification: ["待來源驗證（未進入計算）", "unverified"]
  };
  var EVENT_CLASS = {physical_asset_incident: "實體資產事件（黃金不法轉出）", financial_reporting_misstatement: "財報不實",
    restatement: "財報重編", market_action: "市場處置", disclosure: "公司說明"};
  var VARIABLE_TEXT = {GMI: "GMI", TATA: "TATA", ch_inv: "ΔInventory（ch_inv）", rsst_acc: "RSST Accruals", soft_assets: "Soft Assets"};
  var state = {data: null, policy: "latest_available", model: "all", variable: "GMI"};

  function el(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "text") { node.textContent = attrs[key] == null ? "" : String(attrs[key]); }
        else if (key === "className") { node.className = attrs[key]; }
        else { node.setAttribute(key, attrs[key]); }
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child == null) { continue; }
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }
  function badge(text, cls) { return el("span", {className: "badge " + (cls || ""), text: text}); }
  function clear(target) { target.className = ""; while (target.firstChild) { target.removeChild(target.firstChild); } }
  function setState(target, text, error) { target.className = "state" + (error ? " error" : ""); target.textContent = text; }
  function safeLink(url, label) {
    try {
      var parsed = new URL(String(url));
      if ((parsed.protocol === "https:" || parsed.protocol === "http:") && OFFICIAL_HOSTS.indexOf(parsed.hostname) >= 0) {
        return el("a", {href: parsed.href, target: "_blank", rel: "noopener noreferrer", text: label || "官方來源"});
      }
    } catch (e) { /* not a URL */ }
    return el("span", {className: "muted", text: "（無可公開的官方連結）"});
  }
  var SECTIONS = ["identityBody", "gridBody", "seriesBody", "strictBody", "crosswalkBody", "timelineBody"];

  function load() {
    SECTIONS.forEach(function (id) { setState(document.getElementById(id), "載入中…"); });
    clear(document.getElementById("cellDetail"));
    var url = "/api/integrity/research-cases/1785/summary?version_policy=" + encodeURIComponent(state.policy);
    fetch(url, {headers: {"Accept": "application/json"}}).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok || !payload.success) {
          var detail = payload && payload.detail;
          var error = new Error((detail && (detail.message || detail.error_code)) || payload.error || ("HTTP " + response.status));
          error.status = response.status;
          throw error;
        }
        return payload.data;
      });
    }).then(function (data) {
      state.data = data;
      if (data.status !== "available") { renderUnavailable(data); return; }
      render();
      document.getElementById("liveStatus").textContent = "案例資料已載入：" + state.policy;
    }).catch(function (error) {
      var map = {400: "參數不正確", 404: "此案例不在支援清單", 502: "後端服務暫時無法連線", 503: "研究資料暫時無法讀取"};
      SECTIONS.forEach(function (id) { setState(document.getElementById(id), (map[error.status] || "查詢失敗") + "：" + error.message, true); });
    });
  }

  function renderUnavailable(data) {
    var target = document.getElementById("identityBody");
    clear(target);
    target.appendChild(el("div", {className: "state error", text: "研究資料不可用（" + data.reason + "）：" + data.instructions}));
    SECTIONS.slice(1).forEach(function (id) { setState(document.getElementById(id), "資料不可用；不顯示任何分數，也不改用其他公司資料。"); });
  }

  function render() {
    renderIdentity(); renderGrid(); renderSeries(); renderStrict(); renderCrosswalk(); renderTimeline();
    var wanted = /^(beneish_1999_full8_v1|dechow_2011_model1_v1):(\d{4})$/.exec(state.pendingCell || "");
    if (wanted) {
      var cell = state.data.cells.filter(function (c) { return c.model_id === wanted[1] && c.fiscal_year === Number(wanted[2]); })[0];
      if (cell) { renderCell(cell); }
    }
  }

  function renderIdentity() {
    var d = state.data, target = document.getElementById("identityBody");
    clear(target);
    document.getElementById("caseBanner").textContent = d.banner + "（review_mode=" + d.review_mode + "，hindsight=true）";
    var id = d.dataset_identity, base = d.baseline_check, c = d.counts[d.version_policy];
    target.appendChild(el("div", {className: "grid2"},
      el("div", {className: "stat"}, el("span", {text: "本版本計算結果"}),
        el("strong", {text: c.computed + " 已計算／" + c.not_computable + " 不可計算（共 " + c.cells + " 格）"})),
      el("div", {className: "stat"}, el("span", {text: "與已驗收研究證據比對（兩個版本合計）"}),
        el("strong", null, badge(base.matches ? "一致：26／34、run id 相同" : "不一致：請檢查", base.matches ? "ok" : "unverified")))));
    target.appendChild(el("p", {className: "muted", text: "run_id " + id.run_id + "（已驗收 " + id.accepted_run_id + "）；輸入摘要 " +
      id.input_digest.slice(0, 16) + "…；方法版本 " + id.method_version + "；persisted=false。"}));
    target.appendChild(el("p", {className: "muted", text: d.separation}));
  }

  function cellClass(cell) {
    if (cell.status === "computed") { return "computed"; }
    return cell.missing_reasons.indexOf("cross_filing_overlap_mismatch") >= 0 ? "withdrawn" : "";
  }

  function renderGrid() {
    var d = state.data, target = document.getElementById("gridBody");
    clear(target);
    var years = [];
    for (var y = d.fiscal_years.start; y <= d.fiscal_years.end; y++) { years.push(y); }
    var models = Object.keys(d.models).filter(function (m) { return state.model === "all" || state.model === m; });
    var head = el("tr", null, el("th", {text: "模型"}));
    years.forEach(function (year) { head.appendChild(el("th", {text: "FY" + year})); });
    var body = el("tbody");
    models.forEach(function (model) {
      var tr = el("tr", null, el("th", {text: d.models[model]}));
      years.forEach(function (year) {
        var cell = d.cells.filter(function (c) { return c.model_id === model && c.fiscal_year === year; })[0];
        if (!cell) { tr.appendChild(el("td", {text: "—"})); return; }
        var button = el("button", {type: "button", className: "cell-btn " + cellClass(cell),
          text: cell.status === "computed" ? cell.score : (STATUS_TEXT[cell.status] || cell.status)});
        button.setAttribute("aria-label", d.models[model] + " FY" + year + " " + (STATUS_TEXT[cell.status] || cell.status));
        button.addEventListener("click", function () { renderCell(cell); });
        tr.appendChild(el("td", null, button));
      });
      body.appendChild(tr);
    });
    target.appendChild(el("div", {className: "table-wrap"}, el("table", null, el("thead", null, head), body)));
    target.appendChild(el("p", {className: "muted", text: "藍色＝已計算（顯示原始分數，非機率）；紅色＝跨申報重疊期不一致而撤回；其餘為不可計算。點選任一格查看元件、缺漏與官方來源。"}));
  }

  function renderCell(cell) {
    var target = document.getElementById("cellDetail");
    clear(target);
    target.appendChild(el("h3", {text: state.data.models[cell.model_id] + " FY" + cell.fiscal_year + "：" + (STATUS_TEXT[cell.status] || cell.status) +
      (cell.score ? "（分數 " + cell.score + "）" : "")}));
    if (cell.zero_evidence_used && cell.zero_evidence_used.length) {
      target.appendChild(el("p", {className: "state error", text: "此分數使用 verified_zero 零值證明（" + cell.zero_evidence_used.length + " 筆），該規則尚待方法負責人核准。"}));
    }
    var comps = el("tbody");
    cell.components.forEach(function (comp) {
      var sources = el("ul", {className: "plain"});
      comp.observations.forEach(function (o) {
        sources.appendChild(el("li", null, o.metric + "@" + o.relative_period + " " + (o.line_key || "") + " = " + (o.published_value || "") + " " +
          (o.published_unit || "") + (o.pdf_page ? "（第 " + o.pdf_page + " 頁）" : "") + " obs " + o.observation_id + " ", safeLink(o.source_url, "官方檔")));
      });
      if (comp.observations_total > comp.observations.length) {
        sources.appendChild(el("li", {className: "muted", text: "共 " + comp.observations_total + " 筆觀測值（此處列出 " + comp.observations.length + " 筆）"}));
      }
      comps.appendChild(el("tr", null, el("td", {text: comp.variable}), el("td", {text: STATUS_TEXT[comp.status] || comp.status}),
        el("td", {className: "num", text: comp.value == null ? "—" : comp.value}), el("td", {text: comp.reasons.join("、") || "—"}), el("td", null, sources)));
    });
    target.appendChild(el("div", {className: "table-wrap"}, el("table", null,
      el("thead", null, el("tr", null, el("th", {text: "元件"}), el("th", {text: "狀態"}), el("th", {text: "數值"}), el("th", {text: "原因"}), el("th", {text: "來源觀測值"}))), comps)));
    if (cell.missing_reasons.length) { target.appendChild(el("p", {className: "muted", text: "缺漏原因：" + cell.missing_reasons.join("、")})); }
    var filings = el("ul", {className: "plain"});
    cell.filing_versions.forEach(function (f) {
      filings.appendChild(el("li", null, "FY" + f.fiscal_year + " " + f.filing_version_type + " " + f.accounting_framework + "（" + f.filing_version_id +
        "；可得時間 " + (f.available_at || "未驗證") + "） ", safeLink(f.source_url, "官方申報")));
    });
    target.appendChild(el("h3", {text: "使用的申報版本"}));
    target.appendChild(filings.childNodes.length ? filings : el("p", {className: "muted", text: "無"}));
  }

  function renderSeries() {
    var d = state.data, target = document.getElementById("seriesBody");
    clear(target);
    var rows = d.series[state.variable] || [];
    var values = rows.filter(function (r) { return r.value != null; }).map(function (r) { return Math.abs(Number(r.value)); });
    var max = values.length ? Math.max.apply(null, values) || 1 : 1;
    var bars = el("div", {className: "bars"});
    rows.forEach(function (r) {
      var track = el("div", {className: "bar-track"}, el("div", {className: "bar-zero"}));
      if (r.value != null) {
        var v = Number(r.value), width = Math.min(50, Math.abs(v) / max * 50);
        var fill = el("div", {className: "bar-fill" + (v < 0 ? " neg" : "")});
        fill.style.width = width + "%";
        fill.style.left = v < 0 ? (50 - width) + "%" : "50%";
        track.appendChild(fill);
      }
      bars.appendChild(el("div", {className: "bar-row"}, el("span", {text: "FY" + r.fiscal_year}), track,
        el("span", {className: "num", text: r.value == null ? (STATUS_TEXT[r.status] || r.status) : r.value})));
    });
    target.appendChild(el("p", {className: "muted", text: VARIABLE_TEXT[state.variable] + "（" + state.policy + "）：長條以 0 為中心；不可計算的年度不畫長條。數值為事後計算，非門檻判定。"}));
    target.appendChild(bars);
    var turnover = el("ul", {className: "plain"});
    d.inventory_turnover_readiness.forEach(function (t) {
      turnover.appendChild(el("li", {text: "FY" + t.fiscal_year + "：" + (t.status === "inputs_available_same_filing" ? "同一申報版本具備 COGS_t、存貨 t／t−1" : "未就緒（" + t.missing.join("、") + "）")}));
    });
    target.appendChild(el("h3", {text: "存貨週轉率（readiness only，不計算數值）"}));
    target.appendChild(turnover);
  }

  function renderStrict() {
    var s = state.data.strict_pre_event, target = document.getElementById("strictBody");
    clear(target);
    target.appendChild(el("p", null, badge(STATUS_TEXT[s.status] || s.status, "unverified"), " 截點 " + s.cutoff_at + "（不含）"));
    target.appendChild(el("p", {text: s.conclusion}));
    target.appendChild(el("p", {className: "muted", text: s.note || ""}));
  }

  function renderCrosswalk() {
    var target = document.getElementById("crosswalkBody");
    clear(target);
    var body = el("tbody");
    state.data.crosswalk.forEach(function (row) {
      body.appendChild(el("tr", null, el("td", {text: row.feature}), el("td", {text: row.method}),
        el("td", {text: row.case_question + "（簡報第 " + row.slide_page + " 頁）"}),
        el("td", null, badge({implemented: "已實作（引擎元件）", readiness_only: "僅就緒度", not_available_in_frozen_inputs: "凍結輸入無此科目"}[row.implementation] || row.implementation,
          row.implementation === "implemented" ? "ok" : "na")),
        el("td", {text: row.evidence}), el("td", {text: row.limitations.join("；")})));
    });
    target.appendChild(el("div", {className: "table-wrap"}, el("table", null, el("thead", null, el("tr", null,
      el("th", {text: "指標"}), el("th", {text: "方法"}), el("th", {text: "案例問題"}), el("th", {text: "實作狀態"}),
      el("th", {text: "證據"}), el("th", {text: "限制"}))), body)));
  }

  function renderTimeline() {
    var d = state.data, target = document.getElementById("timelineBody");
    clear(target);
    var meta = d.event_registry;
    target.appendChild(el("p", {className: "muted", text: "候選事件來源：" + meta.source_document.title + "（" + meta.source_document.owner + "；研究參考，不是已驗證來源）。" + meta.verification_rule}));
    target.appendChild(el("p", {className: "state error", text: meta.incident_distinction}));
    var list = el("div", {className: "timeline"});
    d.events.forEach(function (e) {
      var status = EVENT_STATUS[e.verification_status] || [e.verification_status, "na"];
      var item = el("div", {className: "tl-item"},
        el("b", {text: e.date + "　" + e.title}),
        el("div", null, badge(EVENT_CLASS[e.event_class] || e.event_class, e.event_class === "physical_asset_incident" ? "physical" : ""), " ",
          badge(status[0], status[1]), " ", el("span", {className: "muted", text: "簡報第 " + e.slide_pages.join("、") + " 頁"})),
        el("p", {className: "muted", text: e.verification_scope}));
      if (e.slide_claims.length) { item.appendChild(el("p", {className: "muted", text: "簡報敘述（未逐項驗證）：" + e.slide_claims.join("；")})); }
      var records = el("ul", {className: "plain"});
      e.verifying_records.concat(e.related_records).forEach(function (r) {
        records.appendChild(el("li", null, r.evidence_tier + "｜" + r.publication_at + "｜" + r.title + " ", safeLink(r.source_url, "官方來源")));
      });
      if (records.childNodes.length) { item.appendChild(records); }
      list.appendChild(item);
    });
    target.appendChild(list);
    var refs = el("ul", {className: "plain"});
    meta.slide_references_unverified.forEach(function (r) {
      refs.appendChild(el("li", {text: r.publisher + "（" + r.date + "）：" + r.url_text + "（簡報第 " + r.slide_page + " 頁所列；本系統未擷取、未驗證）"}));
    });
    target.appendChild(el("h3", {text: "研究簡報所列參考（未驗證，僅文字）"}));
    target.appendChild(refs);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var params = new URLSearchParams(window.location.search);
    var policy = params.get("version_policy");
    if (policy === "original_only" || policy === "latest_available") { state.policy = policy; }
    var model = params.get("model");
    if (model === "beneish_1999_full8_v1" || model === "dechow_2011_model1_v1") { state.model = model; }
    var variable = params.get("variable");
    if (VARIABLE_TEXT[variable]) { state.variable = variable; }
    document.getElementById("policySelect").value = state.policy;
    document.getElementById("modelSelect").value = state.model;
    document.getElementById("variableSelect").value = state.variable;
    document.getElementById("policySelect").addEventListener("change", function (e) { state.policy = e.target.value; load(); });
    document.getElementById("modelSelect").addEventListener("change", function (e) { state.model = e.target.value; if (state.data && state.data.status === "available") { renderGrid(); } });
    document.getElementById("variableSelect").addEventListener("change", function (e) { state.variable = e.target.value; if (state.data && state.data.status === "available") { renderSeries(); } });
    state.pendingCell = params.get("cell");
    load();
  });
})();
