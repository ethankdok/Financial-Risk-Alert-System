document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-chip]').forEach(chip=>{chip.addEventListener('click',()=>{const target=document.querySelector(chip.dataset.target||'#keyword');if(target){target.value=chip.dataset.chip;target.focus();}});});
  document.querySelectorAll('.search-tab').forEach(tab=>{tab.addEventListener('click',()=>{document.querySelectorAll('.search-tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.search-panel').forEach(x=>x.classList.remove('active'));tab.classList.add('active');document.getElementById('tab-'+tab.dataset.tab).classList.add('active');});});
  document.querySelectorAll('.ai-example').forEach(chip=>chip.addEventListener('click',()=>{const box=document.querySelector('#tab-ai textarea');box.value=chip.textContent.trim();}));
  const imageInput=document.getElementById('imageInput');if(imageInput){imageInput.addEventListener('change',()=>{document.getElementById('fileName').textContent=imageInput.files[0]?`已選擇：${imageInput.files[0].name}`:'尚未選擇圖片';});}
  const voiceButton=document.getElementById('voiceButton');if(voiceButton){voiceButton.addEventListener('click',()=>{document.getElementById('voiceStatus').textContent='展示模式：已接收語音「查詢聯發科近期財報與官方資訊是否支持市場樂觀說法」。';const ta=document.querySelector('#tab-voice textarea');if(ta)ta.value='查詢聯發科近期財報與官方資訊是否支持市場樂觀說法。';});}
  const demoForm=document.querySelector('#analysisForm');if(demoForm){demoForm.addEventListener('submit',e=>{e.preventDefault();const active=document.querySelector('.search-panel.active');const field=active?active.querySelector('textarea,input[type="text"],input:not([type])'):null;const q=(field&&field.value.trim())||'聯發科近期財報與官方資訊是否支持市場樂觀說法？';localStorage.setItem('demoQuery',q);window.location.href='/analyzing';});}
  document.querySelectorAll('.home-example').forEach(chip=>chip.addEventListener('click',()=>{const box=document.getElementById('homeAiQuery');box.value=chip.textContent.trim();box.focus();}));
  const homeBtn=document.getElementById('homeAiSubmit');if(homeBtn){homeBtn.addEventListener('click',()=>{const q=document.getElementById('homeAiQuery').value.trim()||'聯發科近期財報與官方資訊是否支持市場樂觀說法？';localStorage.setItem('demoQuery',q);window.location.href='/analyzing';});}
  const q=localStorage.getItem('demoQuery')||'聯發科近期財報與官方資訊是否支持市場樂觀說法？';const loadingQuery=document.getElementById('loadingQuery');if(loadingQuery)loadingQuery.textContent=`查詢內容：「${q}」`;const summaryQuery=document.getElementById('summaryQuery');if(summaryQuery)summaryQuery.textContent=`查詢內容：「${q}」｜整合三個資料來源產生初步結論。`;
  if(document.body.querySelector('.analysis-loading-shell')){
    const question = localStorage.getItem('demoQuery')
        || '聯發科近期財報與官方資訊是否支持市場樂觀說法？';

    fetch('/api/analyze', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            question: question
        })
    })
    .then(async response => {
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || '分析失敗');
        }

        localStorage.setItem('analysisResult', JSON.stringify(data));

        setTimeout(() => {
            window.location.href = '/summary';
        }, 1500);
    })
    .catch(error => {
        console.error(error);

        const note = document.querySelector('.loading-note');

        if (note) {
            note.textContent = '分析失敗：' + error.message;
        }
    });
}
});

document.addEventListener('DOMContentLoaded', () => {
  const summaryPage = document.querySelector('.ai-overview-card');

  if (!summaryPage) {
    return;
  }

  const rawResult = localStorage.getItem('analysisResult');

  if (!rawResult) {
    return;
  }

  try {
    const data = JSON.parse(rawResult);

    const summaryQuery = document.getElementById('summaryQuery');
    if (summaryQuery) {
      summaryQuery.textContent =
        `查詢內容：「${data.question}」｜整合三個資料來源產生初步結論。`;
    }

    const title = document.querySelector('.ai-overview-head h2');
    if (title) {
      title.textContent = data.summary;
    }

    const statusTag = document.querySelector('.ai-overview-head .status-tag');
    if (statusTag) {
      statusTag.textContent = data.risk_level;
    }

    const overviewCopy = document.querySelector('.overview-copy');
    if (overviewCopy) {
      overviewCopy.textContent = data.summary;
    }

    const metricValues = document.querySelectorAll('.overview-metrics strong');

    if (metricValues.length >= 3) {
      metricValues[0].textContent = `${data.credibility_score}%`;
      metricValues[1].textContent = data.risk_level;
      metricValues[2].textContent = `${data.sources.length} 類`;
    }

    const reasonItems = document.querySelectorAll('.reason-list .reason');

    data.reasons.forEach((reason, index) => {
      if (!reasonItems[index]) {
        return;
      }

      const titleElement = reasonItems[index].querySelector('b');
      const descriptionElement = reasonItems[index].querySelector('span');

      if (titleElement) {
        titleElement.textContent = reason;
      }

      if (descriptionElement) {
        descriptionElement.textContent = reason;
      }
    });

    const sourceCards = document.querySelectorAll('.source-cards article');

    data.sources.forEach((source, index) => {
      if (!sourceCards[index]) {
        return;
      }

      const label = sourceCards[index].querySelector('.source-label');
      const heading = sourceCards[index].querySelector('h4');
      const description = sourceCards[index].querySelector('p');

      if (label) {
        label.textContent = source;
      }

      if (heading) {
        heading.textContent = `${source} 查詢結果`;
      }

      if (description) {
        description.textContent =
          '此區塊目前使用模擬資料，之後可接入實際爬蟲結果與來源連結。';
      }
    });
  } catch (error) {
    console.error('無法讀取分析結果：', error);
  }
});

document.addEventListener('DOMContentLoaded', () => {
  const FINANCIAL_DEMO_TICKER = '2454';

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function severityLabel(value) {
    const labels = {
      normal: '正常',
      attention: '需注意',
      warning: '需注意',
      high: '高關注',
      critical: '高關注',
      positive: '正向觀察',
      insufficient_data: '資料不足'
    };
    return labels[value] || value || '—';
  }

  function severityClass(value) {
    if (['high', 'critical'].includes(value)) return 'tag-red';
    if (['attention', 'warning'].includes(value)) return 'tag-orange';
    if (value === 'positive') return 'tag-green';
    return 'tag-blue';
  }

  function formatNumber(value, unit = '') {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    const number = Number(value);
    if (Math.abs(number) >= 100000000) {
      return `${(number / 100000000).toLocaleString('zh-TW', { maximumFractionDigits: 2 })} 億${unit.includes('元') ? '元' : ''}`;
    }
    return number.toLocaleString('zh-TW', { maximumFractionDigits: 2 });
  }

  function formatMetric(metric) {
    const value = formatNumber(metric.latest_value, metric.unit);
    const unit = metric.unit && !String(value).includes(metric.unit) && !String(value).includes('億') ? metric.unit : '';
    return `${value}${unit}`;
  }

  async function fetchFinancialCard(ticker = FINANCIAL_DEMO_TICKER) {
    const response = await fetch(`/api/financial/companies/${ticker}/card`);
    const result = await response.json();
    if (!response.ok && !result.data) {
      throw new Error(result.error || '無法取得財報官方證據');
    }
    return result.data || {};
  }

  function renderSummaryCard(container, card) {
    const ticker = card.ticker || container.dataset.ticker || FINANCIAL_DEMO_TICKER;
    const status = container.querySelector('[data-fin-status]');
    const company = container.querySelector('[data-fin-company]');
    const summary = container.querySelector('[data-fin-summary]');
    const metrics = container.querySelector('[data-fin-metrics]');
    const note = container.querySelector('[data-fin-note]');

    if (company) company.textContent = `${card.company_name || ticker}財報官方證據`;
    if (status) {
      status.textContent = severityLabel(card.overall_severity || card.evidence_readiness);
      status.className = `status-tag ${severityClass(card.overall_severity)}`;
    }
    if (summary) {
      summary.textContent = card.summary || '目前尚未取得完整財報摘要；請確認 FinTrust FastAPI 是否已完成 refresh。';
    }

    const keyMetrics = (card.key_metrics || []).slice(0, 4);
    if (metrics) {
      if (keyMetrics.length) {
        metrics.innerHTML = keyMetrics.map(metric => `
          <div>
            <span>${escapeHtml(metric.label || metric.code)}</span>
            <strong>${escapeHtml(formatMetric(metric))}</strong>
          </div>
        `).join('');
      } else {
        metrics.innerHTML = `
          <div><span>公司</span><strong>${escapeHtml(ticker)}</strong></div>
          <div><span>證據狀態</span><strong>${escapeHtml(card.evidence_readiness || '—')}</strong></div>
          <div><span>官方來源</span><strong>${(card.official_sources || []).length}</strong></div>
          <div><span>限制說明</span><strong>${(card.limitations || []).length}</strong></div>
        `;
      }
    }

    if (note) {
      const limitations = card.limitations || [];
      note.textContent = limitations[0] || '財報證據層僅提供官方資料與規則引擎佐證，不構成投資建議。';
    }
  }

  function renderDetailCard(container, card) {
    const ticker = card.ticker || container.dataset.ticker || FINANCIAL_DEMO_TICKER;
    const title = container.querySelector('[data-fin-detail-title]');
    const status = container.querySelector('[data-fin-detail-status]');
    const metricBody = container.querySelector('[data-fin-detail-metrics]');
    const ruleList = container.querySelector('[data-fin-detail-rules]');
    const sourceList = container.querySelector('[data-fin-detail-sources]');
    const limitationList = container.querySelector('[data-fin-detail-limitations]');

    if (title) title.textContent = `${card.company_name || ticker}官方財報證據詳細分析`;
    if (status) {
      status.textContent = severityLabel(card.overall_severity || card.evidence_readiness);
      status.className = `status-tag ${severityClass(card.overall_severity)}`;
    }

    const keyMetrics = card.key_metrics || [];
    if (metricBody) {
      metricBody.innerHTML = keyMetrics.length ? keyMetrics.slice(0, 8).map(metric => `
        <tr>
          <td>${escapeHtml(metric.label || metric.code)}</td>
          <td>${escapeHtml(formatMetric(metric))}</td>
          <td>${escapeHtml(formatNumber(metric.previous_value, metric.unit))}</td>
          <td>${metric.change_percent === null || metric.change_percent === undefined ? '—' : `${escapeHtml(formatNumber(metric.change_percent))}%`}</td>
        </tr>
      `).join('') : '<tr><td colspan="4">尚無可顯示的關鍵財務指標。</td></tr>';
    }

    const rules = (card.rule_cards || []).slice(0, 6);
    if (ruleList) {
      ruleList.innerHTML = rules.length ? rules.map(rule => `
        <article class="financial-rule-item">
          <div>
            <b>${escapeHtml(rule.name || rule.rule_id)}</b>
            <span>${escapeHtml(rule.category || '規則引擎')}</span>
          </div>
          <span class="status-tag ${rule.triggered ? 'tag-orange' : 'tag-blue'}">${rule.triggered ? '觸發' : '未觸發'}</span>
          <p>${escapeHtml(rule.explanation || '')}</p>
        </article>
      `).join('') : '<p class="muted-text">尚無規則卡片資料。</p>';
    }

    const sources = (card.official_sources || []).slice(0, 3);
    if (sourceList) {
      sourceList.innerHTML = sources.length ? sources.map(source => `
        <article>
          <span class="source-label">${escapeHtml(source.status || 'official')}</span>
          <h4>${escapeHtml(source.source_name || '官方資料來源')}</h4>
          <p>${escapeHtml(source.period || source.limitation || 'MOPS / TWSE 官方資料來源')}</p>
        </article>
      `).join('') : '<article><span class="source-label">metadata</span><h4>官方資料來源</h4><p>目前尚無可顯示的來源清單。</p></article>';
    }

    if (limitationList) {
      const limitations = (card.limitations || []).slice(0, 4);
      limitationList.innerHTML = limitations.length
        ? limitations.map(item => `<li>${escapeHtml(item)}</li>`).join('')
        : '<li>財報證據層僅提供官方資料佐證，不構成投資建議。</li>';
    }
  }

  function renderFinancialError(container, error) {
    const target = container.querySelector('[data-fin-summary], [data-fin-detail-rules]');
    const status = container.querySelector('[data-fin-status], [data-fin-detail-status]');
    if (status) {
      status.textContent = '讀取失敗';
      status.className = 'status-tag tag-red';
    }
    if (target) {
      target.textContent = `無法讀取財報官方證據：${error.message}`;
    }
  }

  document.querySelectorAll('[data-financial-card]').forEach(async container => {
    try {
      const card = await fetchFinancialCard(container.dataset.ticker || FINANCIAL_DEMO_TICKER);
      renderSummaryCard(container, card);
    } catch (error) {
      console.error('financial summary card failed:', error);
      renderFinancialError(container, error);
    }
  });

  document.querySelectorAll('[data-financial-detail]').forEach(async container => {
    try {
      const card = await fetchFinancialCard(container.dataset.ticker || FINANCIAL_DEMO_TICKER);
      renderDetailCard(container, card);
    } catch (error) {
      console.error('financial detail card failed:', error);
      renderFinancialError(container, error);
    }
  });
});
