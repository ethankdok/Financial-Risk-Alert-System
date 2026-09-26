/* 說法查證：official.html only.
 * Browser → same-origin Flask /api/financial/claims/verify → FinTrustClient → FastAPI.
 * All response text is rendered with textContent; no HTML from the server is injected.
 */
(() => {
  const form = document.getElementById('claimVerifyForm');
  if (!form) return;

  const nodes = {
    company: document.getElementById('claimCompany'),
    claim: document.getElementById('claimText'),
    submit: document.getElementById('claimVerifySubmit'),
    loading: document.getElementById('claimLoading'),
    error: document.getElementById('claimError'),
    result: document.getElementById('claimResult'),
  };
  const TIMEOUT_MS = 60000;

  const VERDICTS = {
    supported: { label: '官方資料支持', tag: 'tag-green' },
    conflicting: { label: '與官方資料不一致', tag: 'tag-red' },
    insufficient_evidence: { label: '證據不足', tag: 'tag-orange' },
  };
  const RELATIONS = {
    supports: { label: '支持說法', tag: 'tag-green' },
    conflicts: { label: '與說法不一致', tag: 'tag-red' },
    context: { label: '參考資料', tag: 'tag-blue' },
  };
  const STATUSES = {
    verified: '已驗證',
    partially_verified: '部分驗證',
    needs_review: '待人工複核',
    metadata_only: '僅有公告標題',
  };
  const SOURCE_TYPES = {
    financial_fact: '官方財報數值',
    financial_metric: '官方財報計算指標',
    conference_table: '法說會簡報表格',
    conference_chart: '法說會簡報圖表',
    conference_text: '法說會簡報文字',
    official_announcement: '官方重大訊息',
  };
  const CLAIM_TYPES = {
    numeric_metric: '財務數值',
    percentage_mix: '營收占比',
    trend: '趨勢／變化方向',
    company_statement: '公司聲明',
    operational_metric: '營運數據',
    unsupported: '不支援的說法類型',
  };
  const COMPARATORS = { lt: '低於', gt: '高於' };

  const el = (tag, className, textValue) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (textValue !== undefined && textValue !== null) node.textContent = String(textValue);
    return node;
  };
  const tag = (label, className) => el('span', `status-tag ${className}`, label);
  const field = (list, label, value) => {
    if (value === undefined || value === null || value === '') return;
    const row = el('div');
    row.append(el('b', null, `${label}：`), document.createTextNode(String(value)));
    list.appendChild(row);
  };
  const safeUrl = (value) => {
    try {
      const url = new URL(String(value || ''));
      return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
    } catch (_) {
      return null;
    }
  };

  const setBusy = (busy) => {
    nodes.submit.disabled = busy;
    nodes.submit.textContent = busy ? '查證中…' : '開始查證';
    nodes.loading.hidden = !busy;
  };
  const showError = (message) => {
    nodes.result.hidden = true;
    nodes.error.textContent = message;
    nodes.error.hidden = false;
  };

  const renderInterpretation = (claim) => {
    const box = el('div', 'financial-official-item');
    box.appendChild(el('h4', null, '系統解讀'));
    const list = el('div', 'reason-list');
    field(list, '說法類型', CLAIM_TYPES[claim.claim_type] || claim.claim_type);
    field(list, '公司', [claim.company_code, claim.company_name].filter(Boolean).join(' '));
    field(list, '指標／主題', claim.metric_or_topic);
    field(list, '期間', claim.period);
    if (claim.comparison_period) field(list, '比較期間', claim.comparison_period);
    if (claim.value !== null && claim.value !== undefined) {
      field(list, '說法數值', `${COMPARATORS[claim.comparator] || ''}${claim.value_text || claim.value}${claim.unit || ''}`);
    }
    if (claim.missing_fields && claim.missing_fields.length) field(list, '無法辨識的欄位', claim.missing_fields.join('、'));
    field(list, '解析方式', claim.extraction_method === 'deterministic' ? '規則式解析' : '規則式解析＋語意輔助（需複核）');
    box.appendChild(list);
    return box;
  };

  const renderEvidence = (item) => {
    const card = el('article', 'financial-official-item');
    const head = el('div', 'financial-rule-head');
    head.appendChild(el('b', null, SOURCE_TYPES[item.source_type] || item.source_type));
    const relation = RELATIONS[item.relation] || RELATIONS.context;
    head.appendChild(tag(relation.label, relation.tag));
    if (item.decisive) head.appendChild(tag('判定依據', 'tag-blue'));
    card.appendChild(head);

    const list = el('div');
    field(list, '來源', item.source_title);
    field(list, '文件', item.document);
    field(list, '日期', item.source_date);
    field(list, '頁碼', item.page ? `第 ${item.page} 頁` : null);
    field(list, '期間', item.period);
    field(list, '項目', item.label || item.metric);
    field(list, '官方數值', item.value !== null && item.value !== undefined
      ? `${item.value}${item.unit && !String(item.value).endsWith('%') ? ` ${item.unit}` : ''}` : null);
    field(list, '驗證狀態', STATUSES[item.verification_status] || item.verification_status);
    if (item.comparison && item.comparison.formula) field(list, '比對', item.comparison.formula);
    card.appendChild(list);

    if (item.source_text) {
      const quote = el('p', null, item.source_text);
      card.appendChild(quote);
    }
    if (item.note) card.appendChild(el('small', 'muted-text', item.note));
    const url = safeUrl(item.source_reference);
    if (url) {
      const link = el('a', 'feature-link', '查看官方來源');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      card.appendChild(el('div')).appendChild(link);
    }
    return card;
  };

  const renderResult = (data) => {
    const verdict = VERDICTS[data.verdict] || VERDICTS.insufficient_evidence;
    nodes.result.replaceChildren();

    const head = el('div', 'financial-official-group');
    const title = el('h3');
    title.append('判定：', tag(verdict.label, verdict.tag));
    head.appendChild(title);
    head.appendChild(el('p', null, data.summary));
    const original = el('p', 'muted-text');
    original.append(el('b', null, '原始說法：'), document.createTextNode(data.request ? data.request.claim : ''));
    head.appendChild(original);
    if (data.requires_review) head.appendChild(tag('建議人工複核', 'tag-orange'));
    nodes.result.appendChild(head);

    if (data.structured_claim) nodes.result.appendChild(renderInterpretation(data.structured_claim));

    const evidence = Array.isArray(data.evidence) ? data.evidence : [];
    const evidenceGroup = el('div', 'financial-official-group');
    evidenceGroup.appendChild(el('h4', null, `官方證據（${evidence.length} 筆）`));
    if (!evidence.length) {
      evidenceGroup.appendChild(el('p', 'muted-text', '目前收錄的官方資料中沒有可對應此說法的證據。'));
    } else {
      const grid = el('div', 'financial-official-grid');
      evidence.forEach((item) => grid.appendChild(renderEvidence(item)));
      evidenceGroup.appendChild(grid);
    }
    nodes.result.appendChild(evidenceGroup);

    if (Array.isArray(data.limitations) && data.limitations.length) {
      const limits = el('div', 'financial-official-group');
      limits.appendChild(el('h4', null, '限制說明'));
      const list = el('ul');
      data.limitations.forEach((note) => list.appendChild(el('li', 'muted-text', note)));
      limits.appendChild(list);
      nodes.result.appendChild(limits);
    }
    nodes.error.hidden = true;
    nodes.result.hidden = false;
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const companyCode = nodes.company.value.trim();
    const claim = nodes.claim.value.trim();
    if (!companyCode || claim.length < 2) {
      showError('請輸入公司代號與想查證的說法。');
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    setBusy(true);
    nodes.error.hidden = true;
    try {
      const response = await fetch('/api/financial/claims/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ company_code: companyCode, claim }),
        signal: controller.signal,
      });
      let payload = null;
      try {
        payload = await response.json();
      } catch (_) {
        payload = null;
      }
      if (!response.ok || !payload || !payload.success || !payload.data || !payload.data.verdict) {
        if (response.status === 400 && payload && payload.error) showError(payload.error);
        else if (response.status >= 500) showError('查證服務暫時無法使用，請稍後再試。');
        else if (!response.ok) showError('查證請求未被接受，請確認輸入內容後再試。');
        else showError('查證服務回應格式異常，請稍後再試。');
        return;
      }
      renderResult(payload.data);
    } catch (error) {
      showError(error && error.name === 'AbortError' ? '查證逾時，請稍後再試。' : '無法連線到查證服務，請確認網路後再試。');
    } finally {
      clearTimeout(timer);
      setBusy(false);
    }
  });
})();
