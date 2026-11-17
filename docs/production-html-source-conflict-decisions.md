# HTML Source Conflict — Keputusan Pending (Final Audit E2)

**Tanggal (WIB / Asia/Jakarta):** 2026-11-17
**HEAD committed:** `2132797a0ec4c3c5a73dfc8a28ee4c126e543b3c`
**Mode:** AUDIT ONLY — tidak menetapkan APPROVED
**Handoff:** `/tmp/epv3-fase3-handoff/index.html` SHA-256 `d612eaa0f5b75037a80f20d92861916d30e10b8fc8b8ef600b02d8738d5bb0ba`
**Sandbox:** `/tmp/epv3-fase3-sandbox/index.html` SHA-256 `b25e601e872442f332ced1c45eddb29f86f012d75fa5e6981991f9031d2dd25a`

Semua status tetap **SOURCE CONFLICT** sampai Direktur memutuskan.

| ID | Modul | Handoff | Sandbox | V3 aktual | Dampak operasional | Dampak UX | Rekomendasi | Keputusan Direktur |
|---|---|---|---|---|---|---|---|---|
| SC-01 | 0-Source | ~40KB, shell Final tipis + `v3_frontend.js` | ~98KB, inline + banyak modul | `production.html` + `live-runtime.js` (besar, operasional) | Rendah jika kontrak API sama | Tinggi: struktur/visual beda | Pin satu SHA sebagai CANDIDATE→APPROVED; V3 tetap implementasi | Pilih handoff SHA, sandbox SHA, atau hybrid |
| SC-02 | 0-Source | Menu Final-7: inbox, payments, schedule, tasks, delivery, buffer, settings | Menu beda: dashboard, flow, **control**, tanpa payments terpisah | Live: Final-7 **plus** Overview, Master Mesin, Laporan, Slip Gaji, History | V3-extra punya fungsi ops (mesin/laporan) | Menu lebih ramai vs Final-7 | **Jangan hapus** V3-extra tanpa approval; NAV-V3-* sudah BERBEDA DISETUJUI di inventaris | Apakah Live = Final-7 only atau Final-7 + V3-extra |
| SC-03 | 0-Source | Paket `v3_frontend.js` | `settings.js` + `workflow.js` + inline | Monolith HTML + live-runtime | Tooling/test beda | Perilaku sheet beda | Tetap V3 runtime; handoff sebagai kontrak kolom/UX | Paket referensi resmi mana |
| SC-04 | 0-Source | 0 demo mutasi (kontrak integrasi) | Banyak jalur demo/fixture/audit | Live: demo diblokir; Preview fixture terpisah (C2/E1) | Risiko demo→Live jika longgar | Preview vs Live | Pertahankan isolasi Preview; jangan ikuti sandbox demo | Konfirmasi kebijakan zero-demo Live |
| SC-05 | 0-Source | Kontrak gate/penerimaan (INTEGRATION_CONTRACT) | Label Belum/Sebagian/Lunas di UI sandbox | V3: `financial_payment_status=UNKNOWN`; bukan Lunas palsu | Gate produksi vs outstanding Accurate | Label finansial | Pertahankan UNKNOWN≠PAID | Setujui label V3 vs sandbox |
| SC-06 | 0-Source | `INTEGRATION_CONTRACT.md`, test_final | Banyak `AUDIT_V*` | Docs V3 di `docs/` | Audit trail | — | Handoff contract = acuan API; sandbox AUDIT = historis | Artefak mana yang mengikat |
| SC-07 | 0-Source | CANDIDATE (belum APPROVED stamp) | Tidak ada stamp APPROVED | V3 mengikuti CANDIDATE handoff | Blokir “Final locked” | — | Jangan auto-APPROVED | Pin APPROVED SHA + tanggal |
| MOD-kontrol | R-Kontrol | Tidak ada `data-page=control` | Ada halaman Kontrol Produksi | Tidak ada page `control`; ada Overview / labs | Fitur kontrol sandbox tidak di Final | Navigasi | Jangan port sandbox control tanpa keputusan; jangan hapus Overview | Apakah Kontrol sandbox wajib di Live |

## Menu Final-7 vs V3-extra (detail SC-02)

Bukti browser E2 (`/tmp/epv3-e2-browser-evidence.json`):

- Final-7 hadir di Live: Inbox, Monitoring Penerimaan, Jadwal Produksi, Tugas Tim, Jadwal Pengiriman, Monitoring Buffer, Pengaturan.
- V3-extra hadir: Overview, Master Mesin, Laporan Produksi, Cetak Slip Gaji, Log History.
- Sandbox `control` **tidak** menjadi menu Live setara.

**Rekomendasi operasional:** biarkan V3-extra sampai Direktur memerintahkan penyederhanaan; penghapusan menu mesin/laporan akan memutus fungsi operasional.

## Yang tidak dilakukan E2

- Tidak menetapkan sumber APPROVED.
- Tidak mengubah product code.
- Tidak menghapus menu V3-extra.
