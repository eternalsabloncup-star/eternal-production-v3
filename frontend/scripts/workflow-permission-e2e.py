"""Chromium against the explicitly isolated local test fixture; no external requests."""
import asyncio,json,uuid
from urllib.parse import urlsplit
from playwright.async_api import async_playwright,expect
BASE='http://127.0.0.1:5173'
async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        context=await browser.new_context()
        async def local(route):
            if urlsplit(route.request.url).hostname in {'localhost','127.0.0.1'}: await route.continue_()
            else: await route.abort()
        await context.route('**/*',local)
        page=await context.new_page()
        async def login(name,password):
            await page.goto(BASE)
            await page.get_by_label('Username',exact=True).fill(name)
            await page.get_by_label('Password',exact=True).fill(password)
            await page.get_by_role('button',name='Masuk ke Production V49').click()
        await login('sandbox-owner','sandbox-owner-password')
        await expect(page.get_by_role('heading',name='Settings & Permission')).to_be_visible()
        owner=await page.evaluate("localStorage.getItem('epv3_access_token')")
        async def call(path,token=owner,method='GET',body=None):
            return await page.evaluate('''async ([path,token,method,body])=>{const r=await fetch('/api/v1/'+path,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===null?undefined:JSON.stringify(body),cache:'no-store'});return {status:r.status,body:await r.json()};}''',[path,token,method,body])
        async def mutate(path,body,method='POST'):
            rev=(await call('settings/capabilities'))['body']['revision']
            r=await call(path,method=method,body={'revision':rev,'reason':'Isolated Chromium acceptance',**body})
            assert r['status'] in (200,201),r
            return r['body']
        stamp=uuid.uuid4().hex[:8];username='workflow-operator-'+stamp
        user=await mutate('settings/users',{'username':username,'display_name':'Operator test','password':'sandbox-operator-initial'})
        uid=user['user']['id']
        group=await mutate('settings/groups',{'name':'Workflow '+stamp});gid=group['group_id']
        await mutate(f'settings/users/{uid}/memberships',{'group_id':gid,'active':True})
        async def grant(cap,ownership='own'):
            return await mutate(f'settings/groups/{gid}/grants',{'capability':cap,'branches':['SANDBOX-A'],'ownership':ownership,'assignments':[]})
        tg=await grant('task.read');await grant('job.read','all')
        await mutate('production/access/ownership',{'job_id':1,'user_id':uid,'task_kind':'operator','assignment_id':1})
        r=await call('production/jobs',method='POST',body={'accurate_so_number':'SANDBOX-CROSS-'+stamp,'branch_id':'SANDBOX-B'})
        assert r['status'] in (200,201),r
        other=r['body']['id']
        assert (await call(f'production/jobs/{other}'))['status']==200
        await page.get_by_role('button',name='Logout',exact=True).click()
        await login(username,'sandbox-operator-initial')
        await expect(page.get_by_role('heading',name='Ganti password awal')).to_be_visible()
        await page.get_by_label('Password saat ini').fill('sandbox-operator-initial')
        await page.get_by_label('Password baru',exact=True).fill('sandbox-operator-changed')
        await page.get_by_role('button',name='Ganti password dan login ulang').click()
        await expect(page.get_by_role('button',name='Masuk ke Production V49')).to_be_visible()
        await login(username,'sandbox-operator-changed')
        await expect(page.get_by_role('heading',name='Tugas sesuai akses')).to_be_visible()
        await expect(page.get_by_text('SANDBOX-SETTINGS',exact=True)).to_be_visible()
        operator=await page.evaluate("localStorage.getItem('epv3_access_token')")
        rows=(await call('production/access/tasks',operator))['body']['items']
        assert [(r['job_id'],r['assignment_id']) for r in rows]==[(1,1)]
        assert (await call(f'production/jobs/{other}',operator))['status']==403
        assert (await call('settings/users',operator))['status']==403
        await page.get_by_role('button',name='Export tugas').click()
        await expect(page.get_by_role('alert')).to_contain_text('Akses ditolak')
        await grant('task.export')
        async with page.expect_download() as info: await page.get_by_role('button',name='Export tugas').click()
        download=await info.value
        assert download.suggested_filename=='production-task.export.json'
        assert (await call('production/access/documents/job.print',operator))['status']==403
        pg=await grant('job.print')
        assert len((await call('production/access/documents/job.print',operator))['body']['items'])==1
        grants=(await call(f'settings/groups/{gid}/grants'))['body']['items']
        for item in grants:
            if item['capability'] in ('task.read','job.print'):
                await mutate(f"settings/grants/{item['id']}/revoke",{})
        await page.get_by_role('button',name='Muat ulang tugas').click()
        await expect(page.get_by_role('alert')).to_contain_text('Akses ditolak')
        await expect(page.get_by_text('SANDBOX-SETTINGS',exact=True)).to_have_count(0)
        assert (await call('production/access/documents/job.print',operator))['status']==403
        print(json.dumps({'status':'PASS','checks':['Director cross-branch read','Operator stable ownership only','direct API deny','cross-branch deny','manual export download','manual print dataset','same-session allow-to-deny and stale UI removal'],'production_cutover':'HELD; test fixture only'}))
        await browser.close()
asyncio.run(main())
