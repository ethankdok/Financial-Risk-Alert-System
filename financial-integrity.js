/* Financial Integrity Workbench (Phase 1) page.
 * Talks only to same-origin Flask proxy routes (/api/integrity/...). Every dynamic value is written with
 * textContent / createElement; links are emitted only for https/http URLs on the official regulator hosts.
 */
(function () {
  "use strict";

  var OFFICIAL_HOSTS = ["mopsov.twse.com.tw", "mops.twse.com.tw", "doc.twse.com.tw", "www.twse.com.tw",
    "www.tpex.org.tw", "emops.twse.com.tw"];
  var STATUS_TEXT = {
    descriptive_divergence: "描述性背離（超過未校準篩檢門檻）",
    within_screening_heuristic: "未超過篩檢門檻（不代表低風險）",
    descriptive_gap: "描述性差異",
    supported: "與申報財報一致（同一發行人）",
    conflicting: "與申報財報不一致（不等於造假）",
    insufficient_evidence: "證據不足",
    inconclusive: "無法判定",
    not_computable: "不可計算",
    not_comparable: "不可比較",
    unavailable: "資料不可用"
  };
  var QUEUE_TEXT = {
    requires_verification: "需要補件確認",
    monitor: "持續監測",
    insufficient_evidence: "資料不足",
    no_item_triggered: "未觸發篩檢項目（不代表低風險）"
  };
  var QUEUE_CLASS = {requires_verification: "verify", monitor: "monitor", insufficient_evidence: "na", no_item_triggered: "ok"};
  var METRIC_TEXT = {revenue: "營業收入", accounts_receivable: "應收帳款淨額", net_income: "本期淨利",
    operating_cash_flow: "營業活動現金流量", total_assets: "資產總計"};
  var METHODS = [
    ["Beneish (1999) The Detection of Earnings Manipulation", "10.2469/faj.v55.n5.2296", "already implemented（歷史研究案例）／正式公司：readiness only",
      "8 變數 M-Score；本頁只呈現可計算性與缺漏清單，不以 1785 研究分數替代。"],
    ["Dechow, Ge, Larson & Sloan (2011) Predicting Material Accounting Misstatements", "10.1111/j.1911-3846.2010.01041.x",
      "already implemented（歷史研究案例）／正式公司：readiness only", "Table 7 Model 1 F-Score（不是 Piotroski F-score），無台灣驗證門檻。"],
    ["Brazel, Jones & Zimbelman (2009) Using Nonfinancial Measures to Assess Fraud Risk", "10.1111/j.1475-679X.2009.00349.x",
      "design inspiration（F4 readiness only）", "需同口徑兩年非財務指標；目前無經驗證資料，F1/F2 不是 Brazel 複製。"],
    ["Larcker & Zakolyukina (2012) Detecting Deceptive Discussions in Conference Calls", "10.1111/j.1475-679X.2012.00450.x",
      "future validation", "法說會逐字稿語言模型；本頁 JSD 只是簡報文字分布差異，不是該論文的欺騙語言分類器。"],
    ["Loughran & McDonald (2011) When Is a Liability Not a Liability?", "10.1111/j.1540-6261.2010.01625.x",
      "design inspiration", "財務領域文字處理的理由；沿用團隊既有 JSD tokenizer，未移植英文詞典到中文。"],
    ["Bao, Ke, Li, Yu & Zhang (2020) Detecting Accounting Fraud … Machine Learning Approach", "10.1111/1475-679X.12292",
      "future validation", "Phase 2+ 評估設計（需 PIT 標籤與對照組；含 2022 勘誤）；目前沒有訓練好的分類器。"],
    ["Barrot & Sauvagnat (2016) Input Specificity and the Propagation of Idiosyncratic Shocks", "10.1093/qje/qjw018",
      "design inspiration", "說明 B2B 使用者為何關心交易對手財務狀況；不推估停供或供應鏈中斷機率。"]
  ];

  var VIEWS = ["overview", "models", "cross", "b2b"];
  var state = {companies: [], result: null, expand: false};

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

  function safeLink(url, label) {
    try {
      var parsed = new URL(String(url));
      if ((parsed.protocol === "https:" || parsed.protocol === "http:") && OFFICIAL_HOSTS.indexOf(parsed.hostname) >= 0) {
        return el("a", {href: parsed.href, target: "_blank", rel: "noopener noreferrer", text: label || "官方來源"});
      }
    } catch (e) { /* not a URL */ }
    return el("span", {className: "muted", text: "（無可公開的官方連結）"});
  }

  function badge(text, cls) { return el("span", {className: "badge " + (cls || ""), text: text}); }
  function statusBadge(status) {
    var cls = {descriptive_divergence: "verify", conflicting: "conflict", supported: "ok", descriptive_gap: "monitor"}[status] || "na";
    return badge(STATUS_TEXT[status] || status, cls);
  }
  function money(value) {
    if (value == null) { return "—"; }
    var n = Number(value);
    if (!isFinite(n)) { return String(value); }
    if (Math.abs(n) < 1e6) { return n.toLocaleString("zh-TW") + " 元"; }
    return (n / 1e8).toLocaleString("zh-TW", {maximumFractionDigits: 2}) + " 億元";
  }
  function pct(value) { return value == null ? "—" : (Number(value) * 100).toFixed(2) + "%"; }
  function setState(target, text, error) {
    target.className = "state" + (error ? " error" : "");
    target.textContent = text;
  }
  function clear(target) { target.className = ""; while (target.firstChild) { target.removeChild(target.firstChild); } }
  function announce(text) { document.getElementById("liveStatus").textContent = text; }

  function request(method, url, body) {
    var options = {method: method, headers: {"Accept": "application/json"}};
    if (body) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok || !payload.success) {
          var detail = payload && payload.detail;
          var message = (detail && (detail.message || detail.error_code)) || payload.error || ("HTTP " + response.status);
          var error = new Error(message);
          error.status = response.status;
          throw error;
        }
        return payload.data;
      });
    });
  }

  function errorText(error) {
    var map = {400: "輸入格式不正確", 403: "沒有權限", 404: "此公司不在支援清單", 409: "此分析模式尚未支援",
      422: "請求內容不符合規格", 502: "後端服務暫時無法連線", 503: "資料來源暫時無法讀取"};
    return (map[error.status] || "查詢失敗") + "：" + error.message;
  }

  // ---------------------------------------------------------------------------------------- tabs
  function selectTab(view) {
    Array.prototype.forEach.call(document.querySelectorAll(".tabs button"), function (button) {
      var active = button.getAttribute("data-view") === view;
      button.setAttribute("aria-selected", active ? "true" : "false");
      button.tabIndex = active ? 0 : -1;
      document.getElementById("view-" + button.getAttribute("data-view")).hidden = !active;
    });
  }

  // ------------------------------------------------------------------------------------- summary
  function renderSummary(r) {
    var target = document.getElementById("summaryBody");
    clear(target);
    var p = r.investigation_priority;
    var anomalies = r.financial_findings.concat(r.claim_findings, r.narrative_findings).filter(function (f) {
      return f.review_queue === "requires_verification" || f.review_queue === "monitor";
    });
    var insufficient = r.missing_data.length;
    var grid = el("div", {className: "summary"},
      el("div", {className: "stat"}, el("span", {text: "公司"}), el("strong", {text: r.company + "（" + r.ticker + "）"}),
        el("small", {text: r.subindustry + "；資料年度 " + r.source_coverage.annual_years.join("、")})),
      el("div", {className: "stat"}, el("span", {text: "查核優先順序（非風險等級）"}),
        el("strong", null, badge(QUEUE_TEXT[p.queue] || p.queue, QUEUE_CLASS[p.queue])),
        el("small", {text: "規則 " + p.rule_version + "；獨立第三方佐證 " + p.independent_third_party_corroboration_count + " 件"})),
      el("div", {className: "stat"}, el("span", {text: "已發現的篩檢項目"}), el("strong", {text: anomalies.length + " 項"}),
        el("small", {text: anomalies.map(function (f) { return f.check_id; }).join("、") || "無"})),
      el("div", {className: "stat"}, el("span", {text: "來源不足／不可計算"}), el("strong", {text: insufficient + " 項"}),
        el("small", {text: "最近擷取：" + (r.data_latest_ingested_at || "未知") + "；發布時間未記錄；最新年度不可計算的檢查 " +
          ((r.freshness && r.freshness.stale_findings) || []).length + " 項"}))
    );
    target.appendChild(grid);
    target.appendChild(el("p", {className: "muted", text: "分析模式 " + r.review_mode + "；" + r.hindsight_note + " 產生時間 " + r.generated_at + "；不儲存（persist=false）。"}));
  }

  // ------------------------------------------------------------------------------------ overview
  function renderOverview(r) {
    var target = document.getElementById("overviewBody");
    clear(target);
    target.appendChild(el("h2", {text: "財務概況（MOPS Inline XBRL 年度財報，合併報表）"}));
    var years = {}, metrics = Object.keys(METRIC_TEXT);
    r.financial_overview.rows.forEach(function (row) {
      years[row.fiscal_period] = years[row.fiscal_period] || {};
      years[row.fiscal_period][row.metric] = row;
    });
    var periods = Object.keys(years).sort();
    if (!periods.length) {
      target.appendChild(el("div", {className: "state", text: "此公司尚無已歸檔的年度財報事實；不產生任何篩檢結果。"}));
    } else {
      var head = el("tr", null, el("th", {text: "科目"}));
      periods.forEach(function (period) { head.appendChild(el("th", {className: "num", text: period})); });
      var body = el("tbody");
      metrics.forEach(function (metric) {
        var tr = el("tr", null, el("td", {text: METRIC_TEXT[metric]}));
        periods.forEach(function (period) {
          var row = years[period][metric];
          tr.appendChild(el("td", {className: "num", text: row ? money(row.value_twd) : "—"}));
        });
        body.appendChild(tr);
      });
      target.appendChild(el("div", {className: "table-wrap"}, el("table", null, el("thead", null, head), body)));
      var sourceList = el("ul", {className: "plain"});
      periods.forEach(function (period) {
        var row = years[period].revenue || years[period][Object.keys(years[period])[0]];
        sourceList.appendChild(el("li", null, period + "：" + (row.filing_version || "未記錄版本") + " ", safeLink(row.source_url, "MOPS 財報")));
      });
      target.appendChild(el("h3", {text: "來源"}));
      target.appendChild(sourceList);
    }
    var sources = r.financial_overview.official_sources || {};
    target.appendChild(el("h3", {text: "既有規則訊號（沿用正式規則引擎，未重新計算）"}));
    if (sources.status !== "available") {
      target.appendChild(el("div", {className: "state", text: "官方證據摘要不可用：" + (sources.reason || "未知原因")}));
    } else {
      target.appendChild(el("p", {className: "muted", text: "規則版本 " + (sources.rule_version || "未記錄") + "；觸發 " + sources.rule_signals_triggered + " / " + sources.rule_signals.length + " 條；live fetch：關閉。"}));
      var list = el("ul", {className: "plain"});
      sources.rule_signals.forEach(function (rule) {
        list.appendChild(el("li", {text: rule.rule_id + "：" + (rule.name || "") + (rule.triggered ? "（已觸發）" : "（未觸發）")}));
      });
      target.appendChild(list);
      if (sources.material_events.length) {
        target.appendChild(el("h3", {text: "已歸檔重大訊息"}));
        var events = el("ul", {className: "plain"});
        sources.material_events.forEach(function (e) {
          events.appendChild(el("li", null, (e.event_date || "日期未記錄") + " " + (e.title || "") + " ", safeLink(e.source_url, "MOPS")));
        });
        target.appendChild(events);
      }
    }
    target.appendChild(el("h3", {text: "財務一致性篩檢（F1／F2／F4）"}));
    r.financial_findings.forEach(function (finding) { target.appendChild(renderFinding(finding, r)); });
  }

  function recordIndex(r) {
    var index = {};
    r.evidence_records.forEach(function (rec) { index[rec.evidence_id] = rec; });
    return index;
  }

  function renderFinding(f, r) {
    var box = el("article", {className: "finding"});
    var header = el("header", null, el("strong", {text: f.title}), statusBadge(f.status));
    if (f.review_queue) { header.appendChild(badge(QUEUE_TEXT[f.review_queue] || f.review_queue, QUEUE_CLASS[f.review_queue])); }
    if (f.implementation_tier !== "implemented") { header.appendChild(badge(f.implementation_tier === "readiness_only" ? "僅就緒度檢查" : "未來研究", "na")); }
    box.appendChild(header);
    if (f.period) { box.appendChild(el("p", {className: "muted", text: "期間 " + f.period + "；方法 " + f.method_version})); }
    if (f.freshness_status === "latest_period_not_computable") {
      box.appendChild(el("p", {className: "state error", text: "最新年度 " + f.period + " 無法計算：本項不產生目前的查核結論。"}));
      if (f.last_computable) {
        box.appendChild(el("p", {className: "muted", text: "歷史觀察（非目前結論）：" + f.last_computable.period + " " +
          (STATUS_TEXT[f.last_computable.status] || f.last_computable.status)}));
      }
    }
    if (f.reasons.length) { box.appendChild(el("p", {className: "muted", text: "原因：" + f.reasons.join("、")})); }
    var details = el("details", null, el("summary", {text: "展開：原始數字 → 公式 → 差異 → 來源 → 限制 → 應確認文件"}));
    if (state.expand) { details.setAttribute("open", ""); }
    var steps = el("div", {className: "steps"});
    var index = recordIndex(r);
    var inputs = el("ul", {className: "plain"});
    Object.keys(f.inputs || {}).forEach(function (key) {
      var value = f.inputs[key];
      if (value && typeof value === "object") {
        inputs.appendChild(el("li", {text: key + "：" + money(value.value_twd) + "（" + value.fiscal_period + "，原始 " + value.value + " " + value.unit + "，" + value.scope + "）"}));
      } else if (value != null) {
        inputs.appendChild(el("li", {text: key + "：" + value}));
      }
    });
    steps.appendChild(el("div", {className: "step"}, el("b", {text: "1. 原始數字"}), inputs.childNodes.length ? inputs : el("span", {className: "muted", text: "無（資料不足）"})));
    steps.appendChild(el("div", {className: "step"}, el("b", {text: "2. 公式"}), el("span", {className: "mono", text: f.formula || "—"})));
    var computed = el("ul", {className: "plain"});
    Object.keys(f.computed || {}).forEach(function (key) {
      var value = f.computed[key];
      if (value == null || typeof value === "object") { return; }
      computed.appendChild(el("li", {text: key + " = " + value}));
    });
    if (f.heuristic) {
      computed.appendChild(el("li", {text: "門檻：" + (f.heuristic.threshold != null ? f.heuristic.threshold : "無") + "（" + f.heuristic.version + "，未校準）" + (f.heuristic.threshold_source ? "，來源 " + f.heuristic.threshold_source : "")}));
    }
    if (f.computed && f.computed.sensitivity) {
      var s = f.computed.sensitivity;
      computed.appendChild(el("li", {text: "敏感度（gap > 門檻？）：" + Object.keys(s).map(function (k) { return k + "→" + (s[k] ? "是" : "否"); }).join("，")}));
    }
    steps.appendChild(el("div", {className: "step"}, el("b", {text: "3. 差異"}), computed.childNodes.length ? computed : el("span", {className: "muted", text: "不可計算"})));
    var sources = el("ul", {className: "plain"});
    f.evidence_ids.forEach(function (id) {
      var rec = index[id];
      if (!rec) { return; }
      var text = rec.fiscal_period + " " + rec.concept + "：" + (rec.source_concept || "") + "；版本 " + (rec.filing_version || "未記錄") +
        "；SHA-256 " + (rec.source_sha256 || "未記錄（缺 " + rec.missing_fields.join("、") + "）") +
        (rec.locator && rec.locator.page ? "；第 " + rec.locator.page + " 頁" : "") + "；獨立性 " + rec.independence + " ";
      sources.appendChild(el("li", null, text, safeLink(rec.source_url, "來源")));
    });
    steps.appendChild(el("div", {className: "step"}, el("b", {text: "4. 來源／SHA／頁碼"}), sources.childNodes.length ? sources : el("span", {className: "muted", text: "無可用來源"})));
    var limits = el("ul", {className: "plain"});
    f.limitations.concat(f.legitimate_explanations.map(function (x) { return "可能的正常原因：" + x; })).forEach(function (x) { limits.appendChild(el("li", {text: x})); });
    if (f.not_independent_of.length) { limits.appendChild(el("li", {text: "與下列模型變數共用底層數字（非獨立佐證）：" + f.not_independent_of.join("、")})); }
    steps.appendChild(el("div", {className: "step"}, el("b", {text: "5. 方法限制"}), limits));
    var docs = el("ul", {className: "plain"});
    r.next_checks.filter(function (c) { return c.triggered_by === f.finding_id; }).forEach(function (c) {
      docs.appendChild(el("li", {text: c.question_for_counterparty + "（" + c.documents_to_request.join("、") + "）"}));
    });
    steps.appendChild(el("div", {className: "step"}, el("b", {text: "6. 建議向合作方確認"}), docs.childNodes.length ? docs : el("span", {className: "muted", text: "未觸發補件項目"})));
    details.appendChild(steps);
    box.appendChild(details);
    return box;
  }

  // -------------------------------------------------------------------------------------- models
  function renderModels(r) {
    var target = document.getElementById("modelsBody");
    clear(target);
    target.appendChild(el("h2", {text: "文獻模型可計算性（Beneish 1999／Dechow et al. 2011）"}));
    target.appendChild(el("p", {className: "muted", text: "沿用已驗收的計分核心（公式未修改）。正式公司沒有依文獻輸入證據政策凍結的輸入時，分數為空並列出缺漏；不使用 1785 歷史研究案例分數替代。"}));
    if (!r.paper_models.length) { target.appendChild(el("div", {className: "state", text: "未要求此分區。"})); return; }
    r.paper_models.forEach(function (m) {
      var box = el("article", {className: "finding"},
        el("header", null, el("strong", {text: m.paper}), statusBadge(m.status), badge("分數：" + (m.raw_score == null ? "無（不可計算）" : m.raw_score), "na"), badge(m.approval_status, "na")));
      box.appendChild(el("p", {className: "muted", text: "年度 " + (m.fiscal_year || "—") + "；元件 " + m.component_coverage.computed + "/" + m.component_coverage.required + "；缺漏輸入 " + m.missing_input_count + " 項；原因 " + m.missing_reasons.join("、")}));
      var table = el("table", null, el("thead", null, el("tr", null, el("th", {text: "模型輸入"}), el("th", {text: "對應管線科目"}), el("th", {text: "t 年有資料"}), el("th", {text: "t−1 年有資料"}), el("th", {text: "是否採為模型輸入"}))));
      var body = el("tbody");
      m.pipeline_fact_availability.forEach(function (a) {
        body.appendChild(el("tr", null, el("td", {text: a.model_input}), el("td", {text: a.pipeline_metric || "—"}),
          el("td", {text: a.pipeline_fact_t ? "有" : "無"}), el("td", {text: a.pipeline_fact_t_minus_1 ? "有" : "無"}), el("td", {text: "否"})));
      });
      table.appendChild(body);
      var details = el("details", null, el("summary", {text: "缺漏輸入與限制"}), el("div", {className: "table-wrap"}, table));
      var limits = el("ul", {className: "plain"});
      m.limitations.concat(m.shares_inputs_with.map(function (x) { return "共用輸入：" + x; })).forEach(function (x) { limits.appendChild(el("li", {text: x})); });
      details.appendChild(limits);
      box.appendChild(details);
      target.appendChild(box);
    });
  }

  // ---------------------------------------------------------------------------------- cross check
  function renderCross(r) {
    var target = document.getElementById("crossBody");
    clear(target);
    target.appendChild(el("h2", {text: "發行人主張比對（F3）"}));
    if (!r.claim_checks.length) {
      target.appendChild(el("div", {className: "state", text: "此公司沒有已登錄、可定位來源的發行人主張；不產生比對結果。"}));
    }
    r.claim_checks.forEach(function (c) {
      var box = el("article", {className: "finding"},
        el("header", null, el("strong", {text: c.statement.document + " 第 " + c.statement.page + " 頁"}), statusBadge(c.verdict),
          badge(c.corroboration.independent_corroboration ? "獨立佐證" : "同一發行人自報（非獨立佐證）", "na")));
      box.appendChild(el("p", null, "原文：", el("span", {className: "mono", text: c.statement.excerpt})));
      box.appendChild(el("p", {className: "muted", text: "表頭：" + c.statement.context_excerpt + "；發布日 " + c.statement.published_on + "（" + c.statement.published_on_basis + "）"}));
      var details = el("details", null, el("summary", {text: "來源驗證與比對"}));
      if (state.expand) { details.setAttribute("open", ""); }
      var list = el("ul", {className: "plain"});
      var v = c.source_verification;
      list.appendChild(el("li", {text: "來源檢查：文件 " + (v.document_found ? "存在" : "缺") + "；SHA-256 與登錄一致 " + (v.sha256_matches_pin ? "是" : "否") + "；原文出現在該頁 " + (v.excerpt_found ? "是" : "否") + "；SHA-256 " + (v.archive_sha256 || "—")}));
      list.appendChild(el("li", {text: "正規化主張：" + c.normalized_claim + "（" + c.normalization + "）"}));
      if (c.precision_check) { list.appendChild(el("li", {text: "列印精度檢查：主張 " + c.precision_check.claimed_twd + " 元，官方 " + c.precision_check.official_twd + " 元，差 " + c.precision_check.difference_twd + " 元（容許 ±" + c.precision_check.printed_precision_half_step_twd + "）"})); }
      c.evidence.forEach(function (e) {
        list.appendChild(el("li", null, "比對證據：" + (e.source_title || e.source_type) + " " + (e.period || "") + " " + (e.value || "") + " " + (e.unit || "") + "（" + e.relation + "） ", safeLink(e.source_reference, "MOPS")));
      });
      c.limitations.forEach(function (x) { list.appendChild(el("li", {text: x})); });
      list.appendChild(el("li", {text: c.corroboration.explanation || ""}));
      details.appendChild(list);
      box.appendChild(details);
      target.appendChild(box);
    });

    target.appendChild(el("h3", {text: "官方法說會文件文字差異（JSD／Cosine，團隊既有方法）"}));
    var s = r.data_shift;
    if (!s) { target.appendChild(el("div", {className: "state", text: "未要求此分區。"})); return; }
    var box = el("article", {className: "finding"},
      el("header", null, el("strong", {text: (s.period_1 || "—") + " → " + (s.period_2 || "—")}),
        badge({comparable: "可比較", not_comparable: "不可比較", unavailable: "不可用", quality_insufficient: "資料品質不足", method_unavailable: "方法不可用"}[s.status] || s.status, s.status === "comparable" ? "ok" : "na"),
        badge(s.calibration_status === "calibrated" ? "已校準" : "未校準：不判定漂移等級", "na")));
    box.appendChild(el("p", {className: "muted", text: s.warning}));
    var list = el("ul", {className: "plain"});
    if (s.metrics) { list.appendChild(el("li", {text: "JSD = " + s.metrics.jsd + "；Cosine = " + s.metrics.cosine_similarity + "（原始值，不是風險分數）"})); }
    list.appendChild(el("li", {text: "漂移等級：" + (s.drift_level || "無（未校準或不可比較）")}));
    list.appendChild(el("li", {text: "文件類型 " + (s.document_type || "—") + "；語言 " + (s.language || "—") + "；原因 " + (s.reason || "—")}));
    Object.keys(s.compatibility_checks || {}).forEach(function (k) { list.appendChild(el("li", {text: "相容性檢查 " + k + "：" + (s.compatibility_checks[k] === true ? "通過" : "未通過")})); });
    s.source_documents.forEach(function (d) { list.appendChild(el("li", null, d.period + " " + d.document + "（SHA-256 " + d.sha256 + "） ", safeLink(d.source_url, "MOPS"))); });
    s.limitations.forEach(function (x) { list.appendChild(el("li", {text: x})); });
    list.appendChild(el("li", {text: "簡報 PDF 不等同於 Larcker & Zakolyukina (2012) 使用的英文法說會逐字稿；JSD 不是該論文的欺騙語言分類器。"}));
    box.appendChild(list);
    target.appendChild(box);
  }

  // ------------------------------------------------------------------------------------------ B2B
  function renderB2B(r) {
    var target = document.getElementById("b2bBody");
    clear(target);
    target.appendChild(el("h2", {text: "B2B 合作前查核清單"}));
    target.appendChild(el("p", {className: "muted", text: "依有來源的篩檢項目產生；每一項都是「要確認什麼」，不是風險結論。沒有已證實的往來關係時，不估計停供或供應鏈中斷機率。"}));
    var table = el("table", null, el("thead", null, el("tr", null, el("th", {text: "觸發條件"}), el("th", {text: "建議詢問"}), el("th", {text: "建議索取文件"}), el("th", {text: "理由"}))));
    var body = el("tbody");
    r.next_checks.forEach(function (c) {
      body.appendChild(el("tr", null, el("td", {text: c.condition}), el("td", {text: c.question_for_counterparty}),
        el("td", {text: c.documents_to_request.join("、") || "—"}), el("td", {text: c.rationale})));
    });
    table.appendChild(body);
    target.appendChild(el("div", {className: "table-wrap"}, table));
    target.appendChild(el("h3", {text: "資料不足項目"}));
    var missing = el("ul", {className: "plain"});
    r.missing_data.forEach(function (m) { missing.appendChild(el("li", {text: m.section + " / " + m.item + "：" + m.reasons.join("、")})); });
    target.appendChild(missing.childNodes.length ? missing : el("p", {className: "muted", text: "無"}));
  }

  function renderMethods() {
    var target = document.getElementById("methodBody");
    var table = el("table", null, el("thead", null, el("tr", null, el("th", {text: "文獻"}), el("th", {text: "DOI"}), el("th", {text: "本系統實作分層"}), el("th", {text: "說明"}))));
    var body = el("tbody");
    METHODS.forEach(function (m) {
      body.appendChild(el("tr", null, el("td", {text: m[0]}),
        el("td", null, el("a", {href: "https://doi.org/" + m[1], target: "_blank", rel: "noopener noreferrer", text: m[1]})),
        el("td", {text: m[2]}), el("td", {text: m[3]})));
    });
    table.appendChild(body);
    target.appendChild(el("div", {className: "table-wrap"}, table));
    target.appendChild(el("p", {className: "muted", text: "方法核准狀態：DRAFT_PENDING_METHOD_OWNER_REVIEW。F1／F2 為財務一致性篩檢，與 Beneish／Dechow 共用底層變數，不可視為獨立佐證。"}));
  }


  // Historical 1785 research is not a CURRENT_REVIEW assessment.  Reuse the existing
  // verified retrospective endpoint without injecting its scores into F1/F3/B2B.
  var HISTORICAL_TICKER = "1785";
  var historicalPolicy = "latest_available";

  function renderHistoricalCells(data, target, showDetail) {
    var years = [], first = data.fiscal_years.start, last = data.fiscal_years.end;
    for (var y = first; y <= last; y++) { years.push(y); }
    var head = el("tr", null, el("th", {text: "文獻模型"}));
    years.forEach(function (year) { head.appendChild(el("th", {text: String(year)})); });
    var body = el("tbody");
    Object.keys(data.models).forEach(function (model) {
      var tr = el("tr", null, el("th", {text: data.models[model]}));
      years.forEach(function (year) {
        var cell = data.cells.find(function (item) { return item.model_id === model && item.fiscal_year === year; });
        if (!cell) { tr.appendChild(el("td", {text: "—"})); return; }
        var display = cell.status === "computed" ? String(cell.score) : "不可計算";
        var td = el("td", {className: "num"});
        if (showDetail) {
          var button = el("button", {type: "button", className: "fi-historical-cell", text: display,
            "aria-label": data.models[model] + " FY" + year + " " + display});
          button.addEventListener("click", function () { renderHistoricalDetail(data, cell); });
          td.appendChild(button);
        } else {
          td.textContent = display;
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    target.appendChild(el("div", {className: "table-wrap"}, el("table", null, el("thead", null, head), body)));
    target.appendChild(el("p", {className: "muted",
      text: "數字為文獻模型原始分數，並非舞弊機率；不可計算不代表低風險。"}));
  }

  function renderHistoricalDetail(data, cell) {
    var target = document.getElementById("histCellDetail");
    if (!target) { return; }
    clear(target);
    var reasons = cell.missing_reasons || [];
    target.appendChild(el("h3", {text: data.models[cell.model_id] + " FY" + cell.fiscal_year +
      "：" + (cell.status === "computed" ? "已計算（" + cell.score + "）" : "不可計算")}));
    if (reasons.length) {
      target.appendChild(el("p", {className: "state error", text: reasons.join("、")}));
    }
    var body = el("tbody");
    (cell.components || []).forEach(function (component) {
      var refs = el("ul", {className: "plain"});
      (component.observations || []).forEach(function (o) {
        refs.appendChild(el("li", null, (o.metric || "科目") + "（" + (o.relative_period || "—") + "） " +
          (o.published_value || "—") + " " + (o.published_unit || ""), " ", safeLink(o.source_url, "官方來源")));
      });
      body.appendChild(el("tr", null, el("td", {text: component.variable}),
        el("td", {text: component.status}),
        el("td", {text: component.value == null ? "—" : String(component.value)}),
        el("td", {text: (component.reasons || []).join("、") || "—"}),
        el("td", null, refs)));
    });
    target.appendChild(el("div", {className: "table-wrap"},
      el("table", null, el("thead", null, el("tr", null,
        el("th", {text: "元件"}), el("th", {text: "狀態"}), el("th", {text: "數值"}),
        el("th", {text: "說明"}), el("th", {text: "來源"}))), body)));
  }

  function renderHistoricalCase(data) {
    var summary = document.getElementById("summaryBody"),
      overview = document.getElementById("overviewBody"),
      models = document.getElementById("modelsBody");
    clear(summary); clear(overview); clear(models);
    var counts = data.counts[data.version_policy];
    var baseline = data.baseline_check;
    summary.appendChild(el("div", {className: "disclaimer", text:
      "RETROSPECTIVE_CASE｜1785 光洋科：事後研究，包含可能於事件後公開的申報資料。" +
      "與 CURRENT_REVIEW 完全分開，不代表事前成功預警或現行風險評等。"}));
    summary.appendChild(el("div", {className: "summary"},
      el("div", {className: "stat"}, el("span", {text: "研究案例"}), el("strong", {text: "1785 光洋科"}),
        el("small", {text: "歷史財報／申報版本比較"})),
      el("div", {className: "stat"}, el("span", {text: "目前申報版本"}),
        el("strong", {text: data.version_policy === "latest_available" ? "含後續重編" : "原始申報"}),
        el("small", {text: data.version_policy})),
      el("div", {className: "stat"}, el("span", {text: "文獻模型年度結果"}),
        el("strong", {text: counts.computed + "／" + counts.cells + " 格已計算"}),
        el("small", {text: counts.not_computable + " 格不可計算"})),
      el("div", {className: "stat"}, el("span", {text: "兩版本合計驗收"}),
        el("strong", {text: baseline.matches ? "60／60 一致" : "需要重新核對"}),
        el("small", {text: "26 已計算、34 不可計算；非預測準確率"}))));
    overview.appendChild(el("h2", {text: "1785 光洋科｜歷史財報研究結果"}));
    overview.appendChild(el("p", {className: "muted",
      text: "已收錄財報重編與歷史模型研究，分析期間 FY" + data.fiscal_years.start +
        "–FY" + data.fiscal_years.end + "；研究狀態：DRAFT_PENDING_METHOD_OWNER_REVIEW。"}));
    var policyLabel = el("label", null, "申報版本：");
    var policy = el("select", {"aria-label": "歷史研究申報版本"});
    policy.appendChild(el("option", {value: "latest_available", text: "latest_available（含後續重編）"}));
    policy.appendChild(el("option", {value: "original_only", text: "original_only（原始申報）"}));
    policy.value = data.version_policy;
    policy.addEventListener("change", function () { historicalPolicy = policy.value; runHistorical(); });
    policyLabel.appendChild(policy);
    overview.appendChild(el("div", {className: "controls"}, policyLabel));
    overview.appendChild(el("h3", {text: "Beneish／Dechow 歷史年度模型"}));
    renderHistoricalCells(data, overview, false);
    overview.appendChild(el("p", {className: "state",
      text: data.strict_pre_event.conclusion}));
    models.appendChild(el("h2", {text: "模型計算結果與逐格來源證據"}));
    models.appendChild(el("p", {className: "muted",
      text: "點選年度分數可查看變數、缺漏原因及官方來源；不會存入正式企業健檢。"}));
    renderHistoricalCells(data, models, true);
    models.appendChild(el("div", {id: "histCellDetail", className: "state",
      text: "點選任一年度與模型查看計算組成及來源。"}));
    var cross = document.getElementById("crossBody"), b2b = document.getElementById("b2bBody");
    clear(cross); clear(b2b);
    cross.appendChild(el("h2", {text: "光洋科歷史申報版本與財報重編"}));
    cross.appendChild(el("p", {className: "muted",
      text: "此案例採 RETROSPECTIVE_CASE；不得把其他公司的現行 F3／JSD 主張查核結果套用到光洋科。"}));
    cross.appendChild(el("p", null, el("a", {href: "historical-research.html#bridge",
      text: "查看光洋科歷史財務重編比較與來源"})));
    b2b.appendChild(el("h2", {text: "歷史案例不提供 B2B 合作風險評級"}));
    b2b.appendChild(el("p", {className: "state",
      text: "光洋科事後研究分數不能替代任何公司的 CURRENT_REVIEW／B2B 查核；本模式不產生合作方評級。"}));
  }

  function runHistorical() {
    var button = document.getElementById("runBtn");
    button.disabled = true;
    state.result = null;
    selectTab("overview");
    ["summaryBody", "overviewBody", "modelsBody", "crossBody", "b2bBody"].forEach(function (id) {
      setState(document.getElementById(id), "光洋科歷史研究載入中…");
    });
    announce("光洋科歷史研究載入中");
    request("GET", "/api/integrity/research-cases/1785/summary?version_policy=" + encodeURIComponent(historicalPolicy))
      .then(function (data) {
        if (data.status !== "available") {
          var unavailable = "光洋科研究資料不可用：" + (data.reason || "研究資料庫尚未設定") +
            "。請確認兩份唯讀歷史 SQLite 資料庫已連接。";
          ["summaryBody", "overviewBody", "modelsBody", "crossBody", "b2bBody"].forEach(function (id) {
            setState(document.getElementById(id), unavailable, true);
          });
          announce(unavailable);
          return;
        }
        renderHistoricalCase(data);
        announce("光洋科歷史案例載入完成");
      }).catch(function (error) {
        ["summaryBody", "overviewBody", "modelsBody", "crossBody", "b2bBody"].forEach(function (id) {
          setState(document.getElementById(id), errorText(error), true);
        });
        announce(errorText(error));
      }).then(function () { button.disabled = false; });
  }

  function updateSelectionMode() {
    var historical = document.getElementById("tickerSelect").value === HISTORICAL_TICKER;
    document.getElementById("runBtn").textContent = historical ?
      "查看光洋科歷史分析（不儲存）" : "產生健檢（預覽，不儲存）";
    document.getElementById("pickNote").textContent = historical ?
      "光洋科為已登錄的事後歷史研究案例；會顯示 Beneish／Dechow 年度模型，不是 CURRENT_REVIEW 或舞弊風險判定。" :
      "只列出已登錄的公司；尚無已歸檔財報快照的公司仍可查詢，但會顯示資料不足。";
    var mode = document.getElementById("reviewModeBadge");
    var hint = document.getElementById("reviewModeHint");
    if (mode) { mode.textContent = historical ? "RETROSPECTIVE_CASE" : "CURRENT_REVIEW"; }
    if (hint) { hint.textContent = historical ?
      "（事後歷史研究，非事件前預警）" : "（目前已歸檔資訊，不是歷史時點重建）"; }
  }

  function addHistoricalOption(select) {
    var group = el("optgroup", {label: "歷史研究案例（不屬於目前企業健檢）"});
    group.appendChild(el("option", {value: HISTORICAL_TICKER, text: "1785 光洋科｜歷史財報研究（事後）"}));
    select.appendChild(group);
  }

  // ------------------------------------------------------------------------------------------ flow
  function run() {
    var ticker = document.getElementById("tickerSelect").value;
    if (!/^\d{4,6}$/.test(ticker)) { return; }
    if (ticker === HISTORICAL_TICKER) { runHistorical(); return; }
    var button = document.getElementById("runBtn");
    button.disabled = true;
    ["overviewBody", "modelsBody", "crossBody", "b2bBody", "summaryBody"].forEach(function (id) { setState(document.getElementById(id), "載入中…"); });
    announce("健檢產生中");
    request("POST", "/api/integrity/assessments/preview", {ticker: ticker, review_mode: "CURRENT_REVIEW",
      sections: ["financial_checks", "literature", "jsd", "claims"]}).then(function (r) {
      state.result = r;
      renderSummary(r); renderOverview(r); renderModels(r); renderCross(r); renderB2B(r);
      announce("健檢完成：" + r.company);
    }).catch(function (error) {
      ["overviewBody", "modelsBody", "crossBody", "b2bBody", "summaryBody"].forEach(function (id) { setState(document.getElementById(id), errorText(error), true); });
      announce(errorText(error));
    }).then(function () { button.disabled = false; });
  }

  function loadCompanies() {
    var select = document.getElementById("tickerSelect");
    request("GET", "/api/integrity/companies").then(function (data) {
      while (select.firstChild) { select.removeChild(select.firstChild); }
      select.appendChild(el("option", {value: "", text: "請選擇"}));
      data.companies.forEach(function (c) {
        if (c.ticker === HISTORICAL_TICKER) { return; } // historical case has a different review_mode
        select.appendChild(el("option", {value: c.ticker, text: c.ticker + " " + c.name + (c.persisted_snapshot ? "" : "（尚無已歸檔財報：會顯示資料不足）")}));
      });
      addHistoricalOption(select);
      var wanted = new URLSearchParams(window.location.search).get("ticker");
      if (wanted && /^\d{4,6}$/.test(wanted)) { select.value = wanted; }
      document.getElementById("runBtn").disabled = !select.value;
      updateSelectionMode();
      if (select.value) { run(); }
    }).catch(function (error) {
      while (select.firstChild) { select.removeChild(select.firstChild); }
      select.appendChild(el("option", {value: "", text: "現行健檢公司清單暫時無法載入"}));
      addHistoricalOption(select);
      var wanted = new URLSearchParams(window.location.search).get("ticker");
      if (wanted === HISTORICAL_TICKER) {
        select.value = HISTORICAL_TICKER;
        document.getElementById("runBtn").disabled = false;
        updateSelectionMode();
        runHistorical();
      } else {
        setState(document.getElementById("summaryBody"), errorText(error), true);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".tabs button"), function (button) {
      button.addEventListener("click", function () { selectTab(button.getAttribute("data-view")); });
    });
    document.getElementById("tickerSelect").addEventListener("change", function (event) {
      document.getElementById("runBtn").disabled = !event.target.value;
      updateSelectionMode();
    });
    document.getElementById("runBtn").addEventListener("click", run);
    var params = new URLSearchParams(window.location.search);
    state.expand = params.get("expand") === "1";
    var hash = String(window.location.hash || "").replace("#", "");
    if (VIEWS.indexOf(hash) >= 0) { selectTab(hash); }
    renderMethods();
    loadCompanies();
  });
})();
