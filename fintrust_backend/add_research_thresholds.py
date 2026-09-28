from pathlib import Path
from datetime import datetime
import ast
import shutil

file = Path("app/routers/research_dashboard.py")

if not file.exists():
    raise SystemExit("找不到儀表板檔案，請確認工作目錄")

code = file.read_text(encoding="utf-8")

anchor = "function show(name){"
call_anchor = 'draw("cosine",rows,"historical_cosine");'

if "function decorateResearchChart(" in code:
    raise SystemExit("門檻功能已存在，不需要重複安裝")

if anchor not in code or call_anchor not in code:
    raise SystemExit("儀表板結構不符，未修改任何檔案")

js = r"""
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
"""

code = code.replace(anchor, js+"\n"+anchor, 1)

code = code.replace(
    call_anchor,
    call_anchor + """
 decorateResearchChart(
  "jsd",rows,"historical_jsd",
  0.90,"JSD P90"
 );
 decorateResearchChart(
  "cosine",rows,"historical_cosine",
  0.05,"Cosine P05"
 );
""",
    1
)

ast.parse(code)

backup = file.with_name(
    "research_dashboard_backup_"
    + datetime.now().strftime("%Y%m%d_%H%M%S")
    + ".py"
)

shutil.copy2(file,backup)
file.write_text(code,encoding="utf-8")

print("=== 安裝成功 ===")
print("已加入：JSD 探索性門檻")
print("已加入：Cosine 探索性門檻")
print("已加入：保留測試資料標記")
print("備份：",backup)
