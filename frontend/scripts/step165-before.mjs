
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";
const BASE="http://127.0.0.1:5173";
const OUT="/opt/cursor/artifacts/step165";
const URL=`${BASE}/production.html?epv3_preview=fixture`;
fs.mkdirSync(OUT,{recursive:true});
const browser=await puppeteer.launch({executablePath:process.env.CHROME_PATH||"/usr/local/bin/google-chrome",headless:"new",args:["--no-sandbox","--disable-setuid-sandbox"]});
const page=await browser.newPage();
await page.setViewport({width:1440,height:900});
async function shot(name, fn){
  await page.goto(URL,{waitUntil:"networkidle0",timeout:60000});
  await page.waitForFunction(()=>document.documentElement.classList.contains("v3-auth-ok"),{timeout:20000});
  if(fn) await fn();
  await new Promise(r=>setTimeout(r,700));
  await page.screenshot({path:path.join(OUT,name),fullPage:false});
}
await shot("before-inbox-1440.png", async()=>{ await page.evaluate(()=>go("inbox")); });
await shot("before-jadwal-1440.png", async()=>{ await page.evaluate(()=>go("schedule")); });
await shot("before-tugas-1440.png", async()=>{ await page.evaluate(()=>go("tasks")); });
await shot("before-sidebar-toolbar-1440.png", async()=>{ await page.evaluate(()=>go("inbox")); await page.evaluate(()=>{const el=document.querySelector("#v41-primary-sidebar"); if(el) el.scrollTop=0;}); });
await shot("before-detail-po-1440.png", async()=>{
  await page.evaluate(()=>go("inbox"));
  await new Promise(r=>setTimeout(r,500));
  await page.evaluate(()=>{
    const btn=[...document.querySelectorAll("button,a")].find(b=>/Ringkasan|Detail PO|ⓘ|Info/i.test(b.textContent||"") || /v49Open|showScheduleDetail|openPo/i.test(b.getAttribute("onclick")||""));
    if(btn) btn.click();
    else if(typeof v49OpenPoDetail==="function"){ const o=orders?.[0]; if(o) v49OpenPoDetail(o.id); }
    else if(typeof showScheduleDetail==="function" && orders?.[0]) showScheduleDetail(orders[0].id);
  });
  await new Promise(r=>setTimeout(r,600));
});
await shot("before-empty-state-1440.png", async()=>{
  await page.evaluate(()=>go("inbox"));
  await new Promise(r=>setTimeout(r,400));
  await page.evaluate(()=>{
    const input=document.querySelector("#v36-inbox-search");
    if(input){ input.value="ZZZ_NO_MATCH_XYZ"; input.dispatchEvent(new Event("input",{bubbles:true})); }
  });
  await new Promise(r=>setTimeout(r,500));
});
console.log("before shots done", fs.readdirSync(OUT).filter(f=>f.startsWith("before")));
await browser.close();
