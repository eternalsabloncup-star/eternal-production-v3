import {readFileSync} from 'node:fs';
import {expect,it,vi} from 'vitest';
const source=readFileSync('public/workflow-documents.js','utf8');
// Actual public script, with network/DOM doubles only.
it.each(['exportSheet','taskExportCsv','exportProductionReport','printSalarySlip'])('%s never invokes a legacy handler in enforced mode',async(name)=>{
  const old=vi.fn(),toast=vi.fn(), win:any={[name]:old,toast};
  const fetch=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({workflow_authorization:'enforced'})}).mockResolvedValue({ok:false,status:403});
  new Function('window','fetch','localStorage',source)(win,fetch,{getItem:()=> 'test'});
  await win[name]();expect(old).not.toHaveBeenCalled();expect(toast).toHaveBeenCalled();
  if(name!=='printSalarySlip') expect(fetch.mock.calls[1][0]).toContain('/production/access/documents/');
});
