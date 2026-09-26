document.addEventListener('DOMContentLoaded', () => {

  // =========================================================
  // 共用互動
  // =========================================================

  document
    .querySelectorAll('[data-chip]')
    .forEach(chip => {

      chip.addEventListener('click', () => {

        const target = document.querySelector(
          chip.dataset.target || '#keyword'
        );

        if (target) {
          target.value = chip.dataset.chip;
          target.focus();
        }

      });

    });


  document
    .querySelectorAll('.search-tab')
    .forEach(tab => {

      tab.addEventListener('click', () => {

        document
          .querySelectorAll('.search-tab')
          .forEach(x => x.classList.remove('active'));

        document
          .querySelectorAll('.search-panel')
          .forEach(x => x.classList.remove('active'));

        tab.classList.add('active');

        const target = document.getElementById(
          'tab-' + tab.dataset.tab
        );

        if (target) {
          target.classList.add('active');
        }

      });

    });


  document
    .querySelectorAll('.ai-example')
    .forEach(chip => {

      chip.addEventListener('click', () => {

        const box = document.querySelector(
          '#tab-ai textarea'
        );

        if (box) {
          box.value = chip.textContent.trim();
        }

      });

    });


  // =========================================================
  // 圖片
  // =========================================================

  const imageInput = document.getElementById(
    'imageInput'
  );

  if (imageInput) {

    imageInput.addEventListener(
      'change',
      () => {

        const label = document.getElementById(
          'fileName'
        );

        if (!label) return;

        label.textContent =
          imageInput.files[0]
            ? `已選擇：${imageInput.files[0].name}`
            : '尚未選擇圖片';

      }
    );

  }


  // =========================================================
  // 語音 Demo
  // =========================================================

  const voiceButton = document.getElementById(
    'voiceButton'
  );

  if (voiceButton) {

    voiceButton.addEventListener(
      'click',
      () => {

        const status = document.getElementById(
          'voiceStatus'
        );

        if (status) {
          status.textContent =
            '已接收語音「查詢台積電最近的重大訊息，以及保證漲停貼文是否可信」。';
        }

        const ta = document.querySelector(
          '#tab-voice textarea'
        );

        if (ta) {
          ta.value =
            '查詢台積電最近的重大訊息，以及保證漲停貼文是否可信。';
        }

      }
    );

  }


  // =========================================================
  // Analysis Form
  // =========================================================

  const analysisForm = document.querySelector(
    '#analysisForm'
  );

  if (analysisForm) {

    analysisForm.addEventListener(
      'submit',
      e => {

        e.preventDefault();

        const active = document.querySelector(
          '.search-panel.active'
        );

        const field = active
          ? active.querySelector(
              'textarea,input[type="text"],input:not([type])'
            )
          : null;

        const q =
          (field && field.value.trim())
          ||
          '台積電下週保證漲停是真的嗎？';

        localStorage.setItem(
          'analysisQuery',
          q
        );

        localStorage.removeItem(
          'dataShiftResult'
        );

        window.location.href =
          'analyzing.html';

      }
    );

  }


  // =========================================================
  // Home Example
  // =========================================================

  document
    .querySelectorAll('.home-example')
    .forEach(chip => {

      chip.addEventListener(
        'click',
        () => {

          const box = document.getElementById(
            'homeAiQuery'
          );

          if (!box) return;

          box.value =
            chip.textContent.trim();

          box.focus();

        }
      );

    });


  const homeBtn = document.getElementById(
    'homeAiSubmit'
  );

  if (homeBtn) {

    homeBtn.addEventListener(
      'click',
      () => {

        const box = document.getElementById(
          'homeAiQuery'
        );

        const q =
          box?.value.trim()
          ||
          '台積電下週保證漲停是真的嗎？';

        localStorage.setItem(
          'analysisQuery',
          q
        );

        window.location.href =
          'analyzing.html';

      }
    );

  }


  // =========================================================
  // Query Display
  // =========================================================

  const q =
    localStorage.getItem(
      'analysisQuery'
    )
    ||
    '台積電下週保證漲停是真的嗎？';


  const loadingQuery =
    document.getElementById(
      'loadingQuery'
    );

  if (loadingQuery) {

    loadingQuery.textContent =
      `查詢內容：「${q}」`;

  }


  const summaryQuery =
    document.getElementById(
      'summaryQuery'
    );

  if (summaryQuery) {

    summaryQuery.textContent =
      `查詢內容：「${q}」｜整合三個資料來源產生初步結論。`;

  }

});



/* ===========================================================
   V4.2 REAL BACKEND FLOW
   =========================================================== */

(() => {

  const page =
    location.pathname
      .split('/')
      .pop();


  // =========================================================
  // Escape HTML
  // =========================================================

  const esc = value =>
    String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');


  // =========================================================
  // Risk Analysis
  // analyzing.html
  // =========================================================

  if (page === 'analyzing.html') {

    const query =
      localStorage.getItem(
        'analysisQuery'
      )
      || '';


    async function runAnalysis() {

      if (!query.trim()) {

        location.href =
          'analysis.html';

        return;

      }


      try {

        const response =
          await fetch(
            '/api/analyze',
            {
              method: 'POST',

              headers: {
                'Content-Type':
                  'application/json'
              },

              body: JSON.stringify({
                text: query
              })
            }
          );


        const data =
          await response.json();


        if (!response.ok) {

          throw new Error(
            data.error
            ||
            `HTTP ${response.status}`
          );

        }


        localStorage.setItem(
          'analysisResult',
          JSON.stringify(data)
        );


        setTimeout(
          () => {

            location.href =
              'result.html';

          },
          700
        );

      }

      catch (error) {

        console.error(
          'Analysis API Error:',
          error
        );


        const loadingQuery =
          document.getElementById(
            'loadingQuery'
          );


        if (loadingQuery) {

          loadingQuery.textContent =
            '分析失敗：'
            +
            error.message;

        }

      }

    }


    runAnalysis();

  }



  // =========================================================
  // Result Page
  // =========================================================

  if (page === 'result.html') {

    renderRiskResult();

    renderStoredDataShiftResult();

    bindAutoDataShift();

  }



  // =========================================================
  // Risk Result Renderer
  // =========================================================

  function renderRiskResult() {

    const raw =
      localStorage.getItem(
        'analysisResult'
      );


    if (!raw) return;


    let data;


    try {

      data =
        JSON.parse(raw);

    }

    catch (e) {

      console.error(
        '無法讀取分析結果',
        e
      );

      return;

    }


    // -------------------------------------------------------
    // Query
    // -------------------------------------------------------

    const heroQuery =
      document.querySelector(
        '.page-hero p'
      );


    if (heroQuery) {

      heroQuery.textContent =
        `查詢內容：「${data.text || ''}」`;

    }



    // -------------------------------------------------------
    // Score
    // -------------------------------------------------------

    const score =
      Math.max(
        0,
        Math.min(
          100,
          Number(data.score) || 0
        )
      );


    const scoreNumber =
      document.querySelector(
        '.score-ring strong'
      );


    if (scoreNumber) {

      scoreNumber.textContent =
        score;

    }


    const scoreRing =
      document.querySelector(
        '.score-ring'
      );


    if (scoreRing) {

      scoreRing.style.background =
        `conic-gradient(
          var(--orange) 0 ${score}%,
          #dfe8f4 ${score}% 100%
        )`;

    }


    const progressBar =
      document.querySelector(
        '.progress span'
      );


    if (progressBar) {

      progressBar.style.width =
        `${score}%`;

    }



    // -------------------------------------------------------
    // Description
    // -------------------------------------------------------

    const resultTitle =
      document.querySelector(
        '.result-report-main h2'
      );


    if (resultTitle) {

      resultTitle.textContent =
        '風險分析分數';

    }


    const resultDescription =
      document.querySelector(
        '.result-report-main p'
      );


    if (resultDescription) {

      resultDescription.textContent =
        `共命中 ${
          data.summary
            ?.keyword_count
          ?? 0
        } 個關鍵字、${
          data.summary
            ?.feature_count
          ?? 0
        } 個風險特徵。`;

    }



    // -------------------------------------------------------
    // Risk Level
    // -------------------------------------------------------

    const riskStrong =
      document.querySelector(
        '.risk-box strong'
      );


    if (riskStrong) {

      riskStrong.textContent =
        data.risk_level
        ||
        '低風險';

    }


    const riskSmall =
      document.querySelector(
        '.risk-box small'
      );


    if (riskSmall) {

      riskSmall.textContent =

        data.risk_level
          === '高風險'

          ? '建議提高警覺並進一步查證'

          : data.risk_level
              === '中風險'

            ? '建議檢查資訊來源與相關證據'

            : '目前未偵測到明顯高風險訊號';

    }



    // -------------------------------------------------------
    // Reasons
    // -------------------------------------------------------

    const reasonList =
      document.querySelector(
        '.reason-list'
      );


    if (reasonList) {

      if (
        data.matched_features
          ?.length
      ) {

        reasonList.innerHTML =
          data
            .matched_features
            .map(
              (
                feature,
                index
              ) => {

                const hits =
                  (
                    feature
                      .matched_keywords
                    ||
                    []
                  )
                  .join('、');


                return `
                  <div class="reason">

                    <div>
                      ${
                        String(
                          index + 1
                        )
                        .padStart(
                          2,
                          '0'
                        )
                      }
                    </div>

                    <div>

                      <b>
                        ${
                          esc(
                            feature.name
                          )
                        }
                      </b>

                      <span>

                        ${
                          esc(
                            feature.explain
                            ||
                            feature.definition
                            ||
                            ''
                          )
                        }

                        ${
                          hits
                            ? `（命中：${esc(hits)}）`
                            : ''
                        }

                      </span>

                    </div>

                  </div>
                `;

              }
            )
            .join('');

      }

      else {

        reasonList.innerHTML =
          `
            <div class="reason">

              <div>
                01
              </div>

              <div>

                <b>
                  未偵測到明顯風險特徵
                </b>

                <span>
                  目前內容未命中後台啟用中的風險特徵。
                </span>

              </div>

            </div>
          `;

      }

    }

  }



  // =========================================================
  // Data Shift API
  //
  // 之後任何頁面只要呼叫：
  //
  // window.runDataShift({
  //   ticker: "...",
  //   source_type: "...",
  //   period_1: "...",
  //   period_2: "...",
  //   text_1: "...",
  //   text_2: "..."
  // });
  //
  // =========================================================

  window.runDataShift =
    async function(payload) {

      try {

        const response =
          await fetch(
            '/api/data-shift',
            {

              method: 'POST',

              headers: {

                'Content-Type':
                  'application/json'

              },

              body:
                JSON.stringify(
                  payload
                )

            }
          );


        const result =
          await response.json();


        if (!response.ok) {

          throw new Error(
            result.error
            ||
            `HTTP ${response.status}`
          );

        }


        localStorage.setItem(
          'dataShiftResult',
          JSON.stringify(
            result.data
          )
        );


        return result.data;

      }

      catch (error) {

        console.error(
          'Data Shift API Error:',
          error
        );


        throw error;

      }

    };




  // =========================================================
  // Auto Data Shift
  //
  // 使用者只要輸入 ticker，例如 AMT，
  // 後端會從 STRUX 自動抓最新兩期法說會並分析。
  // =========================================================

  function bindAutoDataShift() {

    const button =
      document.getElementById(
        'runDataShiftButton'
      );

    const input =
      document.getElementById(
        'driftTickerInput'
      );

    if (!button || !input) {
      return;
    }

    button.addEventListener(
      'click',
      async () => {

        const ticker =
          input.value
            .trim()
            .toUpperCase();

        if (!ticker) {
          setRunStatus(
            '請先輸入股票代號。',
            true
          );
          return;
        }

        button.disabled = true;
        button.textContent =
          '分析中…';

        setRunStatus(
          `正在取得 ${ticker} 最新兩期 STRUX 法說會資料並計算 JSD / Cosine…`,
          false
        );

        try {

          const response =
            await fetch(
              '/api/data-shift/auto',
              {
                method: 'POST',

                headers: {
                  'Content-Type':
                    'application/json'
                },

                body: JSON.stringify({
                  ticker
                })
              }
            );

          const result =
            await response.json();

          if (!response.ok) {
            throw new Error(
              result.error
              ||
              `HTTP ${response.status}`
            );
          }

          localStorage.setItem(
            'dataShiftResult',
            JSON.stringify(
              result.data
            )
          );

          renderDataShift(
            result.data
          );

          setRunStatus(
            `${ticker} 跨期分析完成。`,
            false
          );

        }

        catch (error) {

          console.error(
            'Auto Data Shift Error:',
            error
          );

          setRunStatus(
            '分析失敗：'
            + error.message,
            true
          );

        }

        finally {

          button.disabled = false;
          button.textContent =
            '執行跨期分析';

        }

      }
    );


    input.addEventListener(
      'keydown',
      event => {

        if (event.key === 'Enter') {
          event.preventDefault();
          button.click();
        }

      }
    );

  }


  function setRunStatus(
    text,
    isError
  ) {

    const element =
      document.getElementById(
        'driftRunStatus'
      );

    if (!element) {
      return;
    }

    element.textContent = text;

    element.style.color =
      isError
        ? '#b42318'
        : '#52606d';

  }


  // =========================================================
  // Stored Data Shift Result
  // =========================================================

  function renderStoredDataShiftResult() {

    const raw =
      localStorage.getItem(
        'dataShiftResult'
      );


    if (!raw) {

      return;

    }


    try {

      const data =
        JSON.parse(raw);


      renderDataShift(
        data
      );

    }

    catch (error) {

      console.error(
        'Data Shift Result Parse Error:',
        error
      );

    }

  }



  // =========================================================
  // Data Shift Renderer
  // =========================================================

  function renderDataShift(data) {

    const empty =
      document.getElementById(
        'dataShiftEmpty'
      );


    const content =
      document.getElementById(
        'dataShiftContent'
      );


    if (
      !content
    ) {

      return;

    }


    if (empty) {

      empty.style.display =
        'none';

    }


    content.style.display =
      'block';



    // -------------------------------------------------------
    // Basic Info
    // -------------------------------------------------------

    setText(
      'driftTicker',
      data.ticker || '—'
    );


    setText(
      'driftPeriod',

      `${data.period_1 || '—'}
       → 
       ${data.period_2 || '—'}`
    );


    setText(
      'driftSource',
      data.dataset
        ? `${data.dataset}／${sourceName(data.source_type)}`
        : sourceName(
            data.source_type
          )
    );



    // -------------------------------------------------------
    // Metrics
    // -------------------------------------------------------

    const jsd =
      Number(
        data.metrics?.jsd
      );


    const cosine =
      Number(
        data.metrics
          ?.cosine_similarity
      );


    setText(
      'driftJsd',
      Number.isFinite(jsd)
        ? jsd.toFixed(3)
        : '—'
    );


    setText(
      'driftCosine',
      Number.isFinite(cosine)
        ? cosine.toFixed(3)
        : '—'
    );


    setText(
      'driftLevel',
      data.drift?.level
      ||
      '—'
    );



    // -------------------------------------------------------
    // Data Quality
    // -------------------------------------------------------

    const qualityElement =
      document.getElementById(
        'driftQuality'
      );


    const passed =
      data.data_quality?.passed;


    if (qualityElement) {

      qualityElement.textContent =
        passed
          ? '✓ 通過'
          : '⚠ 未通過';


      qualityElement.classList.remove(
        'quality-ok',
        'quality-warning'
      );


      qualityElement.classList.add(
        passed
          ? 'quality-ok'
          : 'quality-warning'
      );

    }



    // -------------------------------------------------------
    // Threshold
    // -------------------------------------------------------

    const p90 =
      Number(
        data
          .drift
          ?.jsd_percentile_thresholds
          ?.p90
      );


    const p95 =
      Number(
        data
          .drift
          ?.jsd_percentile_thresholds
          ?.p95
      );


    const p99 =
      Number(
        data
          .drift
          ?.jsd_percentile_thresholds
          ?.p99
      );


    setText(
      'driftThresholdText',

      `本研究以歷史法說會資料建立經驗分布：
       P90 = ${format3(p90)}、
       P95 = ${format3(p95)}、
       P99 = ${format3(p99)}。`
    );



    // -------------------------------------------------------
    // Interpretation
    // -------------------------------------------------------

    let interpretation =
      '目前沒有足夠資料進行判讀。';


    if (
      Number.isFinite(jsd)
      &&
      Number.isFinite(p90)
    ) {

      if (
        Number.isFinite(p99)
        &&
        jsd >= p99
      ) {

        interpretation =
          `本次 JSD 為 ${jsd.toFixed(3)}，
           已高於歷史 P99 門檻 ${p99.toFixed(3)}，
           表示本期文字分布相較前一期出現高度異常變化。`;

      }

      else if (
        Number.isFinite(p95)
        &&
        jsd >= p95
      ) {

        interpretation =
          `本次 JSD 為 ${jsd.toFixed(3)}，
           已高於歷史 P95 門檻 ${p95.toFixed(3)}，
           表示兩期文字內容存在明顯資料漂移。`;

      }

      else if (
        jsd >= p90
      ) {

        interpretation =
          `本次 JSD 為 ${jsd.toFixed(3)}，
           已高於歷史 P90 門檻 ${p90.toFixed(3)}，
           文字分布變化值得進一步注意。`;

      }

      else {

        interpretation =
          `本次 JSD 為 ${jsd.toFixed(3)}，
           低於歷史 P90 門檻 ${p90.toFixed(3)}，
           目前未偵測到明顯資料漂移。`;

      }

    }


    if (!passed) {

      interpretation +=
        ' 但本次資料品質檢查未通過，因此漂移結果可能受到文字缺失或兩期篇幅差異影響。';

    }


    setText(
      'driftInterpretation',
      interpretation
    );



    // -------------------------------------------------------
    // Emerging Terms
    // -------------------------------------------------------

    renderTerms(
      'emergingTerms',
      data.emerging_terms,
      false
    );



    // -------------------------------------------------------
    // Disappearing Terms
    // -------------------------------------------------------

    renderTerms(
      'disappearingTerms',
      data.disappearing_terms,
      true
    );

  }



  // =========================================================
  // Helpers
  // =========================================================

  function setText(
    id,
    text
  ) {

    const el =
      document.getElementById(
        id
      );


    if (el) {

      el.textContent =
        text;

    }

  }


  function format3(
    value
  ) {

    return Number.isFinite(
      value
    )

      ? value.toFixed(3)

      : '—';

  }


  function sourceName(
    value
  ) {

    const mapping = {

      earnings_call:
        '法說會',

      financial_report:
        '財務報告',

      annual_report:
        '年報',

      mops:
        '公開資訊觀測站'

    };


    return mapping[value]
      ||
      value
      ||
      '—';

  }


  function renderTerms(
    elementId,
    terms,
    down
  ) {

    const container =
      document.getElementById(
        elementId
      );


    if (!container) {

      return;

    }


    if (
      !Array.isArray(terms)
      ||
      !terms.length
    ) {

      container.innerHTML =
        '<span class="term-tag">無明顯變化詞彙</span>';

      return;

    }


    container.innerHTML =
      terms
        .slice(0, 10)
        .map(item => {

          const term =
            esc(
              item.term
              ||
              ''
            );


          return `
            <span
              class="term-tag ${
                down
                  ? 'down'
                  : ''
              }"
            >
              ${term}
            </span>
          `;

        })
        .join('');

  }

})();


/* === FinTrust financial evidence frontend layer === */
(() => {
  const page = location.pathname.split('/').pop() || 'index.html';
  if (page !== 'result.html' && page !== 'result') return;

  const section = document.querySelector('[data-financial-evidence]');
  if (!section) return;

  const nodes = {
    state: section.querySelector('[data-financial-state]'),
    loading: section.querySelector('[data-financial-loading]'),
    empty: section.querySelector('[data-financial-empty]'),
    content: section.querySelector('[data-financial-content]'),
    summary: section.querySelector('[data-financial-summary]'),
    metrics: section.querySelector('[data-financial-metrics]'),
    rules: section.querySelector('[data-financial-rules]'),
    dimensions: section.querySelector('[data-financial-dimensions]'),
    llm: section.querySelector('[data-financial-llm]'),
    llmState: section.querySelector('[data-financial-llm-state]'),
    official: section.querySelector('[data-financial-official]'),
  };

  const text = (value, fallback = '尚未提供') => {
    if (value === null || value === undefined || value === '') return fallback;
    return String(value);
  };

  const clear = (element) => {
    if (!element) return;
    while (element.firstChild) element.removeChild(element.firstChild);
  };

  const el = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = text(value, '');
    return node;
  };

  const appendText = (parent, tag, className, value) => {
    const child = el(tag, className, value);
    parent.appendChild(child);
    return child;
  };

  const setState = (label, className = 'tag-blue') => {
    if (!nodes.state) return;
    nodes.state.textContent = label;
    nodes.state.className = `status-tag ${className}`;
  };

  const severityTag = (value) => {
    const raw = text(value, 'unknown');
    const normalized = raw.toLowerCase();
    if (normalized.includes('high') || normalized.includes('data_issue') || raw.includes('高')) return 'tag-red';
    if (normalized.includes('attention') || normalized.includes('insufficient') || raw.includes('注意') || raw.includes('不足')) return 'tag-orange';
    if (normalized.includes('positive') || raw.includes('正向')) return 'tag-green';
    return 'tag-blue';
  };

  const formatNumber = (value) => {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    if (!Number.isFinite(number)) return text(value);
    return new Intl.NumberFormat('zh-TW', {
      maximumFractionDigits: Math.abs(number) >= 100 ? 0 : 2,
    }).format(number);
  };

  const formatMetricValue = (value, unit) => {
    const formatted = formatNumber(value);
    if (formatted === null) return '尚無數值';
    return `${formatted}${unit && unit !== 'ratio' ? ` ${unit}` : ''}`;
  };

  const formatDate = (value) => {
    if (!value) return '尚未提供';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return text(value);
    return new Intl.DateTimeFormat('zh-TW', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  const buildBadge = (value, className) => {
    const badge = el('span', `status-tag ${className || severityTag(value)}`, value);
    return badge;
  };

  const buildSourceLink = (item) => {
    const href = item?.detail_url || item?.document_url || item?.source_url || item?.video_url;
    if (!href) return appendText(document.createDocumentFragment(), 'span', null, text(item?.source_name, '官方來源'));
    const link = el('a', 'financial-source-link', text(item?.document_title || item?.source_name || href));
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  };

  const appendTagList = (parent, label, items) => {
    const values = (items || []).filter(Boolean).slice(0, 6);
    if (!values.length) return;
    const wrap = el('div', 'financial-tag-list');
    appendText(wrap, 'b', null, label);
    values.forEach((value) => appendText(wrap, 'span', null, value));
    parent.appendChild(wrap);
  };

  const appendDisclosureClaims = (parent, claims) => {
    const values = (claims || []).slice(0, 3);
    if (!values.length) return;
    const details = el('details', 'financial-details');
    appendText(details, 'summary', null, '官方揭露主張');
    const list = el('div', 'financial-compact-list');
    values.forEach((claim) => {
      const row = el('div', 'financial-compact-row');
      appendText(row, 'b', null, text(claim.claim_type, 'official_claim'));
      appendText(row, 'small', null, text(claim.text));
      appendTagList(row, 'related metrics', claim.related_metrics);
      list.appendChild(row);
    });
    details.appendChild(list);
    parent.appendChild(details);
  };

  const showEmpty = (message, detail) => {
    setState('暫無財報證據', 'tag-orange');
    if (nodes.loading) nodes.loading.hidden = true;
    if (nodes.content) nodes.content.hidden = true;
    if (nodes.empty) {
      clear(nodes.empty);
      appendText(nodes.empty, 'b', null, message);
      appendText(nodes.empty, 'p', 'muted-text', detail);
      nodes.empty.hidden = false;
    }
  };

  const getAnalysisText = () => {
    const raw = localStorage.getItem('analysisResult');
    if (raw) {
      try {
        const data = JSON.parse(raw);
        return text(data.text, '');
      } catch (error) {
        console.error('Unable to parse analysisResult for financial evidence', error);
      }
    }
    return text(localStorage.getItem('analysisQuery') || document.querySelector('.page-hero p')?.textContent, '');
  };

  const pickSupportedCompany = async () => {
    const response = await fetch('/api/financial/companies');
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
      throw new Error(payload.error || '無法讀取 FinTrust 支援公司清單。');
    }
    const companies = payload.data?.companies || payload.companies || [];
    const analysisText = getAnalysisText();
    const explicitTicker = analysisText.match(/\b\d{4}\b/)?.[0];
    if (explicitTicker) {
      const byTicker = companies.find((company) => String(company.ticker) === explicitTicker);
      if (byTicker) return byTicker;
      return null;
    }
    const lowerText = analysisText.toLocaleLowerCase();
    return companies.find((company) => {
      const aliases = [company.ticker, company.name, ...(company.aliases || [])].filter(Boolean);
      return aliases.some((alias) => lowerText.includes(String(alias).toLocaleLowerCase()));
    }) || null;
  };

  const renderSummary = (card, snapshot, aiAnalysis) => {
    clear(nodes.summary);
    const periodStart = aiAnalysis?.source_period_start;
    const periodEnd = aiAnalysis?.source_period_end;
    const period = periodStart && periodEnd ? `${periodStart}–${periodEnd}` : '尚未提供';
    const items = [
      ['公司', `${text(card.company_name || snapshot.company_name)}（${text(card.ticker || snapshot.ticker)}）`],
      ['產業分類', `${text(snapshot.industry || '半導體')} / ${text(card.subindustry || snapshot.subindustry)}`],
      ['財報期間', period],
      ['資料更新', formatDate(snapshot.data_updated_at || card.generated_at)],
      ['整體狀態', text(card.overall_severity || snapshot.overall_severity)],
      ['官方證據', text(card.evidence_readiness || card.raw?.official_evidence?.readiness)],
    ];
    items.forEach(([label, value]) => {
      const item = el('div', 'financial-summary-item');
      appendText(item, 'span', null, label);
      if (label === '整體狀態') item.appendChild(buildBadge(value));
      else appendText(item, 'strong', null, value);
      nodes.summary.appendChild(item);
    });
    const overview = el('div', 'financial-overview');
    appendText(overview, 'b', null, card.headline || '官方財報證據已讀取');
    appendText(overview, 'p', null, snapshot.summary || card.summary || 'FinTrust 已回傳官方財報證據。');
    nodes.summary.appendChild(overview);
  };

  const renderMetrics = (metrics) => {
    clear(nodes.metrics);
    if (!metrics.length) {
      appendText(nodes.metrics, 'p', 'muted-text', '目前 backend 未提供 key metrics。');
      return;
    }
    metrics.forEach((metric) => {
      const item = el('article', 'financial-metric-item');
      appendText(item, 'span', 'source-label', metric.category || metric.code);
      appendText(item, 'h4', null, metric.label || metric.code);
      appendText(item, 'strong', null, formatMetricValue(metric.latest_value, metric.unit));
      const meta = el('div', 'financial-metric-meta');
      appendText(meta, 'span', null, `前期：${formatMetricValue(metric.previous_value, metric.unit)}`);
      if (metric.change_percent !== null && metric.change_percent !== undefined) {
        appendText(meta, 'span', null, `變動：${formatMetricValue(metric.change_percent, '%')}`);
      }
      if (metric.change_percentage_points !== null && metric.change_percentage_points !== undefined) {
        appendText(meta, 'span', null, `百分點變動：${formatMetricValue(metric.change_percentage_points, 'pp')}`);
      }
      item.appendChild(meta);
      const details = el('details', 'financial-details');
      appendText(details, 'summary', null, '期間數值與公式');
      const list = el('div', 'financial-period-list');
      Object.entries(metric.period_values || {}).forEach(([period, value]) => {
        appendText(list, 'span', null, `${period}: ${formatMetricValue(value, metric.unit)}`);
      });
      if (!list.childNodes.length) appendText(list, 'span', null, 'backend 未提供 period values');
      appendText(list, 'span', null, `公式：${text(metric.formula)}`);
      details.appendChild(list);
      item.appendChild(details);
      nodes.metrics.appendChild(item);
    });
  };

  const renderRules = (ruleCards, ruleMonitoring) => {
    clear(nodes.rules);
    const rules = ruleCards.length ? ruleCards : ruleMonitoring;
    if (!rules.length) {
      appendText(nodes.rules, 'p', 'muted-text', '目前 backend 未提供 deterministic rule results。');
      return;
    }
    rules.forEach((rule, index) => {
      const item = el('article', 'financial-rule-item');
      const head = el('div', 'financial-rule-head');
      appendText(head, 'b', null, `${String(index + 1).padStart(2, '0')} ${rule.name || rule.rule_id}`);
      head.appendChild(buildBadge(rule.severity || rule.signal || rule.evaluation_status));
      item.appendChild(head);
      appendText(item, 'p', null, rule.explanation || rule.rationale || rule.summary || 'backend 未提供規則說明');
      const evidence = el('div', 'financial-rule-evidence');
      appendText(evidence, 'span', null, `判斷：${rule.triggered === true ? 'triggered' : rule.triggered === false ? 'not triggered' : text(rule.evaluation_status || rule.status)}`);
      appendText(evidence, 'span', null, `證據期間：${(rule.evidence_periods || rule.evidence_references || []).join('、') || text(rule.evidence_basis)}`);
      appendText(evidence, 'span', null, `門檻：${text(rule.threshold_description || rule.threshold_basis)}`);
      item.appendChild(evidence);
      const details = el('details', 'financial-details');
      appendText(details, 'summary', null, '規則細節');
      const detailList = el('div', 'financial-period-list');
      appendText(detailList, 'span', null, `rule_id：${text(rule.rule_id)}`);
      appendText(detailList, 'span', null, `scope：${text(rule.rule_scope)}`);
      appendText(detailList, 'span', null, `formula / logic：${text(rule.logic_expression)}`);
      appendText(detailList, 'span', null, `metrics：${(rule.evidence_metrics || rule.direct_metrics || []).join('、') || '尚未提供'}`);
      Object.entries(rule.actual_values || {}).forEach(([key, value]) => {
        appendText(detailList, 'span', null, `${key}: ${formatNumber(value) ?? 'null'}`);
      });
      details.appendChild(detailList);
      item.appendChild(details);
      nodes.rules.appendChild(item);
    });
    if (ruleMonitoring.length && ruleMonitoring.length !== rules.length) {
      const allRules = el('details', 'financial-details financial-all-rules');
      appendText(allRules, 'summary', null, `查看完整 rule monitoring（${ruleMonitoring.length} 條）`);
      const list = el('div', 'financial-compact-list');
      ruleMonitoring.forEach((rule) => {
        const row = el('div', 'financial-compact-row');
        appendText(row, 'span', null, text(rule.rule_id));
        appendText(row, 'b', null, text(rule.name));
        row.appendChild(buildBadge(rule.severity || rule.evaluation_status));
        appendText(row, 'small', null, text(rule.rationale || rule.evidence_basis));
        list.appendChild(row);
      });
      allRules.appendChild(list);
      nodes.rules.appendChild(allRules);
    }
  };

  const renderDimensions = (dimensions) => {
    clear(nodes.dimensions);
    if (!dimensions.length) {
      appendText(nodes.dimensions, 'p', 'muted-text', '目前 backend 未提供 dimension assessments。');
      return;
    }
    dimensions.forEach((dimension) => {
      const item = el('article', 'financial-dimension-item');
      const head = el('div', 'financial-rule-head');
      appendText(head, 'b', null, dimension.label || dimension.dimension);
      head.appendChild(buildBadge(dimension.signal || '未標示'));
      item.appendChild(head);
      appendText(item, 'p', null, dimension.summary || 'backend 未提供面向摘要');
      appendText(item, 'small', 'muted-text', `coverage: ${formatMetricValue(dimension.coverage_ratio, '')}｜rules: ${text(dimension.evaluated_rules)}/${text(dimension.total_rules)}`);
      if (dimension.triggered_rule_ids?.length) {
        appendText(item, 'small', 'muted-text', `triggered rules: ${dimension.triggered_rule_ids.join('、')}`);
      }
      nodes.dimensions.appendChild(item);
    });
  };

  const renderLlm = (aiAnalysis) => {
    clear(nodes.llm);
    const narrative = aiAnalysis?.llm_narrative;
    const trace = aiAnalysis?.llm_trace || {};
    if (!narrative) {
      if (nodes.llmState) {
        nodes.llmState.textContent = trace.status === 'failed' ? 'LLM failed' : '暫時無法取得';
        nodes.llmState.className = `status-tag ${trace.status === 'failed' ? 'tag-red' : 'tag-orange'}`;
      }
      appendText(nodes.llm, 'p', 'muted-text', 'AI 財報解讀目前無法取得；官方財報數據、deterministic rules 與官方證據仍可正常檢視。');
      if (trace.status) appendText(nodes.llm, 'small', 'muted-text', `LLM status: ${trace.status}`);
      return;
    }
    if (nodes.llmState) {
      nodes.llmState.textContent = trace.status === 'completed' ? 'LLM completed' : text(trace.status, 'available');
      nodes.llmState.className = `status-tag ${trace.status === 'completed' ? 'tag-green' : 'tag-blue'}`;
    }
    appendText(nodes.llm, 'p', 'financial-llm-summary', narrative.executive_summary);
    const insights = Object.entries(narrative.dimension_insights || {});
    if (insights.length) {
      const list = el('div', 'financial-compact-list');
      insights.forEach(([label, insight]) => {
        const row = el('div', 'financial-compact-row');
        appendText(row, 'b', null, label);
        appendText(row, 'small', null, insight);
        list.appendChild(row);
      });
      nodes.llm.appendChild(list);
    }
    if (narrative.watch_items?.length) {
      const watch = el('div', 'financial-note-list');
      appendText(watch, 'b', null, '關注項目');
      narrative.watch_items.forEach((item) => appendText(watch, 'span', null, item));
      nodes.llm.appendChild(watch);
    }
    if (narrative.limitations?.length) {
      const limitations = el('div', 'financial-note-list');
      appendText(limitations, 'b', null, '限制');
      narrative.limitations.forEach((item) => appendText(limitations, 'span', null, item));
      nodes.llm.appendChild(limitations);
    }
  };

  const renderOfficialItems = (title, items, emptyText) => {
    const group = el('article', 'financial-official-group');
    appendText(group, 'h4', null, title);
    if (!items.length) {
      appendText(group, 'p', 'muted-text', emptyText);
      return group;
    }
    items.slice(0, 4).forEach((item) => {
      const row = el('div', 'financial-official-item');
      const rowHead = el('div', 'financial-rule-head');
      appendText(rowHead, 'b', null, item.title || item.document_title || item.source_name);
      rowHead.appendChild(buildBadge(item.status || item.document_extract_status || item.category));
      row.appendChild(rowHead);
      appendText(row, 'p', null, item.summary || item.raw_text || item.document_text_preview || '目前僅取得官方基本資料。');
      const dateText = [item.conference_date || item.event_date || item.generated_at, item.event_time].filter(Boolean).join(' ');
      appendText(row, 'small', 'muted-text', text(dateText, '日期尚未提供'));
      appendTagList(row, 'topics', item.extracted_topics);
      appendTagList(row, 'related metrics', item.related_metrics);
      if (item.document_extract_status) {
        appendText(row, 'small', 'muted-text', `document extract: ${item.document_extract_status}`);
      }
      if (item.category) {
        appendText(row, 'small', 'muted-text', `category: ${item.category}`);
      }
      appendDisclosureClaims(row, item.disclosure_claims);
      row.appendChild(buildSourceLink(item));
      if (item.limitations?.length) {
        appendText(row, 'small', 'muted-text', `限制：${item.limitations.join('；')}`);
      }
      group.appendChild(row);
    });
    return group;
  };

  const renderOfficialEvidence = (card, snapshot) => {
    clear(nodes.official);
    const conferences = card.investor_conferences || card.raw?.conferences || [];
    const materialEvents = card.material_events || card.raw?.material_events || [];
    const sources = [...(card.sources || []), ...(snapshot.sources || [])];
    nodes.official.appendChild(renderOfficialItems('法說會 Investor Conference Evidence', conferences, '目前未取得法說會資料。'));
    nodes.official.appendChild(renderOfficialItems('重大訊息 Material Event Evidence', materialEvents, '目前未取得重大訊息資料。'));
    const sourceGroup = el('article', 'financial-official-group');
    appendText(sourceGroup, 'h4', null, 'Official Sources');
    if (!sources.length) {
      appendText(sourceGroup, 'p', 'muted-text', 'backend 未提供官方來源連結。');
    } else {
      sources.slice(0, 8).forEach((source) => {
        const row = el('div', 'financial-source-row');
        row.appendChild(buildSourceLink(source));
        row.appendChild(buildBadge(source.status || 'available'));
        appendText(row, 'small', 'muted-text', text(source.period || source.limitation, ''));
        sourceGroup.appendChild(row);
      });
    }
    nodes.official.appendChild(sourceGroup);
    const limitations = [...(card.limitations || []), ...(snapshot.limitations || [])];
    if (limitations.length) {
      const limitationGroup = el('article', 'financial-official-group');
      appendText(limitationGroup, 'h4', null, '限制與資料狀態');
      limitations.forEach((item) => appendText(limitationGroup, 'p', 'muted-text', item));
      nodes.official.appendChild(limitationGroup);
    }
  };

  const renderFinancialEvidence = (card) => {
    const snapshot = card.raw?.snapshot || card.financial_snapshot || {};
    const aiAnalysis = snapshot.ai_analysis || {};
    const metrics = snapshot.key_metrics || card.key_metrics || [];
    const ruleCards = snapshot.rule_cards || card.rule_cards || [];
    const ruleMonitoring = aiAnalysis.rule_monitoring || [];
    const dimensions = aiAnalysis.dimension_assessments || [];

    if (nodes.loading) nodes.loading.hidden = true;
    if (nodes.empty) nodes.empty.hidden = true;
    if (nodes.content) nodes.content.hidden = false;
    setState('已取得官方證據', severityTag(card.overall_severity || snapshot.overall_severity));

    renderSummary(card, snapshot, aiAnalysis);
    renderMetrics(metrics);
    renderRules(ruleCards, ruleMonitoring);
    renderDimensions(dimensions);
    renderLlm(aiAnalysis);
    renderOfficialEvidence(card, snapshot);
  };

  const loadFinancialEvidence = async () => {
    try {
      const company = await pickSupportedCompany();
      if (!company) {
        showEmpty('此查詢未對應 FinTrust 目前支援的台股半導體公司。', '原本風險分析已完成；Financial Evidence 區塊不會影響美股或未支援 ticker 的流程。');
        return;
      }
      setState(`讀取 ${company.ticker}`, 'tag-blue');
      const response = await fetch(`/api/financial/companies/${encodeURIComponent(company.ticker)}/card`);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.success === false) {
        throw new Error(payload.error || payload.detail || `HTTP ${response.status}`);
      }
      renderFinancialEvidence(payload.data || payload);
    } catch (error) {
      console.error(error);
      showEmpty('財報與官方證據目前無法取得。', error.message || 'FinTrust FastAPI 可能尚未啟動，或此 ticker 尚無最新 snapshot。');
    }
  };

  document.querySelectorAll('[data-follow-company]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (!window.MemberAuth) {
        location.href = 'login.html?next=member.html';
        return;
      }
      const member = await MemberAuth.getMember();
      if (!member) {
        location.href = 'login.html?next=' + encodeURIComponent(location.pathname.split('/').pop() || 'member.html');
        return;
      }
      try {
        await MemberAuth.api('/api/member/watchlist', {
          method: 'POST',
          body: JSON.stringify({
            ticker: button.dataset.followCompany,
            company_name: button.dataset.followCompanyName || '',
            alert_enabled: true,
          }),
        });
        button.textContent = '已追蹤';
        button.disabled = true;
      } catch (error) {
        button.textContent = error.message || '追蹤失敗';
      }
    });
  });

  loadFinancialEvidence();
})();
