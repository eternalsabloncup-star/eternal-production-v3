"""Chromium against a seeded, migrated LOCAL Settings sandbox only.

Provision epv3_settings_e2e_test and an explicitly attested sandbox-owner first.
Does not bootstrap, reset, migrate, or access an external application itself.
Requires playwright and a local /usr/bin/chromium. No Live credentials accepted.
"""
import asyncio
import json
import uuid
import re
from pathlib import Path
from playwright.async_api import async_playwright, expect

BASE = 'http://127.0.0.1:5173'
RUN = uuid.uuid4().hex[:8]
OPERATOR = 'sandbox-operator-' + RUN
GROUP = 'Sandbox Operator Group ' + RUN

async def main():
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
        context = await browser.new_context()
        async def local_only(route):
            from urllib.parse import urlsplit
            host = urlsplit(route.request.url).hostname
            if host in {'127.0.0.1','localhost'}: await route.continue_()
            else: await route.abort()
        await context.route('**/*', local_only)
        page = await context.new_page()
        page.on('dialog', lambda dialog: asyncio.create_task(dialog.accept()))
        await page.goto(BASE)
        await page.get_by_label('Username',exact=True).fill('sandbox-owner')
        await page.get_by_label('Password',exact=True).fill('sandbox-owner-password')
        await page.get_by_role('button',name='Masuk ke Production V49').click()
        await expect(page.get_by_role('heading',name='Settings & Permission')).to_be_visible()
        results.append('PASS Director login and active Settings')
        await page.get_by_label('Alasan perubahan').fill('Sandbox E2E review')
        await page.get_by_label('Username',exact=True).fill(OPERATOR)
        await page.get_by_label('Nama tampilan').fill('Sandbox Operator')
        await page.get_by_label('Password awal').fill('sandbox-operator-initial')
        await page.get_by_role('button',name='Simpan pengguna',exact=True).click()
        await expect(page.get_by_role('button',name='Edit ' + OPERATOR,exact=True)).to_be_visible()
        results.append('PASS create operator with initial password')
        await page.get_by_role('button',name='Grup & Permission',exact=True).click()
        await page.get_by_label('Nama grup baru').fill(GROUP)
        await page.get_by_role('button',name='Buat grup tanpa izin').click()
        await expect(page.get_by_role('status')).to_contain_text('tersimpan')
        await page.get_by_label('Grup akses').select_option(label=GROUP)
        await expect(page.get_by_label('Cabang (pisahkan koma)')).to_be_enabled()
        assert await page.get_by_role('checkbox').evaluate_all('(nodes)=>nodes.every(n=>!n.checked)')
        await page.get_by_label('Cabang (pisahkan koma)').fill('SANDBOX-A')
        await page.get_by_role('combobox',name=re.compile('^Ownership')).select_option('selected')
        await page.get_by_label('ID assignment (pisahkan koma)').fill('1')
        await page.get_by_role('checkbox',name='task.read (read; branch)',exact=True).check()
        await page.get_by_role('button',name='Berikan permission terpilih').click()
        await expect(page.get_by_role('button',name='Cabut task.read')).to_be_visible()
        results.append('PASS default-deny group, manual grant, branch and existing assignment scope')
        await page.get_by_role('button',name='Pengguna',exact=True).click()
        await page.get_by_role('button',name='Edit ' + OPERATOR,exact=True).click()
        await page.get_by_label('Membership grup').select_option(label=GROUP)
        await page.get_by_role('button',name='Simpan membership').click()
        await expect(page.get_by_role('status')).to_contain_text('tersimpan')
        await page.get_by_role('button',name='Logout',exact=True).click()
        await page.get_by_label('Username',exact=True).fill(OPERATOR)
        await page.get_by_label('Password',exact=True).fill('sandbox-operator-initial')
        await page.get_by_role('button',name='Masuk ke Production V49').click()
        await expect(page.get_by_role('heading',name='Ganti password awal')).to_be_visible()
        denied = await page.evaluate("""async()=> (await fetch('/api/v1/production/jobs/tasks',{headers:{Authorization:'Bearer '+localStorage.getItem('epv3_access_token')}})).status""")
        assert denied == 403
        await page.get_by_label('Password saat ini').fill('sandbox-operator-initial')
        await page.get_by_label('Password baru',exact=True).fill('sandbox-operator-changed')
        await page.get_by_role('button',name='Ganti password dan login ulang').click()
        await expect(page.get_by_role('button',name='Masuk ke Production V49')).to_be_visible()
        await page.get_by_label('Username',exact=True).fill(OPERATOR)
        await page.get_by_label('Password',exact=True).fill('sandbox-operator-changed')
        await page.get_by_role('button',name='Masuk ke Production V49').click()
        await expect(page.get_by_role('heading',name='Akun aktif')).to_be_visible()
        denied = await page.evaluate("""async()=> (await fetch('/api/v1/settings/users',{headers:{Authorization:'Bearer '+localStorage.getItem('epv3_access_token')}})).status""")
        assert denied == 403
        results.append('PASS mandatory first-password change, relogin, unauthorized direct API denial')
        results.append('BLOCKED workflow capability activation/cross-assignment enforcement: cutover held')
        await page.get_by_role('button',name='Logout',exact=True).click()
        await page.get_by_label('Username',exact=True).fill('sandbox-owner')
        await page.get_by_label('Password',exact=True).fill('sandbox-owner-password')
        await page.get_by_role('button',name='Masuk ke Production V49').click()
        await expect(page.get_by_role('heading',name='Settings & Permission')).to_be_visible()
        await page.get_by_label('Alasan perubahan').fill('Sandbox revoke')
        await page.get_by_role('button',name='Grup & Permission',exact=True).click()
        await page.get_by_label('Grup akses').select_option(label=GROUP)
        await page.get_by_role('button',name='Cabut task.read').click()
        await expect(page.get_by_role('button',name='Cabut task.read')).to_have_count(0)
        await page.get_by_role('button',name='Effective Access',exact=True).click()
        await page.get_by_label('Pengguna untuk preview').select_option(label=OPERATOR)
        await page.get_by_role('button',name='Lihat akses efektif').click()
        await expect(page.locator('pre')).to_contain_text('"grants": []')
        await page.get_by_role('button',name='Audit',exact=True).click()
        await page.get_by_role('button',name='Muat audit',exact=True).click()
        await expect(page.locator('pre')).to_contain_text('grant.revoke')
        results.append('PASS revoke persisted grant, immediate effective-access update and audit')
        results.append('BLOCKED workflow allow-to-deny browser scenario until cutover')
        await browser.close()
    print(json.dumps(results,indent=2))

asyncio.run(main())
