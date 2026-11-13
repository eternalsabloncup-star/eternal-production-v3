import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
const source = readFileSync('public/live-runtime.js', 'utf8');
function extract(start: string, end: string) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))); }
function harness(request: ReturnType<typeof vi.fn>) {
  const w = { orders: [{ id: 'A', branchId: 'BR', design_status: 'approved', v3JobId: 1 }], render: vi.fn(), __V3_OFFICIAL_TASKS__: [] };
  const run = new Function('request', 'window', `
    const API='/api/v1'; let paymentEpoch=0, taskRequestSequence=0, selectedSo='A';
    let boardCache={A:{job:{id:1,payment_status:'approved'}}}, jobCache={A:{id:1,payment_status:'approved'}};
    const boardRequestSequence=Object.create(null); const inFlight=new Set(), messages=[], drawers=[];
    const toast=m=>messages.push(m), orderBySo=so=>window.orders.find(o=>o.id===so);
    const snapshotDeliveryDraft=()=>({}), restoreDeliveryDraft=()=>{}, renderWorkflowDrawer=so=>drawers.push(so);
    const mergeAuthorityRows=a=>a, authorityOverlay={}, applyBoardToOrder=()=>{};
    const mapOfficialTaskRows=rows=>rows;
    ${extract('  function syncOrderGatesFromJob(', '  async function lookupJob(')}
    ${extract('  async function lookupJob(', '  async function createJob(')}
    ${extract('  async function loadBoard(', '  const DELIVERY_DRAFT_IDS')}
    ${extract('  async function refreshOfficialTasks(', '  window.v50RefreshInbox')}
    return {mutate,loadBoard,lookupJob,refreshOfficialTasks,window,messages,drawers,
      select:so=>selectedSo=so, state:()=>({boardCache,jobCache})};
  `);
  return run(request, w);
}
const tasks = (status: string) => ({source: 'v3_official', tasks: [{payment_status: status}], jobs: [{id:1,accurate_so_number:'A',payment_status:status}]});
const board = (status: string) => ({job:{id:1,payment_status:status}});

describe('actual live-runtime payment refresh functions', () => {
  it('refreshes tasks read-only and the affected board when selection changes', async () => {
    const request = vi.fn(async (path: string) => path.endsWith('/tasks') ? tasks('pending') : board('pending'));
    const h = harness(request);
    await h.mutate('pay:A', async () => { h.select('B'); }, {payment:true, so:'A'});
    expect(h.state().jobCache.A.payment_status).toBe('pending');
    expect(h.window.__V3_OFFICIAL_TASKS__[0].payment_status).toBe('pending');
    expect(h.drawers).not.toContain('B');
    expect((request.mock.calls.find(call=>call[0].endsWith('/tasks')) as any)[1].body.sync_ensure).toBe(false);
  });
  it('does not retain approved caches after refresh failure', async () => {
    const h = harness(vi.fn(async () => { throw new Error('offline'); }));
    await expect(h.mutate('pay:A', async()=>{}, {payment:true,so:'A'})).rejects.toThrow('offline');
    expect(h.state().boardCache.A).toBeUndefined();
    expect(h.state().jobCache.A).toBeUndefined();
    expect(h.window.__V3_OFFICIAL_TASKS__).toEqual([]);
    expect(h.window.orders[0].approval).toBe(false);
    expect(h.messages.join(' ')).toContain('Payment tersimpan; refresh gagal');
  });
  it('rejects stale task responses from before a payment mutation', async () => {
    let release!: (value: unknown)=>void; let count=0;
    const request = vi.fn(async (path: string) => {
      if (path.endsWith('/tasks') && count++===0) return new Promise(resolve=>{ release=resolve; });
      return path.endsWith('/tasks') ? tasks('pending') : board('pending');
    });
    const h=harness(request); const old=h.refreshOfficialTasks();
    await h.mutate('pay:A',async()=>{}, {payment:true,so:'A'});
    release(tasks('approved')); await old;
    expect(h.state().jobCache.A.payment_status).toBe('pending');
    expect(h.window.__V3_OFFICIAL_TASKS__[0].payment_status).toBe('pending');
  });
  it('refreshes an open drawer when external task refresh observes a changed gate', async()=>{
    const h=harness(vi.fn(async (path:string)=>path.endsWith('/tasks')?tasks('pending'):board('pending')));
    await h.refreshOfficialTasks(undefined,true);
    expect(h.state().boardCache.A.job.payment_status).toBe('pending');
    expect(h.drawers).toContain('A');
  });
  it('discards a stale board response after payment mutation',async()=>{
    let release!: (value: unknown)=>void; let count=0;
    const h=harness(vi.fn(async(path:string)=> {
      if(path.endsWith('/board') && count++===0) return new Promise(resolve=>{release=resolve;});
      return path.endsWith('/tasks')?tasks('pending'):board('pending');
    }));
    const old=h.loadBoard('A',true);
    await h.mutate('pay:A',async()=>{}, {payment:true,so:'A'});
    release(board('approved')); await old;
    expect(h.state().boardCache.A.job.payment_status).toBe('pending');
  });
});

it('rejects an old board after an external task refresh in the same epoch',async()=>{
  let release!: (value: unknown)=>void; let count=0;
  const h=harness(vi.fn(async(path:string)=> {
    if(path.endsWith('/board') && count++===0) return new Promise(resolve=>{release=resolve;});
    return path.endsWith('/tasks')?tasks('pending'):board('pending');
  }));
  const old=h.loadBoard('A',true);
  await h.refreshOfficialTasks(undefined,true);
  release(board('approved')); await old;
  expect(h.state().boardCache.A.job.payment_status).toBe('pending');
});

it('rejects a stale job lookup after payment refresh',async()=>{
  let release!: (value: unknown)=>void;
  const h=harness(vi.fn(async(path:string)=> {
    if(path.includes('/by-so/')) return new Promise(resolve=>{release=resolve;});
    return path.endsWith('/tasks')?tasks('pending'):board('pending');
  }));
  const old=h.lookupJob('A');
  await h.mutate('pay:A',async()=>{}, {payment:true,so:'A'});
  release({id:1,payment_status:'approved'}); await old;
  expect(h.state().jobCache.A.payment_status).toBe('pending');
});

it('clears stale approval when the payment response is lost after a possible commit',async()=>{
  const h=harness(vi.fn());
  await expect(h.mutate('pay:A',async()=>{throw new Error('response lost');},{payment:true,so:'A'})).rejects.toThrow('response lost');
  expect(h.state().jobCache.A).toBeUndefined();
  expect(h.state().boardCache.A).toBeUndefined();
  expect(h.window.orders[0].approval).toBe(false);
  expect(h.drawers).toContain('A');
});
