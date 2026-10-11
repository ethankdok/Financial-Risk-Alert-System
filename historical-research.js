// Historical research page (Phase 4). Pure render functions + DOM wiring.
// Data comes only from the Flask proxy (/api/research/...), which forwards to the FastAPI research API.
// No research arithmetic happens here: values are exact decimal strings from the API, formatted as text.
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FinTrustResearch = api;
  if (typeof document !== 'undefined' && typeof window !== 'undefined' && !window.__RESEARCH_NO_AUTO_INIT__) {
    document.addEventListener('DOMContentLoaded', () => api.init(document, window.fetch.bind(window)));
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const TICKER = '1785';
  const OFFICIAL_HOSTS = ['mopsov.twse.com.tw', 'mops.twse.com.tw', 'doc.twse.com.tw', 'www.twse.com.tw',
    'www.tpex.org.tw', 'emops.twse.com.tw'];
  const METRIC_LABELS = {
    revenue: '營業收入', cost_of_goods_sold: '營業成本', gross_profit: '營業毛利', operating_income: '營業利益',
    net_income: '本期淨利', current_assets: '流動資產', total_assets: '資產總計', current_liabilities: '流動負債',
    total_liabilities: '負債總計', equity: '權益總計', eps: '每股盈餘', inventory: '存貨', accounts_receivable: '應收帳款',
  };
  const STATE_LABELS = {
    READY: ['ready', 'READY 可計算'], computed: ['ready', '已計算'], PARTIAL: ['partial', 'PARTIAL 部分可計算'],
    NOT_COMPUTABLE: ['not-computable', 'NOT_COMPUTABLE 不可計算'], not_computable: ['not-computable', '不可計算'],
    insufficient_point_in_time_evidence: ['not-computable', 'NOT_COMPUTABLE：截點前無可驗證財務資料'],
    EVIDENCE_UNVERIFIED: ['unverified', 'EVIDENCE_UNVERIFIED 證據未驗證'],
    INCONSISTENT: ['inconsistent', 'INCONSISTENT 來源不一致'], mismatch_unresolved: ['inconsistent', '差異待查證'],
    NOT_APPLICABLE: ['not-applicable', 'NOT_APPLICABLE 不適用'], not_applicable: ['not-applicable', '不適用'],
    NOT_READY: ['not-ready', 'NOT_READY 資料資格未通過'], match: ['ready', '一致'], not_comparable: ['not-applicable', '不可比較'],
    CONSISTENT: ['ready', '一致'],
    INCONCLUSIVE_NOT_COMPARABLE: ['not-applicable', '無可比較項目（不判定一致）'],
  };
  const FEATURE_LABELS = {
    gross_margin: '毛利率', cogs_sales_ratio: '營業成本率', operating_margin: '營業利益率', net_margin: '淨利率',
    inventory_to_assets: '存貨／總資產', inventory_turnover: '存貨週轉率', inventory_growth_assets: 'Δ存貨／平均總資產',
    receivables_sales_ratio: '應收帳款／營收', receivables_growth_assets: 'Δ應收帳款／平均總資產',
    earnings_cashflow_gap_proxy: '(淨利−營業現金流)／平均總資產（代理指標）', debt_asset_ratio: '負債比率',
    source_value_gap: '來源數值差異',
  };

  function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function safeLink(url, label) {
    if (!url) return '<span class="muted">（無公開連結）</span>';
    let parsed;
    try { parsed = new URL(String(url)); } catch (error) { return '<span class="muted">（連結無效）</span>'; }
    if (!['https:', 'http:'].includes(parsed.protocol) || !OFFICIAL_HOSTS.includes(parsed.hostname)) {
      return '<span class="muted">（非官方連結已隱藏）</span>';
    }
    return `<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label || '官方來源')}</a>`;
  }

  function badge(status) {
    const [cls, label] = STATE_LABELS[status] || ['', status || '—'];
    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
  }

  function groupDigits(text) {
    const value = String(text);
    const negative = value.startsWith('-');
    const [whole, fraction] = (negative ? value.slice(1) : value).split('.');
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return (negative ? '-' : '') + grouped + (fraction !== undefined ? `.${fraction}` : '');
  }

  // Exact formatting of a TWD decimal string as thousand TWD (string arithmetic only).
  function thousand(twd) {
    if (twd === null || twd === undefined || twd === '') return '—';
    const value = String(twd);
    if (/^-?\d+000$/.test(value)) return `${groupDigits(value.slice(0, -3))} 千元`;
    return `${groupDigits(value)} 元`;
  }

  function percent(ratio) {
    if (ratio === null || ratio === undefined || ratio === '') return '—';
    const match = /^(-?)(\d+)\.(\d{6})$/.exec(String(ratio));
    if (!match) return escapeHtml(ratio);
    const digits = (match[2] + match[3]).replace(/^0+(?=\d{5})/, '');
    const whole = digits.slice(0, -4).replace(/^0+(?=\d)/, '') || '0';
    return `${match[1]}${whole}.${digits.slice(-4)}%`;
  }

  function stat(label, value, note) {
    return `<div class="stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${note ? `<small>${escapeHtml(note)}</small>` : ''}</div>`;
  }

  function modeLine(data) {
    const cutoff = data.cutoff_at_taipei ? `截點（不含）${escapeHtml(data.cutoff_at_taipei)}` : '無截點';
    const hindsight = data.hindsight ? '<span class="badge partial" title="事後資訊，不可作事前預警特徵">hindsight=true</span>' : '';
    return `<p><span class="badge mode">${escapeHtml(data.analysis_mode)}</span> ${cutoff} ${hindsight}</p>`;
  }

  function renderOverview(data) {
    const coverage = data.coverage || {};
    const events = (data.key_events || []).map((e) => `<tr><td>${escapeHtml(e.publication_at || '—')}</td>
      <td>${escapeHtml(e.publication_precision || '')}</td><td>${escapeHtml(e.role)}</td><td>${escapeHtml(e.note)}</td>
      <td><span class="badge">${escapeHtml(e.evidence_tier)}</span></td><td>${safeLink(e.source_url)}</td></tr>`).join('');
    const hypotheses = (data.hypotheses || []).map((h) => `<li>${escapeHtml(h.statement)}
      <span class="badge unverified" title="${escapeHtml((data.hypothesis_source || {}).basis)}">研究假說（法律分類未驗證）</span></li>`).join('');
    return `<h2>${escapeHtml(data.company_name)}（${escapeHtml(data.ticker)}）歷史稽核研究案例</h2>
      <p><span class="badge not-applicable">非正式公司清單（production_universe=false）</span>
      ${(data.supported_modes || []).map((m) => `<span class="badge mode">${escapeHtml(m)}</span>`).join(' ')}</p>
      <div class="grid">
        ${stat('研究涵蓋年度', `${data.research_coverage.start_year}–${data.research_coverage.end_year}`, `事件優先期間 ${data.priority_event_period.start_year}–${data.priority_event_period.end_year}`)}
        ${stat('正式財報事實（Full）', coverage.canonical_facts, 'FY2013–FY2025，每年 18 項')}
        ${stat('可 PIT 驗證事實', coverage.point_in_time_eligible_facts, '數值層級公告定時；非 XBRL 檔案公開時間')}
        ${stat('官方重編對照列', coverage.restatement_comparisons, '2016-11-13 公告，FY2011–FY2015')}
        ${stat('公告時間線事件', coverage.publication_events, `不同事件鍵 ${coverage.distinct_event_keys}`)}
        ${stat('財報版本', coverage.filing_versions, 'XBRL／PDF 版本分開記錄')}
        ${stat('董事會公告數值', coverage.disclosed_values, 'FY2020–FY2025 合併財報決議公告')}
        ${stat('嚴格事前可行性', '不可評估', data.strict_feasibility_note)}
      </div>
      <h3>主要事件（以封存官方時間線為準）</h3>
      <div class="table-wrap"><table><thead><tr><th>公開時間</th><th>精度</th><th>角色</th><th>說明</th><th>證據層級</th><th>來源</th></tr></thead>
      <tbody>${events}</tbody></table></div>
      <h3>會計機制研究假說</h3><ul>${hypotheses}</ul>
      <p class="muted">${escapeHtml((data.hypothesis_source || {}).basis)}</p>`;
  }

  function heatClass(cell) {
    if (!cell || cell.delta_twd === null) return 'heat-na';
    if (cell.delta_pct === null) return cell.delta_twd === '0' ? 'heat-zero' : 'heat-na';
    const pct = String(cell.delta_pct);
    if (/^0\.0+$/.test(pct)) return 'heat-zero';
    const strong = /^-?(0\.[1-9]|[1-9])/.test(pct);
    return pct.startsWith('-') ? (strong ? 'heat-neg-strong' : 'heat-neg') : (strong ? 'heat-pos-strong' : 'heat-pos');
  }

  function renderBridge(data) {
    if (data.status === 'insufficient_point_in_time_evidence') {
      return `${modeLine(data)}<div class="state">${badge(data.status)} 截點前沒有任何已公開的官方重編對照（重編前後數值於 2016-11-13 21:25:31 起才公開）。</div>`;
    }
    const years = data.heatmap.fiscal_years;
    const metrics = ['revenue', 'cost_of_goods_sold', 'gross_profit', 'operating_income', 'net_income', 'current_assets',
      'total_assets', 'current_liabilities', 'total_liabilities', 'equity'];
    const cells = {};
    data.heatmap.cells.forEach((c) => { cells[`${c.metric}|${c.fiscal_year}`] = c; });
    const head = years.map((y) => `<th class="num">${y}<br><small>${y < 2013 ? 'TW-GAAP' : 'TIFRS'}</small></th>`).join('');
    const rows = metrics.map((m) => `<tr><th>${escapeHtml(METRIC_LABELS[m] || m)}</th>${years.map((y) => {
      const c = cells[`${m}|${y}`];
      if (!c) return '<td class="cell heat-na" title="此公告未列示此科目">不可計算</td>';
      const label = c.delta_pct === null ? `${thousand(c.delta_twd)}<br><small>${escapeHtml(c.denominator_status)}</small>`
        : `${percent(c.delta_pct)}<br><small>${thousand(c.delta_twd)}</small>`;
      return `<td class="cell ${heatClass(c)}"><button class="cell-btn" type="button" data-key="${escapeHtml(c.comparison_key)}"
        title="Δ = 重編後 − 重編前；百分比僅在分母穩定時顯示">${label}</button></td>`;
    }).join('')}</tr>`).join('');
    const bridges = data.year_bridges.map((b) => {
      const m = b.margins;
      const marginRow = (name, label) => `<tr><td>${label}</td><td class="num">${percent(m[name].pre.value)}</td>
        <td class="num">${percent(m[name].post.value)}</td><td class="num">${m[name].change === null ? badge('not_computable') : percent(m[name].change)}</td></tr>`;
      return `<details><summary>${escapeHtml(b.period)}（${escapeHtml(b.accounting_framework)}）公告 ${escapeHtml(b.announcement_key)}</summary>
        <div class="table-wrap"><table><thead><tr><th>比率</th><th class="num">重編前</th><th class="num">重編後</th><th class="num">變動</th></tr></thead>
        <tbody>${marginRow('gross_margin', '毛利率')}${marginRow('cogs_sales_ratio', '營業成本率')}${marginRow('operating_margin', '營業利益率')}${marginRow('net_margin', '淨利率')}</tbody></table></div>
        <p class="muted">ΔCOGS ${thousand(b.decomposition.delta_cost_of_goods_sold_twd)}；Δ毛利 ${thousand(b.decomposition.delta_gross_profit_twd)}；Δ淨利 ${thousand(b.decomposition.delta_net_income_twd)}；
        營業外及所得稅殘差 ${thousand(b.decomposition.residual_non_operating_and_tax_twd)}。公告 SHA-256 <span class="mono">${escapeHtml(b.notice_sha256)}</span></p></details>`;
    }).join('');
    const links = (data.hypothesis_links || []).map((h) => {
      const consistent = h.observations.filter((o) => o.direction_consistent).length;
      return `<li>${escapeHtml(h.statement)}：方向一致 ${consistent}／${h.observations.length} 項觀察 <span class="badge unverified">描述性，非機制證明</span></li>`;
    }).join('');
    return `${modeLine(data)}
      <div class="warning" role="note"><strong>依 2016 年 11 月公告回溯重述。</strong>${escapeHtml(data.warning)}</div>
      <p>${badge(data.status)} 對照列 ${data.integrity.rows_total}（基準 ${data.integrity.expected_baseline_rows}：${escapeHtml(data.integrity.baseline_check)}）；
      跨準則：${years.filter((y) => y < 2013).length ? '2011–2012 TW-GAAP 與 2013 起 TIFRS 不可直接比較' : '—'}。重編前數值語意：依 2016 年公告所列，非已證實之原始首次公告數字。</p>
      <div class="table-wrap"><table class="heat"><caption class="sr-only">重編差異熱圖</caption><thead><tr><th>科目</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
      <p class="muted">${escapeHtml(data.inventory_note)}</p>
      <h3>年度橋接與比率</h3>${bridges}
      <h3>與研究假說的方向比對</h3><ul>${links || '<li class="muted">此模式不顯示（假說比對僅限 RETROSPECTIVE_FORENSIC）</li>'}</ul>
      <p class="muted">${escapeHtml(data.interpretation)}</p>`;
  }

  function renderTimeline(data) {
    const tiers = Object.entries(data.tier_counts || {}).map(([tier, count]) => `<span class="badge">${escapeHtml(tier)}：${count}</span>`).join(' ');
    if (!data.total) return `${modeLine(data)}<div class="state">截點前沒有符合條件的事件。</div>`;
    const rows = data.events.map((e) => `<tr><td class="mono">${escapeHtml(e.available_from)}</td><td>${escapeHtml(e.publication_precision)}</td>
      <td>${escapeHtml(e.title)}</td><td><span class="badge ${e.source_document_included ? 'ready' : 'unverified'}"
      title="${escapeHtml(data.tier_definitions[e.evidence_tier] || '')}">${escapeHtml(e.evidence_tier)}</span></td>
      <td>${e.source_document_included ? '已封存原文' : '僅官方清單'}</td><td>${safeLink(e.source_url)}</td></tr>`).join('');
    return `${modeLine(data)}<p>共 ${data.total} 筆事件（顯示 ${data.events.length} 筆）。${tiers}</p>
      <div class="table-wrap"><table><thead><tr><th>可得時間</th><th>精度</th><th>標題</th><th>證據層級</th><th>原文</th><th>來源</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function renderSignals(data) {
    const result = data.result || data;
    const features = result.features || [];
    const years = [...new Set(features.map((f) => f.fiscal_year))];
    const ids = [...new Set(features.map((f) => f.feature_id))];
    const byKey = {};
    features.forEach((f, i) => { byKey[`${f.feature_id}|${f.fiscal_year}`] = i; });
    const rows = ids.map((id) => `<tr><th>${escapeHtml(FEATURE_LABELS[id] || id)}</th>${years.map((y) => {
      const index = byKey[`${id}|${y}`];
      const f = features[index];
      const content = f.status === 'computed' ? (f.unit === 'ratio' ? percent(f.value) : escapeHtml(f.value)) : badge(f.status);
      return `<td class="num"><button class="cell-btn" type="button" data-feature-index="${index}">${content}</button></td>`;
    }).join('')}</tr>`).join('');
    const literature = ((result.literature_models || {}).models || []).map((m) => `<li>${escapeHtml(m.model_id)}：${badge(m.full_model_status === 'not_computable' ? 'NOT_COMPUTABLE' : m.full_model_status)}</li>`).join('');
    const note = result.strict_note ? `<div class="warning" role="note">${escapeHtml(result.strict_note)}<br>目前缺乏可核驗的事件前財務輸入，因此不能評估預警能力；缺少資料不可解讀為任何風險評等。</div>` : '';
    return `${modeLine(result)}${note}<p>${badge(result.status)} 已計算 ${result.counts.computed}、不可計算 ${result.counts.not_computable}、不適用 ${result.counts.not_applicable}。
      方法狀態 <span class="badge unverified">${escapeHtml(result.approval_status)}</span> run_id <span class="mono">${escapeHtml(data.run_id || '')}</span></p>
      <div class="table-wrap"><table><thead><tr><th>指標</th>${years.map((y) => `<th class="num">FY${y}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>
      <h3>文獻模型就緒度</h3><ul>${literature}</ul><p class="muted">${escapeHtml(result.usage_policy)}</p>`;
  }

  function renderFeatureDetail(feature) {
    if (!feature) return '';
    const inputs = (feature.inputs || []).map((i) => `<tr><td>${escapeHtml(METRIC_LABELS[i.metric_code] || i.metric_code)}</td>
      <td>${escapeHtml(i.period)}</td><td class="num">${thousand(i.value)}</td><td class="mono">${escapeHtml(i.fact_id)}</td>
      <td>${escapeHtml(i.availability_evidence_ref || '—')}<br><span class="mono">${escapeHtml(i.availability_evidence_hash || '')}</span></td>
      <td>${escapeHtml(i.observation_evidence_status)}<br>${escapeHtml(i.artifact_evidence_status)}</td>
      <td>${escapeHtml(i.artifact_reference_status)}</td></tr>`).join('');
    const reasons = (feature.missing_reasons || []).map((r) => `<li><span class="mono">${escapeHtml(r.code)}</span> ${escapeHtml(r.metric || '')} ${escapeHtml(r.detail || '')}</li>`).join('');
    return `<div class="panel"><h3>${escapeHtml(FEATURE_LABELS[feature.feature_id] || feature.feature_id)}　FY${feature.fiscal_year}</h3>
      <p>公式 <span class="mono">${escapeHtml(feature.formula)}</span>（${escapeHtml(feature.formula_version)}；${escapeHtml(feature.original_vs_proxy)}）</p>
      <p>${badge(feature.status)} ${feature.value !== null ? `值 ${escapeHtml(feature.value)}（分子 ${escapeHtml(feature.numerator)}／分母 ${escapeHtml(feature.denominator)}）` : ''}</p>
      ${reasons ? `<ul>${reasons}</ul>` : ''}${(feature.warnings || []).map((w) => `<p class="muted">${escapeHtml(w)}</p>`).join('')}
      ${inputs ? `<div class="table-wrap"><table><thead><tr><th>輸入</th><th>期間</th><th class="num">數值</th><th>fact_id</th><th>可得性證據</th><th>證據維度</th><th>檔案引用</th></tr></thead><tbody>${inputs}</tbody></table></div>` : ''}</div>`;
  }

  function renderDiscrepancies(data) {
    const counts = Object.entries(data.counts || {}).map(([kind, c]) => `<tr><td>${escapeHtml(kind)}</td><td class="num">${c.match}</td>
      <td class="num">${c.mismatch_unresolved}</td><td class="num">${c.not_comparable}</td></tr>`).join('');
    const findings = (data.discrepancies || []).map((f) => {
      const items = f.items.map((i) => `<tr><td>${escapeHtml(METRIC_LABELS[i.metric] || i.metric)}</td>
        <td class="num">${groupDigits(i.board_notice_value)} 千元</td><td class="num">${groupDigits(i.filed_value_thousand_twd)} 千元</td>
        <td class="num"><strong>${groupDigits(i.difference_thousand_twd)} 千元</strong></td></tr>`).join('');
      const pdf = f.audited_pdf || {};
      const checks = (pdf.checks || []).map((c) => (c.status === 'compared'
        ? `<li>${escapeHtml(c.pdf_line)}（等於申報 XBRL：${c.equals_filed_xbrl ? '是' : '否'}；等於董事會公告：${c.equals_board_notice ? '是' : '否'}）</li>`
        : `<li>${escapeHtml(METRIC_LABELS[c.metric] || c.metric)}：${badge('not_comparable')} ${escapeHtml((c.reasons || []).join(', '))}</li>`)).join('');
      const identity = pdf.identity_checks ? Object.entries(pdf.identity_checks).map(([k, v]) => `${escapeHtml(k)}=${escapeHtml(v)}`).join('；')
        : `PDF 證據不可用：${escapeHtml(pdf.reason || '')}`;
      return `<div class="panel"><h3>${escapeHtml(f.period)} ${escapeHtml(f.statement_scope)}：來源數值差異待查證 ${badge('mismatch_unresolved')}</h3>
        <div class="table-wrap"><table><thead><tr><th>科目</th><th class="num">董事會公告</th><th class="num">申報 XBRL／查核 PDF</th><th class="num">差額</th></tr></thead><tbody>${items}</tbody></table></div>
        <div class="compare"><div class="source"><strong>來源 A：董事會決議公告</strong><br>${escapeHtml(f.board_notice.announcement_key)}　公開 ${escapeHtml(f.board_notice.notice_published_at)}<br>
          SHA-256 <span class="mono">${escapeHtml(f.board_notice.notice_sha256)}</span><br>${safeLink(f.board_notice.source_url, 'MOPS 公告查詢頁')}</div>
        <div class="source"><strong>來源 B：申報 XBRL 與查核財報 PDF</strong><br>XBRL SHA-256 <span class="mono">${escapeHtml(f.filed_report.artifact_sha256)}</span>（${escapeHtml(f.filed_report.artifact_evidence_status)}）<br>${safeLink(f.filed_report.artifact_url, 'XBRL 下載')}<br>
          PDF 第 ${escapeHtml(pdf.pdf_page_index || '—')} 頁（頁碼 ${escapeHtml(pdf.printed_page_label || '—')}）SHA-256 <span class="mono">${escapeHtml(pdf.pdf_sha256 || '')}</span><br>${safeLink(pdf.source_url, '查核財報 PDF')}</div></div>
        <p class="muted">PDF 身分檢查（單位／年度／合併範圍）：${identity}</p><ul>${checks}</ul><p class="warning" role="note">原因：未證實（cause=${escapeHtml(f.cause)}）。${escapeHtml(f.explanation_limits)}</p>
        <p class="muted">不轉入風險分數（routes_to_risk_score=false）；不產生舞弊標籤。</p></div>`;
    }).join('');
    return `${modeLine(data)}<p>${badge(data.status)} 一致性：${badge(data.consistency)}</p>
      <div class="table-wrap"><table><thead><tr><th>比對類型</th><th class="num">一致</th><th class="num">差異待查證</th><th class="num">不可比較</th></tr></thead><tbody>${counts}</tbody></table></div>
      ${findings || '<div class="state">沒有未解決的來源差異。</div>'}`;
  }

  function renderTextReadiness(data) {
    if (!data.archive) {
      return `${modeLine(data)}<div class="state">${badge(data.status)} ${escapeHtml(data.archive_status)}；JSD：${badge((data.jsd || {}).status || 'NOT_APPLICABLE')}（不計算、不以 0 代替）</div>`;
    }
    const a = data.archive;
    const issues = Object.entries(data.readiness_issue_counts || {}).map(([k, v]) => `<li><span class="mono">${escapeHtml(k)}</span>：${v}</li>`).join('');
    const docs = (data.documents || []).map((d) => `<tr><td>${d.announcement_year}</td><td class="mono">${escapeHtml(d.filename)}</td>
      <td>${escapeHtml(d.document_type)}</td><td>${escapeHtml(d.language)}</td><td>${escapeHtml(d.period || '未確認')}</td>
      <td class="num">${d.page_count}／${d.text_pages}</td><td>${d.jsd_ready ? badge('READY') : badge('NOT_READY')}</td>
      <td>${escapeHtml((d.readiness_issues || []).join(', '))}</td></tr>`).join('');
    return `${modeLine(data)}<p>${badge(data.status)} JSD：${badge(data.jsd.status)}（不計算、不以 0 代替）</p>
      <div class="grid">${stat('檔名紀錄', a.file_records, '官方法說會封存')}${stat('不同內容（SHA-256）', a.unique_sha256, '重複上架已辨識')}
      ${stat('頁數／有文字層', `${a.pages}／${a.text_pages}`, '逐頁文字已抽取')}${stat('JSD-ready 季度觀測', data.jsd_ready_records, '期間未由文件驗證')}</div>
      <p class="warning" role="note">${escapeHtml(data.jsd.explanation)}</p><h3>未就緒原因</h3><ul>${issues}</ul>
      <details><summary>文件清單（${(data.documents || []).length}）</summary><div class="table-wrap"><table><thead><tr><th>年度</th><th>檔名</th><th>類型</th><th>語言</th><th>期間</th><th class="num">頁／文字頁</th><th>JSD</th><th>原因</th></tr></thead><tbody>${docs}</tbody></table></div></details>
      <p class="muted">${escapeHtml(data.ownership)}</p>`;
  }

  function cutoffValue(input) {
    const value = String(input || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) return null;
    return `${value.length === 16 ? `${value}:00` : value}+08:00`;
  }

  function errorMessage(payload, status) {
    const detail = payload && (payload.detail || payload.error);
    const message = detail && typeof detail === 'object' ? (detail.message || detail.error_code || JSON.stringify(detail)) : detail;
    return `請求失敗（HTTP ${status}）：${message || '未知錯誤'}`;
  }

  function init(doc, fetchFn) {
    const $ = (id) => doc.getElementById(id);
    const loaded = {};
    let lastSignals = null;
    const announce = (text) => { const live = $('liveStatus'); if (live) live.textContent = text; };

    async function load(target, url, render, options) {
      const element = $(target);
      element.className = 'state';
      element.textContent = '載入中…';
      announce('載入中');
      try {
        const response = await fetchFn(url, options);
        const payload = await response.json();
        if (!response.ok || payload.success === false) throw new Error(errorMessage(payload, response.status));
        element.className = '';
        element.innerHTML = render(payload.data);
        announce('已載入');
        return payload.data;
      } catch (error) {
        element.className = 'state error';
        element.textContent = error.message || String(error);
        announce('載入失敗');
        return null;
      }
    }

    function modeQuery(modeId, cutoffId) {
      const mode = $(modeId).value;
      const params = new URLSearchParams({ analysis_mode: mode });
      if (mode === 'STRICT_AS_OF') {
        const cutoff = cutoffValue($(cutoffId).value);
        if (!cutoff) return null;
        params.set('cutoff_at', cutoff);
      }
      return params;
    }

    const views = {
      overview: () => load('overviewBody', `/api/research/cases/${TICKER}`, renderOverview),
      bridge: () => {
        const params = modeQuery('bridgeMode', 'bridgeCutoff');
        if (!params) { $('bridgeBody').textContent = '請輸入完整截點時間'; return null; }
        params.set('scope', $('bridgeScope').value);
        return load('bridgeBody', `/api/research/cases/${TICKER}/restatement-bridge?${params}`, renderBridge);
      },
      timeline: () => {
        const params = modeQuery('timelineMode', 'timelineCutoff');
        if (!params) { $('timelineBody').textContent = '請輸入完整截點時間'; return null; }
        if ($('timelineTier').value) params.set('evidence_tier', $('timelineTier').value);
        params.set('limit', '300');
        return load('timelineBody', `/api/research/cases/${TICKER}/timeline?${params}`, renderTimeline);
      },
      signals: async () => {
        const mode = $('signalMode').value;
        const body = { ticker: TICKER, analysis_mode: mode, version_policy: $('signalPolicy').value,
          start_year: Number($('signalStart').value), end_year: Number($('signalEnd').value) };
        if (mode === 'STRICT_AS_OF') {
          body.cutoff_at = cutoffValue($('signalCutoff').value);
          if (!body.cutoff_at) { $('signalsBody').textContent = '請輸入完整截點時間'; return null; }
        }
        lastSignals = await load('signalsBody', '/api/research/financial-signals/compute', renderSignals,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        $('signalDetail').innerHTML = '';
        return lastSignals;
      },
      discrepancy: () => load('discrepancyBody', `/api/research/cases/${TICKER}/source-discrepancies?analysis_mode=CURRENT_EVIDENCE_RECONCILIATION`, renderDiscrepancies),
      text: () => load('textBody', `/api/research/cases/${TICKER}/text-readiness?analysis_mode=RETROSPECTIVE_FORENSIC`, renderTextReadiness),
    };

    const tabs = Array.from(doc.querySelectorAll('[role="tab"]'));
    function select(tab, focus) {
      tabs.forEach((other) => {
        const active = other === tab;
        other.setAttribute('aria-selected', String(active));
        other.tabIndex = active ? 0 : -1;
        $(other.getAttribute('aria-controls')).hidden = !active;
      });
      if (focus) tab.focus();
      const view = tab.dataset.view;
      if (!loaded[view]) { loaded[view] = true; views[view](); }
    }
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => select(tab, false));
      tab.addEventListener('keydown', (event) => {
        const keys = { ArrowRight: 1, ArrowLeft: -1 };
        if (event.key in keys) { event.preventDefault(); select(tabs[(index + keys[event.key] + tabs.length) % tabs.length], true); }
        if (event.key === 'Home') { event.preventDefault(); select(tabs[0], true); }
        if (event.key === 'End') { event.preventDefault(); select(tabs[tabs.length - 1], true); }
      });
    });
    [['bridgeMode', 'bridgeCutoff'], ['timelineMode', 'timelineCutoff'], ['signalMode', 'signalCutoff']].forEach(([mode, cutoff]) => {
      const sync = () => { $(cutoff).disabled = $(mode).value !== 'STRICT_AS_OF'; };
      $(mode).addEventListener('change', sync);
      sync();
    });
    $('bridgeLoad').addEventListener('click', () => views.bridge());
    $('timelineLoad').addEventListener('click', () => views.timeline());
    $('signalLoad').addEventListener('click', () => views.signals());
    $('signalsBody').addEventListener('click', (event) => {
      const button = event.target.closest && event.target.closest('[data-feature-index]');
      if (button && lastSignals) {
        $('signalDetail').innerHTML = renderFeatureDetail(lastSignals.result.features[Number(button.dataset.featureIndex)]);
      }
    });
    const hash = (doc.location && doc.location.hash || '').replace('#', '');
    const initial = tabs.find((tab) => tab.dataset.view === hash) || tabs[0];
    select(initial, false);
    return { views, select };
  }

  return { escapeHtml, safeLink, badge, thousand, percent, groupDigits, cutoffValue, renderOverview, renderBridge,
    renderTimeline, renderSignals, renderFeatureDetail, renderDiscrepancies, renderTextReadiness, init };
}));
