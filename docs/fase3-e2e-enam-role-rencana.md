# Rencana E2E Enam Role — Fase 3 (belum dieksekusi mutasi)

**Status:** API mutasi 6 role **PASS** (lihat `fase3-e2e-enam-role-hasil.md`); browser klik **PASS_CLICK_NO_MUTATE** (mutasi UI belum diklaim)
**Kebijakan:** DB disposable saja · ProductionJob nyata · NO LIVE WRITES · authz Production = legacy
**Acuan packs:** `app/authorization/role_packs.py` · matriks 24/12/3

## Prasyarat bersama (disposable)

1. Migrasi head termasuk `20261120_0017` (Master Cabang tidak wajib untuk alur task, tapi schema lengkap).
2. Seed 1+ `ProductionJob` print + `JobLineQty(production_process=print)` + payment/design bypass atau approved.
3. User per role + grant/legacy permission sesuai packs (sandbox enforced terpisah jika diuji deny).
4. Browser: login → Tugas Tim → aksi → assert status/qty/audit; bukti screenshot/JSON response.

## Matriks aksi

| # | Role | Aksi utama | Endpoint (contoh) | Permission / pack | Prasyarat | Efek | Audit / bukti | Expected |
|---|------|------------|-------------------|-------------------|-----------|------|---------------|----------|
| 1 | Kepala Produksi | Buat/ubah jadwal assignment; pantau tasks | `POST /production/jobs/{id}/schedule/assignments`; `GET /ops/schedule`; `GET/POST /jobs/tasks` | `schedule.*` / `task.read` (pack KP) | Job payment+design OK; line print | Assignment aktif; task operator muncul | ProductionEvent / response 200 | success KP; deny operator buat jadwal cabang lain |
| 2 | Designer | Upload desain; decision / approval link | `POST .../design/versions`; `POST .../design/versions/{id}/decision`; approval-links | `design.version.create`, `design.decision.record` | Job ada | `design_status` pending→approved/bypass sesuai aturan | event desain + audit | success designer; deny tanpa cap |
| 3 | Screener | Catat qty screen prep | endpoint prep screener (`prep` / task action) | pack screener | Design+payment OK; print line | PrepState screener qty > 0 | PrepEvent | success; deny role lain |
| 4 | Helper | Catat helper prep / dukungan | endpoint prep helper | pack helper | Screener sesuai gate V3 | PrepState helper | PrepEvent | success; deny |
| 5 | Operator | Input output cetak / packing sesuai workflow | schedule output / production events | pack operator | Assignment aktif | qty cetak / verified / pack bertambah | ProductionEvent | success pada assignment sendiri; deny bypass payment |
| 6 | Driver | Loading confirmation; POD / delivery plan | loading-authority; loading confirm; `POST .../delivery-plan`; deliveries list | pack driver (`delivery.*`, loading) | Packing siap / SJ linked (COVERAGE TERBATAS) | Loading confirmed; POD fields | DeliveryPlanEvent | success loading/POD; deny SJ cancel tanpa cap; Accurate write = tidak |

## Bukti yang wajib sebelum klaim PASS

- Request/response HTTP (status + body ringkas) per aksi.
- Baris DB sebelum/sesudah (job status, qty, prep, assignment) pada disposable.
- Browser: tombol terlihat → klik → toast/error jujur; **bukan** hanya label UI.
- Mode legacy Production; satu putaran enforced sandbox untuk deny (opsional, terisolasi).

## Out of scope klaim saat ini

- Mutasi Kerjakan sukses end-to-end di browser smoke (`mutateClaimed=false`).
- Accurate SJ list-all / write.
- Enforced Live activation.
