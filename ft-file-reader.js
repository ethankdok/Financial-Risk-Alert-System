/* Browser-side local attachment extraction. Never posts raw files to a server. */
(function(){
"use strict";
const MAX_BYTES=15*1024*1024,MAX_TEXT=90000;
const zh=(a,b)=>localStorage.getItem("ft-language")==="en"?b:a;
const scripts={pdf:"https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js",xlsx:"https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js",docx:"https://cdn.jsdelivr.net/npm/mammoth@1.8.0/mammoth.browser.min.js",ocr:"https://cdn.jsdelivr.net/npm/tesseract.js@5.1.0/dist/tesseract.min.js"};
const promises={};
function load(name){
 if(promises[name])return promises[name];
 return promises[name]=new Promise((res,rej)=>{
  const script=document.createElement("script");script.src=scripts[name];script.async=true;script.onload=()=>res();script.onerror=()=>rej(Error(zh("無法載入檔案解析模組","Unable to load file parser")));document.head.appendChild(script);
 });
}
async function pdf(file,status){
 await load("pdf");if(!window.pdfjsLib)throw Error("PDF parser unavailable");
 window.pdfjsLib.GlobalWorkerOptions.workerSrc="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
 const doc=await window.pdfjsLib.getDocument({data:new Uint8Array(await file.arrayBuffer())}).promise;
 const pages=[];for(let i=1;i<=Math.min(doc.numPages,30);i++){
  status(zh("讀取 PDF 第 ","Reading PDF page ")+i+" / "+Math.min(doc.numPages,30));
  const page=await doc.getPage(i);const text=await page.getTextContent();
  pages.push(text.items.map(x=>x.str||"").join(" "));
  if(pages.join("\n").length>=MAX_TEXT)break;
 }
 const full=pages.join("\n");
 if(!full.trim())throw Error(zh("PDF 沒有可擷取文字；掃描文件請改用圖片辨識","No selectable PDF text; use image OCR for scans"));
 return full;
}
async function sheets(file){
 await load("xlsx");if(!window.XLSX)throw Error("Spreadsheet parser unavailable");
 const wb=window.XLSX.read(await file.arrayBuffer(),{type:"array",cellDates:true});
 const out=[];for(const name of wb.SheetNames.slice(0,8)){
  const rows=window.XLSX.utils.sheet_to_csv(wb.Sheets[name],{blankrows:false});
  out.push("["+name+"]\n"+rows.slice(0,40000));if(out.join("\n").length>MAX_TEXT)break;
 }return out.join("\n");
}
async function documentText(file){
 await load("docx");if(!window.mammoth)throw Error("Document parser unavailable");
 const r=await window.mammoth.extractRawText({arrayBuffer:await file.arrayBuffer()});
 return r.value||"";
}
async function imageOCR(file,status){
 await load("ocr");if(!window.Tesseract)throw Error("OCR parser unavailable");
 status(zh("正在辨識圖片中的文字…","Recognizing text in image…"));
 const task=await window.Tesseract.recognize(file,"chi_tra+eng");
 return task.data?.text||"";
}
async function extract(file,status){
 if(file.size>MAX_BYTES)throw Error(zh("檔案不能超過 15MB","File exceeds 15 MB"));
 const ext=(file.name.split(".").pop()||"").toLowerCase();
 if(["txt","csv","json","md"].includes(ext))return await file.text();
 if(ext==="pdf")return await pdf(file,status);
 if(["xls","xlsx"].includes(ext))return await sheets(file);
 if(ext==="docx")return await documentText(file);
 if(["png","jpg","jpeg","webp"].includes(ext))return await imageOCR(file,status);
 throw Error(zh("不支援此格式","Unsupported file type"));
}
function attach(input,textarea,output){
 if(!input||!textarea)return;
 input.addEventListener("change",async()=>{
  const file=input.files?.[0];if(!file)return;
  const notify=s=>{if(output)output.textContent=s;};
  notify(zh("解析中：","Reading: ")+file.name);
  try{
   const content=(await extract(file,notify)).trim();
   if(!content)throw Error(zh("沒有讀到文字","No text was extracted"));
   textarea.value=(textarea.value.trim()?textarea.value.trim()+"\n\n":"")+content.slice(0,MAX_TEXT);
   notify(zh("已讀取：","Imported: ")+file.name);
  }catch(e){notify((e.message||zh("檔案解析失敗","File parsing failed"))+" · "+file.name);}
  input.value="";
 });
}
window.FTFileReader={attach};
})();