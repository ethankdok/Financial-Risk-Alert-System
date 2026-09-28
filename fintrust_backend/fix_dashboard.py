from pathlib import Path
from datetime import datetime
import ast
import shutil

file = Path("app/routers/research_dashboard.py")

if not file.exists():
    raise SystemExit("找不到儀表板檔案")

code = file.read_text(encoding="utf-8")

html_anchor = '<svg id="cosine" viewBox="0 0 700 220"></svg>'
js_anchor = "function show(name){"
call_anchor = 'draw("cosine",rows,"historical_cosine");'

if not all(x in code for x in (html_anchor, js_anchor, call_anchor)):
    raise SystemExit("程式結構不符，未修改任何檔案")

html = """
<h4>固定 TF-IDF：文字清理前後比較</h4>
<p>橘線：清理前｜綠線：清理後</p>
<svg id="cleanCompare" viewBox="0 0 700 220"></svg>
"""

js = """
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
"""

if 'id="cleanCompare"' not in code:
    code = code.replace(html_anchor, html_anchor + html, 1)

if "function drawCleanComparison(rows)" not in code:
    code = code.replace(js_anchor, js + js_anchor, 1)

if "drawCleanComparison(rows);" not in code:
    code = code.replace(
        call_anchor,
        call_anchor + "\n drawCleanComparison(rows);",
        1
    )

ast.parse(code)

backup = file.with_name(
    "research_dashboard_backup_"
    + datetime.now().strftime("%Y%m%d_%H%M%S")
    + ".py"
)

shutil.copy2(file, backup)
file.write_text(code, encoding="utf-8")

print("安裝成功")
print("備份：", backup)
