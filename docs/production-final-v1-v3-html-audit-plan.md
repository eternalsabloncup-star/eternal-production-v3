# Rencana Audit Final — HTML Final × Eternal V1 × Eternal V3

**Status dokumen:** RENCANA / SOURCE DISCOVERY saja — **bukan** hasil Final Audit.
**Tanggal (WIB / Asia/Jakarta):** 2026-11-16
**Disiapkan pada V3 HEAD:** `e49186ae748905e002083b150bbe8b963c4b1d60`
**Branch:** `cursor/epv3-production-schedule-83bf` · PR #15 OPEN · PR #14 HOLD
**Authz Production:** `legacy`

Klasifikasi per fitur (nanti diisi saat eksekusi):
`SESUAI` | `BERBEDA DISETUJUI` | `TIDAK SESUAI` | `BELUM TERVERIFIKASI`

Aturan: V1 **tidak** otomatis menang jika V3 punya perubahan bisnis yang sudah disetujui Owner/Direktur. HTML Final = acuan UI/UX, bukan otomatis override gate backend.

---

## 1. Inventaris sumber (discovery)

| # | Sumber | Status | Lokasi / identitas | Catatan |
|---|---|---|---|---|
| 1 | HTML Final (disetujui) | **DITEMUKAN (lokal /tmp)** | `/tmp/epv3-fase3-handoff/` · `index.html` SHA256 `d612eaa0f5b7…` · `v3_frontend.js` `4a917a40ac21…` · mtime handoff ~2026-11-15 | **Belum di-git** V3. Manifest: `docs/fase3-html-final-asset-manifest.{md,json}`. Konflik SHA vs sandbox. |
| 1b | Sandbox V22 (pelengkap) | **DITEMUKAN (lokal /tmp)** | `/tmp/epv3-fase3-sandbox/` · `index.html` SHA256 `b25e601e8724…` · audit V1 `AUDIT_WORKFLOW_V1_V16.md`, `AUDIT_V1_JADWAL_V20.md`, dll. | Bukan SoT UI Final; pelengkap interaksi/audit. |
| 2 | Eternal V1 | **DITEMUKAN (GitHub, private)** | `prasnda21-tech/eternal-packaging` · default `main` · tip `9ff5a0cd4db2ffbd33033c6a34cf7b7172377d79` (2026-11-04 WIB+7) | Readable via Cursor GitHub; `gh` CLI lokal 404. **Belum di-worktree** `/tmp/epv3-fase1b-wt`. |
| 3 | Eternal V3 | **DITEMUKAN** | `eternalsabloncup-star/eternal-production-v3` · worktree `/tmp/epv3-fase1b-wt` · branch audit `cursor/epv3-production-schedule-83bf` @ `e49186a…` · `origin/main` @ `8cd2792…` | SoT runtime + PostgreSQL. |
| 4 | Aturan bisnis V1 | **PARSIAL** | Repo V1 + sandbox audits (`AUDIT_*_V1*.md` di `/tmp`) | Perlu inventaris path modul produksi V1 pada eksekusi (clone/read-only). |
| 5 | Perubahan bisnis V3 disetujui | **DITEMUKAN (dokumen V3)** | `backend/app/authorization/owner_policy.py` · `docs/authorization-enforced-cutover.md` · settings/payment/schedule docs · acceptance Iterasi 5 | Harus dilist eksplisit vs V1 sebelum `BERBEDA DISETUJUI`. |
| 6 | Matrix 39 fitur HTML Final | **DITEMUKAN** | `docs/fase3-inventaris-39-fitur.md` · `docs/fase3-html-final-kesesuaian.md` | F3-001…039; F3-039 reskin penuh masih BLOCKED. |
| 7 | Permission matrix | **DITEMUKAN** | `docs/fase3-permission-role-matrix.md` · `workflow_map.py` (74 mapped) | Legacy vs enforced. |
| 8 | Workflow canonical | **DITEMUKAN** | `docs/phase3-action-matrix.md` · production routers · acceptance matrix Iterasi 5 | Inbox→…→POD. |
| 9 | Accurate Gateway contract | **DITEMUKAN** | `docs/phase32-accurate-gateway.md` · `docs/production-accurate-integration-audit.md` · `accurate-gateway/` | SJ list-all = **COVERAGE TERBATAS**. |
| 10 | Full Production Acceptance | **DITEMUKAN** | `docs/production-full-acceptance-{matrix,report}.md` · live-readiness Iterasi 5 | READY FOR STAGING; NOT LIVE. |

### Source blockers

| ID | Blocker | Dampak | Yang perlu disediakan |
|---|---|---|---|
| SRC-01 | HTML Final hanya di `/tmp` (ephemeral) | Audit UI bisa hilang jika VM di-reimage | Salin handoff ke `docs/reference/html-final/` (Owner approve) atau lampirkan artifact tetap |
| SRC-02 | V1 belum di-worktree lokal; akses CLI `gh` 404 | Paritas kode V1 lambat/terbatas | Izinkan clone read-only `eternal-packaging@9ff5a0cd…` ke path terpisah (bukan ERP V2) |
| SRC-03 | Konflik handoff vs sandbox (3 file) | Salah acuan UI | Owner tetapkan Handoff = SoT UI Final |
| SRC-04 | Accurate real / SJ list-all | Paritas inbox/SJ Live | Credential staging + keputusan list-all |
| SRC-05 | ERP V2 | **DILARANG** disentuh dari proyek ini | — |

---

## 2. Modul audit (kelompok A–T)

Setiap baris fitur (saat eksekusi) mengisi: HTML Final | V1 | V3 | Expected | Actual | Endpoint | Permission | DB | Tes | Diff | Severity | Rekomendasi | Klasifikasi.

### A. Dashboard dan navigasi
Shell, menu modul, deep-link, role visibility.

### B. Inbox Accurate
List/filter/pagination/provenance; empty vs error; branch scope.

### C. PO dan Detail SO
Field parity, classification PRINT/NON_PRINT/UNKNOWN, multi-line.

### D. Design
Upload, decide, bypass, approval link, SoD.

### E. Monitoring Payment
Receipt, bypass, revoke, settings approval, sticky/sort.

### F. Jadwal Produksi
Assignment, multi-op, HOLD, sticky/resize, cetak-only API.

### G. Prepare Screen
Eligibility, screen size, gate sebelum sample/output.

### H. Prepare Cup
Helper prep parallel/serial rules vs Screen.

### I. Sample dan Approval
Upload, reject, approve, link.

### J. Output Produksi
Qty, multi-operator, idempotency, correction, reject.

### K. Verification
Helper verify ≤ output.

### L. Packing
Batch, parsial, ≤ verified.

### M. Loading
Authority SJ by-id, multi-SJ, cancel confirmation, return flow.

### N. Surat Jalan
By-id vs list-all (**COVERAGE TERBATAS**), links dari SO.

### O. POD
Bukti wajib, line receipt, ≤ loading.

### P. Tugas Tim
Enam role, empty state benar, sticky sheet.

### Q. Kontrol Produksi
KPI qty, status kerja, drift.

### R. Pengaturan, User dan Permission
Users/grup/grant/audit, cabang, Direktur Full Access, inventory cutover.

### S. Filter, tabel, kolom, export, pagination
Parity kolom HTML Final vs V3; export scoped.

### T. Status, quantity, idempotency, audit trail
Invariant Delivered≤…≤Output; AccessAudit / production events.

---

## 3. Rencana eksekusi (urutan)

1. **Pin sumber:** salin/pin HTML Final handoff + catat V1 SHA `9ff5a0cd…` + V3 `e49186a…` (atau tip terbaru saat eksekusi).
2. **Owner decisions:** daftar eksplisit `BERBEDA DISETUJUI` (authz enforced target, payment gate V3, SJ by-id, dll.).
3. **Pass FE:** bandingkan HTML Final ↔ V3 UI per modul A–S (screenshot/DOM bukti).
4. **Pass BE:** bandingkan V1 rules ↔ V3 services/gates per modul (baca V1 read-only).
5. **Pass permission:** matrix HTML/V1 legacy ↔ V3 catalog/workflow_map.
6. **Pass data:** event/qty/audit dari acceptance disposable + gap Live.
7. **Isi matriks** + severity P0/P1/P2; **jangan** auto-fix.
8. **Laporan final** terpisah (bukan dokumen ini).

Larangan eksekusi tahap ini: tidak merombak FE/BE, tidak merge, tidak enforced Live, tidak grant Live, tidak sentuh ERP V2.

---

## 4. Keputusan Direktur / Owner yang diperlukan sebelum/saat audit

1. Pin HTML Final: Handoff `/tmp/epv3-fase3-handoff` sebagai SoT UI (bukan sandbox).
2. Persist aset HTML Final ke repo atau artifact tahan lama.
3. Izin clone/read-only V1 `eternal-packaging` @ `9ff5a0cd…` untuk paritas.
4. Daftar perubahan bisnis V3 yang **disetujui** vs warisan V1.
5. Apakah SJ list-all wajib sebelum Live, atau tetap COVERAGE TERBATAS by-id.
6. Urutan PR #15 vs HOLD #14 untuk cutover authz.

---

## 5. Keluaran yang diharapkan dari Final Audit (nanti)

- Matriks lengkap A–T terisi klasifikasi.
- Daftar `TIDAK SESUAI` + rekomendasi.
- Daftar `BERBEDA DISETUJUI` bertanda bukti keputusan.
- Verdict kesiapan vs HTML Final / V1 / V3 — **tanpa** klaim Live kecuali bukti Accurate + authz Live lengkap.

**Dokumen ini tidak menyelesaikan Final Audit.**
