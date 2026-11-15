import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';

const src = readFileSync('public/live-runtime.js', 'utf8');
const html = readFileSync('public/production.html', 'utf8');

it('shipping schedule is SJ-centric with search, detail, and no Accurate write on view', () => {
  expect(src).toContain('/production/ops/deliveries?');
  expect(src).toContain('/production/ops/deliveries/');
  expect(src).toContain('satu baris per SJ');
  expect(src).toContain('No. SJ');
  expect(src).toContain('BELUM TERSEDIA');
  expect(src).toContain('data-ops="sj-detail"');
  expect(src).toContain('v3-del-form');
  expect(src).toContain('accurate_write_on_view');
  const block = src.slice(
    src.indexOf('guardDemoView("shippingScheduleView"'),
    src.indexOf('guardDemoView("salarySlipView"')
  );
  expect(block).not.toMatch(/method:\s*"(POST|PUT|PATCH|DELETE)"/);
});

it('shipping schedule exposes pagination, coverage, sticky columns, and column toggles', () => {
  expect(src).toContain('COVERAGE TERBATAS');
  expect(src).toContain('include_accurate_links=true');
  expect(src).toContain('data-ops="del-prev"');
  expect(src).toContain('data-ops="del-next"');
  expect(src).toContain('data-ops="del-sort"');
  expect(src).toContain('v3-delivery-sheet');
  expect(src).toContain('data-v3-sticky="sj,so"');
  expect(src).toContain('v3-del-col-toggles');
  expect(src).toContain('inventory_source');
  expect(html).toContain('v3-delivery-sheet');
  expect(html).toContain("return['sj','so']");
});
