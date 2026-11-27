/* Workbench renders actual calculations from a bounded synthetic model API. */
(function(){
"use strict";
const $=id=>document.getElementById(id), n=(tag,txt,cls)=>{const e=document.createElement(tag);if(txt!=null)e.textContent=String(txt);if(cls)e.className=cls;return e;};
const pct=v=>(100*v).toFixed(1)+"%", fmt=v=>Number(v).toFixed(4);
let last=null,busy=false;
function append(host,...items){host.append(...items);return host;}
function title(text){return n("h3",text);}
function note(text){return n("p",text,"ft-sheet-meta");}
function kpi(label,value,detail){return append(n("div",null,"ft-wb-kpi"),n("span",label),n("strong",value),note(detail||""));}
function grid(...items){return append(n("div",null,"ft-wb-kpis"),...items);}
function table(head,rows){const sc=n("div",null,"ft-sheet-scroll"),t=n("table",null,"ft-sheet-table"),h=n("thead"),b=n("tbody");h.append(append(n("tr"),...head.map(x=>n("th",x))));rows.forEach(r=>b.append(append(n("tr"),...r.map((x,i)=>n(i?"td":"th",x)))));return append(sc,append(t,h,b));}
function bar(label,value,max=1,display=null){const row=n("div",null,"ft-wb-bar"),track=n("div",null,"ft-wb-track"),fill=n("div",null,"ft-wb-fill");fill.style.width=Math.min(100,Math.max(0,Math.abs(value)/max*100))+"%";if(value<0)fill.classList.add("negative");return append(row,n("span",label),append(track,fill),n("strong",display??fmt(value)));}
function render(d){
 const tr=d.training,p=d.prediction,tx=d.text_analysis,news=tx.news,prob=p.prediction;
 const level=prob>=.5?"高風險":prob>=.3?"中風險":"低風險";
 $("wb-overview").replaceChildren(kpi("財報分類模型",pct(prob),level+" · 展示企業 "+d.scenario),kpi("文字分布差異",fmt(tx.jsd),"Jensen–Shannon Divergence"),kpi("文字相似度",fmt(tx.cosine),"TF-IDF cosine"),kpi("新聞詞彙風險",news.score+"/100",news.matched+" 個命中詞"));
 $("wb-dimensions").replaceChildren(title("四項獨立分析指標"),bar("財報分類機率",prob,1,pct(prob)),bar("文字差異 JSD",tx.jsd),bar("文字相似度",tx.cosine),bar("新聞字典分數",news.score,100,news.score+"/100"),note("不同指標保留原始尺度，不合併成未驗證的單一風險機率。"));
 const m=tr.metrics,cm=tr.confusion_matrix;
 $("wb-training").replaceChildren(grid(kpi("訓練樣本",tr.train_count,"原始訓練集"),kpi("獨立測試樣本",tr.test_count,"未經 SMOTE"),kpi("PR-AUC",fmt(m.pr_auc),"Average precision"),kpi("ROC-AUC",fmt(m.roc_auc))),
 title("類別不平衡處理"),table(["類別","訓練原始","訓練處理後","獨立測試"],[["N",tr.training_before[0],tr.training_after[0],tr.test_distribution[0]],["Y",tr.training_before[1],tr.training_after[1],tr.test_distribution[1]]]),
 title("混淆矩陣"),table(["實際／預測","N","Y"],[["N",cm[0][0],cm[0][1]],["Y",cm[1][0],cm[1][1]]]),grid(kpi("Accuracy",pct(m.accuracy)),kpi("Precision",pct(m.precision)),kpi("Recall",pct(m.recall)),kpi("F1",pct(m.f1))),
 title("演算法比較"),table(["模型","Accuracy","Precision","Recall","F1","PR-AUC","ROC-AUC"],d.comparison.map(x=>[{lr:"Logistic",dt:"Decision Tree",rf:"Random Forest"}[x.algorithm],...["accuracy","precision","recall","f1","pr_auc","roc_auc"].map(k=>fmt(x[k]))])));
 $("wb-prediction").replaceChildren(grid(kpi("個案","展示企業 "+d.scenario),kpi("Y 類別機率",pct(prob)),kpi("預測標籤",prob>=tr.threshold?"Y":"N","分類門檻 "+tr.threshold),kpi("介面風險等級",level,"0.3 / 0.5 展示分級")),table(["特徵","輸入數值"],p.contributions.map(v=>[v.feature,fmt(v.value)])));
 const max=Math.max(.01,...p.contributions.map(x=>Math.abs(x.shap)));
 $("wb-shap").replaceChildren(grid(kpi("基準機率",pct(p.base_value)),kpi("模型輸出",pct(prob))),title("SHAP 特徵貢獻（機率尺度）"),...p.contributions.slice().sort((a,b)=>Math.abs(b.shap)-Math.abs(a.shap)).map(x=>bar(x.feature,x.shap,max,(x.shap>=0?"+":"")+fmt(x.shap))),note(p.method),note("正值提高模型輸出，負值降低模型輸出；並非因果關係。"));
 const cloud=n("div",null,"ft-wb-cloud");tx.word_counts.forEach(x=>{let v=n("span",x.term);v.style.fontSize=(12+Math.min(20,x.count*3))+"px";cloud.append(v);});
 $("wb-text-result").replaceChildren(grid(kpi("JSD",fmt(tx.jsd)),kpi("Cosine",fmt(tx.cosine)),kpi("最佳分群",tx.cluster_count+" 群"),kpi("Silhouette",fmt(tx.silhouette))),title("詞彙分布與文字雲"),cloud,title("前後期變動詞彙"),table(["詞彙","前期","本期","比例變化"],tx.terms.map(x=>[x.term,x.prior,x.current,fmt(x.change)])),title("Cosine 分群評估"),table(["K","Silhouette"],tx.cluster_options.map(x=>[x.k,fmt(x.silhouette)])),title("文字分群結果"),table(["群別","文件","內容"],tx.clusters.map(x=>[x.cluster+1,x.document,x.text])),note(tx.method));
 $("wb-news-result").replaceChildren(grid(kpi("詞彙風險分數",news.score+"/100"),kpi("命中詞彙",news.matched+" / "+news.dictionary_size)),title("風險字典分類"),table(["類別","命中詞彙","數量"],news.hits.map(h=>[h.category,h.matches.join("、")||"無",h.matches.length])));
}
async function run(){
 if(busy)return;busy=true;const ids=["wb-run","wb-text-run","wb-news-run"];ids.forEach(i=>$(i).disabled=true);$("wb-status").textContent="執行 Python 模型與文字分析中…";
 const body={algorithm:$("wb-model").value,scenario:$("wb-scenario").value,smote:$("wb-smote").checked};
 if(last){body.prior_text=$("wb-prior").value;body.current_text=$("wb-current").value;body.news=$("wb-news-input").value;}
 try{const r=await fetch("/api/workbench/demo",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const j=await r.json();if(!r.ok||!j.success)throw Error(j.error||"HTTP "+r.status);last=j.data;render(last);$("wb-prior").value=last.inputs.prior_text;$("wb-current").value=last.inputs.current_text;$("wb-news-input").value=last.inputs.news;$("wb-export").disabled=false;$("wb-status").textContent="分析完成 · "+new Date().toLocaleString("zh-TW");}catch(e){$("wb-status").textContent="分析未完成："+e.message;}finally{busy=false;ids.forEach(i=>$(i).disabled=false);}
}
async function real(){try{const r=await fetch("/api/research/annual-model-results/6505/2025");const j=await r.json();if(!r.ok||!j.success)throw Error("HTTP "+r.status);const x=j.data.record;$("wb-real").replaceChildren(note(j.data.company+"（6505） · "+j.data.year+" Q4 · "+x.source_file),grid(kpi("Beneish M-Score",fmt(x.beneish.M_score)),kpi("Dechow F-Score",fmt(x.dechow.F_score))),note("已封存 MOPS 財報計算結果，與上方合成分類模型不共用樣本。"));}catch(e){$("wb-real").textContent="官方財報輸出讀取失敗："+e.message;}}
document.addEventListener("DOMContentLoaded",()=>{if(!$("wb-run"))return;["wb-run","wb-text-run","wb-news-run"].forEach(i=>$(i).addEventListener("click",run));$("wb-export").addEventListener("click",()=>{if(!last)return;const u=URL.createObjectURL(new Blob([JSON.stringify(last,null,2)],{type:"application/json"}));const a=n("a");a.href=u;a.download="synthetic-model-workbench.json";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);});run();real();});
})();