# Matriks Permission Enforced — Tiga Privilege + Enam Role

**Tanggal:** 2026-11-16 03:15 WIB (Asia/Jakarta)
**Sumber kode:** `app/authorization/role_packs.py`, `workflow_map.py`, `owner_policy.py`
**Kebijakan:** tidak ada auto-import; Production tetap legacy

## 1. production.job.read

| Tier | Capability | Operasi | Read/Write |
|------|------------|---------|------------|
| minimum_read | `job.read`, `task.read` | get job, schedule list, tasks | READ |
| board | `job.board.read` | board PO | READ |
| schedule_ops_read | `delivery.schedule.read`, `machine.read`, `report.production.read`, `assignee.read` | SJ list, mesin, laporan, assignee | READ |
| sensitive_manual_only | `payment.evidence.read`, `audit.production.read`, `attachment.delivery.read`, `loading.authority.read` | field sensitif board, lampiran, authority | READ |

**Risiko flatten:** satu OR-bundle legacy membuka field sensitif + attachment.
**Status:** `mapped_manual_packs` — grant per tier via Pengaturan.

## 2. production.delivery.manage

| Tier | Capability | Operasi | Read/Write |
|------|------------|---------|------------|
| loading_write | `loading.record`, `loading.cancel_confirmation` | loading / batal konfirmasi | WRITE / CANCEL |
| pod_write | `delivery.pod.record` | POD | WRITE |
| sj_cancel | `delivery.sj.cancel_local` | cancel/supersede SJ lokal | CANCEL |
| plan_write | `delivery.plan.manage` | jadwal kurir | WRITE |
| attachment_write | `attachment.delivery.create` | upload | WRITE |
| attachment_read | `attachment.delivery.read` | unduh/list | READ |

**Risiko flatten:** Driver mendapat cancel SJ / plan.
**Status:** `mapped_manual_packs`.

## 3. production.tracking.read

| Tier | Capability | Operasi | Read/Write |
|------|------------|---------|------------|
| read_only | `tracking.read` | timeline | READ |
| link_create | `tracking.link.create` | buat link pelanggan | WRITE |
| link_revoke | `tracking.link.revoke` | cabut link | CANCEL |

**Keputusan terkunci:** read ≠ link create.
**Status:** `mapped_manual_packs`.

## 4. Paket jabatan (HTML Final)

| Role | Cap utama | Dilarang implisit |
|------|-----------|-------------------|
| Kepala Produksi | jadwal, sample decide, plan/cancel SJ, evidence read | payment.bypass |
| Designer | design create/decide/link | design.bypass |
| Screener | prep.screener.* | output/packing |
| Helper | prep.helper.*, helper.verify, packing | loading/POD |
| Operator | sample upload, output, reject | sample decide, bypass |
| Driver | loading, POD, attachment, schedule read | sj.cancel, plan |

Scope cabang: eksplisit pada setiap grant. Direktur: Full Access lintas cabang (grup sistem).

## 5. Cara grant manual

1. Pengaturan → buat grup biasa (bukan system).
2. Membership pengguna → grup.
3. Grant tiap capability + branches + ownership `all` (default paket).
4. Baca kembali Effective Access.
5. AccessAudit: `grant.create`, `membership.set`, `user.*`.

Tidak ada tombol auto-apply ke akun lama.
