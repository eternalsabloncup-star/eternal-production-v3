"""Chromium E2E for Monitoring Penerimaan against a disposable local backend (fixture receipts, no Accurate)."""
import asyncio, json
from playwright.async_api import async_playwright
BASE = 'http://127.0.0.1:5173'

async def main():
    checks = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        page = await b.new_page()
        await page.goto(BASE)
        await page.fill('input[autocomplete="username"], input[name=username], input:not([type=password])', 'sandbox-owner')
        await page.fill('input[type=password]', 'sandbox-owner-password')
        await page.click('button[type=submit]')
        await page.wait_for_selector('text=Logout')
        await page.goto(BASE + '/production.html')
        await page.wait_for_selector('#v3-app', timeout=20000)
        await page.evaluate("go('paymentMonitor')")
        await page.wait_for_selector('.v36-table tbody tr', timeout=15000)
        text = await page.inner_text('.content')
        assert 'Peran demo' not in text and 'Fixture' not in text and 'demo' not in text.lower().replace('demo browser', ''), text[:400]
        assert await page.locator('.v36-table tbody tr').count() == 25
        assert 'Halaman 1 · 31 penerimaan' in text
        checks.append('official list, 25/page, total 31, no demo role/fixture text')
        await page.click('[data-rm=next]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===6")
        checks.append('pagination next page = 6 rows')
        await page.click('[data-rm=prev]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===25")
        await page.fill('#v3-rm-q', 'SANDBOX-PAY-2'); await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===1")
        row = await page.inner_text('.v36-table tbody tr')
        assert 'Belum terverifikasi' in row and 'Rp 0' not in row, row
        checks.append('search + null amount shown as Belum terverifikasi (no fake zero)')
        await page.click('[data-rm=detail]')
        await page.wait_for_selector('#v3-rm-detail')
        checks.append('detail panel')
        await page.fill('#v3-rm-q', 'tidak-ada-data'); await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_selector('text=Belum ada penerimaan tercatat')
        checks.append('empty state')
        await page.evaluate("document.getElementById('v3-rm-q').value='';document.getElementById('v3-rm-pay').value='approved'")
        await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===25")
        checks.append('status filter approved')
        await page.route('**/payment/receipts?*', lambda r: r.fulfill(status=403, body='{"detail":"x"}', content_type='application/json'))
        await page.fill('#v3-rm-q', 'x'); await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_selector('text=Akses ditolak')
        checks.append('permission-denied state')
        await b.close()
    print(json.dumps({'status': 'PASS', 'checks': checks}, indent=1))
asyncio.run(main())
