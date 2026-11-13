import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';
const src=readFileSync('public/live-runtime.js','utf8');
it('monitor uses the official cross-PO endpoint and no demo role/fixture in operational mode',()=>{
  expect(src).toContain('/production/jobs/payment/receipts?');
  expect(src).toMatch(/isPreviewFixture\(\) \? demoReceiptView\(a\) : rmView\(\)/);
  const view=src.slice(src.indexOf('function rmView()'),src.indexOf('window.v36ReceiptView ='));
  expect(view).not.toMatch(/Peran demo|Uji Fixture|chooseIntakeRole|v36SimulateReceipt/);
});
it('missing amounts render as Belum terverifikasi, never zero',()=>{
  const fn=src.slice(src.indexOf('function rmAmount'),src.indexOf('async function rmLoad'));
  const rmAmount=new Function(`${fn}return rmAmount;`)();
  expect(rmAmount(null)).toBe('Belum terverifikasi');
  expect(rmAmount('')).toBe('Belum terverifikasi');
  expect(rmAmount('abc')).toBe('Belum terverifikasi');
  expect(rmAmount('1500000.00')).toMatch(/^Rp 1[.,]500[.,]000$/);
});
it('payment mutations mark the monitor stale and the list stays read-only',()=>{
  expect(src).toMatch(/taskRequestSequence\+\+;\s*if \(typeof window\.v3PaymentMonitorRefresh === "function"\)/);
  const block=src.slice(src.indexOf('const rm ='),src.indexOf('(async function bootLive'));
  expect(block).not.toMatch(/method:\s*"(POST|PATCH|PUT|DELETE)"/);
});
it('detail opens by official job id from the API, not the Inbox cache, and never invents zero',()=>{
  const open=src.slice(src.indexOf('async function rmOpen'),src.indexOf('function rmView()'));
  expect(open).toContain('jobCache[so] = { id: row.job_id');
  expect(open).toContain('loadBoard(so, true)');
  expect(open).not.toMatch(/v3OpenWorkflow|window\.orders/);
  expect(open).toMatch(/catch \(err\)[\s\S]*toast\(/);
  const row=src.slice(src.indexOf('function rmRowHtml'),src.indexOf('async function rmOpen'));
  expect(row).toContain('Belum ada penerimaan');
  expect(row).toContain('rmAmount(r.verified_amount)');
});
it('states coverage and never labels the verified sum as an official allocation',()=>{
  const view=src.slice(src.indexOf('function rmView()'),src.indexOf('window.v36ReceiptView ='));
  expect(view).toContain('belum menjadi job V3');
  expect(view).toContain('bukan penanda lunas');
  expect(view).not.toMatch(/alokasi/i);
  const open=src.slice(src.indexOf('async function rmOpen'),src.indexOf('function rmView()'));
  expect(open).toContain('Detail Accurate tidak tersedia');
});
