/* FinTrust 官方法說會跨期文字變化 (result.html Data Shift section).
 * Browser → same-origin Flask /api/financial/data-shift/analyze → FastAPI official JSD bridge.
 * Every response string is rendered with textContent; no server HTML is injected.
 */
(() => {
  const nodes = {
    ticker: document.getElementById('officialShiftTicker'),
    period1: document.getElementById('officialShiftPeriod1'),
    period2: document.getElementById('officialShiftPeriod2'),
    run: document.getElementById('officialShiftRun'),
    status: document.getElementById('officialShiftStatus'),
    empty: document.getElementById('officialShiftEmpty'),
    result: document.getElementById('officialShiftResult'),
  };
  if (!nodes.run || !nodes.result) return;

  const TIMEOUT_MS = 90000;
  const DOCUMENT_TYPES = {
    full_earnings_transcript: '法說會逐字稿',
    earnings_presentation: '法說會業績簡報',
    financial_results_release: '業績新聞稿',
    investor_presentation: '投資人簡報',
    analyst_conference_presentation: '券商論壇簡報',
    other_official_conference_document: '其他官方法說會文件',
  };
  const LANGUAGES = { en: '英文', 'zh-Hant': '繁體中文', bilingual: '中英雙語', en_may_include_translation: '英文（可能含翻譯）' };
  const REASONS = {
    periods_not_adjacent: '兩個期間不是相鄰季度。',
    period_not_available: '指定期間沒有通過驗證的官方文件。',
    no_same_type_and_language_pair: '兩期沒有相同文件類型與語言的官方文件。',
    no_comparable_pair: '目前沒有同文件類型、同語言、相鄰季度的兩份官方文件。',
  };

  const el = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  };
  const fmt = (value, digits = 6) => (typeof value === 'number' ? value.toFixed(digits) : '—');
  const row = (parent, label, value) => {
    const item = el('div', 'drift-report-row');
    item.append(el('span', null, label), el('strong', null, value ?? '—'));
    parent.appendChild(item);
  };
  const status = (message, isError = false) => {
    nodes.status.textContent = message || '';
    nodes.status.style.color = isError ? '#b42318' : '#52606d';
  };
  const safeUrl = (value) => {
    try {
      const url = new URL(String(value || ''));
      return url.protocol === 'https:' ? url.href : null;
    } catch (_) {
      return null;
    }
  };

  // Same company context the financial-evidence section uses: stored analysis text.
  const contextTicker = async () => {
    let text = '';
    try {
      const raw = localStorage.getItem('analysisResult');
      text = raw ? String(JSON.parse(raw).text || '') : '';
    } catch (_) {
      text = '';
    }
    text = text || localStorage.getItem('analysisQuery') || '';
    const explicit = text.match(/\b\d{4,6}\b/);
    if (explicit) return explicit[0];
    if (!text) return '';
    try {
      const response = await fetch('/api/financial/companies');
      const payload = await response.json();
      const companies = (payload.data && payload.data.companies) || payload.companies || [];
      const lower = text.toLocaleLowerCase();
      const match = companies.find((company) =>
        [company.ticker, company.name, ...(company.aliases || [])].filter(Boolean)
          .some((alias) => lower.includes(String(alias).toLocaleLowerCase())));
      return match ? String(match.ticker) : '';
    } catch (_) {
      return '';
    }
  };

  const renderSources = (container, documents) => {
    if (!Array.isArray(documents) || !documents.length) return;
    const box = el('div', 'drift-status');
    box.appendChild(el('b', null, '官方來源文件'));
    const list = el('ul');
    documents.forEach((doc) => {
      const item = el('li');
      item.appendChild(document.createTextNode(
        `${doc.period || '—'}｜${DOCUMENT_TYPES[doc.document_type] || doc.document_type}｜${LANGUAGES[doc.language] || doc.language}｜${doc.document || ''}｜SHA-256 ${String(doc.sha256 || '').slice(0, 12)}… `));
      const url = safeUrl(doc.source_page || doc.source_url);
      if (url) {
        const link = el('a', 'feature-link', '公開資訊觀測站');
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        item.appendChild(link);
      }
      list.appendChild(item);
    });
    box.appendChild(list);
    container.appendChild(box);
  };

  const renderTerms = (container, terms) => {
    if (!terms || (!Array.isArray(terms.emerging) && !Array.isArray(terms.disappearing))) return;
    const columns = el('div', 'term-columns');
    [['主要增加詞彙', terms.emerging], ['主要下降詞彙', terms.disappearing]].forEach(([title, items]) => {
      if (!Array.isArray(items) || !items.length) return;
      const box = el('div', 'term-box');
      box.appendChild(el('h4', null, title));
      const tags = el('div', 'term-tags');
      items.forEach((term) => tags.appendChild(el('span', 'term-tag', term)));
      box.appendChild(tags);
      columns.appendChild(box);
    });
    if (columns.children.length) container.appendChild(columns);
  };

  const render = (data) => {
    const container = nodes.result;
    container.replaceChildren();

    const period = el('div', 'drift-period');
    period.append(
      el('span', null, `公司：${data.company || ''}（${data.ticker || '—'}）`),
      el('span', null, `比較期間：${data.period_1 || '—'} → ${data.period_2 || '—'}`),
    );
    if (data.document_type) {
      period.append(el('span', null,
        `文件：${DOCUMENT_TYPES[data.document_type] || data.document_type}／${LANGUAGES[data.language] || data.language}`));
    }
    container.appendChild(period);

    if (data.analysis_status === 'insufficient_data') {
      const box = el('div', 'drift-status');
      box.append(el('b', null, '資料不足，無法比較'),
        el('p', null, REASONS[data.reason_code] || '目前沒有可比較的官方文件。'));
      const available = (data.available_documents || []).map((doc) =>
        `${doc.period}｜${DOCUMENT_TYPES[doc.document_type] || doc.document_type}｜${LANGUAGES[doc.language] || doc.language}${doc.jsd_ready ? '' : '（未通過驗證）'}`);
      if (available.length) box.appendChild(el('p', null, `可用文件：${available.join('、')}`));
      container.appendChild(box);
      return;
    }

    const report = el('div', 'drift-report');
    const calibration = data.calibration || {};
    row(report, 'Jensen-Shannon Divergence', fmt(data.metrics && data.metrics.jsd));
    row(report, 'Cosine Similarity', fmt(data.metrics && data.metrics.cosine_similarity));
    const quality = data.data_quality;
    row(report, '資料品質', quality ? (quality.passed ? `通過（${quality.text_length_1} / ${quality.text_length_2} 字元）`
      : `未通過（${(quality.reasons || []).join('、')}）`) : '—');
    row(report, '歷史校準', calibration.status === 'calibrated'
      ? `已校準（${calibration.history_pair_count} 組歷史相鄰季）` : '尚無相符歷史校準');
    container.appendChild(report);

    const verdict = el('div', 'drift-status');
    verdict.appendChild(el('b', null, '判定結果'));
    if (data.analysis_status === 'method_unavailable') {
      verdict.appendChild(el('p', null, 'JSD 計算模組暫時無法使用，未產生指標。'));
    } else if (data.analysis_status === 'quality_insufficient') {
      verdict.appendChild(el('p', null, '文字資料品質未達方法門檻，未計算指標，也不判定漂移等級。'));
    } else if (calibration.status === 'calibrated') {
      verdict.appendChild(el('p', null, data.drift_result || '—'));
      const t = calibration.thresholds || {};
      verdict.appendChild(el('p', null,
        `歷史門檻：JSD P90 ${fmt(t.jsd_p90)}／P95 ${fmt(t.jsd_p95)}；Cosine P10 ${fmt(t.cosine_p10)}／P05 ${fmt(t.cosine_p05)}。規則：JSD ≥ P90 且 Cosine ≤ P10。`));
    } else {
      verdict.appendChild(el('p', null,
        '已完成文字分布量測，但目前沒有相同公司／文件類型／方法版本的足夠歷史資料，因此不判定漂移等級。'));
    }
    container.appendChild(verdict);

    renderTerms(container, data.terms);
    renderSources(container, data.source_documents);

    const method = data.method || {};
    const methodBox = el('div', 'drift-status');
    methodBox.append(el('b', null, '方法與版本'), el('p', null,
      `${method.method_version || '—'}；前處理 ${method.preprocessing_version || '—'}；研究版本 ${String(method.source_research_commit || '').slice(0, 10) || '—'}`));
    if (Array.isArray(data.limitations) && data.limitations.length) {
      const list = el('ul');
      data.limitations.forEach((note) => list.appendChild(el('li', 'muted-text', note)));
      methodBox.appendChild(list);
    }
    container.appendChild(methodBox);
  };

  nodes.run.addEventListener('click', async () => {
    const ticker = nodes.ticker.value.trim();
    const period1 = nodes.period1.value.trim().toUpperCase();
    const period2 = nodes.period2.value.trim().toUpperCase();
    if (!/^\d{4,6}$/.test(ticker)) {
      status('請輸入台股公司代號，例如 2330。', true);
      return;
    }
    if (Boolean(period1) !== Boolean(period2) || [period1, period2].some((p) => p && !/^20\d{2}Q[1-4]$/.test(p))) {
      status('期間需同時填寫且格式如 2025Q3，或都留空。', true);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    nodes.run.disabled = true;
    nodes.run.textContent = '分析中…';
    status(`正在比較 ${ticker} 的官方法說會文件…`);
    try {
      const body = { company_code: ticker };
      if (period1) Object.assign(body, { period_1: period1, period_2: period2 });
      const response = await fetch('/api/financial/data-shift/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      let payload = null;
      try {
        payload = await response.json();
      } catch (_) {
        payload = null;
      }
      if (!response.ok || !payload || !payload.success || !payload.data) {
        status(response.status === 400 && payload && payload.error ? payload.error
          : response.status >= 500 ? '跨期分析服務暫時無法使用，請稍後再試。' : '跨期分析請求未被接受。', true);
        return;
      }
      render(payload.data);
      nodes.empty.hidden = true;
      nodes.result.hidden = false;
      status(payload.data.analysis_status === 'insufficient_data' ? '資料不足，已列出可用文件。' : `${ticker} 跨期分析完成。`);
    } catch (error) {
      status(error && error.name === 'AbortError' ? '跨期分析逾時，請稍後再試。' : '無法連線到跨期分析服務。', true);
    } finally {
      clearTimeout(timer);
      nodes.run.disabled = false;
      nodes.run.textContent = '執行跨期分析';
    }
  });

  contextTicker().then((ticker) => {
    if (ticker && !nodes.ticker.value) nodes.ticker.value = ticker;
  });
})();
