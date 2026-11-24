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
    host.className="ft-header";
    var current=(page==="member"||page==="member-demo")?"member":page;
    var links=[
      ["home","index.html","nav.home"],
      ["integrated","analysis.html","nav.newsVerification"],
      ["audit","financial-audit.html","nav.companyHealth"],
      ["member","member.html","nav.member"]
    ];
    var main=node("div",null,"ft-head-inner");
    var brand=node("a",null,"ft-brand");
    brand.href="index.html";brand.setAttribute("aria-label","FinTrust");
    brand.appendChild(node("span","F","ft-brand-symbol"));
    brand.appendChild(node("span","FinTrust"));
    main.appendChild(brand);
    var nav=node("nav",null,"ft-top-nav");
    nav.id="ft-top-nav";nav.setAttribute("aria-label",L("主要導覽","Primary navigation"));
    links.forEach(function(item){
      var a=node("a",window.FTLocale?.t?.(item[2])||item[2],"ft-nav-link");
      a.href=item[1];a.setAttribute("data-i18n",item[2]);
      if(current===item[0])a.setAttribute("aria-current","page");
      nav.appendChild(a);
    });
    main.appendChild(nav);
    var right=node("div",null,"ft-head-right");
    var lang=node("button","中文 / EN","ft-language-switch");
    lang.id="ft-language-toggle";lang.type="button";right.appendChild(lang);
    var menu=node("button","☰","ft-menu-toggle");menu.id="ft-menu-toggle";menu.type="button";
    menu.setAttribute("aria-label",L("展開導覽選單","Open navigation menu"));
    menu.setAttribute("aria-controls","ft-top-nav");menu.setAttribute("aria-expanded","false");right.appendChild(menu);
    main.appendChild(right);host.replaceChildren(main);
    if(window.FTLocale){window.FTLocale.apply();lang.addEventListener("click",window.FTLocale.toggle);}
    menu.addEventListener("click",function(){var visible=nav.classList.toggle("ft-nav-visible");menu.setAttribute("aria-expanded",String(visible));});
    document.addEventListener("keydown",function(e){if(e.key==="Escape"){nav.classList.remove("ft-nav-visible");menu.setAttribute("aria-expanded","false");}});
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
    var matched=window.FTCompanies?.findInText?.(q);
    var ticker=extractTicker(q)||(matched?.ticker||"");
    var alone=/^\d{4,6}(?:\s+[^\d]{1,30})?$/.test(q)||!!(matched&&[
      matched.name,matched.fullName,matched.ticker,matched.ticker+" "+matched.name
    ].some(function(v){return String(v||"").trim().normalize("NFKC").replace(/\s+/g,"")===q.normalize("NFKC").replace(/\s+/g,"");}));
    var intent=alone?"audit":detectIntent(q);
    var target=intent==="audit"?"financial-audit.html":"analysis.html";
    try{if(!alone)sessionStorage.setItem("ft:pending-query",q);else sessionStorage.removeItem("ft:pending-query");}catch(e){}
    var params=new URLSearchParams();
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
    clear(target);target.hidden=false;button.disabled=true;
    status(L("正在讀取已串接的官方資料…","Retrieving connected official data…"));
    var jobs=[];
    function add(name,promise){jobs.push({name:name,promise:promise});}
    var validTicker=/^\d{4,6}$/.test(String(ticker||""));
    if(mode==="integrated"||mode==="claim"){
      if(!validTicker){
        status(L("請先輸入有效的公司代號。","Enter a valid company ticker."),true);
        button.disabled=false;return;
      }
      if(mode==="claim"&&String(claim||"").trim().length<2){
        status(L("請輸入至少兩個字的新聞或財務主張。","Enter a news or financial claim (at least 2 characters)."),true);
        button.disabled=false;return;
      }
      if(window.FTLiveFinancial)add("financial",window.FTLiveFinancial.load(ticker));
      // Legacy integrations remain optional until the Cloud Run service exposes them.
      if(mode==="integrated"){
        add("assessment",api("/api/integrity/assessments/preview",{method:"POST",body:JSON.stringify({
          ticker:ticker,review_mode:"CURRENT_REVIEW",sections:["financial_checks","literature","jsd","claims"]
        })}));
      }
      if(mode==="claim"||isVerifiableClaim(claim)){
        add("claim",api("/api/financial/claims/verify",{method:"POST",body:JSON.stringify({
          company_code:ticker,claim:claim
        })}));
      }
    }else{
      if(!String(claim||"").trim()){
        status(L("請輸入要篩檢的文字內容。","Enter text to screen."),true);
        button.disabled=false;return;
      }
      add("text",api("/api/analyze",{method:"POST",body:JSON.stringify({text:claim})}));
    }
    if(!jobs.length){status(L("此查核模式尚未接上資料來源。","No live data source is connected for this mode."),true);button.disabled=false;return;}
    try{
      var results=await Promise.allSettled(jobs.map(function(j){return j.promise;}));
      var success=0,errors=[],missing=[];
      results.forEach(function(out,i){
        var job=jobs[i];
        if(out.status==="fulfilled"){
          success++;
          if(job.name==="financial"){window.FTLiveFinancial.render(target,out.value,{claim:claim});window.FTNewsEvidence?.render(target,out.value,claim);}
          if(job.name==="assessment")renderAssessment(out.value,target);
          if(job.name==="claim")renderClaim(out.value,target);
          if(job.name==="text")renderTextRisk(out.value,target);
        }else if(out.reason&&out.reason.status===404){
          missing.push(job.name);
        }else errors.push(job.name+"："+errorMsg(out.reason||new Error("Unknown error")));
      });
      if(success){
        var msg=L("已取得 "+success+" 個後端資料來源","Received "+success+" connected backend result(s)");
        if(missing.length)msg+=" · "+L("部分進階功能尚未部署","Some advanced endpoints are not deployed");
        if(errors.length)msg+=" · "+L("部分資料讀取失敗","Some requests failed");
        status(msg);
        if(missing.length)target.appendChild(para(L("新聞主張查證／整合稽核尚未部署的功能，可以點「介面示範」查看操作流程。","Claim verification or integrity features not yet deployed can be previewed using UI demo.")));
        errors.forEach(function(e){target.appendChild(node("div",e,"ft-status ft-error"));});
        target.scrollIntoView({behavior:"smooth",block:"start"});
      }else{
        status(L("正式後端尚未提供此模式，請使用「介面示範」查看操作流程。","This mode is not yet available in the connected backend. Use UI demo to explore the interface."),true);
        errors.forEach(function(e){target.appendChild(node("div",e,"ft-status ft-error"));});
      }
    }finally{button.disabled=false;}
  }

  function isVerifiableClaim(text){
    var q=String(text||"").trim();
    if(!q)return false;
    if(/^(幫我|請|查詢|查查|查看|分析|找出|比較|研究|想知道)/.test(q)&&!/新聞(?:說|指出)|報導(?:說|指出)|宣稱|聲稱|「|\d+%/.test(q))return false;
    return q.length>=8;
  }
  async function resolveCompanyFromQuestion(text){
    if(window.FTCompanies){
      await window.FTCompanies.load();
      var directoryCompany=window.FTCompanies.findInText(text);
      if(directoryCompany)return directoryCompany.ticker;
    }
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
    window.FTCompanies?.attachAutocomplete({
      input:ticker,list:$("#ft-news-suggestions"),
      choose:function(item){ticker.value=item.ticker;window.FTCompanies.addRecent(item);}
    });
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
      var code=extractTicker(ticker.value)||window.FTCompanies?.findInText?.(ticker.value)?.ticker||p.ticker||"6505";
      await window.FTDemo.render(result,{mode:mode.value,ticker:code,claim:query.value.trim()});
      status(L("目前顯示的是前端介面示範，非後端查核結果。","Showing a front-end demonstration, not backend verification."));
      result.scrollIntoView({behavior:"smooth",block:"start"});
    });
    $("#ft-form").addEventListener("submit",function(e){
      e.preventDefault();
      var cleaned=extractTicker(ticker.value)||window.FTCompanies?.findInText?.(ticker.value)?.ticker||ticker.value.trim();
      if(cleaned!==ticker.value.trim())ticker.value=cleaned;
      if(window.FTCompanies?.get?.(cleaned))window.FTCompanies.addRecent(window.FTCompanies.get(cleaned));
      runWorkflow(mode.value,cleaned,query.value.trim(),result,button);
    });
    document.querySelectorAll("[data-ft-mode]").forEach(function(b){b.addEventListener("click",function(){mode.value=b.getAttribute("data-ft-mode");query.focus();});});
    if(p.query&&(p.ticker||mode.value==="text"))launchFromHome();
  }
  function startAudit(){
    var p=fromUrl(),ticker=$("#ft-audit-ticker"),button=$("#ft-audit-run"),result=$("#ft-result");
    if(!ticker||!button)return;
    ticker.value=p.ticker||"";

    if(!p.ticker&&p.query){resolveCompanyFromQuestion(p.query).then(function(code){if(code&&!ticker.value.trim()){ticker.value=code;run();}else if(!code)status(L("請先填入公司代號，再執行稽核。","Please enter the company ticker before running the audit."));});}

    async function run(){
      var code=ticker.value.trim();
      if(!/^\d{4,6}$/.test(code)){status(L("請輸入 4–6 碼公司代號。","Enter a 4–6 digit ticker."),true);return;}
      clear(result);result.hidden=false;button.disabled=true;
      status(L("正在取得正式後端的財務資料…","Retrieving financial data from the existing backend…"));
      try{
        var real=null,old=null;
        var tasks=[
          window.FTLiveFinancial?window.FTLiveFinancial.load(code):Promise.reject(new Error("No financial adapter")),
          api("/api/integrity/assessments/preview",{method:"POST",body:JSON.stringify({
            ticker:code,review_mode:"CURRENT_REVIEW",sections:["financial_checks","literature","jsd","claims"]
          })})
        ];
        var done=await Promise.allSettled(tasks);
        if(done[0].status==="fulfilled"){
          real=done[0].value;
          window.FTLiveFinancial.render(result,real);
        }
        if(done[1].status==="fulfilled"){
          old=done[1].value;renderAssessment(old,result);
        }
        if(real||old){
          status(real?L("已取得 Cloud Run 財務後端的真實指標、規則及公告資料。","Loaded real Cloud Run financial metrics, rules and announcements."):L("已取得整合稽核後端的資料。","Loaded integrity assessment from the connected backend."));
          var link=$("#ft-advanced-link");if(link)link.href="financial-integrity.html?ticker="+encodeURIComponent(code)+"&expand=1";
          result.scrollIntoView({behavior:"smooth",block:"start"});
        }else{
          var cause=done[0].reason||done[1].reason||new Error("Not available");
          status(errorMsg(cause),true);
          result.appendChild(para(L("尚無可取得的實際財務結果，請使用「介面示範」。","No real financial results are currently available. Use UI demo.")));
        }
      }finally{button.disabled=false;}
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
