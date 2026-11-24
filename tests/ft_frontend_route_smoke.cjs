/* Standalone, no-dependency navigation regression tests.
 * Execute: node tests/ft_frontend_route_smoke.cjs
 */
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const file=fs.readFileSync(path.join(__dirname,"..","ft-site.js"),"utf8");

function simulateHome(text){
  const handlers={};
  const input={value:text,focus(){},addEventListener:(type,fn)=>handlers["input:"+type]=fn};
  const button={disabled:false,addEventListener:(type,fn)=>handlers["button:"+type]=fn};
  const nodes={
    "#ft-home-query":input,"#ft-home-submit":button,
    "#ft-recent-list":{replaceChildren(){},appendChild(){}},
    "#ft-clear-recent":{hidden:true,addEventListener(){}}
  };
  const document={
    body:{getAttribute:()=>"home"},
    querySelector:sel=>nodes[sel]||null,
    querySelectorAll:()=>[],
    addEventListener:(type,fn)=>handlers[type]=fn,
    createElement:tag=>({tagName:tag,appendChild(){},setAttribute(){},addEventListener(){},style:{}})
  };
  const company={
    ticker:"2330",name:"台積電",fullName:"台灣積體電路製造股份有限公司"
  };
  const FTCompanies={
    findInText:q=>(String(q).includes("台積電")||q==="2330")?company:null,
    addRecent(){},readRecent:()=>[],attachAutocomplete(){},clearRecent(){}
  };
  const location={search:"",hostname:"example.com",href:""};
  const sessionStorage={setItem(){},removeItem(){},getItem:()=>null};
  const window={
    FTCompanies,FTLocale:{language:()=>"zh",phrase:s=>s,t:s=>s},
    addEventListener(){}
  };
  vm.runInNewContext(file,{document,location,sessionStorage,window,URLSearchParams,fetch:async()=>({})},
                     {filename:"ft-site.js"});
  assert.equal(typeof handlers.DOMContentLoaded,"function");
  handlers.DOMContentLoaded();
  handlers["button:click"]();
  return location.href;
}
const cases=[
 ["2330","financial-audit.html?ticker=2330"],
 ["2330 台積電","financial-audit.html?ticker=2330"],
 ["台積電","financial-audit.html?ticker=2330"],
 ["台積電營收","financial-audit.html?ticker=2330"],
 ["台積電獲利","financial-audit.html?ticker=2330"],
 ["台積電財報異常","financial-audit.html?ticker=2330"],
 ["台積電新聞說獲利","analysis.html?ticker=2330"],
 ["核對新聞中的財務數字","analysis.html"],
];
for(const [input,expected] of cases){
  const actual=simulateHome(input);
  assert.equal(actual,expected,"Home input: "+input);
  process.stdout.write("PASS "+JSON.stringify(input)+" → "+actual+"\n");
}
process.stdout.write("\n8/8 home-route cases passed.\n");
