# Dependensi Pengaturan HTML Final ↔ PR #14 (integrasi selektif lokal)

**PR #14:** `cursor/epv3-authz-enforced-activation-83bf` @ `788ce40` — OPEN / HOLD (tidak di-merge)
**PR #15:** `cursor/epv3-production-schedule-83bf` @ `b58d000` + WIP lokal
**Kebijakan Production:** **jangan merge #14**; **jangan aktifkan `enforced` di VPS/Production**.

## Status integrasi (lokal, NO COMMIT)

Fitur PR #14 diintegrasikan **selektif** ke worktree PR #15 tanpa merge Git:

| Komponen | Sumber | Status lokal |
|----------|--------|--------------|
| `owner_policy.py` | #14 | TERINTEGRASI |
| `mode.py` (startup gate + status) | #14 + map SETTINGS_PROD | TERINTEGRASI |
| `V3_WORKFLOW_ENFORCED_APPROVAL_REF` | #14 | TERINTEGRASI |
| `GET /settings/authorization-status` | #14 | TERINTEGRASI |
| `inventory.build(declare_readonly=)` | #14 | TERINTEGRASI |
| SettingsPanel status UI | #14 | TERINTEGRASI |
| `settingsAccessPanel` data-workflow | #14 hunk | TERINTEGRASI (WIP FE dipertahankan) |
| SETTINGS_PROD map (payment/cabang/mesin) | gap #15 | TERINTEGRASI (baru) |
| Merge PR #14 / enforced Production | — | **TIDAK** |

## Yang sudah jalan tanpa merge #14

| Fitur Pengaturan | SoT | Catatan |
|------------------|-----|---------|
| Approval Payment | PG + audit | Capability `settings.payment_approval.*` terpetakan enforced |
| Cabang efektif RO | grants JSONB + job | `settings.branch.read`; `can_manage=false` |
| Master Mesin | PG ops API | `machine.read` / `machine.manage` |
| Users/Grup/ScopedGrant/AccessAudit | Settings API | Manual; SIMPAN→BACA→AUDIT |
| Authorization status | Settings API | Direktur-only; tidak mengaktifkan enforced |
| Katalog inventaris transparan | UI | Non-mutasi |

## Privilege masih BLOCKED (keputusan bisnis)

| Privilege | Status Owner | Dampak enforced tanpa grant granular |
|-----------|--------------|--------------------------------------|
| `production.job.read` | manual_only_no_auto_import | Board/attachment/loading authority 403 |
| `production.delivery.manage` | manual_only_no_auto_import | Loading/POD/cancel/attachment 403 |
| `production.tracking.read` | manual_only_no_auto_import | Tracking/link 403 |
| Master Cabang writable | belum diputuskan | tetap RO |

## Konflik yang dihindari

| Area | Mitigasi diterapkan |
|------|---------------------|
| #14 menghapus `payment_settings_router` | **Tidak** diterapkan; router Fase 3 tetap |
| Overwrite `production.html` WIP | Hanya hunk `settingsAccessPanel` + katalog status |
| Route count 61→70 | Manifest mencakup SETTINGS_PROD; tes dinamis |
| Default Production | tetap `legacy`; gate fail-closed tanpa approval ref |

## Cutover Production (bukan bagian tugas ini)

1. Inventory clear (`python -m app.authorization.inventory`)
2. Grant manual grup operasional + cabang
3. Set `V3_WORKFLOW_ENFORCED_APPROVAL_REF` (Owner)
4. Deploy terpisah dengan `V3_WORKFLOW_AUTHORIZATION=enforced`
5. Rollback mode ≠ restore legacy permissions

## Kesimpulan

Target sistem Final = **enforced**. Integrasi kode & tes lokal **PARSIAL SIAP**.
Aktivasi Production **tetap diblokir** sampai keputusan Direktur terpisah.
