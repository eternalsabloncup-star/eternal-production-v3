import {readFileSync} from 'node:fs';
import {expect, it} from 'vitest';

const src = readFileSync('public/live-runtime.js', 'utf8');
const html = readFileSync('public/production.html', 'utf8');

it('payment monitor has sticky sheet, sort, column toggle, and internal scroll', () => {
  expect(src).toContain('v3-payment-sheet');
  expect(src).toContain('data-v3-sticky="so,customer"');
  expect(src).toContain('data-rm="sort"');
  expect(src).toContain('v3-rm-col-toggles');
  expect(src).toContain('v3-rm-scroll');
  expect(html).toContain('v3-payment-sheet');
  expect(html).toContain("return['so','customer']");
});

it('kontrol produksi labels qty consistently and exposes status kerja', () => {
  expect(src).toContain('Total Qty SO (Cetak)');
  expect(src).toContain('Qty Sudah Dicetak');
  expect(src).toContain('Qty Belum Selesai');
  expect(src).toContain('v3-status-kerja');
  expect(src).toContain('anti double-count multi-operator');
});
