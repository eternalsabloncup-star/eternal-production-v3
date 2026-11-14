/** Settings UI; runtime access is determined by /auth/me and backend authorization. */
import { FormEvent, useEffect, useState } from "react";
import type { SettingsApi } from "./api";
import "./settings.css";

type User = { id: number; username: string; display_name: string; is_active: boolean };
type Group = { id: number; name: string; system: boolean; active: boolean };
type Capability = { code: string; module: string; scope: string; action: string };
type Listing<T> = { revision: number; items: T[] };
type Mutation = { revision: number };
type GrantRow = { id: number; capability: string; branches: string[]; ownership: string; assignments: number[]; active: boolean };
const fields = (event: FormEvent<HTMLFormElement>) => {
  event.preventDefault();
  return new FormData(event.currentTarget);
};
const text = (data: FormData, name: string) => String(data.get(name) ?? "");

export function SettingsPanel({ api, runtime = false, workflowAuthorization = "legacy", confirmAction = window.confirm.bind(window) }: {
  api: SettingsApi; runtime?: boolean; workflowAuthorization?: string; confirmAction?: (message: string) => boolean;
}) {
  const [users, setUsers] = useState<User[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [catalog, setCatalog] = useState<Capability[]>([]);
  const [revision, setRevision] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [tab, setTab] = useState("Pengguna");
  const [selected, setSelected] = useState<User | null>(null);
  const [groupId, setGroupId] = useState("");
  const [checked, setChecked] = useState<string[]>([]);
  const [grants, setGrants] = useState<GrantRow[]>([]);
  const [preview, setPreview] = useState<unknown>(null);
  const [audit, setAudit] = useState<unknown[]>([]);
  const [auditPage, setAuditPage] = useState(0);
  const [query, setQuery] = useState("");
  const [reason, setReason] = useState("");
  const [scope, setScope] = useState("");
  const [ownership, setOwnership] = useState("all");
  const [assignmentIds, setAssignmentIds] = useState("");
  const [authStatus, setAuthStatus] = useState<{ active_now?: boolean; blockers?: string[]; branch_management?: string; workflow_authorization?: string } | null>(null);

  async function refresh() {
    const [u, g, c] = await Promise.all([
      api.request<Listing<User>>(`/users?q=${encodeURIComponent(query)}`),
      api.request<Listing<Group>>("/groups"), api.request<Listing<Capability>>("/capabilities"),
    ]);
    setUsers(u.items); setGroups(g.items); setCatalog(c.items);
    setRevision(Math.min(u.revision, g.revision, c.revision));
    setPreview(null);
    if (runtime) {
      try { setAuthStatus(await api.request("/authorization-status")); }
      catch { /* status panel is advisory; keep account management usable */ }
    }
  }
  useEffect(() => {
    let cancelled = false;
    Promise.all([api.request<Listing<User>>("/users"), api.request<Listing<Group>>("/groups"), api.request<Listing<Capability>>("/capabilities")])
      .then(([u, g, c]) => { if (!cancelled) { setUsers(u.items); setGroups(g.items); setCatalog(c.items); setRevision(Math.min(u.revision, g.revision, c.revision)); } })
      .catch(e => { if (!cancelled) setError(String(e.message)); });
    if (runtime) {
      api.request<{ active_now?: boolean; blockers?: string[]; branch_management?: string; workflow_authorization?: string }>("/authorization-status")
        .then(s => { if (!cancelled) setAuthStatus(s); })
        .catch(() => { /* advisory */ });
    }
    return () => { cancelled = true; };
  }, [api, runtime]);

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "Permintaan gagal"); }
    finally { setBusy(false); }
  }
  async function mutate(path: string, payload: object, method?: string) {
    if (revision === null || !reason.trim()) throw new Error("Alasan perubahan wajib diisi; muat akses terlebih dahulu.");
    if (!confirmAction("Simpan perubahan akses atau akun ini?")) return;
    const result = await api.request<Mutation>(path, { ...payload, revision, reason }, method);
    setRevision(result.revision);
    setMessage("Perubahan tersimpan di API.");
    try { await refresh(); } catch { setError("Perubahan tersimpan, tetapi refresh gagal. Muat ulang sebelum tindakan berikutnya."); setRevision(null); }
  }
  async function loadGrants(id: string) {
    setGrants([]);
    if (id) setGrants((await api.request<Listing<GrantRow>>(`/groups/${id}/grants`)).items);
  }
  const chosenGroup = groups.find(g => String(g.id) === groupId);
  const mode = authStatus?.workflow_authorization || workflowAuthorization;
  const enforcedActive = mode === "enforced" || authStatus?.active_now === true;
  return <section className="shell settings-panel">
    <header><h1 className="brand">Settings & Permission</h1><p className="meta">{runtime
      ? (enforcedActive
        ? "Mode enforced AKTIF: grant Settings memutus akses produksi. Menu Pengguna, Grup, Cabang (via grant), Effective Access, dan Audit tetap tersedia."
        : "Mode legacy AKTIF: workflow memakai izin legacy. Panel ini tetap mengelola akun/grup/grant; grant produksi belum memutus akses sampai cutover disetujui.")
      : "Komponen terisolasi — belum aktif pada navigasi ERP V3."}</p></header>
    {runtime && <section className="flat-notice" data-testid="authorization-status" data-mode={mode}>
      <b>Status otorisasi workflow: {mode.toUpperCase()}</b>
      <p>{authStatus?.branch_management || "Cabang dikelola sebagai ID eksplisit pada grant grup (bukan master cabang terpisah)."}</p>
      {!!authStatus?.blockers?.length && <ul>{authStatus.blockers.map(b => <li key={b}>{b}</li>)}</ul>}
      {!enforcedActive && <p>Aktivasi enforced memerlukan inventory clear, mapping Owner, V3_WORKFLOW_ENFORCED_APPROVAL_REF, lalu deploy terpisah — bukan dari tombol di panel ini.</p>}
    </section>}
    <nav aria-label="Settings">{["Pengguna", "Grup & Permission", "Effective Access", "Audit"].map(name => <button key={name} aria-pressed={tab === name} onClick={() => setTab(name)}>{name}</button>)}</nav>
    <p role="status">{message}</p>{error && <p role="alert" className="status__error">{error}</p>}
    <label>Alasan perubahan<input value={reason} onChange={e => setReason(e.target.value)} maxLength={500} /></label>
    <button disabled={busy} onClick={() => void run(refresh)}>Muat ulang akses</button>
    <fieldset disabled={busy || revision === null}>
    {tab === "Pengguna" && <>
      <form onSubmit={e => { e.preventDefault(); void run(refresh); }}><label>Cari username<input value={query} onChange={e => setQuery(e.target.value)} /></label><button>Cari</button></form>
      <table><thead><tr><th>Username</th><th>Nama</th><th>Status</th><th>Tindakan</th></tr></thead><tbody>{users.map(u => <tr key={u.id}><td>{u.username}</td><td>{u.display_name}</td><td>{u.is_active ? "Aktif" : "Nonaktif"}</td><td><button onClick={() => setSelected(u)}>Edit {u.username}</button><button onClick={() => void run(() => mutate(`/users/${u.id}/active`, { active: !u.is_active }))}>{u.is_active ? "Nonaktifkan" : "Aktifkan"} {u.username}</button></td></tr>)}</tbody></table>
      <h2>{selected ? `Edit ${selected.username}` : "Tambah pengguna"}</h2>
      <form className="login" key={selected?.id ?? "new"} onSubmit={e => {
        const form = e.currentTarget; const data = fields(e);
        const payload = { username: text(data, "username"), display_name: text(data, "display_name"), ...(selected ? {} : { password: text(data, "password") }) };
        const password = form.elements.namedItem("password") as HTMLInputElement | null;
        if (password) password.value = "";
        void run(() => mutate(selected ? `/users/${selected.id}` : "/users", payload, selected ? "PATCH" : "POST"));
      }}>
        <label>Username<input name="username" defaultValue={selected?.username ?? ""} required maxLength={64} autoComplete="off" /></label>
        <label>Nama tampilan<input name="display_name" defaultValue={selected?.display_name ?? ""} required maxLength={120} /></label>
        {!selected && <label>Password awal<input name="password" type="password" minLength={12} maxLength={200} required autoComplete="new-password" /></label>}
        <button>Simpan pengguna</button><button type="button" onClick={() => setSelected(null)}>Form pengguna baru</button>
      </form>
      {selected && <>
        <form className="login" onSubmit={e => { const data = fields(e); (e.currentTarget.elements.namedItem("password") as HTMLInputElement).value = ""; void run(() => mutate(`/users/${selected.id}/password-reset`, { password: text(data, "password") })); }}>
          <label>Password sementara baru<input name="password" type="password" minLength={12} maxLength={200} required autoComplete="new-password" /></label><button>Reset password</button>
        </form><button onClick={() => void run(() => mutate(`/users/${selected.id}/password-reset`, {}))}>Wajibkan ganti password</button>
        <form onSubmit={e => { const data = fields(e); void run(() => mutate(`/users/${selected.id}/memberships`, { group_id: Number(text(data, "group")), active: text(data, "active") === "true" })); }}>
          <label>Membership grup<select name="group" required>{groups.filter(g => g.active).map(g => <option key={g.id} value={g.id}>{g.name}{g.system ? " — System Full Access" : ""}</option>)}</select></label>
          <label>Tindakan membership<select name="active"><option value="true">Berikan</option><option value="false">Cabut</option></select></label><button>Simpan membership</button>
        </form>
      </>}
    </>}
    {tab === "Grup & Permission" && <>
      <form onSubmit={e => { const data = fields(e); void run(() => mutate("/groups", { name: text(data, "name") })); }}><label>Nama grup baru<input name="name" required maxLength={120} /></label><button>Buat grup tanpa izin</button></form>
      <label>Grup akses<select value={groupId} onChange={e => { setGroupId(e.target.value); setChecked([]); void run(() => loadGrants(e.target.value)); }}><option value="">Pilih grup</option>{groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
      {chosenGroup?.system ? <p>System privilege terlindungi: Direktur Full Access.</p> : chosenGroup && <>
        <label>Cabang (pisahkan koma)<input value={scope} onChange={e => setScope(e.target.value)} /></label>
        <label>Ownership<select value={ownership} onChange={e => setOwnership(e.target.value)}><option value="all">Dalam scope cabang</option><option value="own">Assignment sendiri</option><option value="selected">Assignment terpilih</option></select></label>
        {ownership === "selected" && <label>ID assignment (pisahkan koma)<input value={assignmentIds} onChange={e => setAssignmentIds(e.target.value)} /></label>}
        {Array.from(new Set(catalog.map(c => c.module))).filter(m => m !== "settings").map(module => <fieldset key={module}><legend>{module}</legend>{catalog.filter(c => c.module === module).map(c => <label key={c.code}><input type="checkbox" checked={checked.includes(c.code)} onChange={e => setChecked(prev => e.target.checked ? [...prev, c.code] : prev.filter(x => x !== c.code))} />{c.code} ({c.action}; {c.scope})</label>)}</fieldset>)}
        <button disabled={!checked.length} onClick={() => void run(async () => {
          if (!reason.trim() || revision === null) throw new Error("Alasan perubahan wajib diisi.");
          if (!confirmAction(`Berikan ${checked.length} grant? Setiap grant disimpan terpisah.`)) return;
          let current = revision; let completed = 0; let problem = "";
          try {
            for (const code of checked) {
              const global = catalog.find(c => c.code === code)?.scope === "global";
              const response = await api.request<Mutation>(`/groups/${groupId}/grants`, { revision: current, reason, capability: code, branches: global ? [] : scope.split(",").map(s => s.trim()).filter(Boolean), ownership: global ? "all" : ownership, assignments: !global && ownership === "selected" ? assignmentIds.split(",").map(Number) : [] });
              current = response.revision; completed++;
            }
          } catch (e) { problem = e instanceof Error ? e.message : "Gagal"; }
          setChecked(checked.slice(completed)); setRevision(current);
          if (completed) setMessage(`${completed} grant tersimpan di API.`);
          try { await refresh(); await loadGrants(groupId); }
          catch { setRevision(null); problem += " Refresh gagal; muat ulang sebelum tindakan berikutnya."; }
          if (problem) throw new Error(`${completed} grant tersimpan; ${checked.length - completed} belum disimpan. ${problem}`);
        })}>Berikan permission terpilih</button>
        <ul>{grants.filter(g => g.active).map(g => <li key={g.id}>{g.capability} — {g.branches.join(", ") || "global"} — {g.ownership}<button onClick={() => void run(async () => { await mutate(`/grants/${g.id}/revoke`, {}); await loadGrants(groupId); })}>Cabut {g.capability}</button></li>)}</ul>
      </>}
    </>}
    {tab === "Effective Access" && <><form onSubmit={e => { const data = fields(e); void run(async () => setPreview(await api.request(`/users/${text(data, "user")}/effective-access`))); }}><label>Pengguna untuk preview<select name="user">{users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}</select></label><button>Lihat akses efektif</button></form><pre>{preview ? JSON.stringify(preview, null, 2) : "Pilih pengguna untuk membaca akses dari backend."}</pre></>}
    {tab === "Audit" && <><button onClick={() => void run(async () => { setAudit((await api.request<Listing<unknown>>("/access-audit")).items); setAuditPage(0); })}>Muat audit</button><button disabled={audit.length < 50} onClick={() => void run(async () => { const page = auditPage + 1; setAudit((await api.request<Listing<unknown>>(`/access-audit?offset=${page * 50}`)).items); setAuditPage(page); })}>Audit berikutnya</button><pre>{JSON.stringify(audit, null, 2)}</pre></>}
    </fieldset>
  </section>;
}

export function PasswordChangeForm({ api, onChanged }: { api: SettingsApi; onChanged: () => void }) {
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  return <form className="login" onSubmit={async e => {
    const form = e.currentTarget; const data = fields(e); setBusy(true); setError("");
    const payload = { current_password: text(data, "current"), new_password: text(data, "next") }; form.reset();
    try { await api.request("/session/password", payload); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : "Ganti password gagal"); }
    finally { setBusy(false); }
  }}><label>Password saat ini<input name="current" type="password" autoComplete="current-password" required /></label><label>Password baru<input name="next" type="password" minLength={12} maxLength={200} autoComplete="new-password" required /></label><button disabled={busy}>Ganti password dan login ulang</button>{error && <p role="alert">{error}</p>}</form>;
}
