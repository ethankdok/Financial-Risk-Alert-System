/* Company directory/autocomplete across all industries, no industry selection required.
   Sources: uploaded MOPS snapshot, canonical FinTrust APIs, a small verified UI fallback. */
(function(){
"use strict";
const RECENT_KEY="ft-recent-companies-v2";
const fallback=[
 ["2330","台積電","Taiwan Semiconductor Manufacturing Company","半導體業"],
 ["2454","聯發科","MediaTek","半導體業"],
 ["2317","鴻海","Hon Hai Precision Industry","其他電子業"],
 ["2382","廣達","Quanta Computer","電腦及週邊設備業"],
 ["2303","聯電","United Microelectronics","半導體業"],
 ["2308","台達電","Delta Electronics","電子零組件業"],
 ["1785","光洋科","Solar Applied Materials Technology","其他電子業"],
 ["2603","長榮","Evergreen Marine","航運業"],
 ["2881","富邦金","Fubon Financial","金融保險業"]
];
const records=new Map(),sourceReady={snapshot:false,backend:false};
let loadPromise=null;
const lang=()=>window.FTLocale?.language?.()||"zh";
const t=(key)=>window.FTLocale?.t?.(key)||key;
function normalize(value){return String(value||"").normalize("NFKC").toLowerCase().replace(/[\s　\-]/g,"");}
function safeCompany(raw){
 const ticker=String(raw.ticker??raw.code??raw.company_code??"").trim();
 const name=String(raw.short??raw.name??raw.company_name??"").trim();
 if(!/^\d{4,6}$/.test(ticker)||!name||name.length>120)return null;
 return {
  ticker,name,
  fullName:String(raw.fullName||raw.company_name||raw.name||name).trim(),
  english:String(raw.english||raw.english_name||raw.enName||"").trim(),
  industry:String(raw.industry||raw.subindustry||"").trim(),
  market:String(raw.market||"").trim(),
  hasSnapshot:!!raw.hasSnapshot,
  origin:raw.origin||"directory"
 };
}
function upsert(raw){
 const entry=safeCompany(raw);if(!entry)return;
 const old=records.get(entry.ticker);
 if(old){
  entry.hasSnapshot=old.hasSnapshot||entry.hasSnapshot;
  if(old.hasSnapshot&&!entry.hasSnapshot){entry.name=old.name;entry.fullName=old.fullName;}
  entry.english=entry.english||old.english;
  entry.industry=entry.industry||old.industry;
  entry.market=entry.market||old.market;
  entry.origin=entry.hasSnapshot?"snapshot":entry.origin;
 }
 records.set(entry.ticker,entry);
}
fallback.forEach(([ticker,name,english,industry])=>upsert({ticker,name,english,industry,origin:"fallback"}));
async function fetchJson(url){
 const abort=new AbortController();
 const timeout=setTimeout(()=>abort.abort(),4200);
 try{
  const response=await fetch(url,{credentials:"same-origin",headers:{Accept:"application/json"},signal:abort.signal});
  if(!response.ok||!(response.headers.get("content-type")||"").includes("json"))return null;
  return await response.json();
 }catch{return null;}finally{clearTimeout(timeout);}
}
async function load(){
 if(loadPromise)return loadPromise;
 loadPromise=(async()=>{
  const snapshot=await fetchJson("ft-mops-data.json");
  if(snapshot?.industries){
   for(const [industry,companies] of Object.entries(snapshot.industries)){
    for(const [ticker,entry] of Object.entries(companies))upsert({ticker,name:entry.short,fullName:entry.name,market:entry.market,industry,hasSnapshot:true,origin:"snapshot"});
   }
   sourceReady.snapshot=true;
  }
  const endpoints=["/api/financial/companies","/api/integrity/companies"];
  const results=await Promise.all(endpoints.map(fetchJson));
  results.forEach((payload)=>{
   const response=payload?.data??payload??{};
   const arr=Array.isArray(response)?response:response.companies||response.items||[];
   if(!Array.isArray(arr))return;
   for(const entry of arr)upsert({...entry,origin:"backend"});
   if(arr.length)sourceReady.backend=true;
  });
  return all();
 })();
 return loadPromise;
}
function all(){return Array.from(records.values()).sort((a,b)=>a.ticker.localeCompare(b.ticker));}
function matches(q,filter){
 const parts=normalize(q).split(/[,，]/).filter(Boolean);if(!parts.length)return false;
 if(filter&&filter!=="all"&&!parts.some(p=>p.includes(filter))&&!filter.includes(q)){
  // filtered by industry, but never require industry to be set
 }
 return true;
}
function search(query,industry="all",limit=9){
 const raw=String(query||"").trim();
 if(raw.length<1)return[];
 const q=normalize(raw);const tokens=raw.trim().split(/\s+/).map(normalize).filter(Boolean);
 let candidates=all().filter(item=>{
  if(industry&&industry!=="all"&&item.industry!==industry)return false;
  const full=normalize(item.ticker+" "+item.name+" "+item.fullName+" "+item.english);
  return tokens.every(token=>full.includes(token))||(tokens.length===1&&full.includes(q));
 });
 candidates.sort((a,b)=>{
  function score(v){let score=0;if(v.ticker===q)score+=110;
   if(v.ticker.startsWith(q))score+=70;if(normalize(v.name).startsWith(q))score+=55;
   if(normalize(v.fullName).startsWith(q))score+=30;
   if(v.hasSnapshot)score+=4;return score;}
  return score(b)-score(a)||a.ticker.localeCompare(b.ticker);
 });
 return candidates.slice(0,limit);
}
function get(ticker){return records.get(String(ticker))||null;}
function findInText(input){
 const raw=String(input||"").trim();
 const code=(raw.match(/(?:^|\D)(\d{4,6})(?!\d)/)||[])[1];
 if(code)return get(code);
 const norm=normalize(raw);
 if(!norm)return null;
 const found=all().filter(v=>v.name.length>=2&&norm.includes(normalize(v.name)));
 return found.length===1?found[0]:null;
}
function readRecent(){
 try{
 const value=JSON.parse(localStorage.getItem(RECENT_KEY)||"[]");
 return Array.isArray(value)?value.filter(v=>v&&/^\d{4,6}$/.test(String(v.ticker))).slice(0,7):[];
 }catch{return[];}
}
function addRecent(item){
 if(!item||!/^\d{4,6}$/.test(String(item.ticker)))return;
 const list=[{ticker:String(item.ticker),name:String(item.name||item.ticker).slice(0,60),at:Date.now()},...readRecent().filter(x=>x.ticker!==String(item.ticker))].slice(0,7);
 try{localStorage.setItem(RECENT_KEY,JSON.stringify(list));}catch{}
 window.dispatchEvent(new CustomEvent("ft:recent-changed"));
}
function clearRecent(){
 try{localStorage.removeItem(RECENT_KEY);}catch{}
 window.dispatchEvent(new CustomEvent("ft:recent-changed"));
}
function attachAutocomplete({input,list,industry,choose,limit=9}){
 if(!input||!list)return()=>{};
 const root=list;root.hidden=true;root.role="listbox";
 root.setAttribute("aria-label",t("audit.listRole"));
 input.setAttribute("role","combobox");input.setAttribute("aria-autocomplete","list");
 input.setAttribute("aria-controls",root.id);input.setAttribute("aria-expanded","false");
 let options=[],focused=-1,composing=false;
 const close=()=>{root.hidden=true;input.setAttribute("aria-expanded","false");focused=-1;};
 const show=()=>{
  if(composing)return;
  options=search(input.value,industry?.value||"all",limit);
  root.replaceChildren();focused=-1;
  if(!input.value.trim()){close();return;}
  if(!options.length){const hint=document.createElement("div");hint.className="ft-search-empty";hint.textContent=t("audit.noMatch");root.appendChild(hint);}
  else options.forEach((entry,i)=>{
   const button=document.createElement("button");button.type="button";button.role="option";
   button.className="ft-search-option";button.id=root.id+"-"+i;
   const name=document.createElement("span");name.className="ft-search-name";name.textContent=entry.ticker+"　"+entry.name;
   const subtitle=document.createElement("small");subtitle.textContent=entry.hasSnapshot?t("audit.available"):entry.industry||t("audit.directoryOnly");
   button.append(name,subtitle);
   button.addEventListener("mousedown",e=>e.preventDefault());
   button.addEventListener("click",()=>pick(i));root.appendChild(button);
  });
  root.hidden=false;input.setAttribute("aria-expanded","true");
 };
 const highlight=()=>{[...root.querySelectorAll('[role="option"]')].forEach((n,i)=>{n.classList.toggle("active",i===focused);n.setAttribute("aria-selected",String(i===focused));});
  if(focused>=0)input.setAttribute("aria-activedescendant",root.id+"-"+focused);else input.removeAttribute("aria-activedescendant");};
 const pick=i=>{const value=options[i];if(!value)return;
   input.value=value.ticker+" "+value.name;close();input.dispatchEvent(new Event("ft:company-selected"));choose?.(value);
 };
 input.addEventListener("compositionstart",()=>{composing=true;});
 input.addEventListener("compositionend",()=>{composing=false;show();});
 input.addEventListener("input",()=>{if(!composing)show();});
 input.addEventListener("focus",()=>{if(input.value.trim())show();});
 input.addEventListener("keydown",e=>{
  if(root.hidden||composing)return;
  if(e.key==="ArrowDown"){e.preventDefault();focused=Math.min(options.length-1,focused+1);highlight();}
  if(e.key==="ArrowUp"){e.preventDefault();focused=Math.max(0,focused-1);highlight();}
  if(e.key==="Enter"&&options.length&&(focused>=0||options.length===1)){e.preventDefault();pick(focused>=0?focused:0);}
  if(e.key==="Escape")close();
 });
 root.addEventListener("keydown",e=>{if(e.key==="Escape"){close();input.focus();}});
 document.addEventListener("click",e=>{if(e.target!==input&&!root.contains(e.target))close();});
 industry?.addEventListener("change",()=>{if(!root.hidden)show();});
 load().then(()=>{if(document.activeElement===input&&input.value.trim())show();});
 return close;
}
window.FTCompanies={all,load,get,search,findInText,addRecent,readRecent,clearRecent,attachAutocomplete,sources:sourceReady};
})();