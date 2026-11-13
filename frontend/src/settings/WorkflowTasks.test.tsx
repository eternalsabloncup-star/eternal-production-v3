// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkflowTasks } from './WorkflowTasks';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('clears previously visible assignments after revocation and rejects export',async()=>{
  const fetch=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({items:[{job_id:1,assignment_id:2,branch_id:'A',so_number:'OWN-SO',qty_planned:'10',payment_status:'pending',design_status:'pending'}]})}).mockResolvedValue({ok:false,status:403});
  vi.stubGlobal('fetch',fetch);render(<WorkflowTasks/>);
  await screen.findByText('OWN-SO');fireEvent.click(screen.getByText('Muat ulang tugas'));
  await screen.findByRole('alert');expect(screen.queryByText('OWN-SO')).toBeNull();
  fireEvent.click(screen.getByText('Export tugas'));
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(3));
  expect(fetch.mock.calls[2][0]).toContain('documents/task.export');
});
