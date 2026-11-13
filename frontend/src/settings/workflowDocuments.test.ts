import {readFileSync} from 'node:fs';
import {expect,it,vi} from 'vitest';
const source=readFileSync('public/workflow-documents.js','utf8');
const enforced=()=>({ok:true,json:async()=>({workflow_authorization:'enforced'})});
// Actual public script, with network/DOM doubles only.
it.each(['exportSheet','taskExportCsv','exportProductionReport','printSalarySlip'])('%s never invokes a legacy handler in enforced mode when denied',async(name)=>{
  const old=vi.fn(),toast=vi.fn(), win:any={[name]:old,toast,v3LastPayrollRunId:7};
  const fetch=vi.fn().mockResolvedValueOnce(enforced()).mockResolvedValue({ok:false,status:403});
  new Function('window','fetch','localStorage',source)(win,fetch,{getItem:()=> 'test'});
  await win[name]();expect(old).not.toHaveBeenCalled();expect(toast).toHaveBeenCalled();
  expect(fetch.mock.calls[1][0]).toContain('/production/access/documents/');
});

it('payroll print requires a computed run and an explicit backend grant',async()=>{
  const old=vi.fn(),toast=vi.fn(),win:any={printSalarySlip:old,toast};
  const fetch=vi.fn().mockResolvedValueOnce(enforced());
  new Function('window','fetch','localStorage',source)(win,fetch,{getItem:()=> 'test'});
  await win.printSalarySlip();
  expect(fetch).toHaveBeenCalledTimes(1);expect(old).not.toHaveBeenCalled();
  win.v3LastPayrollRunId=12;
  fetch.mockResolvedValueOnce(enforced()).mockResolvedValueOnce({ok:true,json:async()=>({items:[]})});
  await win.printSalarySlip();
  expect(fetch.mock.calls[2][0]).toBe('/api/v1/production/access/documents/payroll.print?run_id=12');
  expect(old).toHaveBeenCalledTimes(1);
});

it('legacy mode keeps the existing handler',async()=>{
  const old=vi.fn(),win:any={printSalarySlip:old,toast:vi.fn()};
  const fetch=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({workflow_authorization:'legacy'})});
  new Function('window','fetch','localStorage',source)(win,fetch,{getItem:()=> 'test'});
  await win.printSalarySlip();expect(old).toHaveBeenCalledTimes(1);expect(fetch).toHaveBeenCalledTimes(1);
});

const runtime=readFileSync('public/live-runtime.js','utf8');
const html=readFileSync('public/production.html','utf8');
it('409 codes are distinguished: reconcile never reads as a plain failure',()=>{
  expect(runtime).toContain('access_changed_reconcile');
  expect(runtime).toMatch(/PERLU REKONSILIASI[^"]*tersimpan/);
  expect(runtime).toContain('access_changed_nothing_written');
  expect(runtime).toMatch(/Tidak ada data yang tersimpan[^"]*Aman untuk dicoba lagi/);
  const reconcile=runtime.slice(runtime.indexOf('access_changed_reconcile'),runtime.indexOf('access_changed_nothing_written'));
  expect(reconcile).toContain('delete boardCache[so]');
  expect(reconcile).not.toMatch(/Aman untuk dicoba lagi/);
});
it('payroll slip stays labelled as an unofficial simulation',()=>{
  expect(html).toContain('SIMULASI · SLIP GAJI MINGGUAN');
  expect(html).toContain('Draft / Tidak Resmi');
  expect(html).toContain('DOKUMEN SIMULASI — BUKAN SLIP GAJI RESMI');
  expect(html).toContain('GAJI BERSIH (DEMO)');
});
