/* UI language switch: Chinese by default, English on demand. No extra slogans. */
(function(){
"use strict";
const d={
"首頁":"Home","查核分析":"Verification","整合查核":"Integrated verification",
"財務異常稽核":"Financial audit","會員中心":"Account",
"你想查核什麼？":"What would you like to verify?",
"開始查核":"Start verification","上傳檔案":"Upload file",
"產業":"Industry","公司":"Company","財報年度":"Fiscal year",
"查核其他公司":"Check another company","完整分析工作台":"Advanced workbench",
"公司代號":"Ticker","執行查核":"Run audit","分析方式":"Analysis method","查核內容":"Content to verify",
"新聞主張查核":"News verification","投資言論篩檢":"Investment text screening",
"登入":"Log in","註冊":"Sign up","會員登入":"Account sign in","歡迎回來":"Welcome back",
"建立會員帳號":"Create an account","密碼":"Password","電子郵件":"Email",
"我的分析紀錄":"My analysis history","個人資料":"Profile","通知設定":"Notifications",
"追蹤公司":"Watchlist","通知紀錄":"Notification history","儲存":"Save",
"登出":"Log out","財務報表":"Financial statements","官方來源":"Official sources",
"模型指標":"Model indicators","來源查證":"Source verification",
"檢視計算":"Inspect calculation","無資料":"No data",
"財報查核":"Financial verification","年增率":"Year-over-year","本期":"Current","前期":"Prior",
"風險通知":"Risk alerts","查核結果":"Results","資料來源":"Sources","財務異常":"Financial anomaly"
};
function apply(){
 const english=localStorage.getItem("ft-language")==="en";
 document.documentElement.lang=english?"en":"zh-Hant";
 document.querySelectorAll("[data-ft-en]").forEach(node=>{
   if(node.dataset.ftZh==null)node.dataset.ftZh=Array.from(node.childNodes).filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.nodeValue).join("");
   const wanted=english?node.dataset.ftEn:node.dataset.ftZh;
   const textNode=Array.from(node.childNodes).find(n=>n.nodeType===Node.TEXT_NODE);
   if(textNode)textNode.nodeValue=wanted;
   else if(!node.children.length)node.textContent=wanted;
 });
 document.querySelectorAll("[data-ft-en-placeholder]").forEach(node=>{
  if(node.dataset.ftZhPlaceholder==null)node.dataset.ftZhPlaceholder=node.getAttribute("placeholder")||"";
  node.setAttribute("placeholder",english?node.dataset.ftEnPlaceholder:node.dataset.ftZhPlaceholder);
 });
 const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 let n;while(n=walker.nextNode()){
   if(n.parentElement?.closest("[data-ft-en],script,style"))continue;
   if(!n.ftOriginal)n.ftOriginal=n.nodeValue;
   const trimmed=n.ftOriginal.trim();
   if(!trimmed||!d[trimmed])continue;
   const wanted=english?d[trimmed]:trimmed;
   const prefix=n.ftOriginal.match(/^\s*/)?.[0]||"";
   const suffix=n.ftOriginal.match(/\s*$/)?.[0]||"";
   if(n.nodeValue!==prefix+wanted+suffix)n.nodeValue=prefix+wanted+suffix;
 }
 const control=document.querySelector("#ft-language-toggle");
 if(control){
    control.textContent=english?"EN / 中文":"中文 / EN";
    control.setAttribute("aria-label",english?"Switch to Chinese":"Switch to English");
    control.setAttribute("title",english?"Switch to Chinese":"Switch to English");
 }
}
function toggle(){
 const english=localStorage.getItem("ft-language")==="en";
 localStorage.setItem("ft-language",english?"zh":"en");
 location.reload();
}
window.FTLocale={apply,toggle,language:()=>localStorage.getItem("ft-language")==="en"?"en":"zh"};
document.addEventListener("DOMContentLoaded",apply);
})();