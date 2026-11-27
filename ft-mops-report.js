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

let healthRequest=0;
async function renderLiveHealth(ticker){
 const container=$("#ft-live-dashboard");if(!container)return;
 const seq=++healthRequest;
 const narrative=$("#ft-narrative-health");
 if(narrative) narrative.replaceChildren(el("h2",t("文字漂移與敘事差異","Text drift & narrative changes")),el("p",t("正在讀取此公司的文字資料…","Loading text evidence for this company…"),"ft-home-muted"));
 container.replaceChildren(el("p",t("正在讀取企業營運指標…","Retrieving company financial indicators…"),"ft-sheet-meta"));
 if(!window.FTLiveFinancial){container.textContent=t("營運指標介面尚未載入","Financial API module unavailable");return;}
 try{
  const result=await window.FTLiveFinancial.load(ticker);
  if(seq!==healthRequest)return;
  window.FTLiveFinancial.render(container,result);
  if(narrative&&window.FTNarrative?.renderFromCard)window.FTNarrative.renderFromCard(narrative,result.card,ticker);
 }catch(e){
  if(seq!==healthRequest)return;
  container.replaceChildren(el("p",t("目前沒有這家公司的既有後端財務分析結果；可使用上方已收錄的財報指標，或進入介面示範。","No connected financial analysis was found for this company. Use the uploaded financial snapshot or UI demo."),"ft-home-muted"));
  if(narrative){narrative.replaceChildren(el("h2",t("文字漂移與敘事差異","Text drift & narrative changes")),el("p",t("目前無法取得這家公司的文字比較結果。","Text comparison is currently unavailable for this company."),"ft-home-muted"));window.FTNarrative?.officialCompare?.(narrative,ticker);}
 }
}

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
 const endpoint="/api/research/annual-model-results/"+encodeURIComponent(company)+"/"+encodeURIComponent(year);
 const a=el("a",t("查看後端已封存模型輸出（JSON）","View archived backend model output (JSON)"),"ft-inline-link");a.href=endpoint;a.target="_blank";a.rel="noopener";root.appendChild(a);
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
/* Explain the published linear score, not a new trained model or a fraud probability. */
const riskModels=[
 {id:"beneish",name:"Beneish M-Score",key:"M_score",cut:-1.78,base:-4.84,weights:{DSRI:.920,GMI:.528,AQI:.404,SGI:.892,DEPI:.115,SGAI:-.172,LVGI:-.327,TATA:4.679}},
 {id:"dechow",name:"Dechow F-Score",key:"F_score",cut:1,base:-7.893,weights:{RSST:.790,dAR:2.518,dInventory:1.191,soft_assets:1.979,dCash_sales:.171,dROA:-.932,actual_issuance:1.029}}
];
const numeric=v=>typeof v==="number"&&Number.isFinite(v);
function riskValue(rec,m){const v=rec?.[m.id]?.[m.key];return numeric(v)?v:null;}
function signed(v,d=4){return numeric(v)?(v>0?"+":"")+fmt(v,d):"—";}
function explainScore(rec,m){
 const v=rec?.[m.id]||{};
 if(riskValue(rec,m)==null||!Object.keys(m.weights).every(k=>numeric(v[k])))return null;
 const terms=Object.entries(m.weights).map(([key,weight])=>({key,weight,value:v[key],contribution:weight*v[key]}));
 const linear=terms.reduce((s,x)=>s+x.contribution,m.base);
 const score=m.id==="beneish"?linear:1/(1+Math.exp(-linear))/.0037;
 return {terms,linear,score};
}
function jumpModel(rec,m,key){
 tab=m.id;render();
 if(key){const def=(m.id==="beneish"?beneish:dechow).find(d=>d[0]===key);if(def){showInputs(rec,key+" · "+t(def[1],def[2]),def[3],def[4],rec[m.id][key]);return;}}
 $("#ft-sheet-body")?.scrollIntoView({behavior:"smooth",block:"start"});
}
function riskGauge(co,rec,m){
 const box=el("div",null,"ft-fin-risk-gauge"),v=riskValue(rec,m);
 if(v==null){box.appendChild(el("p",t("必要科目不足，無法計算","Required inputs missing"),"ft-sheet-meta"));return box;}
 const values=Object.values(co.years).map(r=>riskValue(r,m)).filter(numeric);
 let lo=Math.min(m.cut,v,...values),hi=Math.max(m.cut,v,...values);
 const pad=Math.max((hi-lo)*.16,m.id==="beneish"?.2:.12);lo-=pad;hi+=pad;if(m.id==="dechow")lo=Math.max(0,lo);
 const pos=x=>Math.max(0,Math.min(100,100*(x-lo)/(hi-lo)));
 const scale=el("div",null,"ft-fin-risk-scale");
 scale.style.setProperty("--cut",pos(m.cut)+"%");
 const marker=el("span",null,"ft-fin-risk-marker");marker.style.left=pos(v)+"%";
 const threshold=el("span",null,"ft-fin-risk-cut");threshold.style.left=pos(m.cut)+"%";
 scale.append(marker,threshold);
 const bounds=el("div",null,"ft-fin-risk-bounds");bounds.append(el("span",fmt(lo,2)),el("span",t("門檻 ","Cutoff ")+m.cut),el("span",fmt(hi,2)));
 box.append(scale,bounds,el("p",t("與門檻差距：","Distance from cutoff: ")+signed(v-m.cut), "ft-sheet-meta"));
 return box;
}
function trendChart(co,m){
 const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg");
 svg.setAttribute("viewBox","0 0 520 170");svg.setAttribute("role","img");svg.setAttribute("aria-label",m.name+" "+t("歷年趨勢","annual trend"));
 svg.classList.add("ft-fin-risk-trend");const years=Object.keys(co.years).sort();
 const values=years.map(y=>riskValue(co.years[y],m)).filter(numeric);
 let lo=Math.min(m.cut,...values),hi=Math.max(m.cut,...values);
 const pad=Math.max((hi-lo)*.2,.1);lo-=pad;hi+=pad;
 const x=i=>48+i*424/Math.max(1,years.length-1),y=v=>120-(v-lo)*83/(hi-lo);
 function add(tag,attrs,txt){const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));if(txt!=null)n.textContent=txt;svg.append(n);return n;}
 add("text",{x:12,y:15,fill:"#304c5f","font-size":12},m.name);
 add("line",{x1:32,x2:488,y1:y(m.cut),y2:y(m.cut),stroke:"#a07935","stroke-dasharray":"5 4"});
 add("text",{x:12,y:y(m.cut)-5,fill:"#886426","font-size":10},t("門檻 ","Cutoff ")+m.cut);
 let last=null;
 years.forEach((yr,i)=>{
  const v=riskValue(co.years[yr],m),px=x(i);
  add("text",{x:px,y:154,"text-anchor":"middle",fill:"#536b7b","font-size":11,"font-weight":yr===year?700:400},yr);
  if(v==null){add("text",{x:px,y:137,"text-anchor":"middle",fill:"#77848c","font-size":10},"—");last=null;return;}
  const py=y(v);if(last)add("line",{x1:last[0],y1:last[1],x2:px,y2:py,stroke:"#477b87","stroke-width":2.3});
  add("circle",{cx:px,cy:py,r:yr===year?6:4,fill:v>m.cut?"#a7563c":"#477b87",stroke:"#fff","stroke-width":1.5});
  add("text",{x:px,y:py-10,"text-anchor":"middle",fill:"#263d4d","font-size":11},fmt(v,3));last=[px,py];
 });
 return svg;
}
function contributionPanel(rec,prev,m){
 const box=el("section",null,"ft-fin-explain-card");
 box.appendChild(el("h3",m.name+" · "+t("分數形成原因","Score decomposition")));
 const result=explainScore(rec,m),previous=explainScore(prev,m);
 if(!result){box.appendChild(el("p",t("此年度無完整模型特徵，無法分解。","Incomplete features; decomposition unavailable."),"ft-sheet-meta"));return box;}
 const hasPrev=!!previous;
 const rows=result.terms.map(x=>({...x,delta:hasPrev?x.contribution-previous.terms.find(z=>z.key===x.key).contribution:null}));
 const defs=m.id==="beneish"?beneish:dechow;
 const scale=Math.max(.000001,...rows.map(x=>Math.abs(hasPrev?x.delta:x.contribution)));
 box.appendChild(el("p",hasPrev?t("各項指標對線性模型分數的年度變動貢獻（係數 × 指標變動）。","Year-over-year contribution to the linear score (coefficient × feature change)."):t("各項指標的加權項（係數 × 指標值）。","Weighted model terms (coefficient × feature value)."),"ft-sheet-meta"));
 if(m.id==="dechow")box.appendChild(el("p",t("F-Score 的貢獻以轉換前的 logit（Pred）表示。","F-Score contributions are on the pre-transformation logit scale."),"ft-sheet-meta"));
 const ordered=rows.slice().sort((a,b)=>Math.abs(hasPrev?b.delta:b.contribution)-Math.abs(hasPrev?a.delta:a.contribution));
 const bars=el("div",null,"ft-fin-contributions");
 ordered.forEach(x=>{
  const def=defs.find(d=>d[0]===x.key),v=hasPrev?x.delta:x.contribution;
  const b=el("button",null,"ft-fin-contribution");b.type="button";b.title=t("查看計算公式與原始財報科目","Inspect formula and source accounts");
  b.addEventListener("click",()=>jumpModel(rec,m,x.key));
  const label=el("span",null,"ft-fin-term");label.append(el("strong",x.key),el("small",t(def[1],def[2])));
  const track=el("span",null,"ft-fin-contribution-track"),fill=el("span",null,"ft-fin-contribution-fill "+(v>=0?"up":"down"));
  fill.style.width=(Math.abs(v)/scale*50)+"%";track.appendChild(fill);
  b.append(label,track,el("span",signed(v),"ft-fin-contribution-value"));bars.appendChild(b);
 });box.appendChild(bars);
 const drivers=ordered.filter(x=>(hasPrev?x.delta:x.contribution)>0).slice(0,3);
 if(drivers.length){box.appendChild(el("p",t(hasPrev?"主要推升線性分數的年度變動：":"主要正向加權項：",hasPrev?"Largest positive annual contributions: ":"Largest positive weighted terms: ")+drivers.map(x=>x.key+" "+signed(hasPrev?x.delta:x.contribution)).join("、"),"ft-fin-driver"));}
 const det=el("details",null,"ft-fin-decomposition");det.appendChild(el("summary",t("展開模型係數、數值與完整分數計算","Expand coefficients, inputs and score calculation")));
 det.appendChild(table([t("指標","Feature"),t("指標值","Value"),t("係數","Weight"),t("加權項","Weighted term"),t("較前年度貢獻","YoY contribution")],rows.map(x=>tr([x.key,fmt(x.value,6),fmt(x.weight,3),signed(x.contribution,6),signed(x.delta,6)]))));
 det.appendChild(el("p",t("截距 ","Intercept ")+m.base+" + "+t("加權項合計 ","sum of weighted terms ")+fmt(result.linear-m.base,6)+" = "+fmt(result.linear,6),"ft-sheet-meta"));
 if(m.id==="dechow")det.appendChild(el("p","F = logistic("+fmt(result.linear,6)+") / 0.0037 = "+fmt(result.score,6),"ft-sheet-meta"));
 det.appendChild(el("p",t("以已保存的六位小數特徵重算：","Recomputed from stored rounded features: ")+fmt(result.score,6)+" · "+t("原始模型輸出：","Archived output: ")+fmt(riskValue(rec,m),6),"ft-sheet-meta"));
 box.appendChild(det);return box;
}
// Relative screening index: equal-weight midrank percentile within the same industry/year.
function relativeRisk(rec,industry,yr){
 if(!riskModels.every(m=>riskValue(rec,m)!=null))return null;
 const peers=Object.values(database.industries[industry]||{}).map(c=>c.years[yr]).filter(r=>r&&riskModels.every(m=>riskValue(r,m)!=null));
 if(peers.length<5)return null;
 const ranks=riskModels.map(m=>{const v=riskValue(rec,m);const less=peers.filter(r=>riskValue(r,m)<v).length,equal=peers.filter(r=>riskValue(r,m)===v).length;return 100*(less+.5*equal)/peers.length;});
 return {value:(ranks[0]+ranks[1])/2,ranks,count:peers.length};
}
function riskDial(rec,industry){
 const index=relativeRisk(rec,industry,year),box=el("div",null,"ft-fin-dial");
 const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox","0 0 300 178");svg.setAttribute("role","img");svg.setAttribute("aria-label",index?t("同業相對風險指數 ","Relative risk index ")+fmt(index.value,1):t("資料不足","Insufficient data"));
 const pt=v=>[150-112*Math.cos(Math.PI*v/100),138-112*Math.sin(Math.PI*v/100)];
 function add(tag,attrs,txt){const e=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));if(txt!=null)e.textContent=txt;svg.append(e);return e;}
 [[0,33.333,"#78a99f"],[33.333,66.667,"#d4b06b"],[66.667,100,"#b96c59"]].forEach(([a,b,c])=>{const p=pt(a),q=pt(b);add("path",{d:"M "+p.join(" ")+" A 112 112 0 0 1 "+q.join(" "),fill:"none",stroke:index?c:"#d9e1e5","stroke-width":18});});
 if(index){const p=pt(index.value);add("line",{x1:150,y1:138,x2:150+(p[0]-150)*.82,y2:138+(p[1]-138)*.82,stroke:"#233f50","stroke-width":4,"stroke-linecap":"round"});add("circle",{cx:150,cy:138,r:6,fill:"#233f50"});}
 add("text",{x:22,y:160,"font-size":11,fill:"#536b7b"},0);add("text",{x:278,y:160,"font-size":11,"text-anchor":"end",fill:"#536b7b"},100);
 box.append(el("h3",t("同業相對財報風險指數","Industry-relative financial risk index")),svg,el("strong",index?fmt(index.value,1)+" / 100":"—","ft-fin-dial-value"));
 if(index){const level=index.value>=66.667?t("相對偏高","Relatively high"):index.value>=33.333?t("相對居中","Mid-range"):t("相對偏低","Relatively low");box.append(el("p",level+" · "+index.count+" "+t("家同業完整樣本","complete industry peers"),"ft-fin-driver"));box.append(el("p","M "+fmt(index.ranks[0],1)+" / F "+fmt(index.ranks[1],1)+" "+t("百分位，等權平均","percentiles, equal-weight mean"),"ft-sheet-meta"));}
 else box.append(el("p",t("雙模型完整且同業至少五家才計算。","Requires both scores and at least five complete peers."),"ft-sheet-meta"));
 box.append(el("p",t("0–100 為同產業同年度的相對篩檢排序，不是舞弊機率。是否超標另依下方文獻門檻。","Relative screening rank within industry and year, not fraud probability. Original model cutoffs are shown separately."),"ft-sheet-meta"));return box;
}

function renderRiskDashboard(co,rec,prev,industry){
 const root=el("section",null,"ft-fin-risk-dashboard");root.id="ft-fin-risk-dashboard";
 root.appendChild(el("h2",t("財報舞弊風險篩檢儀表板","Financial misstatement risk dashboard")));
 const available=riskModels.filter(m=>riskValue(rec,m)!=null);
 const flagged=available.filter(m=>riskValue(rec,m)>m.cut).length;
 const overall=el("div",null,"ft-fin-risk-overall");
 const label=available.length<2?t("資料不足｜無法完成雙模型判斷","Incomplete dual-model assessment"):flagged===2?t("雙模型警示｜優先查核","Dual-model alert | Priority review"):flagged===1?t("單模型警示｜加強查核","Single-model alert | Further review"):t("雙模型未超標","Neither model exceeds cutoff");
 overall.classList.add(flagged?"alert":"neutral");overall.append(el("div",label,"ft-fin-risk-level"),el("strong",flagged+" / "+available.length),el("span",t("已超標模型／可計算模型（共 2 組）","Flagged / computable models (2 total)"),"ft-sheet-meta"));
 const overview=el("div",null,"ft-fin-risk-overview");overview.append(riskDial(rec,industry),overall);root.appendChild(overview);
 const stats=el("div",null,"ft-sheet-summary");
 riskModels.forEach(m=>{
  const value=riskValue(rec,m),flag=value!=null&&value>m.cut,box=el("div",null,"ft-sheet-stat ft-fin-risk-card");
  box.append(el("span",m.name,"ft-sheet-meta"),el("strong",fmt(value,4)),quality(value==null?t("無資料","No data"):flag?t("超過篩檢門檻","Above cutoff"):t("未超過篩檢門檻","Below cutoff"),flag));
  box.appendChild(riskGauge(co,rec,m));
  if(m.id==="dechow"&&value!=null)box.appendChild(el("p",t("相對基準發生率的倍數：","Multiple of baseline incidence: ")+fmt(value,4)+"×","ft-sheet-meta"));
  const btn=el("button",t("查看模型指標與公式","Inspect model indicators"),"ft-btn");btn.type="button";btn.addEventListener("click",()=>jumpModel(rec,m));box.appendChild(btn);stats.appendChild(box);
 });root.appendChild(stats);
 const trends=el("div",null,"ft-fin-risk-grid");riskModels.forEach(m=>trends.appendChild(trendChart(co,m)));root.appendChild(trends);
 const exp=el("div",null,"ft-fin-risk-grid");riskModels.forEach(m=>exp.appendChild(contributionPanel(rec,prev,m)));root.appendChild(exp);
 root.appendChild(el("p",t("整體判斷依兩組模型原始門檻，不另行估計舞弊機率。","Overall assessment uses the original model cutoffs, not an estimated fraud probability."),"ft-sheet-meta"));
 return root;
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
   root.appendChild(el("p",t("此公司尚無本次 2021–2025 年 Beneish／Dechow 指標快照；下方可查看已串接的營運健檢資料。","No Beneish/Dechow snapshot for this company in 2021–2025. Connected operational health evidence may be available below."),"ft-snapshot-message"));
   const actions=el("div",null,"ft-snapshot-actions");
   const link=el("a",t("使用原有系統查核公司","Check company in the original workbench"),"ft-btn ft-btn-primary");
   link.href="financial-integrity.html?ticker="+encodeURIComponent(company);
   actions.appendChild(link);
   const demo=el("button",t("查看功能示範","View UI demo"),"ft-btn");
   demo.type="button";
   demo.addEventListener("click",async()=>{
     const result=$("#ft-result");
     if(!result||!window.FTDemo)return;
     await window.FTDemo.render(result,{ticker:company,mode:"integrated"});
     result.scrollIntoView({behavior:"smooth",block:"start"});
   });
   actions.appendChild(demo);
   const official=el("a",t("前往公開資訊觀測站","Open MOPS"),"ft-btn");
   official.href="https://mops.twse.com.tw/";official.target="_blank";official.rel="noopener noreferrer";
   actions.appendChild(official);root.appendChild(actions);
   if(status)status.textContent=t("已找到公司；本次 Beneish／Dechow 未收錄，下方載入既有營運指標。","Company found. This snapshot has no Beneish/Dechow metrics; see live financial indicators below.");
   const ticker=$("#ft-audit-ticker");if(ticker)ticker.value=company;
   return;
 }
 if(status)status.textContent=t("已載入 MOPS 財務指標資料","MOPS financial metrics loaded");
 const [industry,companies]=data,co=companies[company];let rec=co.years[year];if(!rec){year=Object.keys(co.years).sort().at(-1);rec=co.years[year];$("#ft-year").value=year;}
 const prev=co.years[String(Number(year)-1)];
 root.replaceChildren(header({group:industry}));
 root.appendChild(renderRiskDashboard(co,rec,prev,industry));
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
 fillYears();render();renderLiveHealth(company);
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
  const params=new URLSearchParams(location.search),wanted=params.get("ticker"),requestedYear=params.get("year"),requestedModel=params.get("model");
  if(/^20[0-9]{2}$/.test(requestedYear||""))year=requestedYear;
  if(["beneish","dechow","source","financial"].includes(requestedModel))tab=requestedModel;
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
  render();renderLiveHealth(company);
 }catch(e){$("#ft-sheet-report").textContent=t("財報快照載入失敗，請重新整理頁面。","Unable to load financial snapshot.");}
});
})();