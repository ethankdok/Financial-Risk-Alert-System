/* News verification uses only connected official evidence from Cloud Run.
 * It does not infer or fabricate a truth verdict when claim verification isn't available.
 */
(function(){
"use strict";
const t=(zh,en)=>window.FTLocale?.language?.()==="en"?en:zh;
const el=(tag,text,cl)=>{const x=document.createElement(tag);if(text!=null)x.textContent=String(text);if(cl)x.className=cl;return x;};
const arr=x=>Array.isArray(x)?x:[];
function isSafeOfficial(url){
 try{const u=new URL(url);return u.protocol==="https:"&&/(^|\.)twse\.com\.tw$|(^|\.)tpex\.org\.tw$/.test(u.hostname)?u.href:null;}catch{return null;}
}
function source(url,label){
 const safe=isSafeOfficial(url);if(!safe)return null;
 const a=el("a",label,"ft-inline-link");a.href=safe;a.target="_blank";a.rel="noopener noreferrer";return a;
}
function section(title){const div=el("section",null,"ft-news-evidence-section");div.appendChild(el("h3",title));return div;}
function render(container,payload,claim){
 if(!container)return;
 const card=payload.card||{};
 const existing=container.querySelector(".ft-live-report")||container;
 if(existing.querySelector(".ft-news-evidence-section"))return;
 const shell=el("div",null,"ft-news-evidence");
 const original=section(t("待查核的外部資訊","External claim to verify"));
 const content=String(claim||"").trim();
 original.appendChild(el("p",content||t("尚未輸入新聞或財務主張","No external claim was entered"),"ft-news-claim-text"));
 original.appendChild(el("span",t("核驗狀態：尚未取得逐項查證結論","Verification status: no claim-level verdict available"),"ft-demo-pill"));
 shell.appendChild(original);
 const status=card.source_status||{},inventory=section(t("官方證據索引","Official evidence index"));
 const totals=el("div",null,"ft-news-coverage");
 const counts=[
  [t("財務資料","Financial snapshot"),status.financial_snapshot_present===true?"✓":t("未取得","Unavailable")],
  [t("法說會／IR","Investor meetings / IR"),status.conference_count??arr(card.investor_conferences).length],
  [t("重大訊息","Material disclosures"),status.material_event_count??arr(payload.events).length],
  [t("官方揭露主題","Extracted disclosure topics"),status.claim_count??arr(card.disclosure_claims).length]
 ];
 for(const [title,value] of counts){
  const tile=el("div",null,"ft-news-stat");
  tile.appendChild(el("strong",value));tile.appendChild(el("span",title));totals.appendChild(tile);
 }inventory.appendChild(totals);
 const events=arr(payload.events).slice(0,8);
 if(events.length){
  inventory.appendChild(el("h4",t("近期官方重大訊息","Recent official material disclosures")));
  const list=el("div",null,"ft-news-events");
  for(const record of events){
   const row=el("div",null,"ft-news-event");
   row.appendChild(el("time",record.event_date||record.published_at||"—","ft-sheet-meta"));
   const main=el("div",null);main.appendChild(el("strong",record.title||record.subject||t("官方公告","Official disclosure")));
   const link=source(record.source_url||record.official_url,t("官方來源","Official source"));if(link)main.appendChild(link);
   row.appendChild(main);list.appendChild(row);
  }inventory.appendChild(list);
 }
 const claims=arr(card.disclosure_claims);
 if(claims.length){
  const details=el("details");details.className="ft-news-claim-details";
  details.appendChild(el("summary",t("查看已擷取的官方揭露主題","View extracted official disclosure topics")));
  const table=el("div",null,"ft-news-claim-rows");
  claims.slice(0,16).forEach(c=>{
   const row=el("div",null,"ft-news-claim-row");
   row.appendChild(el("strong",String(c.text||c.claim_type||"—").slice(0,210)));
   if(arr(c.related_metrics).length)row.appendChild(el("small",t("關聯財務指標：","Related metrics: ")+arr(c.related_metrics).slice(0,6).join("、")));
   table.appendChild(row);
  });details.appendChild(table);inventory.appendChild(details);
 }
 inventory.appendChild(el("p",t("這些是官方來源與系統已歸檔的揭露內容，並非對輸入新聞的自動核驗結論。","These are archived official sources and extracted disclosures, not an automatic verdict on the submitted news claim."),"ft-sheet-meta"));
 shell.appendChild(inventory);
 const narrative=el("section");narrative.id="ft-narrative-health";narrative.className="ft-news-narrative";
 shell.appendChild(narrative);
 const first=existing.firstChild;existing.insertBefore(shell,first);
 window.FTNarrative?.renderFromCard?.(narrative,card,payload.ticker);
}
window.FTNewsEvidence={render};
})();