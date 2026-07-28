document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-chip]').forEach(chip=>{chip.addEventListener('click',()=>{const target=document.querySelector(chip.dataset.target||'#keyword');if(target){target.value=chip.dataset.chip;target.focus();}});});
  document.querySelectorAll('.search-tab').forEach(tab=>{tab.addEventListener('click',()=>{document.querySelectorAll('.search-tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.search-panel').forEach(x=>x.classList.remove('active'));tab.classList.add('active');document.getElementById('tab-'+tab.dataset.tab).classList.add('active');});});
  document.querySelectorAll('.ai-example').forEach(chip=>chip.addEventListener('click',()=>{const box=document.querySelector('#tab-ai textarea');box.value=chip.textContent.trim();}));
  const imageInput=document.getElementById('imageInput');if(imageInput){imageInput.addEventListener('change',()=>{document.getElementById('fileName').textContent=imageInput.files[0]?`已選擇：${imageInput.files[0].name}`:'尚未選擇圖片';});}
  const voiceButton=document.getElementById('voiceButton');if(voiceButton){voiceButton.addEventListener('click',()=>{document.getElementById('voiceStatus').textContent='展示模式：已接收語音「查詢台積電最近的重大訊息，以及保證漲停貼文是否可信」。';const ta=document.querySelector('#tab-voice textarea');if(ta)ta.value='查詢台積電最近的重大訊息，以及保證漲停貼文是否可信。';});}
  const demoForm=document.querySelector('#analysisForm');if(demoForm){demoForm.addEventListener('submit',e=>{e.preventDefault();const active=document.querySelector('.search-panel.active');const field=active?active.querySelector('textarea,input[type="text"],input:not([type])'):null;const q=(field&&field.value.trim())||'台積電下週保證漲停是真的嗎？';localStorage.setItem('demoQuery',q);window.location.href='/analyzing';});}
  document.querySelectorAll('.home-example').forEach(chip=>chip.addEventListener('click',()=>{const box=document.getElementById('homeAiQuery');box.value=chip.textContent.trim();box.focus();}));
  const homeBtn=document.getElementById('homeAiSubmit');if(homeBtn){homeBtn.addEventListener('click',()=>{const q=document.getElementById('homeAiQuery').value.trim()||'台積電下週保證漲停是真的嗎？';localStorage.setItem('demoQuery',q);window.location.href='/analyzing';});}
  const q=localStorage.getItem('demoQuery')||'台積電下週保證漲停是真的嗎？';const loadingQuery=document.getElementById('loadingQuery');if(loadingQuery)loadingQuery.textContent=`查詢內容：「${q}」`;const summaryQuery=document.getElementById('summaryQuery');if(summaryQuery)summaryQuery.textContent=`查詢內容：「${q}」｜整合三個資料來源產生初步結論。`;
  if(document.body.querySelector('.analysis-loading-shell')){
    const question = localStorage.getItem('demoQuery')
        || '台積電下週保證漲停是真的嗎？';

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
