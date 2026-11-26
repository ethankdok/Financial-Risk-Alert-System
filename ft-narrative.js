/* FinTrust enterprise health: live narrative drift from archived official evidence.
   Read-only GET /api/financial/companies/:ticker/card. JSD is NOT fraud probability.
*/
(function(){
"use strict";
const t=(zh,en)=>window.FTLocale?.language?.()==="en"?en:zh;
const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=String(text);if(cls)e.className=cls;return e;};
const num=v=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toFixed(6);
const labels=[
 ["raw_text_word_jsd","原始文字 JSD","Raw-text JSD"],
 ["cleaned_text_word_jsd","清洗後文字 JSD","Clean-text JSD"],
 ["relevant_text_word_jsd","相關文字 JSD","Relevant-text JSD"],
 ["topic_distribution_jsd","主題分布 JSD","Topic-distribution JSD"],
 ["semantic_tfidf_cosine_similarity","文字 Cosine 相似度","TF-IDF cosine similarity"]
];
let token=0;
function sheet(head,rows){
 const sc=el("div",null,"ft-sheet-scroll"),tb=el("table",null,"ft-sheet-table"),thead=el("thead"),tr=el("tr");
 head.forEach(h=>tr.appendChild(el("th",h)));thead.appendChild(tr);tb.appendChild(thead);
 const body=el("tbody");
 rows.forEach(r=>{const row=el("tr");r.forEach((cell,i)=>row.appendChild(el(i===0?"th":"td",cell)));body.appendChild(row);});
 tb.appendChild(body);sc.appendChild(tb);return sc;
}
function sourceLink(obj){
 const u=obj?.source_url||obj?.document_url;if(!u)return null;
 try{const url=new URL(u);if(url.protocol!=="https:"||!/(^|\.)twse\.com\.tw$|(^|\.)tpex\.org\.tw$/.test(url.hostname))return null;
 const a=el("a",t("查看官方來源","View official evidence"),"ft-inline-link");a.href=url.href;a.target="_blank";a.rel="noopener noreferrer";return a;
 }catch{return null;}
}
function officialCompare(target,ticker){
 const wrapper=el("div",null,"ft-official-compare");
 wrapper.appendChild(el("h3",t("官方法說會跨期分析","Official conference comparison")));
 wrapper.appendChild(el("p",t("使用已歸檔的相鄰季度同類型文件執行 JSD 與 Cosine。期間留空則使用最新可比組合；此分析不同於年度財報文字研究。","Compare adjacent-quarter archived documents. Leave periods blank for the latest pair; distinct from annual-report research."),"ft-sheet-meta"));
 const form=el("form",null,"ft-audit-inline"),first=el("input",null,"ft-input"),second=el("input",null,"ft-input");
 first.placeholder="2025Q2";second.placeholder="2025Q3";first.setAttribute("aria-label","前期");second.setAttribute("aria-label","本期");first.pattern=second.pattern="20[0-9]{2}Q[1-4]";
 const btn=el("button",t("執行官方文字比較","Compare official documents"),"ft-btn ft-btn-primary");btn.type="submit";form.append(first,second,btn);wrapper.appendChild(form);
 const result=el("div",null,"ft-official-compare-result");result.setAttribute("aria-live","polite");wrapper.appendChild(result);target.appendChild(wrapper);
 form.addEventListener("submit",async e=>{
  e.preventDefault();if(Boolean(first.value)!==Boolean(second.value)){result.textContent="請同時填寫兩個期間，或皆留空。";return;}
  btn.disabled=true;result.textContent="正在執行文字比較…";
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),45000);
  try{
   const res=await fetch("/api/financial/data-shift/analyze",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({company_code:ticker,period_1:first.value||null,period_2:second.value||null}),signal:controller.signal});
   const payload=await res.json();if(!res.ok||payload.success===false)throw Error(payload.error||"HTTP "+res.status);
   const d=payload.data||payload;result.replaceChildren();
   result.appendChild(el("p",ticker+" · "+(d.period_1||"—")+" → "+(d.period_2||"—")+" · "+(d.document_type||"")+" · "+(d.language||"")));
   if(d.metrics&&typeof d.metrics.jsd==="number"&&typeof d.metrics.cosine_similarity==="number"){
    result.appendChild(sheet(["分析指標","後端實際輸出"],[["JSD",num(d.metrics.jsd)],["Cosine Similarity",num(d.metrics.cosine_similarity)]]));
   }else result.appendChild(el("p","未取得可計算指標："+(d.reason_code||d.analysis_status||"資料不足"),"ft-narrative-warning"));
   result.appendChild(el("p","資料品質："+(d.data_quality?.passed===true?"通過":d.data_quality?.passed===false?"未通過":"未評估")+"；校準："+(d.calibration?.status||"未評估")+"；方法："+(d.method?.method_version||"未提供"),"ft-sheet-meta"));
   for(const item of d.source_documents||[]){const row=el("p",String(item.document_name||item.title||item.period||"官方文件")+" ");const link=sourceLink(item);if(link)row.appendChild(link);result.appendChild(row);}
   for(const item of d.limitations||[])result.appendChild(el("p",String(item),"ft-sheet-meta"));
   const details=el("details");details.appendChild(el("summary","後端 JSD 模型輸出與來源"));const pre=el("pre",JSON.stringify(d,null,2),"ft-code");pre.style.whiteSpace="pre-wrap";details.appendChild(pre);result.appendChild(details);
  }catch(err){result.textContent="文字比較未完成："+err.message;}finally{clearTimeout(timer);btn.disabled=false;}
 });
}
function display(target,card,ticker){
 target.replaceChildren();
 const n=card?.narrative_shift;
 const heading=el("div",null,"ft-panel-heading");heading.appendChild(el("h2",t("文字漂移與敘事差異","Text drift & narrative changes")));
 target.appendChild(heading);
 if(!n||!n.metrics||!Object.values(n.metrics).some(v=>typeof v==="number")){
  target.appendChild(el("p",t("這家公司尚無可比較的官方文字資料。","No comparable official text evidence is available for this company."),"ft-home-muted"));officialCompare(target,ticker);return;
 }
 const meta=el("div",null,"ft-narrative-meta");
 meta.appendChild(el("strong",(card.company_name||ticker)+"（"+ticker+"）"));
 meta.appendChild(el("span",(n.period_1||"—")+"　→　"+(n.period_2||"—"),"ft-sheet-meta"));
 meta.appendChild(el("span",t("比較來源：","Compared source: ")+(n.period_1_source_type||"—")+" / "+(n.period_2_source_type||"—"),"ft-sheet-meta"));
 target.appendChild(meta);
 const passed=n.data_quality?.passed===true;
 const quality=el("span",passed?t("通過文字品質檢查","Text quality check passed"):t("未通過文字品質檢查","Text quality check not passed"),"ft-sheet-badge"+(passed?"":" alert"));
 target.appendChild(quality);
 if(!passed){
  const reasons=Array.isArray(n.data_quality?.reasons)?n.data_quality.reasons:[];
  if(reasons.length)target.appendChild(el("p",reasons.join("；"),"ft-narrative-warning"));
 }
 const body=labels.map(([key,zh,en])=>[t(zh,en),num(n.metrics[key])]);
 target.appendChild(sheet([t("分析指標","Metric"),t("模型輸出","Value")],body));
 const details=el("details");details.className="ft-narrative-details";
 details.appendChild(el("summary",t("查看主題、文字變化及證據","Review topics, terms & evidence")));
 if(Array.isArray(n.topic_changes)&&n.topic_changes.length){
  details.appendChild(el("h3",t("主題分布變化","Topic distribution changes")));
  details.appendChild(sheet([t("主題","Topic"),t("前期比例","Prior"),t("本期比例","Current"),t("差異","Change")],n.topic_changes.slice(0,10).map(v=>[
   String(v.topic||"—"),num(v.period_1_rate),num(v.period_2_rate),num(v.change)
  ])));
 }
 if(Array.isArray(n.emerging_terms)&&n.emerging_terms.length){
  details.appendChild(el("h3",t("新增或增加詞彙","Emerging or increasing terms")));
  details.appendChild(sheet([t("詞彙","Term"),t("變化量","Change")],n.emerging_terms.slice(0,10).map(v=>[String(v.term||"—"),num(v.change)])));
 }
 const sentences=Array.isArray(n.supporting_sentences)?n.supporting_sentences.slice(0,5):[];
 if(sentences.length){
  details.appendChild(el("h3",t("官方文字證據","Official text evidence")));
  sentences.forEach(v=>{
   const entry=el("div",null,"ft-narrative-evidence");
   entry.appendChild(el("span",(v.event_date||v.period||"")+" · "+(v.section||v.source_type||""),"ft-sheet-meta"));
   entry.appendChild(el("p",String(v.original_text||v.cleaned_text||"").slice(0,500)));
   const link=sourceLink(v);if(link)entry.appendChild(link);
   details.appendChild(entry);
  });
 }
 target.appendChild(details);
 officialCompare(target,ticker);
 target.appendChild(el("p",t("JSD 反映不同期間文字分布差異，Cosine 反映文字相似度；兩者均不是舞弊或財報不實機率。未通過品質門檻時不進行風險判定。","JSD measures distribution shifts and cosine measures text similarity. Neither is fraud probability. When quality requirements are not met, no risk judgement is made."),"ft-sheet-meta"));
}
async function show(ticker){
 const target=document.getElementById("ft-narrative-health");if(!target)return;
 const current=++token;
 target.replaceChildren(el("p",t("正在讀取官方文字資料…","Loading archived official text evidence…"),"ft-home-muted"));
 if(!/^\d{4,6}$/.test(String(ticker))){target.replaceChildren();return;}
 const ctl=new AbortController(),timer=setTimeout(()=>ctl.abort(),15000);
 try{
  const url="/api/financial/companies/"+encodeURIComponent(ticker)+"/card";
  const res=await fetch(url,{headers:{Accept:"application/json"},credentials:"same-origin",cache:"no-store",signal:ctl.signal});
  if(!res.ok)throw Error("HTTP "+res.status);
  const payload=await res.json();
  if(payload.success===false)throw Error(payload.error||"API unavailable");
  if(token!==current)return;
  display(target,payload.data||payload,ticker);
 }catch(e){
  if(token!==current)return;
  target.replaceChildren();
  const h=el("h2",t("文字漂移與敘事差異","Text drift & narrative changes"));target.appendChild(h);
  target.appendChild(el("p",t("目前無法取得這家公司的文字比較結果。","Text comparison is currently unavailable for this company."),"ft-home-muted"));
 }finally{clearTimeout(timer);}
}
window.FTNarrative={show,renderFromCard:display,officialCompare};
})();