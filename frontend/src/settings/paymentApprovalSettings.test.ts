import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';

const src = readFileSync('public/live-runtime.js', 'utf8');
const html = readFileSync('public/production.html', 'utf8');

it('wires Approval Payment settings to PostgreSQL endpoints, not localStorage', () => {
  expect(src).toContain('/production/settings/payment-approval');
  expect(src).toContain('method: "PUT"');
  expect(src).toContain('v3PaymentApprovalSettingsView');
  expect(src).toMatch(/Preview\/fixture[\s\S]*tidak dipakai/);
  const block = src.slice(
    src.indexOf('const PAY_SETTING_FIELDS'),
    src.indexOf('(async function bootLive')
  );
  expect(block).not.toMatch(/localStorage\.setItem/);
  expect(block).toContain('bypass_enabled');
  expect(block).toContain('payment-approval/audit');
});

it('settings page exposes Approval Payment tab and Live SoT label', () => {
  expect(html).toContain("['payment','Approval Payment']");
  expect(html).toContain('v3PaymentApprovalSettingsView');
  expect(html).toContain('LIVE · POSTGRESQL V3');
});

it('monitor distinguishes gate approval_source from financial UNKNOWN', () => {
  expect(src).toContain('financial_payment_status');
  expect(src).toContain('approval_source');
  expect(src).toContain('can_bypass');
  expect(src).toContain('Status finansial:');
});
