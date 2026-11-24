/* FinTrust interface demo: never produces fake backend evidence or model inferences.
 * Finance values, if present, are read from the uploaded MOPS snapshot.
 * News, JSD, rule findings, verification statuses are deliberately left unverified.
 */
(function(){
"use strict";
const $=(s,root=document)=>root.querySelector(s);
const t=(zh,en)=>window.FTLocale?.language?.()==="en"?en:zh;
let cache=null;
async function snapshot(){
 if(cache)return cache;
 const r=await fetch("ft-mops-data.json",{cache:"force-cache"});
 if(!r.ok)throw new Error("snapshot unavailable");
 return(cache=await r.json());
}
function el(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n;}
function makeTable(labels,data){const sc=el("div",null,"ft-sheet-scroll");
 const table=el("table",null,"ft-sheet-table ft-demo-table"),head=el("thead"),tr=el("tr");
 labels.forEach(v=>tr.appendChild(el("th",v)));head.appendChild(tr);table.appendChild(head);
 const body=el("tbody");data.forEach(row=>{const r=el("tr");row.forEach((v,i)=>r.appendChild(el(i===0?"th":"td",v)));body.appendChild(r);});table.appendChild(body);sc.appendChild(table);return sc;
}
const metricTitle={DSRI:["應收帳款指數","Receivables index"],GMI:["毛利率指數","Gross margin index"],AQI:["資產品質指數","Asset quality index"],SGI:["營收成長指數","Sales growth index"],DEPI:["折舊指數","Depreciation index"],SGAI:["銷管費用指數","SG&A index"],LVGI:["負債指數","Leverage index"],TATA:["總應計項目","Total accruals"],RSST:["應計項目變動","Accrual changes"],dAR:["應收帳款變動","Receivables change"],dInventory:["存貨變動","Inventory change"],soft_assets:["軟性資產比率","Soft assets"],dCash_sales:["現金銷售變動","Cash-sales change"],dROA:["資產報酬變動","ROA change"],actual_issuance:["新增籌資","New issuance"]};
const finan=[["Sales_t","營業收入","Revenue"],["COGS_t","營業成本","Cost of revenue"],["REC_t","應收帳款","Accounts receivable"],["INV_t","存貨","Inventory"],["TA_t","資產總額","Total assets"],["CL_t","流動負債","Current liabilities"],["NIc_t","本期淨利","Net income"],["CFO_t","營業活動現金流量","Operating cash flow"]];
const fmt=v=>typeof v==="number"?v.toLocaleString("zh-TW",{maximumFractionDigits:6}):"—";
function rowBlock(title,body){const section=el("section",null,"ft-demo-section");section.appendChild(el("h3",title));if(body)section.appendChild(body);return section;}
function emptyFrame(header,rows){return makeTable(header,rows);}
function demoBadge(text){return el("span",text,"ft-demo-pill");}
function buildFinancial(rec,year){
 const wrap=el("div");if(!rec){
   wrap.appendChild(el("p",t("這家公司尚無本次財報快照；正式串接後顯示相應的官方財報數字。","No uploaded financial snapshot for this company. Live data will appear here once available."),"ft-home-muted"));return wrap;
 }
 const entries=finan.map(([key,zh,en])=>[t(zh,en),fmt(rec.raw_kNTD?.[key.replace("_t","_p")]),fmt(rec.raw_kNTD?.[key])]);
 wrap.appendChild(makeTable([t("財報科目（仟元）","Account (NTD thousands)"),String(Number(year)-1),String(year)],entries));
 const details=el("details"),sum=el("summary",t("查看資料檔名","Show source filename"));details.appendChild(sum);
 details.appendChild(el("code",rec.source_file||"—"));wrap.appendChild(details);return wrap;
}
function buildModels(rec){
 const box=el("div");if(!rec){
  box.appendChild(el("p",t("資料尚未收錄，模型欄位不填入示意分數。","No available inputs. Model scores are intentionally not simulated."),"ft-home-muted"));return box;
 }
 const q=el("div",null,"ft-demo-scores");
 for(const [name,val,flag] of [["Beneish M-score",rec.beneish?.M_score,rec.beneish?.flag],["Dechow F-score",rec.dechow?.F_score,rec.dechow?.flag]]){
  const unit=el("div",null,"ft-demo-score");unit.append(el("span",name),el("strong",fmt(val)),demoBadge(val==null?t("不可計算","Not computable"):flag?t("超過門檻","Above threshold"):t("未超過門檻","Below threshold")));q.appendChild(unit);
 }
 box.appendChild(q);
 for(const [group,model] of [["Beneish",rec.beneish],["Dechow",rec.dechow]]){
  const details=el("details");details.open=group==="Beneish";
  details.appendChild(el("summary",group+" · "+t("完整指標","All metrics")));
  const names=group==="Beneish"?["DSRI","GMI","AQI","SGI","DEPI","SGAI","LVGI","TATA"]:["RSST","dAR","dInventory","soft_assets","dCash_sales","dROA","actual_issuance"];
  details.appendChild(makeTable([t("指標","Metric"),t("名稱","Name"),t("數值","Value")],names.map(key=>[key,t(...metricTitle[key]),fmt(model?.[key])])));
  box.appendChild(details);
 }
 return box;
}
function buildVerify(claim,rec){
 const box=el("div");const given=claim.trim();
 box.appendChild(makeTable([t("查核項目","Check item"),t("查核內容","Content"),t("驗證狀態","Verification status")],[
  [t("輸入主張","Submitted claim"),given||t("尚未輸入新聞或財務主張","No claim entered"),given?t("等待後端查證","Backend verification pending"):t("尚無主張","No claim")],
  [t("官方財報比較","Official statement comparison"),rec?t("已有上傳財務科目","Uploaded financial accounts available"):t("尚無此公司財報快照","No uploaded financial snapshot"),t("尚未執行官方核對","Not verified")],
  [t("重大訊息與新聞","Material events and news"),t("後端提供資料時顯示日期、主張及來源","Publication date, claim and sources will appear from backend"),t("尚未取得資料","No data received")]
 ]));
 return box;
}
function buildText(){
 const box=el("div");
 box.appendChild(makeTable([t("分析項目","Analysis item"),t("預計輸出欄位","Expected output"),t("執行狀態","Execution status")],[
 [t("文字風險規則","Text-risk rules"),t("觸發條件、對應文字、原因","Matched phrases, rules and reasons"),t("示範，尚未執行","Demo only")],
 [t("敘事文字比較","Narrative comparison"),"JSD、Cosine、"+t("比較期間及來源","Periods and sources"),t("示範，尚未執行","Demo only")],
 [t("財報文字版本","Disclosure versions"),t("首次申報、更新版本與發布日期","Initial filing, revisions and publication dates"),t("需要官方版本資料","Requires official evidence")]
 ]));
 return box;
}
async function render(target,options={}){
 if(!target)return;
 target.hidden=false;target.replaceChildren();
 const demo=el("div",null,"ft-demo-shell");target.appendChild(demo);
 const toolbar=el("div",null,"ft-demo-toolbar");
 toolbar.appendChild(demoBadge(t("介面示範｜非實際查核結果","UI demo · Not a real verification result")));
 const exit=el("button",t("返回實際查核","Return to live verification"),"ft-text-button");exit.type="button";exit.addEventListener("click",()=>{target.replaceChildren();target.hidden=true;});
 toolbar.appendChild(exit);demo.appendChild(toolbar);
 const ticker=String(options.ticker||"6505").match(/\d{4,6}/)?.[0]||"6505";
 let doc=null,info=null;
 try{
  const data=await snapshot();
  for(const industry of Object.values(data.industries)){if(industry[ticker]){info=industry[ticker];break;}}
  if(info){const year=Object.keys(info.years).sort().at(-1);doc={year,record:info.years[year]};}
 }catch(_){}
 const selected=window.FTCompanies?.get(ticker);
 demo.appendChild(el("h2",(selected?.name||info?.short||t("範例報告","Example report"))+"（"+ticker+"）"));
 demo.appendChild(el("p",doc?
   t("財務數字來自你提供的 MOPS Pipeline 輸出；其餘欄位只展示未接通功能的介面。","Financial values use the supplied MOPS Pipeline snapshot; other sections demonstrate the future UI.") :
   t("此公司尚無財務快照。下列為操作流程示範，不包含模型分數或真偽判斷。","No financial snapshot for this company. The UI demo contains no model scores or verification verdict."),"ft-sheet-meta"));
 const tabs=el("div",null,"ft-sheet-tabs");
 const body=el("div",null,"ft-demo-body");
 const panels=[
 ["finance",t("財務報表","Financial statements"),()=>buildFinancial(doc?.record,doc?.year)],
 ["models",t("異常指標","Risk metrics"),()=>buildModels(doc?.record)],
 ["verify",t("證據查核","Evidence verification"),()=>buildVerify(options.claim||"",doc?.record)],
 ["text",t("文字分析","Text analysis"),()=>buildText()]
 ];
 let active=options.mode==="text"?"text":options.mode==="claim"?"verify":"finance";
 function display(){
  tabs.replaceChildren();body.replaceChildren();
  panels.forEach(([id,label,fn])=>{
   const b=el("button",label);b.className=active===id?"active":"";b.type="button";
   b.addEventListener("click",()=>{active=id;display();});tabs.appendChild(b);
  });
  const p=panels.find(x=>x[0]===active);body.appendChild(rowBlock(p[1],p[2]()));
 }
 demo.append(tabs,body);display();
}
async function health(){
 const abort=new AbortController();const timeout=setTimeout(()=>abort.abort(),5000);
 try{
  const r=await fetch("/api/financial/health",{credentials:"same-origin",cache:"no-store",signal:abort.signal,headers:{Accept:"application/json"}});
  if(!r.ok)throw Error("HTTP "+r.status);
  const payload=await r.json();
  const result=payload?.data||payload;
  return {available:result&&typeof result==="object"&&!!(result.status||result.service||result.fintrust_api||result.healthy),detail:result};
 }catch(e){return{available:false,error:e.message};}finally{clearTimeout(timeout);}
}
async function mountHealth(elem){
 if(!elem)return;elem.classList.add("ft-api-health");
 elem.textContent=t("檢查後端連線…","Checking backend connection…");
 const status=await health();
 elem.textContent=status.available?t("已連線：既有後端","Connected: existing backend"):t("後端未確認連線，可使用介面示範","Backend unavailable; UI demo available");
 elem.classList.toggle("ft-health-ok",status.available);
 elem.classList.toggle("ft-health-offline",!status.available);
 elem.title=status.available?t("既有後端 API 有回應","Existing API returned a response"):String(status.error||"");
}
window.FTDemo={render,health,mountHealth};
document.addEventListener("DOMContentLoaded",()=>{document.querySelectorAll("[data-ft-api-health]").forEach(mountHealth);});
})();