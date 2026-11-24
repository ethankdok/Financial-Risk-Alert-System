/* Existing FinTrust Cloud Run financial backend -> new UI.
 * All numerical values and verdicts originate from the existing GET APIs.
 * No model inferences run here; Beneish/Dechow snapshots remain separate.
 */
(function(){
"use strict";
const t=(zh,en)=>window.FTLocale?.language?.()==="en"?en:zh;
const el=(tag,txt,cls)=>{const n=document.createElement(tag);if(txt!=null)n.textContent=String(txt);if(cls)n.className=cls;return n;};
const arr=value=>Array.isArray(value)?value:[];
const num=(value,unit)=>{
 if(value===null||value===undefined||value==="")return"—";
 const n=Number(value);if(!Number.isFinite(n))return String(value);
 return n.toLocaleString("zh-TW",{maximumFractionDigits:(unit==="新台幣元"||unit==="NTD")?0:4});
};
const allowUrl=url=>{
 try{const u=new URL(url);
  if(u.protocol!=="https:")return null;
  if(!/(^|\.)twse\.com\.tw$|(^|\.)tpex\.org\.tw$/.test(u.hostname))return null;
  return u.href;
 }catch{return null;}
};
async function api(url){
 const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),14000);
 try{
  const resp=await fetch(url,{headers:{Accept:"application/json"},credentials:"same-origin",cache:"no-store",signal:ctrl.signal});
  if(!resp.ok)throw Error("HTTP "+resp.status);
  const data=await resp.json();if(data?.success===false)throw Error(String(data.error||"Server error"));
  return data?.data??data;
 }finally{clearTimeout(timer);}
}
async function load(ticker){
 const code=String(ticker||"").trim();
 if(!/^\d{4,6}$/.test(code))throw Error(t("請輸入有效公司代號","Enter a valid ticker"));
 const base="/api/financial/companies/"+encodeURIComponent(code);
 const settled=await Promise.allSettled([
  api(base+"/card"),
  api(base+"/metrics?latest_only=false&limit=500"),
  api(base+"/material-events")
 ]);
 const [card,metrics,events]=settled.map(x=>x.status==="fulfilled"?x.value:null);
 if(!card&&!metrics)throw Error(t("既有財務後端尚未提供此公司查核資料","No financial data was returned by the existing backend for this company"));
 return{
  ticker:code,card:card||{},metrics:metrics||{},events:arr(events||card?.material_events),
  fetchedAt:new Date().toISOString(),
  partial:!card||!metrics||!events
 };
}
function sheet(headers,rows){
 const container=el("div",null,"ft-sheet-scroll"),table=el("table",null,"ft-sheet-table");
 const head=el("thead"),tr=el("tr");headers.forEach(v=>tr.appendChild(el("th",v)));head.appendChild(tr);table.appendChild(head);
 const body=el("tbody");
 rows.forEach(row=>{const line=el("tr");row.forEach((v,i)=>line.appendChild(el(i===0?"th":"td",v??"—")));body.appendChild(line);});
 table.appendChild(body);container.appendChild(table);return container;
}
function section(title){
 const sec=el("section",null,"ft-live-section");sec.appendChild(el("h3",title));return sec;
}
function render(container,result,opts={}){
 if(!container)return;
 const {ticker,card,metrics,events}=result;
 const snapshot=card.financial_snapshot||{},analysis=Object.keys(snapshot).length?snapshot:card;
 container.hidden=false;container.replaceChildren();
 const root=el("div",null,"ft-live-report");container.appendChild(root);
 const top=el("div",null,"ft-live-heading");
 const intro=el("div");intro.appendChild(el("h2",(card.company_name||snapshot.company_name||ticker)+"（"+ticker+"）"));
 intro.appendChild(el("p",t("既有 Cloud Run 財務資料","Live Cloud Run financial data")+" · "+(card.subindustry||analysis.subindustry||t("公司資料","Company data")),"ft-sheet-meta"));
 top.appendChild(intro);
 const badge=el("span",t("已取得後端資料","Backend response received"),"ft-sheet-badge");
 top.appendChild(badge);root.appendChild(top);
 const distinctMetricCount=new Set(arr(metrics.metrics).map(item=>String(item.metric_code||item.label||"")).filter(Boolean)).size;
 const triggeredCount=arr(card.rule_cards||analysis.rule_cards).filter(item=>item.triggered===true).length;
 const eventCount=events.length||arr(card.material_events).length;
 const atAGlance=el("div",null,"ft-live-at-a-glance");
 [
  [t("歷史財務指標","Historical metrics"),distinctMetricCount||arr(card.key_metrics).length],
  [t("觸發風險規則","Triggered screening rules"),triggeredCount],
  [t("官方重大訊息","Official disclosures"),eventCount]
 ].forEach(([label,count])=>{
  const cardEl=el("div",null,"ft-live-glance-card");
  cardEl.appendChild(el("strong",String(count)));
  cardEl.appendChild(el("span",label));
  atAGlance.appendChild(cardEl);
 });
 root.appendChild(atAGlance);
 const metricsList=arr(card.key_metrics||analysis.key_metrics);
 const metricRows=arr(metrics.metrics);
 const years=["2021FY","2022FY","2023FY","2024FY","2025FY"];
 const matrix=metricsList.length?metricsList.map(item=>[
   item.label||item.code, ...years.map(y=>num(item.period_values?.[y],item.unit)),item.unit||"—"
 ]):[];
 if(!matrix.length&&metricRows.length){
  const groups=new Map();
  metricRows.forEach(r=>{const code=String(r.metric_code||r.label||"");if(!code)return;
   if(!groups.has(code))groups.set(code,{label:r.label||code,unit:r.unit||"",periods:{}});
   groups.get(code).periods[r.period]=r.value;
  });
  for(const g of groups.values())matrix.push([g.label,...years.map(y=>num(g.periods[y],g.unit)),g.unit||"—"]);
 }
 const money=section(t("歷年財務指標","Historical financial metrics"));
 if(matrix.length){
  money.appendChild(sheet([t("項目","Metric"),...years.map(y=>y.slice(0,4)),t("單位","Unit")],matrix.slice(0,50)));
  const dl=el("button",t("下載目前表格","Download displayed table"),"ft-btn");dl.type="button";dl.addEventListener("click",()=>{
    const rows=[[t("項目","Metric"),...years.map(y=>y.slice(0,4)),t("單位","Unit")],...matrix.slice(0,50)];
    const csv="\ufeff"+rows.map(v=>v.map(x=>'"'+String(x??"").replaceAll('"','""')+'"').join(",")).join("\r\n");
    const blob=new Blob([csv],{type:"text/csv;charset=utf-8"});const href=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=href;a.download=ticker+"_live_financial_metrics.csv";a.click();setTimeout(()=>URL.revokeObjectURL(href),500);
  });
  money.appendChild(dl);
 }else money.appendChild(el("p",t("此後端目前沒有可展示的歷年指標","The backend returned no historical metric values"),"ft-sheet-meta"));
 root.appendChild(money);
 const rules=arr(card.rule_cards||analysis.rule_cards);
 if(rules.length){
  const sectionRules=section(t("既有財務風險規則","Existing financial screening rules"));
  const triggered=rules.filter(r=>r.triggered===true);
  sectionRules.appendChild(el("p",t("觸發","Triggered")+" "+triggered.length+" / "+rules.length+"　·　"+(analysis.rule_version||"—"),"ft-sheet-meta"));
  const list=triggered.length?triggered:rules.slice(0,8);
  sectionRules.appendChild(sheet([t("篩檢規則","Rule"),t("狀態","Status"),t("對應期間","Period")],list.map(r=>[
   r.name||r.rule_id||"—",r.triggered?t("觸發","Triggered"):t("未觸發","Not triggered"),arr(r.evidence_periods).join(", ")||"—"
  ])));
  const details=el("details");details.appendChild(el("summary",t("查看規則說明與門檻","Inspect rule criteria and thresholds")));
  list.slice(0,12).forEach(r=>{
   const block=el("div",null,"ft-live-rule");
   block.appendChild(el("strong",r.name||r.rule_id));
   if(r.explanation)block.appendChild(el("p",r.explanation));
   if(r.threshold_description)block.appendChild(el("p",r.threshold_description,"ft-sheet-meta"));
   details.appendChild(block);
  });
  sectionRules.appendChild(details);
  sectionRules.appendChild(el("p",t("規則是財務趨勢篩檢，不代表財報造假。","These are financial screening rules, not proof of false reporting."),"ft-sheet-meta"));
  root.appendChild(sectionRules);
 }
 if(events.length){
  const eventsSection=section(t("官方重大訊息","Official material disclosures"));
  const table=sheet([t("日期","Date"),t("重大訊息","Announcement"),t("資料來源","Source")],events.slice(0,12).map(v=>[
   v.event_date||v.published_at||"—",v.title||v.subject||"—",v.source_name||"TWSE"
  ]));eventsSection.appendChild(table);
  const sources=[...new Set(events.map(ev=>allowUrl(ev.source_url||ev.official_url||"")).filter(Boolean))].slice(0,3);
  for(const href of sources){const a=el("a",t("查看交易所公開資訊","View exchange disclosure source"),"ft-inline-link");a.href=href;a.target="_blank";a.rel="noopener noreferrer";eventsSection.appendChild(a);}
  root.appendChild(eventsSection);
 }
 const origin=arr(card.sources||analysis.sources);
 if(origin.length){
  const sources=section(t("財報來源","Financial report sources"));
  sources.appendChild(sheet([t("年度","Fiscal year"),t("來源","Document"),t("狀態","Status")],origin.slice(0,16).map(v=>[
   v.period||"—",v.source_name||"MOPS",v.status||"—"
  ])));
  const links=el("div",null,"ft-live-source-links");
  origin.slice(0,8).forEach((v,i)=>{const url=allowUrl(v.source_url);
   if(!url)return;
   const a=el("a",String(v.period||i+1)+" "+t("官方來源","Official source"),"ft-inline-link");
   a.href=url;a.target="_blank";a.rel="noopener noreferrer";links.appendChild(a);
  });
  sources.appendChild(links);root.appendChild(sources);
 }
 if(typeof opts.claim==="string"&&opts.claim.trim()){
  const inquiry=section(t("輸入內容","Submitted claim"));
  inquiry.appendChild(el("p",opts.claim.slice(0,1700)));
  inquiry.appendChild(el("p",t("此區僅提供公司財務與官方公告證據；主張核驗結論以獨立查證結果為準。","This section presents company financial and disclosure evidence only; see the separate claim verification result for the verdict."),"ft-sheet-meta"));
  root.appendChild(inquiry);
 }
 if(typeof analysis.summary==="string"&&analysis.summary.trim()){
  const details=el("details");details.className="ft-live-technical";
  details.appendChild(el("summary",t("查看後端分析摘要","View backend analysis summary")));
  details.appendChild(el("p",analysis.summary));
  root.appendChild(details);
 }
 root.appendChild(el("p",t("資料由既有後端提供；申報日期、歷史版本與指標有效性以各來源記錄為準。JCAATs 尚未串接。","Data originates from the existing backend. Filing versions and validity depend on source records. JCAATs is not connected."),"ft-sheet-meta"));
}
window.FTLiveFinancial={load,render};
})();