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
        '.result-top h2'
      );


    if (resultTitle) {

      resultTitle.textContent =
        '風險分析分數';

    }


    const resultDescription =
      document.querySelector(
        '.result-top p'
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