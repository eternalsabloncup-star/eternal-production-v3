import { useEffect, useState } from "react";
import { getApiBaseUrl } from "../api/client";

type Task = {job_id:number;assignment_id:number|null;branch_id:string;so_number:string;qty_planned:string|null;payment_status:string;design_status:string};
export function WorkflowTasks() {
  const [items,setItems]=useState<Task[]>([]), [error,setError]=useState("");
  async function request(path:string) {
    const response=await fetch(`${getApiBaseUrl()}/production/access/${path}`, {headers:{Authorization:`Bearer ${localStorage.getItem("epv3_access_token")||""}`},cache:"no-store"});
    if(!response.ok) throw new Error(response.status===403?"Akses ditolak. Permission atau penugasan tidak berlaku.":"Data tugas tidak dapat dimuat.");
    return response.json();
  }
  async function refresh() {
    setItems([]);setError("");
    try {setItems((await request("tasks")).items);} catch(e) {setError((e as Error).message);}
  }
  async function document(kind:string) {
    setError("");
    try {
      const data=await request(`documents/${kind}`);
      const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
      const url=URL.createObjectURL(blob),link=window.document.createElement("a");
      link.href=url;link.download=`production-${kind}.json`;link.click();URL.revokeObjectURL(url);
    } catch(e) {setError((e as Error).message);}
  }
  useEffect(()=>{void refresh();},[]);
  return <main className="shell"><h1>Tugas sesuai akses</h1>
    <button onClick={()=>void refresh()}>Muat ulang tugas</button>
    <button onClick={()=>void document("task.export")}>Export tugas</button>
    {error&&<p role="alert">{error}</p>}
    <table><thead><tr><th>SO</th><th>Cabang</th><th>Assignment ID</th><th>Qty rencana</th><th>Payment</th><th>Design</th></tr></thead>
    <tbody>{items.map(t=><tr key={`${t.job_id}-${t.assignment_id}`}><td>{t.so_number}</td><td>{t.branch_id}</td><td>{t.assignment_id??"—"}</td><td>{t.qty_planned??"—"}</td><td>{t.payment_status}</td><td>{t.design_status}</td></tr>)}</tbody></table>
  </main>;
}
