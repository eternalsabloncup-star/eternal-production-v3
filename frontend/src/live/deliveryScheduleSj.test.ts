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
  expect(src).toContain('coverage_label');
  expect(src).toContain('atomic_snapshot_guaranteed');
  expect(src).toContain('full_accurate_sj_universe');
  expect(src).toContain('include_accurate_links=true');
  expect(src).toContain('accurate_sj_list_endpoint');
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

it('Lengkap shows eight Final Delivery columns as Belum terhubung when unlinked', () => {
  expect(src).toContain('Belum terhubung');
  expect(src).toContain('data-del-unlinked="1"');
  expect(src).toContain('data-column="customer_phone"');
  expect(src).toContain('data-column="outlet"');
  expect(src).toContain('data-column="sj_printed_at"');
  expect(src).toContain('data-column="item_outlets"');
  expect(src).toContain('data-column="warehouse_signer"');
  expect(src).toContain('data-column="goods_checker"');
  expect(src).toContain('data-column="courier_signer"');
  expect(src).toContain('data-column="recipient_signer"');
});

it('keeps expedition column separate from Final-8 outlet placeholder', () => {
  expect(src).toContain('data-column="expedition"');
  expect(src).toContain('data-column="outlet"');
  expect(src).toContain('Ekspedisi');
  // Empty Final-8 cells use Belum terhubung — not shipped_at / POD invent.
  expect(src).toMatch(/data-del-unlinked="1">Belum terhubung/);
});
