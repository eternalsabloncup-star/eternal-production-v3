# Tahap H — DIRECT LIVE RELEASE PREPARATION

**WIB / Asia/Jakarta:** 2026-11-17  
**Policy Direktur:** CODING → LOCAL/DISPOSABLE TESTING → FEATURE PRESERVATION AUDIT → OWNER APPROVAL → LIVE DEPLOY  
**Staging deployment:** **bukan tahapan wajib**  
**NO auto-deploy · NO V1 change**

## Workflow (wajib)

```
CODING
  → LOCAL / DISPOSABLE TESTING
  → FEATURE PRESERVATION AUDIT (zero silent removal)
  → OWNER / DIREKTUR APPROVAL
  → LIVE DEPLOY (backup → deploy → health → smoke → rollback ready)
```

## Zero Silent Feature Removal

1. Jangan hapus / sembunyikan / nonaktifkan fitur tanpa persetujuan Direktur.
2. Bandingkan baseline sebelum vs sesudah (lihat `docs/h-feature-inventory-baseline.md`).
3. Audit sidebar, nav, tombol, form, tabel, filter, kolom, route, API, permission — semua role & cabang.
4. Larangan menyembunyikan fitur aktif via `display:none`, conditional hide, feature flag, permission gate palsu, atau placeholder tanpa dasar bisnis disetujui.
5. Integrasi gagal → perbaiki sumber; jangan sembunyikan UI.
6. Pertahankan keputusan UI/workflow yang sudah disetujui (Master Mesin keluar sidebar Live = **disetujui**; enforced authz Live = **HOLD** sampai Owner).
7. Perubahan yang sudah disetujui Direktur tetap berlaku (G4A/G4B Live evidence, primeOwing, SJ list discovery).
8. Audit lintas role/cabang, bukan hanya akun Direktur.

## Release gates (H1–H6 lokal)

| Gate | Nama | Kriteria PASS |
|---|---|---|
| **H1** | Tests | Focused + regresi lintas modul terkait PASS |
| **H2** | Build | Frontend `npm run build` PASS (tsc + vite + routing + security checks) |
| **H3** | Workflow + feature preservation | Checklist before/after PASS; tidak ada silent removal |
| **H4** | Authorization & branch isolation | Mode Production **legacy** (tidak diubah); tes authz/branch PASS; enforced Live tetap HOLD |
| **H5** | Data integrity | Qty/receipt/SJ/loading invariants + fail-closed UNKNOWN/outstanding PASS |
| **H6** | Backup / rollback readiness | Rencana backup+rollback terdokumentasi; **tidak** dieksekusi tanpa approval |

Jika **satu gate kritis gagal → STOP. Jangan deploy.**

## Deployment policy

- Tidak ada deployment otomatis.
- Commit / push / merge / Live deploy hanya setelah persetujuan tahapan.
- Backup wajib sebelum perubahan Live.
- Health check + smoke wajib setelah deploy.
- Rollback wajib tersedia.
- Jangan mengubah V1.

## Artefak terkait

- `docs/h-feature-inventory-baseline.md`
- `docs/h-feature-preservation-regression-checklist.md`
- `docs/h-direct-live-readiness-report.md` (hasil putaran ini)

## Status Tahap H

**PREPARATION ONLY** — menunggu persetujuan Direktur sebelum commit/push/Live deploy.
