import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';
const html=readFileSync('public/production.html','utf8');
const start=html.indexOf('function settingsAccessPanel(){');
const end=html.indexOf('function settingsView(){');
const panel=(auth:any)=>new Function('window','escape',`${html.slice(start,end)}return settingsAccessPanel();`)({__V3_AUTH__:auth},(s:string)=>s);

it('menu Pengaturan wires the existing Settings entry without a duplicate endpoint',()=>{
  expect(start).toBeGreaterThan(0);expect(end).toBeGreaterThan(start);
  expect(html).toContain('const accessLink=settingsAccessPanel();');
  expect(html).not.toMatch(/fetch\([^)]*\/settings\//);
});
it.each([
  [{status:'ok'},'NONAKTIF',false,'legacy'],
  [{status:'ok',settings_enabled:true,system_director:false,workflow_authorization:'legacy'},'TERBATAS',false,'legacy'],
  [{status:'ok',settings_enabled:true,system_director:true,workflow_authorization:'legacy'},'AKTIF',true,'legacy'],
  [{status:'ok',settings_enabled:true,system_director:true,workflow_authorization:'enforced'},'AKTIF',true,'enforced'],
])('settings access state %#',(auth,state,link,mode)=>{
  const out=panel(auth);
  expect(out).toContain(`data-state="${state}"`);
  expect(out).toContain(`data-workflow="${mode}"`);
  expect(out.includes('href="/?view=settings"')).toBe(link);
  expect(out).toContain(`Mode otorisasi workflow: ${mode}`);
});
it('missing auth object never exposes the link',()=>{
  expect(new Function('window','escape',`${html.slice(start,end)}return settingsAccessPanel();`)({},(s:string)=>s)).not.toContain('href=');
});
