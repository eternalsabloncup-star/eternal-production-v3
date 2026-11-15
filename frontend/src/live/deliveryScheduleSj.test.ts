import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';

const src = readFileSync('public/live-runtime.js', 'utf8');

it('shipping schedule is SJ-centric with search, detail, and no Accurate write on view', () => {
  expect(src).toContain('/production/ops/deliveries?');
  expect(src).toContain('/production/ops/deliveries/');
  expect(src).toContain('satu baris per SJ');
  expect(src).toContain('No. SJ');
  expect(src).toContain('BELUM TERSEDIA');
  expect(src).toContain('data-ops="sj-detail"');
  expect(src).toContain('v3-del-form');
  expect(src).toContain('accurate_write_on_view=false');
  const block = src.slice(
    src.indexOf('guardDemoView("shippingScheduleView"'),
    src.indexOf('guardDemoView("salarySlipView"')
  );
  expect(block).not.toMatch(/method:\s*"(POST|PUT|PATCH|DELETE)"/);
});
