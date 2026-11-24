/* MOPS sheet report: uses user-provided, locally captured 2021-2025 iXBRL output. */
(function(){
"use strict";
const $=s=>document.querySelector(s);
const fmt=(x,d=3)=>x==null||!Number.isFinite(Number(x))?"—":Number(x).toLocaleString("zh-TW",{maximumFractionDigits:d,minimumFractionDigits:d});
const integer=x=>x==null||!Number.isFinite(Number(x))?"—":Number(x).toLocaleString("zh-TW",{maximumFractionDigits:0});
const t=(zh,en)=>localStorage.getItem("ft-language")==="en"?en:zh;
const field={
 Sales:["營業收入","Revenue"],COGS:["營業成本","Cost of revenue"],SGA:["營業費用","Operating expenses"],
 NIc:["本期淨利","Net income"],Cash:["現金及約當現金","Cash and equivalents"],
 STI:["短期投資","Short-term investments"],REC:["應收帳款","Accounts receivable"],INV:["存貨","Inventory"],
 CA:["流動資產","Current assets"],PPE:["不動產、廠房及設備","Property, plant & equipment"],LTI:["長期投資","Long-term investments"],
 TA:["資產總額","Total assets"],CL:["流動負債","Current liabilities"],TL:["負債總額","Total liabilities"],
 DebtCL:["一年內到期借款","Current debt"],LTD:["長期借款","Long-term debt"],CFO:["營業活動現金流量","Operating cash flow"],
 Dep:["折舊費用","Depreciation"],IssShare:["增資金額","Equity issues"],IssBond:["發行債券","Bond issues"],IssLTD:["新增長期融資","New long-term borrowing"]
};
const groups=[
 ["損益表","Income statement",["Sales","COGS","SGA","NIc"]],
 ["資產負債表","Balance sheet",["Cash","STI","REC","INV","CA","PPE","LTI","TA","DebtCL","CL","LTD","TL"]],
 ["現金流量表及其他","Cash flows and financing",["CFO","Dep","IssShare","IssBond","IssLTD"]]
];
const beneish=[
 ["DSRI","應收帳款指數","Receivables index","(REC_t / Sales_t) / (REC_p / Sales_p)",["REC_t","Sales_t","REC_p","Sales_p"]],
 ["GMI","毛利率指數","Gross margin index","((Sales_p - COGS_p) / Sales_p) / ((Sales_t - COGS_t) / Sales_t)",["Sales_p","COGS_p","Sales_t","COGS_t"]],
 ["AQI","資產品質指數","Asset quality index","(1 - (CA_t + PPE_t) / TA_t) / (1 - (CA_p + PPE_p) / TA_p)",["CA_t","PPE_t","TA_t","CA_p","PPE_p","TA_p"]],
 ["SGI","營收成長指數","Sales growth index","Sales_t / Sales_p",["Sales_t","Sales_p"]],
 ["DEPI","折舊指數","Depreciation index","(Dep_p / (Dep_p + PPE_p)) / (Dep_t / (Dep_t + PPE_t))",["Dep_p","PPE_p","Dep_t","PPE_t"]],
 ["SGAI","銷管費用指數","SG&A index","(SGA_t / Sales_t) / (SGA_p / Sales_p)",["SGA_t","Sales_t","SGA_p","Sales_p"]],
 ["LVGI","負債指數","Leverage index","((CL_t + LTD_t) / TA_t) / ((CL_p + LTD_p) / TA_p)",["CL_t","LTD_t","TA_t","CL_p","LTD_p","TA_p"]],
 ["TATA","總應計項目","Total accruals","(NIc_t - CFO_t) / TA_t",["NIc_t","CFO_t","TA_t"]]
];
const dechow=[
 ["RSST","應計項目變動","Accrual changes","(ΔWC + ΔNCO + ΔFIN) / ((TA_t + TA_p) / 2)",["CA_t","CA_p","Cash_t","Cash_p","STI_t","STI_p","CL_t","CL_p","DebtCL_t","DebtCL_p","TA_t","TA_p"]],
 ["dAR","應收帳款變動","Receivables change","(REC_t - REC_p) / AverageAssets",["REC_t","REC_p","TA_t","TA_p"]],
 ["dInventory","存貨變動","Inventory change","(INV_t - INV_p) / AverageAssets",["INV_t","INV_p","TA_t","TA_p"]],
 ["soft_assets","軟性資產比率","Soft assets","(TA_t - PPE_t - Cash_t) / TA_t",["TA_t","PPE_t","Cash_t"]],
 ["dCash_sales","現金銷售變動","Cash sales change","(CashSales_t - CashSales_p) / CashSales_p",["Sales_t","REC_t","REC_p","Sales_p","REC_pp"]],
 ["dROA","資產報酬變動","ROA change","NIc_t / AverageAssets_t - NIc_p / AverageAssets_p",["NIc_t","NIc_p","TA_t","TA_p","TA_pp"]],
 ["actual_issuance","新增籌資","New issuance","(IssShare > 0 OR IssBond > 0 OR IssLTD > 0) ? 1 : 0",["IssShare","IssBond","IssLTD"]]
];
let database=null,company="6505",year="2025",tab="financial";
function el(tag,text,cls){const x=document.createElement(tag);if(text!=null)x.textContent=String(text);if(cls)x.className=cls;return x;}
function tr(cells){const r=el("tr");cells.forEach((v,i)=>{const c=el(i===0?"th":"td",v);if(i===0)c.scope="row";r.appendChild(c);});return r;}
function table(head,rows){const sc=el("div",null,"ft-sheet-scroll");const tb=el("table",null,"ft-sheet-table");const thead=el("thead"),headrow=el("tr");head.forEach(x=>headrow.appendChild(el("th",x)));thead.appendChild(headrow);tb.appendChild(thead);const bd=el("tbody");rows.forEach(row=>bd.appendChild(row));tb.appendChild(bd);sc.appendChild(tb);return sc;}
function quality(v,flag){const tag=el("span",v,"ft-sheet-badge"+(flag===true?" alert":""));return tag;}
function header(p){
  const top=el("div",null,"ft-sheet-heading");
  const name=el("div");name.appendChild(el("h2",database.industries[p.group][company].short+"（"+company+"）"));
  name.appendChild(el("span",(p.group||"")+" · "+year+" Q4 · "+t("合併財報","Consolidated")+" · "+t("單位：新台幣仟元","NTD thousand"),"ft-sheet-meta"));
  top.appendChild(name);
  const action=el("button",t("下載目前表格 CSV","Download current CSV"),"ft-btn");action.type="button";action.addEventListener("click",downloadCSV);top.appendChild(action);
  return top;
}
function showInputs(rec,label,formula,keys,value){
 const dest=$("#ft-formula-details");dest.replaceChildren();
 dest.appendChild(el("h3",label+"　"+fmt(value,6)));
 dest.appendChild(el("p",formula,"ft-code"));
 dest.appendChild(el("h4",t("計算使用的原始科目","Source financial inputs")));
 const rows=keys.map(k=>tr([k,field[k.replace(/_(t|p|pp)$/,"")]?.[localStorage.getItem("ft-language")==="en"?1:0]||k,integer(rec.raw_kNTD?.[k])]));
 dest.appendChild(table([t("欄位","Field"),t("名稱","Account"),t("數值（仟元）","Value (NTD thousand)")],rows));
 dest.hidden=false;dest.scrollIntoView({block:"nearest",behavior:"smooth"});
}
function renderFinancial(rec,prev){
 const root=$("#ft-sheet-body");
 for(const [zh,en,keys] of groups){
  const title=el("div",t(zh,en),"ft-sheet-group");root.appendChild(title);
  const rows=keys.map(key=>{
   const p=rec.raw_kNTD||{},v=p[key+"_t"]??p[key],old=p[key+"_p"]??prev?.raw_kNTD?.[key+"_t"];
   const rate=old==null||old===0||v==null?"—":fmt((v/old-1)*100,2)+"%";
   const row=tr([t(...field[key]),integer(old),integer(v),rate,key]);
   if(typeof rate==="string"&&rate.startsWith("-"))row.classList.add("ft-sheet-down");
   return row;
  });
  root.appendChild(table([t("財報科目","Account"),String(Number(year)-1),year,t("年增率","YoY"),t("科目代碼","Code")],rows));
 }
}
function renderModel(rec,prev,model){
 const root=$("#ft-sheet-body"),isM=model==="beneish";
 const rows=(isM?beneish:dechow).map(def=>{
   const [key,zh,en,formula,inputs]=def;
   const current=rec[model]?.[key],last=prev?.[model]?.[key];
   const row=tr([key,t(zh,en),fmt(last,6),fmt(current,6),current==null?t("不可計算","N/A"):t("檢視計算","View formula")]);
   row.className="ft-sheet-selectable";row.tabIndex=0;row.addEventListener("click",()=>showInputs(rec,key+" · "+t(zh,en),formula,inputs,current));
   row.addEventListener("keydown",e=>{if(e.key==="Enter")row.click();});
   return row;
 });
 root.appendChild(table([t("指標","Metric"),t("名稱","Name"),String(Number(year)-1),year,t("查核","Inspect")],rows));
 const score=rec[model]?.[isM?"M_score":"F_score"];
 const alert=rec[model]?.flag;
 const banner=el("div",null,"ft-sheet-result");
 const main=el("strong",(isM?"M-score":"F-score")+"　"+fmt(score,6));banner.appendChild(main);
 banner.appendChild(quality(score==null?t("資料不足","Unavailable"):alert?t("超過篩檢門檻","Above threshold"):t("未超過篩檢門檻","Below threshold"),alert));
 banner.appendChild(el("span",t("本次門檻","Threshold")+": "+(isM?"-1.78":"1.0"),"ft-sheet-meta"));root.prepend(banner);
 const formulas=isM?
 "M = -4.84 + 0.920×DSRI + 0.528×GMI + 0.404×AQI + 0.892×SGI + 0.115×DEPI − 0.172×SGAI + 4.679×TATA − 0.327×LVGI":
 "Pred = -7.893 + 0.790×RSST + 2.518×ΔAR + 1.191×ΔINV + 1.979×SOFT + 0.171×ΔCashSales − 0.932×ΔROA + 1.029×ISS; F = logistic(Pred) / 0.0037";
 root.appendChild(el("p",formulas,"ft-sheet-formula"));
 if(!isM&&rec.dechow?.F_score!=null)root.appendChild(el("p",t("模型中間輸出","Model intermediate values")+": Pred "+fmt(rec.dechow.pred,6)+"　 P="+fmt(rec.dechow.prob,6),"ft-sheet-meta"));
 root.appendChild(el("p",t("此為財務異常篩檢指標，不是舞弊認定。","Screening indicator only; not proof of fraud."),"ft-sheet-meta"));
}
function renderSource(rec,p){
 const root=$("#ft-sheet-body");
 root.appendChild(el("div",t("官方財報來源與計算依據","Official financial source & calculations"),"ft-sheet-group"));
 const tb=table([t("項目","Item"),t("來源內容","Source")],[
   tr([t("公司代號","Ticker"),company]),
   tr([t("年度／季別","Fiscal period"),year+" Q4"]),
   tr([t("報表範圍","Filing scope"),rec.report_type==="cr"?t("合併財報","Consolidated"):t("個體財報","Separate")]),
   tr([t("原始檔名","Source filename"),rec.source_file||"—"]),
   tr([t("指標來源","Indicator origin"),t("上傳之 MOPS iXBRL pipeline 輸出","Uploaded MOPS iXBRL pipeline output")]),
   tr([t("資料版本","Version"),t("以檔名記錄；是否首次申報需另行查證","Filename version; first filing not verified")])
 ]);root.appendChild(tb);
 const p1=el("p",t("本資料可追溯至檔名，但並未在此預覽中核實官方檔案的申報時間、版本或檔案雜湊。","The filename is recorded; official filing timestamp, version and hash are not verified by this preview."),"ft-sheet-meta");root.appendChild(p1);
 const link=el("a",t("前往公開資訊觀測站查詢","Search MOPS official site"),"ft-inline-link");link.href="https://mops.twse.com.tw/";link.target="_blank";link.rel="noopener noreferrer";root.appendChild(link);
}
function renderClaim(){
 const root=$("#ft-sheet-body");root.appendChild(el("h3",t("財務資訊查證","Verify a financial claim")));
 const box=el("form",null,"ft-claim-box");
 const label=el("label",t("新聞或言論原文","News or claim text"));const input=el("textarea");input.className="ft-textarea";input.placeholder=t("貼上要核對的財務說法…","Paste a financial claim to verify…");input.required=true;
 const btn=el("button",t("對照官方證據","Check official evidence"),"ft-btn ft-btn-primary");btn.type="submit";
 const msg=el("div");msg.className="ft-status";msg.hidden=true;
 box.append(label,input,btn,msg);
 box.addEventListener("submit",async e=>{
   e.preventDefault();btn.disabled=true;msg.hidden=false;msg.textContent=t("正在核對資料…","Checking evidence…");
   try{
    const res=await fetch("/api/financial/claims/verify",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({company_code:company,claim:input.value.trim()})});
    const data=await res.json();if(!res.ok||data.success===false)throw Error(data.error||res.status);
    const out=el("pre",JSON.stringify(data.data||data,null,2),"ft-code");out.style.whiteSpace="pre-wrap";out.style.overflowWrap="anywhere";msg.replaceChildren(out);
   }catch(err){msg.textContent=t("此獨立預覽未連線至 Cloud Run 查核 API；正式串接後才會返回官方證據。","This standalone preview has no Cloud Run evidence API. Official checking requires the connected app.");}
   btn.disabled=false;
 });
 root.appendChild(box);
 root.appendChild(el("p",t("預覽中 Beneish／Dechow 財務指標使用真實上傳資料；新聞驗證使用原有獨立後端，不會把指標超標直接判定為不實。","Beneish/Dechow use the uploaded dataset. News claims require the existing backend; model flags do not prove false claims."),"ft-sheet-meta"));
}
function render(){
 const root=$("#ft-sheet-report");if(!database||!root)return;
 const data=Object.entries(database.industries).find(([,v])=>v[company]);
 const status=$("#ft-company-data-status");
 if(!data){
   const entry=window.FTCompanies?.get(company);
   root.replaceChildren();
   const heading=el("div",null,"ft-sheet-heading");
   heading.appendChild(el("h2",(entry?entry.name:company)+"（"+company+"）"));
   root.appendChild(heading);
   root.appendChild(el("p",t("此公司尚未收錄於本次 2021–2025 年財務指標快照。","This company is not part of the 2021–2025 financial metrics snapshot."),"ft-snapshot-message"));
   const actions=el("div",null,"ft-snapshot-actions");
   const link=el("a",t("使用原有系統查核公司","Check company in the original workbench"),"ft-btn ft-btn-primary");
   link.href="financial-integrity.html?ticker="+encodeURIComponent(company);
   actions.appendChild(link);
   const official=el("a",t("前往公開資訊觀測站","Open MOPS"),"ft-btn");
   official.href="https://mops.twse.com.tw/";official.target="_blank";official.rel="noopener noreferrer";
   actions.appendChild(official);root.appendChild(actions);
   if(status)status.textContent=t("公司名錄可搜尋；此公司沒有本次的財務計算快照。","Company found in the directory; this snapshot has no computed metrics for it.");
   const ticker=$("#ft-audit-ticker");if(ticker)ticker.value=company;
   return;
 }
 if(status)status.textContent=t("已載入 MOPS 財務指標資料","MOPS financial metrics loaded");
 const [industry,companies]=data,co=companies[company];let rec=co.years[year];if(!rec){year=Object.keys(co.years).sort().at(-1);rec=co.years[year];$("#ft-year").value=year;}
 const prev=co.years[String(Number(year)-1)];
 root.replaceChildren(header({group:industry}));
 const stats=el("div",null,"ft-sheet-summary");
 [[ "M-score",rec.beneish?.M_score,rec.beneish?.flag,-1.78],["F-score",rec.dechow?.F_score,rec.dechow?.flag,1.0]].forEach(([name,value,flag,threshold])=>{
   const box=el("div",null,"ft-sheet-stat");box.appendChild(el("span",name,"ft-sheet-meta"));box.appendChild(el("strong",fmt(value,4)));box.appendChild(quality(value==null?t("無資料","No data"):flag?t("異常訊號","Flagged"):t("未超標","Not flagged"),flag));stats.appendChild(box);
 });root.appendChild(stats);
 const tabs=el("div",null,"ft-sheet-tabs");
 [["financial",t("財務報表","Statements")],["beneish","Beneish"],["dechow","Dechow"],["source",t("官方來源","Sources")],["verify",t("查證","Verify")]].forEach(([id,label])=>{
  const b=el("button",label);b.type="button";b.className=id===tab?"active":"";b.addEventListener("click",()=>{tab=id;render();});tabs.appendChild(b);
 });root.appendChild(tabs);
 const body=el("div",null,"ft-sheet-body");body.id="ft-sheet-body";root.appendChild(body);
 const detail=el("div");detail.id="ft-formula-details";detail.className="ft-formula-details";detail.hidden=true;root.appendChild(detail);
 if(tab==="financial")renderFinancial(rec,prev);
 if(tab==="beneish"||tab==="dechow")renderModel(rec,prev,tab);
 if(tab==="source")renderSource(rec,{group:industry});
 if(tab==="verify")renderClaim();
}
function downloadCSV(){
 const table=$("#ft-sheet-body table");if(!table)return;
 const rows=[...table.querySelectorAll("tr")].map(tr=>[...tr.querySelectorAll("th,td")].map(c=>'"'+c.textContent.replaceAll('"','""')+'"').join(","));
 const blob=new Blob(["\ufeff"+rows.join("\r\n")],{type:"text/csv;charset=utf-8"});
 const a=document.createElement("a");const url=URL.createObjectURL(blob);a.href=url;a.download=company+"_"+year+"_"+tab+".csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),300);
}
function selectedCompany(record){
 company=record.ticker;
 const input=$("#ft-company-search");
 if(input)input.value=record.ticker+" "+record.name;
 try{
   const url=new URL(location.href);
   url.searchParams.set("ticker",company);
   history.replaceState(null,"",url);
 }catch(_){}
 if($("#ft-audit-ticker"))$("#ft-audit-ticker").value=company;
 window.FTCompanies?.addRecent(record);
 fillYears();render();window.FTNarrative?.show(company);
}
function fillCompanies(){
 const industry=$("#ft-industry"),input=$("#ft-company-search"),list=$("#ft-company-suggestions");
 if(!industry||!input||!list)return;
 industry.replaceChildren();
 const all=el("option",t("全部產業","All industries"));all.value="all";industry.appendChild(all);
 for(const category of Object.keys(database.industries)){
  const option=el("option",category);option.value=category;industry.appendChild(option);
 }
 industry.value="all";
 const local=Object.values(database.industries).find(x=>x[company])?.[company];
 const match=window.FTCompanies?.get(company);
 input.value=company+" "+(local?.short||match?.name||"");
 window.FTCompanies?.attachAutocomplete({input,list,industry,choose:selectedCompany});
 industry.addEventListener("change",()=>{input.focus();});
}
function fillYears(){
 const sel=$("#ft-year");if(!sel)return;sel.replaceChildren();
 const co=Object.values(database.industries).find(x=>x[company])?.[company];
 if(!co){const opt=el("option","—");opt.value="";sel.appendChild(opt);sel.disabled=true;return;}
 sel.disabled=false;
 const years=Object.keys(co.years).sort().reverse();
 for(const y of years){const opt=el("option",y);opt.value=y;sel.appendChild(opt);}
 if(!co.years[year])year=years[0];
 sel.value=year;
}
document.addEventListener("DOMContentLoaded",async()=>{
 if(!$("#ft-sheet-report"))return;
 try{
  const res=await fetch("ft-mops-data.json",{cache:"force-cache"});
  if(!res.ok)throw Error("HTTP "+res.status);
  database=await res.json();
  const wanted=new URLSearchParams(location.search).get("ticker");
  if(wanted&&/^\d{4,6}$/.test(wanted)){
   company=wanted;
   const record=Object.values(database.industries).find(ind=>ind[wanted])?.[wanted];
   const existing=window.FTCompanies?.get(wanted);
   if(record||existing){
     window.FTCompanies?.addRecent({ticker:wanted,name:record?.short||existing?.name||wanted});
   }
  }
  window.FTCompanies?.load();
  fillCompanies();fillYears();
  $("#ft-year").addEventListener("change",e=>{year=e.target.value;render();});
  render();window.FTNarrative?.show(company);
 }catch(e){$("#ft-sheet-report").textContent=t("財報快照載入失敗，請重新整理頁面。","Unable to load financial snapshot.");}
});
})();