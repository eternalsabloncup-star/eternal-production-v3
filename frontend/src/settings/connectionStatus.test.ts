import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';
const src=readFileSync('public/live-runtime.js','utf8');
const html=readFileSync('public/production.html','utf8');
const block=src.slice(src.indexOf('function connReduce'),src.indexOf('function connDispatch'));
const {connReduce,connLabels}=new Function(`${block}return {connReduce,connLabels};`)();
const start=()=>({api:'checking',gateway:'unchecked',sync:'none',auth:'ok',syncAt:null});
const run=(...evs:any[])=>evs.reduce(connReduce,start());
const L=(st:any)=>connLabels(st,false);

it('backend healthy -> API TERHUBUNG, gateway not claimed from health alone',()=>{
  const l=L(run({t:'health',ok:true}));
  expect(l.api).toBe('TERHUBUNG');expect(l.gateway).toBe('BELUM DIPERIKSA');expect(l.sync).toBe('BELUM TERSEDIA');
});
it('successful Inbox -> gateway TERHUBUNG and sync BERHASIL',()=>{
  const l=L(run({t:'health',ok:true},{t:'inbox_start'},{t:'inbox_ok',at:'10.00.00'}));
  expect(l).toEqual({api:'TERHUBUNG',gateway:'TERHUBUNG',sync:'BERHASIL (10.00.00)'});
  expect(L(run({t:'health',ok:true},{t:'inbox_start'})).gateway).toBe('MEMERIKSA');
});
it('backend down -> GANGGUAN, never a success state',()=>{
  for(const evs of [[{t:'health',ok:false}],[{t:'health',ok:true},{t:'inbox_ok',at:'x'},{t:'inbox_fail',kind:'network'}]]){
    const l=L(run(...evs));expect(l.api).toBe('GANGGUAN');expect(l.gateway).toBe('BELUM DIPERIKSA');expect(l.sync).toBe('GAGAL');
  }
});
it('expired session -> PERLU LOGIN, not backend down',()=>{
  const l=L(run({t:'health',ok:true},{t:'inbox_ok',at:'x'},{t:'auth'}));
  expect(l.api).toBe('PERLU LOGIN');expect(l.sync).toBe('BELUM TERSEDIA');
  expect(L(run({t:'health',ok:true},{t:'inbox_fail',kind:'auth'})).api).toBe('PERLU LOGIN');
});
it('gateway failure with healthy backend is distinct',()=>{
  const l=L(run({t:'health',ok:true},{t:'inbox_start'},{t:'inbox_fail',kind:'gateway'}));
  expect(l).toEqual({api:'TERHUBUNG',gateway:'GANGGUAN',sync:'GAGAL'});
  expect(L(run({t:'health',ok:true},{t:'inbox_fail',kind:'other'})).gateway).toBe('BELUM DIPERIKSA');
});
it('preview fixture is labelled and isolated',()=>{
  expect(connLabels(start(),true).api).toBe('PREVIEW SIMULASI');
});
it('render/tidy no longer hardcode connection text; controller applies after every render',()=>{
  expect(html).not.toMatch(/Menunggu API V3|Menunggu koneksi backend|Accurate • Belum terhubung|Frontend V49/);
  expect(html).toContain("window.v3ApplyConnectionStatus()");
  expect(src).toMatch(/if \(content && !status\.parentElement\) content\.prepend\(status\);\s*window\.v3ApplyConnectionStatus\(\);/);
  expect(src).not.toMatch(/setInterval/);
});
it('operational mode hides historical capability registry and demo-only views',()=>{
  expect(html).toContain("concat(operational?[]:[['audit','Gap ERP V1']])");
  for(const v of ['shippingScheduleView','salarySlipView','productionReportView','monitorBuffer'])expect(src).toContain(`guardDemoView("${v}"`);
  expect(src).toContain('target === "contractMonitor"');
  expect(src).toContain('Belum tersedia secara operasional.');
  expect(html).toContain('bukan konfigurasi perusahaan');
});
it('app activity log no longer collides with window.history (Overview crashed on history.slice)',()=>{expect(html).not.toMatch(/var orders=\[\],history=/);expect(html).toContain('activityLog.slice(0,5)');});
