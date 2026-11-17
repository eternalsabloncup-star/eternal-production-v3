# Final Audit F2 — Laporan (NO COMMIT)

**Tanggal (WIB / Asia/Jakarta):** 2026-11-17
**Verdict:** **PENDING OWNER**
**HEAD committed:** `36abda196e8a627dc9d6ed5d4778830feb5a0201`
**Branch:** `cursor/epv3-production-schedule-83bf`
**PR #15:** OPEN · **PR #14:** HOLD · **authz:** legacy
**Constraint F2:** NO COMMIT / NO PUSH / NO MERGE / NO DEPLOY / NO NEW PR

---

## 1. HEAD dan WIP

| Item | Nilai |
|---|---|
| Expected HEAD | `36abda196e8a627dc9d6ed5d4778830feb5a0201` — **MATCH** |
| Remote tracking | `origin/cursor/epv3-production-schedule-83bf` @ same SHA |
| WIP (uncommitted) | `frontend/public/production.html` (sidebar Master Mesin removed) |
|  | `frontend/src/live/sheetColumnView.test.ts` (+F2 assertions) |
|  | `docs/production-html-source-conflict-decisions.md` (updated) |
|  | `docs/production-html-final-approval-decision-package.md` (new/updated) |
|  | `docs/production-html-final-approval-register.md` (new/updated) |
|  | `docs/production-final-audit-f2-report.md` (this file) |

---

## 2. Menu sebelum / sesudah

**Sebelum sidebar:** Overview · Inbox Accurate · Jadwal Produksi · Tugas Tim · Jadwal Pengiriman · **Master Mesin** · Monitoring Penerimaan · Monitoring Buffer · Laporan Produksi · Cetak Slip Gaji · Log History · Pengaturan

**Sesudah sidebar (1366 & 1440; e3.lead & e3.direktur):** Overview · Inbox Accurate · Jadwal Produksi · Tugas Tim · Jadwal Pengiriman · Monitoring Penerimaan · Monitoring Buffer · Laporan Produksi · Cetak Slip Gaji · Log History · Pengaturan

Final-7 tetap ada. V3-extra Overview/Laporan/Slip/History tetap ada (PENDING Owner).

---

## 3. Status menu “Pilihan”

**PENDING OWNER (BR-F2-01).** Bukan item sidebar. “pilihan” hanya di UI filter/Kolom Tampil (`Cari pilihan nilai`, `Cari dalam pilihan…`). Tidak dihapus.

Bukti: `/opt/cursor/artifacts/F2-pilihan-filter-not-menu.png`

---

## 4. Status Master Mesin

**Owner F2 diterapkan (WIP):** `nav('machineMaster',…)` dihapus dari sidebar Live.
**Dipertahankan:** halaman `machineMaster`, tab Pengaturan → Master Mesin, `go('machineMaster')`, API `/production/ops/machines` (+ POST/PATCH), relasi jadwal mesin di `live-runtime.js`.
**Tidak diubah:** grants, endpoint, DB.

Catatan: hilang dari sidebar ≠ endpoint tidak dapat diakses (direct `go` / API masih hidup).

---

## 5. Fitur mesin yang tetap berfungsi

| Cek | Hasil |
|---|---|
| `go('machineMaster')` → section + judul | PASS |
| `GET /production/ops/machines` | 200 (items kosong di seed OK) |
| Schedule section setelah perubahan menu | PASS |
| Runtime masih request machines untuk assignment | kode tetap (`live-runtime.js`) |

Bukti: `F2-machineMaster-via-go-still-works.png`, `F2-schedule-after-menu-change.png`

---

## 6. Delapan SOURCE CONFLICT — status keputusan

| ID | Status F2 |
|---|---|
| SC-01 | PENDING OWNER |
| SC-02 | **PARTIAL OWNER** (Master Mesin out of sidebar only) |
| SC-03 | PENDING OWNER |
| SC-04 | PENDING OWNER |
| SC-05 | PENDING OWNER (aturan UNKNOWN dipertahankan) |
| SC-06 | PENDING OWNER |
| SC-07 | PENDING OWNER — HTML **CANDIDATE**, bukan APPROVED |
| MOD-kontrol | PENDING OWNER (jangan port sandbox control) |

Tidak ada mass-flip ke BERBEDA DISETUJUI.

---

## 7. HTML approval status

| Sumber | SHA-256 | Status |
|---|---|---|
| Handoff | `d612eaa0f5b75037a80f20d92861916d30e10b8fc8b8ef600b02d8738d5bb0ba` | **CANDIDATE** |
| Sandbox | `b25e601e872442f332ced1c45eddb29f86f012d75fa5e6981991f9031d2dd25a` | historis / bukan kandidat default |
| APPROVED stamp | — | **belum** (dilarang tanpa pin Owner) |

---

## 8. Hasil tes

| Tes | Hasil |
|---|---|
| Browser sidebar 1366/1440 tanpa Master Mesin | PASS |
| Role e3.lead + e3.direktur sidebar + Final-7 + go(machineMaster) + schedule | PASS |
| Pilihan = filter bukan menu | PASS |
| Machines API reachable | PASS |
| Frontend Vitest | **240/240 PASS** (44 files) |
| Frontend build + API routing + staging security | PASS |
| `git diff --check` | PASS (exit 0) |

---

## 9. File berubah (WIP)

- `frontend/public/production.html`
- `frontend/src/live/sheetColumnView.test.ts`
- `docs/production-html-source-conflict-decisions.md`
- `docs/production-html-final-approval-decision-package.md`
- `docs/production-html-final-approval-register.md`
- `docs/production-final-audit-f2-report.md`

---

## 10. Pertanyaan aturan bisnis (Direktur)

Lihat paket keputusan §8: **BR-F2-01 … BR-F2-06** (Pilihan; V3-extra sisa; Delivery/SJ; UNKNOWN; authz enforced; revisi/cancel + backup).

---

## 11. Risiko

| Level | Item |
|---|---|
| P0 | Auto-activate authz enforced / Live Accurate writes — **tidak dilakukan** |
| P1 | Menghapus Overview/Laporan/Slip tanpa jalur alternatif; salah hapus kontrol “Pilihan” |
| P2 | Sidebar tanpa Master Mesin → operator lupa jalur Pengaturan; deep-link `machineMaster` masih terbuka tanpa grant UI |

---

## 12. Verdict

**PENDING OWNER** — implementasi menu Master Mesin siap di WIP lokal; HTML & SC mayoritas belum diputus; residual bisnis butuh keputusan BR-F2-*.

Bukan SIAP GIT (NO COMMIT diperintahkan; SC/HTML/residual masih terbuka).
Bukan PARTIAL “siap merge” — hanya PARTIAL pada SC-02 menu.
