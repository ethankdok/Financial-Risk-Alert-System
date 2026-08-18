document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-chip]').forEach(chip=>{chip.addEventListener('click',()=>{const target=document.querySelector(chip.dataset.target||'#keyword');if(target){target.value=chip.dataset.chip;target.focus();}});});
  document.querySelectorAll('.search-tab').forEach(tab=>{tab.addEventListener('click',()=>{document.querySelectorAll('.search-tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.search-panel').forEach(x=>x.classList.remove('active'));tab.classList.add('active');document.getElementById('tab-'+tab.dataset.tab).classList.add('active');});});
  document.querySelectorAll('.ai-example').forEach(chip=>chip.addEventListener('click',()=>{const box=document.querySelector('#tab-ai textarea');box.value=chip.textContent.trim();}));
  const imageInput=document.getElementById('imageInput');if(imageInput){imageInput.addEventListener('change',()=>{document.getElementById('fileName').textContent=imageInput.files[0]?`已選擇：${imageInput.files[0].name}`:'尚未選擇圖片';});}
  const voiceButton=document.getElementById('voiceButton');if(voiceButton){voiceButton.addEventListener('click',()=>{document.getElementById('voiceStatus').textContent='已接收語音「查詢台積電最近的重大訊息，以及保證漲停貼文是否可信」。';const ta=document.querySelector('#tab-voice textarea');if(ta)ta.value='查詢台積電最近的重大訊息，以及保證漲停貼文是否可信。';});}
  const analysisForm=document.querySelector('#analysisForm');if(analysisForm){analysisForm.addEventListener('submit',e=>{e.preventDefault();const active=document.querySelector('.search-panel.active');const field=active?active.querySelector('textarea,input[type="text"],input:not([type])'):null;const q=(field&&field.value.trim())||'台積電下週保證漲停是真的嗎？';localStorage.setItem('analysisQuery',q);window.location.href='analyzing.html';});}
  document.querySelectorAll('.home-example').forEach(chip=>chip.addEventListener('click',()=>{const box=document.getElementById('homeAiQuery');box.value=chip.textContent.trim();box.focus();}));
  const homeBtn=document.getElementById('homeAiSubmit');if(homeBtn){homeBtn.addEventListener('click',()=>{const q=document.getElementById('homeAiQuery').value.trim()||'台積電下週保證漲停是真的嗎？';localStorage.setItem('analysisQuery',q);window.location.href='analyzing.html';});}
  const q=localStorage.getItem('analysisQuery')||'台積電下週保證漲停是真的嗎？';const loadingQuery=document.getElementById('loadingQuery');if(loadingQuery)loadingQuery.textContent=`查詢內容：「${q}」`;const summaryQuery=document.getElementById('summaryQuery');if(summaryQuery)summaryQuery.textContent=`查詢內容：「${q}」｜整合三個資料來源產生初步結論。`;
  if(document.body.querySelector('.analysis-loading-shell')){setTimeout(()=>{window.location.href='summary.html';},3200);}
});


/* === V4.1 REAL ANALYSIS FLOW === */
(() => {
  const page = location.pathname.split('/').pop();

  const esc = (value) =>
    String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');

  // analyzing.html：
  // 讀取使用者剛才輸入的內容 → 呼叫 Flask /api/analyze
  if (page === 'analyzing.html') {
    const query = localStorage.getItem('analysisQuery') || '';

    async function runAnalysis() {
      if (!query.trim()) {
        location.href = 'analysis.html';
        return;
      }

      try {
        const response = await fetch('/api/analyze', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            text: query
          })
        });

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        // 把 Flask 真正算出的結果暫存給 result.html
        localStorage.setItem('analysisResult', JSON.stringify(data));

        // 稍微保留「分析中」畫面
        setTimeout(() => {
          location.href = 'result.html';
        }, 700);

      } catch (error) {
        console.error(error);

        const loadingQuery = document.getElementById('loadingQuery');
        if (loadingQuery) {
          loadingQuery.textContent = '分析失敗：' + error.message;
        }
      }
    }

    runAnalysis();
  }

  // result.html：
  // 將 Flask 回傳的真實分析結果寫進原本版面
  if (page === 'result.html') {
    const raw = localStorage.getItem('analysisResult');
    if (!raw) return;

    let data;

    try {
      data = JSON.parse(raw);
    } catch (e) {
      console.error('無法讀取分析結果', e);
      return;
    }

    // ---------- 查詢內容 ----------
    const heroQuery = document.querySelector('.page-hero p');
    if (heroQuery) {
      heroQuery.textContent = `查詢內容：「${data.text || ''}」`;
    }

    // ---------- 上方分數 ----------
    const scoreNumber = document.querySelector('.score-ring strong');
    if (scoreNumber) {
      scoreNumber.textContent = data.score ?? 0;
    }

    const resultTitle = document.querySelector('.result-top h2');
    if (resultTitle) {
      resultTitle.textContent = '風險分析分數';
    }

    const resultDescription = document.querySelector('.result-top p');
    if (resultDescription) {
      resultDescription.textContent =
        `共命中 ${data.summary?.keyword_count ?? 0} 個關鍵字、` +
        `${data.summary?.feature_count ?? 0} 個風險特徵。`;
    }

    // ---------- 分數視覺同步 ----------
    const score = Math.max(0, Math.min(100, Number(data.score) || 0));

    const scoreRing = document.querySelector('.score-ring');
    if (scoreRing) {
      scoreRing.style.background =
        `conic-gradient(var(--orange) 0 ${score}%, #dfe8f4 ${score}% 100%)`;
    }

    const progressBar = document.querySelector('.progress span');
    if (progressBar) {
      progressBar.style.width = `${score}%`;
    }

    // ---------- 風險等級 ----------
    const riskStrong = document.querySelector('.risk-box strong');
    if (riskStrong) {
      riskStrong.textContent = data.risk_level || '低風險';
    }

    const riskSmall = document.querySelector('.risk-box small');
    if (riskSmall) {
      riskSmall.textContent =
        data.risk_level === '高風險'
          ? '建議提高警覺並進一步查證'
          : data.risk_level === '中風險'
            ? '建議檢查資訊來源與相關證據'
            : '目前未偵測到明顯高風險訊號';
    }

    // ---------- 判定原因 ----------
    const reasonList = document.querySelector('.reason-list');

    if (reasonList) {
      if (data.matched_features?.length) {
        reasonList.innerHTML = data.matched_features.map((feature, index) => {
          const hits = (feature.matched_keywords || []).join('、');

          return `
            <div class="reason">
              <div>${String(index + 1).padStart(2, '0')}</div>
              <div>
                <b>${esc(feature.name)}</b>
                <span>
                  ${esc(feature.explain || feature.definition || '')}
                  ${hits ? `（命中：${esc(hits)}）` : ''}
                </span>
              </div>
            </div>
          `;
        }).join('');
      } else {
        reasonList.innerHTML = `
          <div class="reason">
            <div>01</div>
            <div>
              <b>未偵測到明顯風險特徵</b>
              <span>目前內容未命中後台啟用中的風險特徵。</span>
            </div>
          </div>
        `;
      }
    }

    // ---------- 關鍵字表格 ----------
    const tbody = document.querySelector('.data-table tbody');

    if (tbody) {
      if (data.matched_keywords?.length) {
        tbody.innerHTML = data.matched_keywords.map(keyword => `
          <tr>
            <td>${esc(keyword.source || '系統字庫')}</td>
            <td>${esc(keyword.phrase)}</td>
            <td>
              <span class="status-tag tag-red">
                ${esc(keyword.risk || keyword.category || '命中')}
              </span>
            </td>
          </tr>
        `).join('');
      } else {
        tbody.innerHTML = `
          <tr>
            <td>系統字庫</td>
            <td>未命中啟用中的風險關鍵字</td>
            <td><span class="status-tag tag-blue">低風險</span></td>
          </tr>
        `;
      }
    }
  }
})();
