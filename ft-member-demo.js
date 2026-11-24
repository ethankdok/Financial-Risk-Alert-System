/* Opt-in member UI demo. It never claims the visitor is authenticated.
 * Only non-sensitive demo profile name, followed tickers, prefs are stored on device.
 */
(function(){
"use strict";
const KEY="ft-member-demo-v1";
const $=s=>document.querySelector(s);
const t=(zh,en)=>window.FTLocale?.language?.()==="en"?en:zh;
const el=(tag,text,cls)=>{const x=document.createElement(tag);if(text!=null)x.textContent=String(text);if(cls)x.className=cls;return x;};
const init={displayName:"",watchlist:[],prefs:{email_enabled:false,important_alerts:true,material_event_alerts:true,narrative_shift_alerts:false,digest_frequency:"weekly"}};
function load(){
 try{const d=JSON.parse(localStorage.getItem(KEY)||"null");
 if(d&&typeof d==="object"&&Array.isArray(d.watchlist)){
  return {displayName:String(d.displayName||"").slice(0,60),watchlist:d.watchlist.filter(s=>/^\d{4,6}$/.test(String(s))).slice(0,30),prefs:{...init.prefs,...(d.prefs||{})}};
 }}catch(e){}
 return JSON.parse(JSON.stringify(init));
}
let data=load(),tab="profile";
function save(){try{localStorage.setItem(KEY,JSON.stringify(data));}catch(e){}}
function button(text,click,css){const b=el("button",text,css||"ft-btn");b.type="button";b.addEventListener("click",click);return b;}
function inputField(label,element){const d=el("label",null,"ft-member-demo-field");d.append(el("span",label),element);return d;}
function profile(panel){
 panel.appendChild(el("h2",t("個人資料","Profile")));
 const name=el("input");name.className="ft-input";name.value=data.displayName;name.maxLength=60;
 panel.appendChild(inputField(t("展示名稱","Display name"),name));
 const feedback=el("span",null,"ft-home-muted");
 panel.appendChild(button(t("儲存展示資料","Save demo profile"),()=>{data.displayName=name.value.trim();save();feedback.textContent=t("已儲存在這台裝置","Saved on this device");},"ft-btn ft-btn-primary"));
 panel.appendChild(feedback);
}
function watchlist(panel){
 panel.appendChild(el("h2",t("追蹤公司","Followed companies")));
 const row=el("div",null,"ft-member-demo-search");
 const field=el("div",null,"ft-company-input-wrap");
 const query=el("input");query.className="ft-input";query.type="search";query.placeholder=t("輸入股票代碼或公司名稱","Search ticker or company name");
 const list=el("div");list.id="ft-member-demo-options";list.className="ft-search-list";list.hidden=true;
 field.append(query,list);row.appendChild(field);panel.appendChild(row);
 const chosen=el("div",null,"ft-member-demo-list");
 function refresh(){
  chosen.replaceChildren();
  if(!data.watchlist.length){chosen.appendChild(el("p",t("尚未追蹤公司","No companies followed yet"),"ft-home-muted"));return;}
  data.watchlist.forEach(code=>{
    const found=window.FTCompanies?.get(code),item=el("div",null,"ft-member-demo-item");
    item.appendChild(el("strong",code+"　"+(found?.name||"")));
    item.appendChild(button(t("取消追蹤","Remove"),()=>{data.watchlist=data.watchlist.filter(c=>c!==code);save();refresh();},"ft-btn"));
    chosen.appendChild(item);
  });
 }
 window.FTCompanies?.attachAutocomplete({input:query,list,choose:item=>{
  if(!data.watchlist.includes(item.ticker))data.watchlist.push(item.ticker);
  save();refresh();query.value="";
 }});
 panel.appendChild(chosen);refresh();
}
function preferences(panel){
 panel.appendChild(el("h2",t("提醒偏好","Notification preferences")));
 const opts=[
 ["email_enabled",t("電子郵件通知","Email notification")],
 ["important_alerts",t("重要／高風險提醒","Important alerts")],
 ["material_event_alerts",t("重大訊息更新","Material disclosures")],
 ["narrative_shift_alerts",t("敘事變化提醒","Narrative shift alerts")]
 ];
 opts.forEach(([key,label])=>{
  const line=el("label",null,"ft-member-demo-check");const check=el("input");check.type="checkbox";check.checked=!!data.prefs[key];
  check.addEventListener("change",()=>{data.prefs[key]=check.checked;save();});
  line.append(check,el("span",label));panel.appendChild(line);
 });
 const freq=el("select");freq.className="ft-select";
 [["daily",t("每日","Daily")],["weekly",t("每週","Weekly")],["off",t("關閉","Off")]].forEach(([value,label])=>{
 const o=el("option",label);o.value=value;freq.appendChild(o);
 });freq.value=data.prefs.digest_frequency;freq.addEventListener("change",()=>{data.prefs.digest_frequency=freq.value;save();});
 panel.appendChild(inputField(t("摘要頻率","Digest frequency"),freq));
 panel.appendChild(el("p",t("示範設定僅儲存在這台裝置，不會發送任何通知。","Demo preferences stay on this device; no notifications are sent."),"ft-home-muted"));
}
function history(panel){
 panel.appendChild(el("h2",t("近期查詢","Recent searches")));
 const records=window.FTCompanies?.readRecent?.()||[];
 if(!records.length)panel.appendChild(el("p",t("尚無近期查詢","No recent searches"),"ft-home-muted"));
 records.forEach(record=>{
  const link=el("a",record.ticker+"　"+record.name,"ft-member-demo-history");
  link.href="financial-audit.html?ticker="+encodeURIComponent(record.ticker);panel.appendChild(link);
 });
 panel.appendChild(el("p",t("這裡是本機近期查詢；正式會員的跨裝置查核報告尚未啟用。","These are on-device recent searches, not account-synced reports."),"ft-home-muted"));
}
function render(){
 const panel=$("#ft-member-panel");if(!panel)return;
 panel.replaceChildren();
 document.querySelectorAll("[data-member-tab]").forEach(b=>b.classList.toggle("active",b.dataset.memberTab===tab));
 if(tab==="profile")profile(panel);
 if(tab==="watchlist")watchlist(panel);
 if(tab==="prefs")preferences(panel);
 if(tab==="history")history(panel);
}
document.addEventListener("DOMContentLoaded",()=>{
 if(!$("#ft-member-panel"))return;
 document.querySelectorAll("[data-member-tab]").forEach(button=>button.addEventListener("click",()=>{tab=button.dataset.memberTab;render();}));
 render();
});
})();