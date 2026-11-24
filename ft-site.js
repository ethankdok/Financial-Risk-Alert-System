/* FinTrust user-first frontend orchestration.
 * Preserves existing /api/integrity, /api/financial, /api/member and /api/analyze contracts.
 * Intent routing uses an explicit rule-based dispatcher. No general-purpose LLM is claimed.
 */
(function(){
  "use strict";
  var page=document.body.getAttribute("data-ft-page")||"";
  var $=function(s){return document.querySelector(s);};
  var L=function(zh,en){return window.FTLocale?.language?.()==="en"?en:zh;};
  var asArray=function(x){return Array.isArray(x)?x:[];};
  function node(tag,text,cls){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined&&text!==null)e.textContent=window.FTLocale?.phrase?.(String(text))||String(text);return e;}
  function clear(e){if(e)e.replaceChildren();}
  function append(parent,children){children.forEach(function(x){if(x)parent.appendChild(x);});return parent;}
  function badge(t,type){return node("span",t,"ft-badge"+(type?" "+type:""));}
  function para(t,cls){return node("p",t,cls||"ft-muted");}
  function topNavigation(){
    var host=$("#ft-header");if(!host)return;
    var insideAudit=page==="audit";
    var insideAnalysis=page==="integrated";
    host.className="ft-header";
    host.innerHTML='<div class="ft-head-inner">'+
      '<a class="ft-brand" href="index.html" aria-label="FinTrust 首頁"><span class="ft-brand-symbol">F</span><span>FinTrust</span></a>'+
      '<nav class="ft-top-nav" id="ft-top-nav" aria-label="主要導覽">'+
      '<a class="ft-nav-link" href="index.html"'+(page==="home"?' aria-current="page"':'')+' data-ft-en="Home">首頁</a>'+
      '<div class="ft-nav-group" id="ft-analysis-nav"><button class="ft-nav-trigger" type="button" aria-expanded="false" aria-controls="ft-nav-pop"'+(insideAudit||insideAnalysis?' aria-current="page"':'')+' data-ft-en="Verification">查核分析 <span class="ft-chevron" aria-hidden="true"></span></button>'+
      '<div class="ft-nav-pop" id="ft-nav-pop"><a href="analysis.html"'+(insideAnalysis?' aria-current="page"':'')+' data-ft-en="Integrated verification">整合查核</a><a href="financial-audit.html"'+(insideAudit?' aria-current="page"':'')+' data-ft-en="Financial audit">財務異常稽核</a></div></div>'+
      '<a class="ft-nav-link" href="member.html"'+(page==="member"?' aria-current="page"':'')+' data-ft-en="Account">會員中心</a>'+
      '</nav><div class="ft-head-right"><a href="login.html" class="ft-pill-link" id="ft-login-link" data-ft-en="Log in">登入</a><button class="ft-language-switch" id="ft-language-toggle" type="button" aria-label="Switch language">中文 / EN</button><button class="ft-menu-toggle" id="ft-menu-toggle" type="button" aria-label="展開導覽選單" aria-controls="ft-top-nav" aria-expanded="false">☰</button></div></div>';
    if(window.FTLocale){window.FTLocale.apply();$("#ft-language-toggle").addEventListener("click",window.FTLocale.toggle);}
    var trigger=$("#ft-analysis-nav .ft-nav-trigger"),group=$("#ft-analysis-nav"),menu=$("#ft-menu-toggle"),nav=$("#ft-top-nav");
    trigger.addEventListener("click",function(){var isOpen=group.classList.toggle("ft-open");trigger.setAttribute("aria-expanded",String(isOpen));});
    menu.addEventListener("click",function(){var visible=nav.classList.toggle("ft-nav-visible");menu.setAttribute("aria-expanded",String(visible));});
    document.addEventListener("keydown",function(e){if(e.key==="Escape"){group.classList.remove("ft-open");trigger.setAttribute("aria-expanded","false");nav.classList.remove("ft-nav-visible");menu.setAttribute("aria-expanded","false");}});
    document.addEventListener("click",function(e){if(!group.contains(e.target)){group.classList.remove("ft-open");trigger.setAttribute("aria-expanded","false");}});
    if(window.MemberAuth&&typeof window.MemberAuth.getMember==="function"){
      window.MemberAuth.getMember().then(function(m){if(m){var link=$("#ft-login-link");if(link){link.href="member.html";link.textContent=window.FTLocale&&window.FTLocale.language()==="en"?"My account":"我的帳戶";}}}).catch(function(){});
    }
  }
  function status(text,isError){var e=$("#ft-status");if(!e)return;e.textContent=window.FTLocale?.phrase?.(String(text))||text;e.className="ft-status"+(isError?" ft-error":"");e.hidden=!text;}
  function parseQuery(){return new URLSearchParams(location.search);}
  function extractTicker(text){var match=String(text||"").match(/(?:^|[^\d])(\d{4,6})(?!\d)/);return match?match[1]:"";}
  function detectIntent(raw){
    var q=raw.toLowerCase();
    var news=/新聞|消息|報導|貼文|言論|報告說|內容|真假|查證|查核|公告|近期|最近|news|claim|fact.check/.test(q);
    var fin=/財報|財務|異常|稽核|beneish|dechow|m.score|f.score|比率|現金流|應收|重編|xbrl|財報不實/.test(q);
    if(fin&&!news)return "audit";
    return "integrated";
  }
  function routeQuery(raw){
    var q=String(raw||"").trim();if(!q)return false;
    var intent=detectIntent(q);
    var target=intent==="audit"?"financial-audit.html":"analysis.html";
    try{sessionStorage.setItem("ft:pending-query",q);}catch(e){return false;}
    var params=new URLSearchParams();
    var matched=window.FTCompanies?.findInText?.(q);
    var ticker=extractTicker(q)||(matched?.ticker||"");
    if(ticker)params.set("ticker",ticker);
    if(matched)window.FTCompanies.addRecent(matched);
    location.href=target+(params.toString()?"?"+params.toString():"");
    return true;
  }
  function attachFile(input,area,display){
    if(window.FTFileReader&&input){window.FTFileReader.attach(input,area,display);return;}
    if(display)display.textContent="檔案解析器未載入";
  }
  async function api(url,options){
    var opts=Object.assign({headers:{Accept:"application/json"},credentials:"same-origin"},options||{});
    if(opts.body){opts.headers=Object.assign({},opts.headers,{"Content-Type":"application/json"});}
    var response=await fetch(url,opts);
    var payload=await response.json().catch(function(){return {};});
    if(!response.ok||payload.success===false){
      var detail=payload.detail;
      var msg=(typeof detail==="object"&&detail&&(detail.message||detail.error_code))||payload.error||("HTTP "+response.status);
      var error=new Error(String(msg));error.status=response.status;throw error;
    }
    return payload.data!==undefined?payload.data:payload;
  }
  function errorMsg(e){var map={400:"查詢參數不正確",401:"需要登入",403:"目前沒有權限",404:"公司未收錄或資料不存在",409:"此分析模式尚不支援",422:"查詢內容不符合格式",502:"後端 API 無法連線",503:"資料來源目前不可用"};return L((map[e.status]||"分析暫時無法完成"),"Verification unavailable")+"："+(e.message||L("請稍後重試","Please try again later"));}
  function fromUrl(){
    var p=parseQuery(),pending="";
    try{pending=sessionStorage.getItem("ft:pending-query")||"";sessionStorage.removeItem("ft:pending-query");}catch(e){}
    var q=p.get("q")||pending;
    return {query:q,ticker:p.get("ticker")||extractTicker(q)};
  }
  function startHome(){
    var input=$("#ft-home-query"),button=$("#ft-home-submit"),companies=window.FTCompanies;
    if(!input||!button)return;
    function renderRecent(){
      var host=$("#ft-recent-list"),clearBtn=$("#ft-clear-recent");if(!host||!companies)return;
      host.replaceChildren();
      var rows=companies.readRecent();
      clearBtn.hidden=!rows.length;
      if(!rows.length){host.appendChild(node("span",L("尚無近期查詢","No recent searches yet"),"ft-home-muted"));return;}
      rows.forEach(function(entry){
        var b=node("button",entry.ticker+"　"+entry.name,"ft-recent-chip");b.type="button";
        b.addEventListener("click",function(){var v=companies.get(entry.ticker)||entry;companies.addRecent(v);location.href="financial-audit.html?ticker="+encodeURIComponent(entry.ticker);});
        host.appendChild(b);
      });
    }
    companies?.attachAutocomplete({
      input:input,list:$("#ft-home-suggestions"),
      choose:function(entry){
        companies.addRecent(entry);
        location.href="financial-audit.html?ticker="+encodeURIComponent(entry.ticker);
      }
    });
    button.addEventListener("click",function(){
      if(!routeQuery(input.value)){
        input.focus();
        var note=$("#ft-home-file-status");if(note)note.textContent=L("請先輸入查核問題。","Enter a question to verify.");
      }
    });
    input.addEventListener("keydown",function(e){if(e.key==="Enter"&&(e.ctrlKey||e.metaKey)){e.preventDefault();routeQuery(input.value);}});
    document.querySelectorAll("[data-ft-suggestion]").forEach(function(b){
      b.addEventListener("click",function(){input.value=b.getAttribute("data-ft-suggestion");routeQuery(input.value);});
    });
    $("#ft-clear-recent")?.addEventListener("click",function(){companies.clearRecent();});
    window.addEventListener("ft:recent-changed",renderRecent);
    renderRecent();
    attachFile($("#ft-home-file"),input,$("#ft-home-file-status"));
  }
  var queueNames={requires_verification:"需要人工核對",monitor:"持續觀察",insufficient_evidence:"證據不足",no_item_triggered:"未觸發篩檢項目"};
  var statusNames={descriptive_divergence:"描述性差異",within_screening_heuristic:"未超過篩檢門檻",supported:"資料支持",conflicting:"資料不一致",insufficient_evidence:"證據不足",not_computable:"不可計算",not_comparable:"不可比較",unavailable:"資料不可用",inconclusive:"無法判定"};
  function safeOfficialLink(url,label){
    try{
      var u=new URL(String(url));var h=u.hostname.toLowerCase();
      if((u.protocol==="https:"||u.protocol==="http:")&&(/(^|\.)twse\.com\.tw$|(^|\.)tpex\.org\.tw$/.test(h))){
        var a=node("a",label||"官方來源","ft-inline-link");a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";return a;
      }
    }catch(e){}
    return node("span","來源連結未提供","ft-muted");
  }
  function summaryItem(title,value,description){
    var b=node("section",null,"ft-mini-card");append(b,[node("h3",title),node("strong",value),para(description||"")]);return b;
  }
  function section(title){var el=node("section",null,"ft-panel");el.appendChild(node("h2",title));return el;}
  function renderFinding(f,evidenceRecords){
    var box=node("div",null,"ft-finding");
    var head=node("div",null,"ft-finding-head");append(head,[node("strong",f.title||f.name||f.finding_id||"財務篩檢項目"),badge(statusNames[f.status]||f.status||"狀態未明",f.status==="descriptive_divergence"?"warn":"")]);
    box.appendChild(head);
    if(f.period)box.appendChild(para("財務期間："+f.period));
    if(asArray(f.reasons).length)box.appendChild(para(asArray(f.reasons).join("；")));
    if(f.freshness_status==="latest_period_not_computable")box.appendChild(para("最新期間無法計算，歷史觀察不能視為目前的結論。"));
    var d=node("details");d.appendChild(node("summary","查看計算方法與來源"));
    var inner=node("div");
    if(f.formula)inner.appendChild(para("公式："+f.formula,"ft-code"));
    if(f.computed&&typeof f.computed==="object"){
      var v=Object.entries(f.computed).filter(function(pair){return pair[1]!=null&&typeof pair[1]!=="object";}).map(function(pair){return pair[0]+"："+pair[1];});
      if(v.length)inner.appendChild(para(v.join("　")));
    }
    if(asArray(f.limitations).length)inner.appendChild(para("限制："+asArray(f.limitations).join("；")));
    if(asArray(f.evidence_ids).length){
      var evidenceIndex={};
      asArray(evidenceRecords).forEach(function(record){if(record&&record.evidence_id)evidenceIndex[record.evidence_id]=record;});
      asArray(f.evidence_ids).forEach(function(id){
        var rec=evidenceIndex[id];
        var line=para((rec?(rec.fiscal_period||"")+" "+(rec.concept||"")+"；版本 "+(rec.filing_version||"未記錄"):"證據編號")+"　"+id,"ft-code");
        if(rec&&rec.source_url)line.appendChild(safeOfficialLink(rec.source_url,"　官方來源"));
        inner.appendChild(line);
      });
    }
    d.appendChild(inner);box.appendChild(d);return box;
  }
  function renderModel(m){
    var box=node("div",null,"ft-finding");
    var head=node("div",null,"ft-finding-head");append(head,[node("strong",m.paper||"文獻模型"),badge(statusNames[m.status]||m.status||"狀態未明")]);box.appendChild(head);
    box.appendChild(para("分數："+(m.raw_score==null?"不可計算":m.raw_score)+"；輸入完整度："+(m.component_coverage?m.component_coverage.computed+"/"+m.component_coverage.required:"未記錄")+"；缺值："+(m.missing_input_count==null?"—":m.missing_input_count)));
    var d=node("details");d.appendChild(node("summary","查看缺漏資訊與模型限制"));
    append(d,[para(asArray(m.missing_reasons).join("；")||"沒有額外的缺漏說明。"),para(asArray(m.limitations).join("；"))]);box.appendChild(d);return box;
  }
  function renderAssessment(r,container,focus){
    if(!r||typeof r!=="object"){container.appendChild(para("分析結果格式不符預期，無法顯示。"));return;}
    var company=r.company||r.ticker||"查核公司",queue=(r.investigation_priority||{}).queue||"insufficient_evidence";
    var findings=asArray(r.financial_findings),models=asArray(r.paper_models),claims=asArray(r.claim_checks),narratives=asArray(r.narrative_findings);
    var high= findings.concat(narratives).filter(function(f){return f.review_queue==="requires_verification"||f.review_queue==="monitor";}).length;
    var intro=section("官方資料查核");
    var head=node("div",null,"ft-result-summary");
    append(head,[node("strong",company+(r.ticker?"（"+r.ticker+"）":"")),badge(queueNames[queue]||queue,queue==="requires_verification"?"warn":"")]);intro.appendChild(head);
    intro.appendChild(para("此分析使用已歸檔官方資料，屬 CURRENT_REVIEW 篩檢；不表示即時新聞已全部蒐集，也不是財報舞弊判定。"));
    var grid=node("div",null,"ft-result-cards");
    append(grid,[summaryItem("需關注的篩檢項目",String(high)+" 項","依後端查核清單統計"),summaryItem("來源不足／不可計算",String(asArray(r.missing_data).length)+" 項","資料不足不代表低風險"),summaryItem("已登錄發行人主張",String(claims.length)+" 項","並非自動蒐集的新聞"),summaryItem("文獻模型",String(models.length)+" 組","顯示可計算性與缺漏")]);
    intro.appendChild(grid);
    if(r.data_latest_ingested_at)intro.appendChild(para("資料最近擷取："+r.data_latest_ingested_at));
    container.appendChild(intro);
    if(focus!=="only-news"){
      var fin=section("財務篩檢與文獻模型");
      if(!findings.length&&!models.length)fin.appendChild(para("目前沒有可顯示的財務篩檢項目。"));
      findings.forEach(function(f){fin.appendChild(renderFinding(f,r.evidence_records));});
      models.forEach(function(m){fin.appendChild(renderModel(m));});
      container.appendChild(fin);
    }
    var cross=section("跨證據查核與文字差異");
    if(!claims.length&&!r.data_shift&&!narratives.length)cross.appendChild(para("目前沒有已登錄、可定位的發行人主張或可比較文字資料。"));
    claims.forEach(function(c){
      var b=node("div",null,"ft-finding");var head=node("div",null,"ft-finding-head");
      append(head,[node("strong",(c.statement&&c.statement.document)||"發行人主張"),badge(statusNames[c.verdict]||c.verdict||"待查核",c.verdict==="conflicting"?"warn":"")]);b.appendChild(head);
      if(c.statement&&c.statement.excerpt)b.appendChild(para(c.statement.excerpt));
      asArray(c.evidence).slice(0,3).forEach(function(v){var line=para((v.source_title||v.source_type||"官方證據")+"　"+(v.period||""));line.appendChild(safeOfficialLink(v.source_reference,"　查看來源"));b.appendChild(line);});
      cross.appendChild(b);
    });
    narratives.forEach(function(n){cross.appendChild(renderFinding(n,r.evidence_records));});
    if(r.data_shift){
      var d=r.data_shift;var summary=node("div",null,"ft-finding");summary.appendChild(node("strong","法說會／財報敘述差異"));
      summary.appendChild(para("比較期間："+(d.period_1||"—")+" → "+(d.period_2||"—")+"；狀態："+(d.status||"未知")));
      if(d.metrics)summary.appendChild(para("JSD："+(d.metrics.jsd==null?"—":d.metrics.jsd)+"；Cosine："+(d.metrics.cosine_similarity==null?"—":d.metrics.cosine_similarity)+"。這些是文字差異指標，不是造假機率。"));
      cross.appendChild(summary);
    }
    container.appendChild(cross);
    var source=section("官方資料與版本");
    var overview=r.financial_overview||{},rows=asArray(overview.rows);
    if(rows.length){
      var table=node("table",null,"ft-table"),thead=node("thead"),tr=node("tr");
      ["期間","財務指標","金額（新台幣）","版本／來源"].forEach(function(t){tr.appendChild(node("th",t));});thead.appendChild(tr);table.appendChild(thead);
      var tbody=node("tbody");
      var names={revenue:"營業收入",accounts_receivable:"應收帳款",net_income:"本期淨利",operating_cash_flow:"營業活動現金流量",total_assets:"資產總額"};
      rows.slice(0,45).forEach(function(row){var tr=node("tr");
        [row.fiscal_period||"—",names[row.metric]||row.metric||"—",row.value_twd==null?"—":Number(row.value_twd).toLocaleString("zh-TW")].forEach(function(t){tr.appendChild(node("td",t));});
        var td=node("td");td.appendChild(node("span",(row.filing_version||"未記錄版本")+"　"));td.appendChild(safeOfficialLink(row.source_url,"來源"));tr.appendChild(td);tbody.appendChild(tr);
      });table.appendChild(tbody);var scroll=node("div",null,"ft-table-scroll");scroll.appendChild(table);source.appendChild(scroll);
      if(rows.length>45)source.appendChild(para("為保持閱讀清晰，僅顯示前 45 列，完整數據可於進階工作台查看。"));
    }else source.appendChild(para("目前沒有已歸檔、可顯示的財務科目資料。"));
    source.appendChild(para("資料必須以實際申報版本與公開日期為準；未取得的歷史版本不得視為首次申報版本。"));
    container.appendChild(source);
  }
  function renderTextRisk(r,container){
    var p=section("文字風險規則篩檢");p.appendChild(para("此結果來自既有關鍵字／話術特徵規則，不是財報模型或新聞真偽機率。"));
    var g=node("div",null,"ft-result-cards");
    append(g,[summaryItem("規則篩檢分數",r.risk_score==null?"—":String(r.risk_score)+"/100","規則權重指標，不是統計機率"),summaryItem("文字風險等級",r.risk_level||"未產生","僅限輸入文字的風險話術")]);p.appendChild(g);
    var features=asArray(r.matched_features);if(!features.length)p.appendChild(para("未命中已設定的文字規則，不代表內容可靠。"));
    features.forEach(function(f){p.appendChild(para((f.name||"特徵")+"："+asArray(f.matched_keywords).join("、")+"。"+(f.explain||"")));});container.appendChild(p);
  }
  function renderClaim(r,container){
    var p=section("新聞／言論主張查核");
    var label=r.verdict||r.status||r.conclusion||(r.result&&r.result.status)||"後端已回應";
    p.appendChild(badge(typeof label==="string"?label:"已取得查核回應"));
    var s=r.summary||r.explanation||r.message||r.reason||(r.result&&r.result.summary);
    if(typeof s==="string")p.appendChild(para(s));
    var support=asArray(r.evidence||r.sources||r.references);
    support.slice(0,8).forEach(function(it){if(typeof it==="string")p.appendChild(para(it));else if(it&&typeof it==="object"){var line=para(it.title||it.source_title||it.summary||"查核來源");if(it.source_url||it.url)line.appendChild(safeOfficialLink(it.source_url||it.url,"　查看官方來源"));p.appendChild(line);}});
    var d=node("details");d.appendChild(node("summary","查看完整查核回應"));
    var pre=node("pre",JSON.stringify(r,null,2).slice(0,13000),"ft-code");pre.style.whiteSpace="pre-wrap";pre.style.overflowWrap="anywhere";d.appendChild(pre);p.appendChild(d);container.appendChild(p);
  }
  function renderEvents(r,container){
    var p=section("近期官方重大訊息");
    var events=asArray(r&&r.events||r&&r.items||r&&r.material_events||r&&r.records);
    if(!events.length){p.appendChild(para("目前沒有從此 API 回應取得可顯示的重大訊息，或資料暫未收錄。"));container.appendChild(p);return;}
    events.slice(0,6).forEach(function(ev){var box=node("div",null,"ft-finding");
      box.appendChild(node("strong",ev.title||ev.subject||"重大訊息"));
      box.appendChild(para(ev.event_date||ev.published_at||"日期未記錄"));
      box.appendChild(safeOfficialLink(ev.detail_url||ev.source_url||ev.official_url,"官方公告"));
      p.appendChild(box);
    });container.appendChild(p);
  }
  async function runWorkflow(mode,ticker,claim,target,button){
    clear(target);target.hidden=false;button.disabled=true;status("正在讀取官方資料並執行已串接的查核…");var jobs=[];
    function add(name,promise){jobs.push({name:name,promise:promise});}
    if(mode==="integrated"){
      if(!ticker){status("整合查核需要有效公司代號（4–6 碼）。",true);button.disabled=false;return;}
      add("assessment",api("/api/integrity/assessments/preview",{method:"POST",body:JSON.stringify({ticker:ticker,review_mode:"CURRENT_REVIEW",sections:["financial_checks","literature","jsd","claims"]})}));
      add("events",api("/api/financial/companies/"+encodeURIComponent(ticker)+"/material-events"));
      if(isVerifiableClaim(claim))add("claim",api("/api/financial/claims/verify",{method:"POST",body:JSON.stringify({company_code:ticker,claim:claim})}));
    }else if(mode==="claim"){
      if(!ticker||claim.length<2){status("主張查核需要公司代號及至少兩個字的新聞／言論內容。",true);button.disabled=false;return;}
      add("claim",api("/api/financial/claims/verify",{method:"POST",body:JSON.stringify({company_code:ticker,claim:claim})}));
    }else{
      if(!claim){status("請輸入要篩檢的文字內容。",true);button.disabled=false;return;}
      add("text",api("/api/analyze",{method:"POST",body:JSON.stringify({text:claim})}));
    }
    var results=await Promise.allSettled(jobs.map(function(j){return j.promise;}));
    var success=0,errors=[];
    results.forEach(function(out,i){var job=jobs[i];
      if(out.status==="fulfilled"){success++;
        if(job.name==="assessment")renderAssessment(out.value,target);
        if(job.name==="claim")renderClaim(out.value,target);
        if(job.name==="events")renderEvents(out.value,target);
        if(job.name==="text")renderTextRisk(out.value,target);
      }else errors.push(job.name+"："+errorMsg(out.reason));
    });
    status(success?("已完成 "+success+" 項查核"+(errors.length?"；部分模組未能取得資料。":"。")):("本次沒有取得可用的分析結果。"),!success);
    errors.forEach(function(x){target.appendChild(node("div",x,"ft-status ft-error"));});
    button.disabled=false;
    if(success)target.scrollIntoView({behavior:"smooth",block:"start"});
  }

  function isVerifiableClaim(text){
    var q=String(text||"").trim();
    if(!q)return false;
    if(/^(幫我|請|查詢|查查|查看|分析|找出|比較|研究|想知道)/.test(q)&&!/新聞(?:說|指出)|報導(?:說|指出)|宣稱|聲稱|「|\d+%/.test(q))return false;
    return q.length>=8;
  }
  async function resolveCompanyFromQuestion(text){
    var q=String(text||"");if(!q)return "";
    var candidates=[];
    for(var i=0;i<2;i++){
      try{
        var data=await api(i===0?"/api/financial/companies":"/api/integrity/companies");
        candidates=asArray(data.companies||data.items);
        var found=candidates.filter(function(c){
          var name=String(c.name||c.company_name||"").trim();
          return name.length>=2&&q.includes(name)&&/^\d{4,6}$/.test(String(c.ticker||c.code||""));
        });
        if(found.length===1)return String(found[0].ticker||found[0].code);
      }catch(e){}
    }
    return "";
  }
  function renderLayoutPreview(target,financial){
    clear(target);target.hidden=false;
    var title=section("結果頁配置預覽");
    title.appendChild(badge("介面示意｜沒有執行分析"));
    title.appendChild(para("以下只展示實際資料回來後會出現的資訊區塊，不含虛構模型分數、公司資料或新聞。"));
    var grid=node("div",null,"ft-result-cards");
    append(grid,[
      summaryItem("查核結論","等待執行","對應官方證據與時間"),
      summaryItem("財務篩檢","等待執行","異常指標與原因"),
      summaryItem("模型可計算性","等待執行","Beneish／Dechow"),
      summaryItem("來源狀態","等待執行","申報版本與原始連結")
    ]);title.appendChild(grid);target.appendChild(title);
    var detail=section(financial?"財務異常與模型明細":"新聞主張與財務交叉核對");
    var d=node("details");d.appendChild(node("summary","展開資訊欄位示意"));
    d.appendChild(para(financial?"指標名稱、期間、公式、輸入科目、可計算性、官方資料來源。":"新聞原文、公司與事件日期、官方數據、查核狀態、財務異常與引用證據。"));
    detail.appendChild(d);target.appendChild(detail);
  }

  function startIntegrated(){
    var p=fromUrl(),ticker=$("#ft-ticker"),query=$("#ft-query"),mode=$("#ft-mode"),button=$("#ft-run"),result=$("#ft-result");
    if(!ticker||!query||!mode||!button)return;
    ticker.value=p.ticker||"";query.value=p.query||"";
    if(p.query&&/保證獲利|穩賺|詐騙|內線消息|投資話術/.test(p.query)&&!/財報|新聞主張|官方財務/.test(p.query))mode.value="text";
    var launched=false;
    function launchFromHome(){
      if(launched||!p.query)return;
      if(mode.value!=="text"&&!ticker.value.trim()){status(L("請先填入公司代號，再執行查核。","Please enter the company ticker before running verification."));return;}
      launched=true;
      runWorkflow(mode.value,ticker.value.trim(),query.value.trim(),result,button);
    }
    if(!p.ticker&&p.query){
      resolveCompanyFromQuestion(p.query).then(function(code){
        if(code&&!ticker.value.trim())ticker.value=code;
        launchFromHome();
      });
    }

    attachFile($("#ft-attach"),query,$("#ft-file-note"));
    $("#ft-demo-run")?.addEventListener("click",async function(){
      if(!window.FTDemo)return;
      await window.FTDemo.render(result,{mode:mode.value,ticker:ticker.value.trim()||p.ticker||"6505",claim:query.value.trim()});
      status(L("目前顯示的是前端介面示範，非後端查核結果。","Showing a front-end demonstration, not backend verification."));
      result.scrollIntoView({behavior:"smooth",block:"start"});
    });
    $("#ft-form").addEventListener("submit",function(e){e.preventDefault();runWorkflow(mode.value,ticker.value.trim(),query.value.trim(),result,button);});
    document.querySelectorAll("[data-ft-mode]").forEach(function(b){b.addEventListener("click",function(){mode.value=b.getAttribute("data-ft-mode");query.focus();});});
    if(p.query&&(p.ticker||mode.value==="text"))launchFromHome();
  }
  function startAudit(){
    var p=fromUrl(),ticker=$("#ft-audit-ticker"),button=$("#ft-audit-run"),result=$("#ft-result");
    if(!ticker||!button)return;
    ticker.value=p.ticker||"";

    if(!p.ticker&&p.query){resolveCompanyFromQuestion(p.query).then(function(code){if(code&&!ticker.value.trim()){ticker.value=code;run();}else if(!code)status(L("請先填入公司代號，再執行稽核。","Please enter the company ticker before running the audit."));});}

    async function run(){
      var code=ticker.value.trim();if(!/^\d{4,6}$/.test(code)){status(L("請輸入 4–6 碼公司代號。","Enter a 4–6 digit ticker."),true);return;}
      clear(result);result.hidden=false;button.disabled=true;status(L("正在讀取財務查核與模型可計算性…","Retrieving financial checks and model availability…"));
      try{
        var r=await api("/api/integrity/assessments/preview",{method:"POST",body:JSON.stringify({ticker:code,review_mode:"CURRENT_REVIEW",sections:["financial_checks","literature","jsd","claims"]})});
        renderAssessment(r,result);
        status(L("已取得後端財務查核結果。","Retrieved backend financial audit results."));
        var link=$("#ft-advanced-link");if(link)link.href="financial-integrity.html?ticker="+encodeURIComponent(code)+"&expand=1";
        result.scrollIntoView({behavior:"smooth",block:"start"});
      }catch(e){status(errorMsg(e),true);result.appendChild(para("本頁不會以示意分數代替真實模型結果。請確認 Flask、FastAPI 與資料來源是否正常。"));}
      button.disabled=false;
    }
    $("#ft-audit-demo-run")?.addEventListener("click",async function(){
      if(!window.FTDemo)return;
      await window.FTDemo.render(result,{mode:"integrated",ticker:ticker.value.trim()||p.ticker||"6505"});
      status(L("目前顯示的是前端介面示範，非後端查核結果。","Showing a front-end demonstration, not backend verification."));
      result.scrollIntoView({behavior:"smooth",block:"start"});
    });
    $("#ft-audit-form").addEventListener("submit",function(e){e.preventDefault();run();});
    if(p.ticker && !location.hostname.endsWith(".vercel.app"))run();
  }
  document.addEventListener("DOMContentLoaded",function(){topNavigation();if(page==="home")startHome();if(page==="integrated")startIntegrated();if(page==="audit")startAudit();});
})();
