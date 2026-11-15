# Dependensi Pengaturan HTML Final ↔ PR #14 (HOLD)

**PR #14:** `cursor/epv3-authz-enforced-activation-83bf` — OPEN / HOLD  
**PR #15:** `cursor/epv3-production-schedule-83bf` — foundation produksi + Fase 3  
**Kebijakan:** **jangan merge #14**; **jangan aktifkan `enforced`**.

## Yang sudah jalan di PR #15 tanpa #14

| Fitur Pengaturan | SoT | Catatan |
|------------------|-----|---------|
| Approval Payment | PG + audit | Independen legacy Direktur / `PAYMENT_BYPASS` |
| Cabang efektif RO | grants JSONB + job | Jujur `can_manage=false` |
| Master Mesin | PG ops API | Permission job/ops existing |
| Katalog inventaris transparan | UI | Non-mutasi |

## Bagian authorization yang dibutuhkan untuk kesesuaian HTML Final

| Bagian Final | Sumber ideal | Status tanpa #14 |
|--------------|--------------|------------------|
| Pengguna CRUD + password awal | Settings users (#14 UI/API) | PARSIAL / sandbox terpisah |
| Grup & permission granular | AccessGroup + grants | HOLD |
| ScopedGrant per cabang/assignment | model grant #14 | HOLD |
| Effective access preview | API #14 | HOLD |
| AccessAudit Direktur | audit #14 | HOLD (payment settings punya audit sendiri) |
| Authorization status / blockers UI | `#14` runtime | HOLD |
| Workflow capability catalog cutover | enforced map | **tidak** diaktifkan |

## Konflik potensial dengan PR #15

| Area | Risiko | Mitigasi |
|------|--------|----------|
| `workflow_map` route counts | #15 menambah endpoint produksi (65+); #14 mengunci matrix authz | Rebase #14 setelah #15 atau sebaliknya; sesuaikan count |
| `COLLECTIONS` / sensitive fields | Endpoint settings payment/branches di luar map #14 | Tetap legacy `require_permissions` sampai katalog di-update |
| Default `bypass_enabled` | Gate payment vs grant `payment.bypass` | Keduanya wajib; settings tidak mengganti grant |
| UI Pengaturan tabs | #15 tab payment/cabang/katalog vs #14 users/grup | Gabung UI setelah merge berurutan; jangan double SoT |
| Migrasi Alembic | #15 `0016` payment settings; #14 mungkin punya revisi sendiri | Linearize down_revision sebelum merge |

## Rencana integrasi aman (tanpa merge sekarang)

1. Checkpoint Fase 3 di **PR #15 saja** (PARSIAL).  
2. Setelah #15 stabil di CI: rebase/audit #14 terhadap HEAD #15.  
3. Update matrix route + COLLECTIONS untuk endpoint Fase 3.  
4. Uji `legacy` masih default; gate enforced hanya di `APP_ENV=test` atau approval ref.  
5. UI: tab Users/Grup dari #14 berdampingan tab Payment/Cabang RO #15.  
6. Cutover enforced = keputusan Owner terpisah (bukan bagian checkpoint ini).

## Kesimpulan

Pengaturan HTML Final **belum lengkap** tanpa #14 untuk Users/Grup/Grant/Workflow.  
Fondasi Payment + Cabang RO + Mesin di #15 **aman** tanpa merge #14.
