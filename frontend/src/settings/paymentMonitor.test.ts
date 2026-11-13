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
