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
        assert 'Halaman 1 · 32 PO' in text
        assert 'alokasi' not in text.lower() and 'bukan penanda lunas' in text and 'belum menjadi job V3' in text
        checks.append('all POs listed (with and without receipts), 25/page, total 32, no demo role/fixture text')
        await page.click('[data-rm=next]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===7")
        checks.append('pagination next page = 7 rows')
        await page.click('[data-rm=prev]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===25")
        await page.fill('#v3-rm-q', 'SANDBOX-SETTINGS'); await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===1")
        row = await page.inner_text('.v36-table tbody tr')
        assert row.count('Belum ada penerimaan') == 2 and 'Rp' not in row, row
        checks.append('PO without receipt: "Belum ada penerimaan", no fake Rp0')
        await page.fill('#v3-rm-q', 'SANDBOX-PAY-2'); await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===1")
        row = await page.inner_text('.v36-table tbody tr')
        assert 'Belum terverifikasi' in row and 'Rp 0' not in row, row
        await page.click('[data-rm=detail]')
        await page.wait_for_selector('#v3-rm-detail')
        checks.append('null amount shown as Belum terverifikasi + receipt detail')
        # Inbox has no orders in this sandbox, so every PO is outside the Inbox page.
        assert await page.evaluate("(window.orders||[]).length") == 0
        await page.click('[data-rm=open]')
        await page.wait_for_selector('#modal :text("SANDBOX-PAY-2")', timeout=10000)
        assert await page.locator('#modal [data-v3="pay-receipt"]').count() == 1
        drawer = await page.inner_text('#modal')
        assert 'Detail Accurate tidak tersedia' in drawer and 'Qty SO Belum terverifikasi' in drawer, drawer[:300]
        checks.append('Buka PO & Payment works for a PO outside the Inbox page (board by official job id)')
        await page.evaluate("document.getElementById('modal').innerHTML=''")
        await page.fill('#v3-rm-q', 'tidak-ada-data'); await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_selector('text=Tidak ada PO sesuai filter')
        checks.append('empty state')
        await page.evaluate("document.getElementById('v3-rm-q').value='';document.getElementById('v3-rm-has').value='without'")
        await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===1")
        checks.append('filter: without receipts')
        await page.route('**/payment/receipts?*', lambda r: r.fulfill(status=403, body='{"detail":"x"}', content_type='application/json'))
        await page.fill('#v3-rm-q', 'x'); await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_selector('text=Akses ditolak')
        await page.unroute('**/payment/receipts?*')
        checks.append('permission-denied state')
        await page.route('**/jobs/*/board', lambda r: r.fulfill(status=403, body='{"error":{"message":"x"}}', content_type='application/json'))
        await page.evaluate("document.getElementById('v3-rm-has').value=''")
        await page.fill('#v3-rm-q', 'SANDBOX-BULK-01'); await page.click('#v3-rm-form button[type=submit]')
        await page.wait_for_function("document.querySelectorAll('.v36-table tbody tr').length===1")
        await page.click('[data-rm=open]')
        await page.wait_for_selector('#toast:not(.hidden)')
        assert 'ditolak' in (await page.inner_text('#toast')).lower()
        assert await page.locator('#modal [data-v3="pay-receipt"]').count() == 0
        checks.append('403 on per-PO detail shows access denied and does not open the drawer')
        await b.close()
    print(json.dumps({'status': 'PASS', 'checks': checks}, indent=1))
asyncio.run(main())
