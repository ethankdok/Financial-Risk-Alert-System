from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["research-dashboard"])

PAGE = """
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FinTrust 研究成果</title>
<style>
body{font-family:Arial,sans-serif;background:#f3f6fb;color:#20314b;margin:0}
header{background:#17365d;color:white;padding:30px 6%}
main{max-width:1050px;margin:30px auto;padding:0 18px}
.card{background:white;border-radius:14px;padding:24px;margin-bottom:20px}
.stats{display:flex;gap:15px}
.stats .card{flex:1}
button{padding:12px 20px;margin:5px;border:1px solid #ccc;border-radius:8px;cursor:pointer}
button.active{background:#245fc0;color:white}
svg{width:100%;height:auto}
table{width:100%;border-collapse:collapse}
th,td{padding:12px;border-bottom:1px solid #ddd;text-align:left}
.warning{background:#fff3d9;padding:15px}
@media(max-width:600px){.stats{display:block}}
</style>
</head>
<body>
<header>
<h1>FinTrust 研究成果儀表板</h1>
<p>半導體產業法說會歷史文字漂移研究</p>
</header>
<main>
<div class="stats">
<div class="card"><h3>研究公司</h3><h1 id="count">—</h1></div>
<div class="card"><h3>比較組數</h3><h1 id="total">—</h1></div>
</div>

<div class="card">
<h2>歷史研究數據</h2>
<button id="b1" onclick="show('TSMC')">台積電</button>
<button id="b2" onclick="show('MediaTek')">聯發科</button>
<h3 id="name"></h3>
<h4>JSD</h4>
<svg id="jsd" viewBox="0 0 700 220"></svg>
<h4>Cosine Similarity</h4>
<svg id="cosine" viewBox="0 0 700 220"></svg>
<h4>固定 TF-IDF：文字清理前後比較</h4>
<p>橘線：清理前｜綠線：清理後</p>
<svg id="cleanCompare" viewBox="0 0 700 220"></svg>

</div>

<div class="card">
<h2>詳細比較</h2>
<table>
<thead><tr><th>期間</th><th>JSD</th><th>Cosine</th><th>用途</th></tr></thead>
<tbody id="rows"></tbody>
</table>
</div>

<div class="card">
<h2>研究限制</h2>
<p class="warning">
目前門檻僅供探索性研究。
文字漂移不代表詐騙，也不能視為詐騙機率。
不同公司的實驗設定不可直接混用。
</p>
<p id="version"></p>
</div>
<p id="error"></p>

<section class="card">
<h2>供應商名稱移除實驗</h2>
<p>檢查 Refinitiv、LSEG 名稱對文字漂移指標的影響。</p>
<a href="/research-provider-evidence">
查看完整實驗結果與詞彙證據
</a>
</section>
</main>

<script>
let snapshot;

function draw(id,rows,key){
 const svg=document.getElementById(id);
 svg.replaceChildren();
 const ns="http://www.w3.org/2000/svg";
 function add(tag,attrs,text){
  const el=document.createElementNS(ns,tag);
  Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));
  if(text!==undefined)el.textContent=text;
  svg.appendChild(el);
 }
 const values=rows.map(r=>Number(r[key]));
 if(!values.length||values.some(v=>!Number.isFinite(v))){
  add("text",{x:30,y:90},"沒有有效數據");
  return;
 }
 const x=i=>50+i*95;
 const y=v=>180-v*145;
 [0,.25,.5,.75,1].forEach(v=>{
  add("line",{x1:40,y1:y(v),x2:675,y2:y(v),stroke:"#ddd"});
  add("text",{x:5,y:y(v)+4,"font-size":12},v.toFixed(2));
 });
 add("polyline",{
  points:values.map((v,i)=>x(i)+","+y(v)).join(" "),
  stroke:"#245fc0",fill:"none","stroke-width":3
 });
 values.forEach((v,i)=>{
  add("circle",{cx:x(i),cy:y(v),r:5,fill:"#245fc0"});
  add("text",{
   x:x(i),y:y(v)-12,"text-anchor":"middle","font-size":12
  },v.toFixed(3));
  add("text",{
   x:x(i),y:205,"text-anchor":"middle","font-size":12
  },rows[i].current_period||rows[i].period||String(i+1));
 });
}


function drawCleanComparison(rows) {
 const svg=document.getElementById("cleanCompare");
 svg.replaceChildren();
 const ns="http://www.w3.org/2000/svg";

 function add(tag,attrs,text) {
  const e=document.createElementNS(ns,tag);
  Object.entries(attrs).forEach(
   ([k,v])=>e.setAttribute(k,v)
  );
  if(text!==undefined)e.textContent=text;
  svg.appendChild(e);
 }

 const x=i=>50+i*95;
 const y=v=>180-v*145;

 [0,.25,.5,.75,1].forEach(v=>{
  add("line",{
   x1:40,y1:y(v),x2:675,y2:y(v),stroke:"#ddd"
  });
  add("text",{x:5,y:y(v)+4},v.toFixed(2));
 });

 for(const [key,color] of [
  ["raw_fixed","#dc8530"],
  ["clean_fixed","#159b83"]
 ]) {
  const values=rows.map(r=>Number(r[key]));
  if(values.some(v=>!Number.isFinite(v)))return;

  add("polyline",{
   points:values.map((v,i)=>x(i)+","+y(v)).join(" "),
   fill:"none",stroke:color,"stroke-width":3
  });

  values.forEach((v,i)=>{
   add("circle",{
    cx:x(i),cy:y(v),r:5,fill:color
   });
  });
 }

 rows.forEach((r,i)=>{
  add("text",{
   x:x(i),y:205,"text-anchor":"middle",
   "font-size":12
  },r.current_period||"");
 });
}

function researchQuantile(values, q) {
 const sorted = [...values].sort((a,b) => a-b);
 const position = (sorted.length-1)*q;
 const low = Math.floor(position);
 const high = Math.ceil(position);
 const fraction = position-low;

 return sorted[low]+
  (sorted[high]-sorted[low])*fraction;
}

function decorateResearchChart(id, rows, key, quantile, title) {
 const svg = document.getElementById(id);
 const ns = "http://www.w3.org/2000/svg";

 function add(tag, attrs, text) {
  const element = document.createElementNS(ns,tag);

  Object.entries(attrs).forEach(([k,v]) =>
   element.setAttribute(k,v)
  );

  if(text !== undefined) {
   element.textContent = text;
  }

  svg.appendChild(element);
  return element;
 }

 const values = rows.map(row => Number(row[key]));

 // 至少五組校準資料及兩組保留測試資料
 if(
  rows.length !== 7 ||
  values.some(v => !Number.isFinite(v))
 ) {
  console.warn("研究資料不完整，略過門檻線");
  return;
 }

 const calibration = values.slice(0,5);
 const threshold = researchQuantile(
  calibration,
  quantile
 );

 const x = i => 50+i*95;
 const y = value => 180-value*145;
 const thresholdY = y(threshold);

 // 探索性門檻
 add("line",{
  x1:40,
  y1:thresholdY,
  x2:675,
  y2:thresholdY,
  stroke:"#dc8530",
  "stroke-width":1.8,
  "stroke-dasharray":"7 5"
 });

 // 最後兩組加上紫色外圈
 [5,6].forEach(i => {
  add("circle",{
   cx:x(i),
   cy:y(values[i]),
   r:9,
   fill:"none",
   stroke:"#9146c7",
   "stroke-width":2.5
  });
 });

 // 圖表下方的研究說明
 const infoId = id+"ResearchInfo";
 let info = document.getElementById(infoId);

 if(!info) {
  info = document.createElement("p");
  info.id = infoId;
  info.style.fontSize = "13px";
  info.style.lineHeight = "1.8";
  info.style.color = "#53627b";
  svg.insertAdjacentElement("afterend",info);
 }

 info.textContent =
  "橘色虛線："+title+" = "+
  threshold.toFixed(4)+
  "｜紫色外圈：保留測試資料"+
  "｜門檻僅供探索性研究";
}

function show(name){
 const company=snapshot.companies.find(c=>c.company===name);
 if(!company)return;
 document.getElementById("b1").classList.toggle("active",name==="TSMC");
 document.getElementById("b2").classList.toggle("active",name==="MediaTek");
 document.getElementById("name").textContent=name;
 const rows=company.comparisons;
 draw("jsd",rows,"historical_jsd");
 draw("cosine",rows,"historical_cosine");
 decorateResearchChart(
  "jsd",rows,"historical_jsd",
  0.90,"JSD P90"
 );
 decorateResearchChart(
  "cosine",rows,"historical_cosine",
  0.05,"Cosine P05"
 );

 drawCleanComparison(rows);
 const body=document.getElementById("rows");
 body.replaceChildren();
 rows.forEach((r,i)=>{
  const tr=document.createElement("tr");
  [
   (r.previous_period||"")+" → "+(r.current_period||r.period||""),
   Number(r.historical_jsd).toFixed(6),
   Number(r.historical_cosine).toFixed(6),
   i<5?"探索性校準":"保留測試"
  ].forEach(value=>{
   const td=document.createElement("td");
   td.textContent=value;
   tr.appendChild(td);
  });
  body.appendChild(tr);
 });
}

async function start(){
 try{
  const response=await fetch("/api/v1/financial/research-snapshots/latest");
  if(!response.ok)throw Error("HTTP "+response.status);
  snapshot=await response.json();
  document.getElementById("count").textContent=snapshot.companies.length;
  document.getElementById("total").textContent=
   snapshot.companies.reduce((n,c)=>n+c.comparisons.length,0);
  document.getElementById("version").textContent=
   "研究狀態："+snapshot.status+"｜版本："+snapshot.snapshot_id;
  show("TSMC");
 }catch(e){
  document.getElementById("error").textContent="載入失敗："+e.message;
 }
}
start();
</script>
</body>
</html>
"""

@router.get("/research-dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(PAGE)


@router.get(
    "/research-provider-evidence",
    response_class=HTMLResponse
)
def provider_evidence_page():
    import csv
    import json
    from pathlib import Path
    from html import escape

    root = Path(__file__).resolve().parents[2]
    folder = root / "data/research-results"

    data = json.loads(
        (folder / "tsmc_provider_impact.json")
        .read_text(encoding="utf-8")
    )

    with (folder / "tsmc_provider_terms.csv").open(
        encoding="utf-8-sig", newline=""
    ) as f:
        terms = list(csv.DictReader(f))

    before = data["baseline"]
    after = data["provider_removed"]

    page = """
    <html lang="zh-Hant">
    <head>
    <meta charset="utf-8">
    <title>FinTrust 實驗證據</title>
    <style>
    body{font-family:Arial,sans-serif;
         background:#f3f6fb;color:#20314b;
         max-width:960px;margin:40px auto;padding:20px}
    section{background:white;padding:25px;
            border-radius:12px;margin-bottom:20px}
    table{width:100%;border-collapse:collapse}
    td,th{padding:12px;border-bottom:1px solid #ddd;
          text-align:left}
    a{color:#245fc0}
    </style>
    </head><body>
    <a href="/research-dashboard">返回研究儀表板</a>
    <h1>供應商名稱移除實驗</h1>
    <section>
    <h2>台積電 2025Q3 → 2025Q4</h2>
    <table>
    <tr><th>指標</th><th>移除前</th>
        <th>移除後</th><th>變化</th></tr>
    """

    for metric in ("jsd", "cosine"):
        a = float(before[metric])
        b = float(after[metric])
        page += (
            "<tr><td>" + metric.upper() + "</td>"
            f"<td>{a:.6f}</td>"
            f"<td>{b:.6f}</td>"
            f"<td>{b-a:+.6f}</td></tr>"
        )

    page += """
    </table></section>
    <section><h2>詞彙變化證據</h2>
    <table>
    <tr><th>季度</th><th>詞彙</th>
        <th>次數</th><th>每千字</th></tr>
    """

    for row in terms:
        page += "<tr>"
        for key in (
            "period", "term", "count",
            "per_1000_words"
        ):
            page += (
                "<td>" +
                escape(str(row.get(key, ""))) +
                "</td>"
            )
        page += "</tr>"

    page += """
    </table></section>
    <section>
    <h2>研究限制</h2>
    <p>本實驗僅驗證指定品牌詞彙移除後，
    文字漂移指標的變化，不代表詐騙偵測結果。</p>
    <p>詞彙統計為描述性證據，
    尚不能單獨證明指標變化的因果關係。</p>
    </section></body></html>
    """

    return HTMLResponse(page)


from app.routers.provider_excerpts import (
    router as provider_excerpts_router
)
router.include_router(provider_excerpts_router)


from app.routers.provider_review import router as review_router
router.include_router(review_router)


from app.routers.provider_batch import router as batch_router
router.include_router(batch_router)
