# Paket Keputusan HTML Final — Tahap F → F2

**Tanggal (WIB / Asia/Jakarta):** 2026-11-17
**Mode F:** AUDIT ONLY · **Mode F2:** keputusan Owner parsial + gate aturan bisnis + implementasi menu aman (NO COMMIT)
**HEAD V3:** `36abda196e8a627dc9d6ed5d4778830feb5a0201`
**WIP F2:** `production.html` tanpa `nav('machineMaster'…)` di sidebar
**PR #15 OPEN · PR #14 HOLD · authz legacy**
**Baseline inventaris:** 202 kontrol · SESUAI 167 · BERBEDA 17 · TIDAK 0 · NT 0 · SC 8 · BLOCKED 10  
**(F2 tidak membalik massal SC→BERBEDA DISETUJUI)**

Dokumen terkait:
- [`production-html-source-conflict-decisions.md`](./production-html-source-conflict-decisions.md)
- [`production-html-final-approval-register.md`](./production-html-final-approval-register.md)
- Contact sheet: `/opt/cursor/artifacts/F-CONTACT-SHEETS.html`

---

## 1. Verifikasi sumber HTML

| Sumber | Path | SHA-256 | Ukuran | Status |
|---|---|---|---:|---|
| HANDOFF | `/tmp/epv3-fase3-handoff/index.html` | `d612eaa0f5b75037a80f20d92861916d30e10b8fc8b8ef600b02d8738d5bb0ba` | 40 407 B | **CANDIDATE** (belum APPROVED) |
| SANDBOX | `/tmp/epv3-fase3-sandbox/index.html` | `b25e601e872442f332ced1c45eddb29f86f012d75fa5e6981991f9031d2dd25a` | 97 950 B | Prototipe lokal / historis |
| V3 Live UI | `frontend/public/production.html` + `live-runtime.js` @ `36abda1` | (repo HEAD) | ~599 KB HTML | Implementasi operasional |

**Aset pendukung**
- Handoff: `v3_frontend.js`, `INTEGRATION_CONTRACT.md`, `payment_policy.py`, `server.py` (viewer READ-ONLY).
- Sandbox: `settings.js`, `workflow.js`, `server.py` (SQLite demo), banyak `AUDIT_V*`.
- V3: `live-runtime.js`, `live-column-resize.js`, `live-qty-integrity.js`, `workflow-documents.js`.

Tidak ada stamp APPROVED pada kedua kandidat. Jangan menetapkan APPROVED tanpa keputusan Direktur.

---

## 2. Pilihan keputusan (template)

Untuk setiap konflik, Direktur memilih salah satu:

| Kode | Arti |
|---|---|
| **A** | Ikuti handoff |
| **B** | Ikuti sandbox |
| **C** | Pertahankan V3 aktual |
| **D** | Kombinasi spesifik (wajib merinci fitur per sumber) |

Status default paket ini: **PENDING OWNER** pada semua baris.

---

## 3. Delapan SOURCE CONFLICT — analisis & rekomendasi

### SC-01 — Struktur / ukuran HTML shell

| # | Isi |
|---|---|
| 1–3 | **ID** SC-01 · **Modul** 0-Source · **Kontrol** Shell HTML Final vs sandbox vs V3 |
| 4 Handoff | ~40KB; shell Final tipis; script `/v3_frontend.js`; tabel kosong sampai API |
| 5 Sandbox | ~98KB; inline + modul; UI lebih padat; data simulasi |
| 6 V3 | Monolith `production.html` + `live-runtime.js`; terhubung API PostgreSQL |
| 7 Operasional | Rendah jika kontrak API sama; tinggi jika menukar shell tanpa mapping |
| 8 Bisnis | Tidak mengubah gate/qty jika hanya shell |
| 9 UX/Visual | Tinggi — layout/komposisi berbeda |
| 10 Rekomendasi | **C + acuan A untuk kontrak kolom/UX** (V3 tetap runtime; handoff = CANDIDATE visual/kontrak) |
| 11 Risiko A | Kehilangan fitur Live yang sudah di V3 |
| 12 Risiko B | Membawa demo/simulasi ke Live |
| 13 Keputusan Direktur | Pin SHA CANDIDATE→APPROVED; apakah V3 harus diselaraskan visual ke SHA itu |

**Pilihan:** A / B / C / D  **Status:** PENDING OWNER
**Rekomendasi agent:** **C** (runtime) dengan handoff sebagai acuan UI/kontrak (bukan mengganti backend).

---

### SC-02 — Set menu navigasi

| # | Isi |
|---|---|
| 1–3 | **ID** SC-02 · **Modul** 0-Source / T-Navigasi · **Kontrol** Final-7 vs menu alternatif |
| 4 Handoff Final-7 | Inbox Accurate, Monitoring Penerimaan, Jadwal Produksi, Tugas Tim, Jadwal Pengiriman, Monitoring Buffer Stok, Pengaturan |
| 5 Sandbox | Ringkasan, Inbox, Jadwal, **Workflow E2E**, Tugas, **Kontrol Produksi**, Pengiriman, Buffer, Pengaturan — **tanpa** Monitoring Penerimaan terpisah |
| 6 V3 (F2) | Final-7 **plus** Overview, Laporan, Slip, History; **Master Mesin keluar sidebar** (halaman/API tetap) |
| 7 Operasional | Menghapus Laporan/Slip memutus operasi & payroll; menyembunyikan Mesin dari nav **tidak** memutus API jika akses Pengaturan tetap |
| 8 Bisnis | Tidak; kecuali menutup akses monitoring payment |
| 9 UX | Final-7 lebih ringkas; V3 lebih ramai |
| 10 Rekomendasi | **D parsial F2:** Final-7 + V3-extra kecuali Master Mesin tidak di sidebar; jangan port `control` sandbox |
| 11 Risiko A (Final-7 only) | Hilang Laporan / Slip / History / Overview |
| 12 Risiko B | Menu control/flow sandbox + data demo |
| 13 Keputusan | **PARTIAL OWNER (F2):** Master Mesin out of Live nav; sisa V3-extra masih PENDING |

**Klasifikasi menu (bukti Tahap F)**

| Menu | Sumber | Klasifikasi |
|---|---|---|
| Inbox Accurate | Final-7 / V3 / sandbox | Fungsi operasional wajib |
| Monitoring Penerimaan | Final-7 / V3 | Fungsi operasional wajib |
| Jadwal Produksi | Semua | Fungsi operasional wajib |
| Tugas Tim | Semua | Fungsi operasional wajib |
| Jadwal Pengiriman | Semua | Fungsi operasional wajib |
| Monitoring Buffer | Semua | Fungsi operasional wajib |
| Pengaturan | Semua | Fungsi operasional wajib |
| Overview | V3 (+ sandbox Ringkasan) | Fungsi tambahan sah |
| Master Mesin | V3 | **F2 Owner:** hilangkan dari sidebar Live; backend/halaman/API **wajib** tetap |
| Laporan Produksi | V3 | Fungsi operasional wajib (laporan) — sidebar masih ada (**PENDING** penyederhanaan) |
| Cetak Slip Gaji | V3 | Fungsi operasional wajib (payroll) — sidebar masih ada (**PENDING**) |
| Log History | V3 | Fungsi tambahan sah — sidebar masih ada (**PENDING**) |
| “Pilihan” | — | **Bukan** menu sidebar; copy filter/Kolom Tampil — **PENDING OWNER** klarifikasi |
| Kontrol Produksi | Sandbox only | Preview-only / legacy simulasi — **jangan port ke Live** (F2) |
| Workflow End-to-End | Sandbox only | Preview-only sandbox |

**Pilihan:** A / B / C / **D (parsial F2)**  **Status:** **PARTIAL OWNER**
**Rekomendasi agent:** lanjutkan **D** — Final-7 + V3-extra kecuali Master Mesin tidak di sidebar; tolak `control` sandbox; tunggu Owner untuk Overview/Laporan/Slip/History dan istilah “Pilihan”.

Bukti visual: `F-SC02-*-menu*.png`, contact sheet HTML; F2: `F2-sidebar-no-mesin-*.png`, `F2-pilihan-filter-not-menu.png`.

---

### SC-03 — Paket JavaScript / tooling

| # | Isi |
|---|---|
| 1–3 | SC-03 · 0-Source · Paket JS referensi |
| 4 Handoff | `v3_frontend.js` tunggal |
| 5 Sandbox | `settings.js` + `workflow.js` + inline |
| 6 V3 | `live-runtime.js` + helper scripts |
| 7–9 | Tooling/test beda; perilaku sheet beda; risiko regresi tinggi jika diganti bulk |
| 10 Rekomendasi | **C** — V3 runtime; handoff sebagai kontrak kolom/UX |
| 11–12 | A/B: rewrite besar tanpa manfaat operasional |
| 13 | Paket referensi resmi mana untuk parity UI |

**Pilihan:** A / B / C / D  **Status:** PENDING OWNER
**Rekomendasi agent:** **C**.

---

### SC-04 — Demo / mutasi / fixture

| # | Isi |
|---|---|
| 1–3 | SC-04 · 0-Source · Zero-demo Live |
| 4 Handoff | 0 demo mutasi; viewer READ-ONLY; API bisnis 503 |
| 5 Sandbox | Banyak jalur demo/fixture/audit; SQLite simulasi |
| 6 V3 | Live: demo diblokir; Preview fixture hanya `?epv3_preview=fixture` (terisolasi) |
| 7–8 | Risiko tinggi jika demo bocor ke Live; bisnis gate bisa dikotori |
| 9 | Preview vs Live harus jujur dilabeli |
| 10 Rekomendasi | **C** selaras semangat **A** (zero-demo Live) |
| 11 Risiko A murni | OK untuk kebijakan; jangan mengganti V3 API |
| 12 Risiko B | Demo→Live |
| 13 | Konfirmasi kebijakan zero-demo Live |

**Pilihan:** A / B / C / D  **Status:** PENDING OWNER
**Rekomendasi agent:** **C** (+ kontrak A: tidak ada mutasi demo di Live).

---

### SC-05 — Label finansial vs gate produksi

| # | Isi |
|---|---|
| 1–3 | SC-05 · 0-Source / E-Payment · Status finansial |
| 4 Handoff | `INTEGRATION_CONTRACT`: `Belum Bayar\|Sebagian\|Lunas` **finansial**; terpisah dari `approval_source` |
| 5 Sandbox | UI historis Belum/Sebagian/Lunas (tanpa kontrak Outstanding Accurate penuh) |
| 6 V3 | `financial_payment_status=UNKNOWN`; outstanding tidak dipetakan; **bukan PAID/Lunas palsu** |
| 7–8 | Menyamakan UNKNOWN→Lunas melanggar kejujuran keuangan |
| 9 | Label V3 kurang “akuntansi klasik”, lebih jujur |
| 10 Rekomendasi | **C** sampai kontrak Outstanding Accurate disetujui Owner |
| 11 Risiko A | Memakai label Lunas tanpa mapping receivable = menyesatkan |
| 12 Risiko B | Sama + data demo |
| 13 | Setujui UNKNOWN≠PAID vs meniru label sandbox/handoff setelah Accurate settlement |

**Pilihan:** A / B / C / D  **Status:** PENDING OWNER
**Rekomendasi agent:** **C** (pertahankan UNKNOWN).

Bukti: `F-SC-payments-V3.png` menampilkan Status finansial: UNKNOWN.

---

### SC-06 — Artefak dokumentasi yang mengikat

| # | Isi |
|---|---|
| 1–3 | SC-06 · 0-Source · Artefak audit/kontrak |
| 4 Handoff | `INTEGRATION_CONTRACT.md`, `test_final.py` |
| 5 Sandbox | Banyak `AUDIT_V*` historis |
| 6 V3 | `docs/` repo (final audit, readiness, SC decisions) |
| 7–9 | Jejak audit; tidak mengubah runtime langsung |
| 10 Rekomendasi | **D:** Handoff contract = acuan API/field; sandbox AUDIT = historis non-binding; docs V3 = jejak keputusan Live |
| 11–12 | Memilih satu sumber saja menghapus jejak |
| 13 | Artefak mana yang mengikat untuk integrasi |

**Pilihan:** A / B / C / D  **Status:** PENDING OWNER
**Rekomendasi agent:** **D** (handoff contract + docs V3; sandbox AUDIT historis).

---

### SC-07 — Stamp APPROVED HTML Final

| # | Isi |
|---|---|
| 1–3 | SC-07 · 0-Source · Approval stamp |
| 4 Handoff | CANDIDATE — belum APPROVED |
| 5 Sandbox | Tidak ada stamp APPROVED |
| 6 V3 | Mengikuti CANDIDATE handoff sebagai acuan; tidak auto-APPROVED |
| 7–9 | Tanpa pin SHA, “Final locked” tidak sah |
| 10 Rekomendasi | **Proses Owner:** pin SHA + tanggal di register; jangan auto-APPROVED |
| 11–12 | A/B tanpa stamp = klaim palsu |
| 13 | Pin APPROVED SHA + tanggal + pengecualian |

**Pilihan:** (proses) pin SHA handoff / SHA lain / tunda
**Status:** PENDING OWNER
**Rekomendasi agent:** Tetap CANDIDATE sampai register ditandatangani; default pin handoff SHA di atas jika disetujui.

---

### MOD-kontrol — Halaman Kontrol Produksi sandbox

| # | Isi |
|---|---|
| 1–3 | MOD-kontrol · R-Kontrol · Kontrol Produksi |
| 4 Handoff | Tidak ada `data-page=control` |
| 5 Sandbox | Ada **Kontrol Produksi** — banner “SIMULASI LEGACY”; data SO-DEMO-* |
| 6 V3 | Tidak ada page `control`; ada Overview / labs terpisah |
| 7 Operasional | Sandbox control belum multi-SJ / bukti V1 lengkap |
| 8 Bisnis | Porting tanpa kontrak = risiko mutasi palsu |
| 9 UX | Sandbox punya halaman khusus; V3 memakai Overview + workflow resmi |
| 10 Rekomendasi | **C** — jangan port control sandbox; jangan hapus Overview |
| 11 Risiko A | N/A (handoff tidak punya) |
| 12 Risiko B | Demo control masuk Live |
| 13 | Apakah Kontrol sandbox wajib di Live |

**Pilihan:** A / B / C / D  **Status:** PENDING OWNER
**Rekomendasi agent:** **C**.

Bukti: `F-SC-control-SANDBOX.png` vs `F-SC-overview-V3.png`.

---

## 4. Aturan bisnis yang wajib dipertahankan (bukan subjek visual)

1. Prepare Screen ∥ Prepare Cup (paralel).
2. Sample gate per PRINT line.
3. Payment `UNKNOWN` ≠ `PAID` / Lunas palsu.
4. Buffer Live tanpa fixture fallback.
5. Scoped permission / branch.
6. Qty Helper dari PrepState; Prasyarat dari backend `reason`.
7. Idempotency & qty integrity.

Jangan mengubah aturan di atas hanya demi kesamaan visual HTML.

---

## 5. Ringkasan rekomendasi agent + status F2

| ID | Rekomendasi | Pilihan | Status F2 |
|---|---|---|---|
| SC-01 | V3 runtime; handoff = CANDIDATE UI/kontrak | **C** (+ acuan A) | PENDING OWNER |
| SC-02 | Final-7 + V3-extra; Mesin out of sidebar; tolak control | **D** parsial | **PARTIAL OWNER** |
| SC-03 | Tetap live-runtime | **C** | PENDING OWNER |
| SC-04 | Zero-demo Live | **C** (~A) | PENDING OWNER |
| SC-05 | UNKNOWN sampai settlement Accurate | **C** | PENDING OWNER (aturan V3 dipertahankan) |
| SC-06 | Contract handoff + docs V3 | **D** | PENDING OWNER |
| SC-07 | Pin SHA via register; jangan auto-APPROVED | proses Owner | PENDING OWNER (CANDIDATE) |
| MOD-kontrol | Jangan port; keep Overview | **C** | PENDING OWNER |

Hanya SC-02 yang punya keputusan Owner **eksplisit parsial** di F2. Lainnya **jangan** diubah menjadi BERBEDA DISETUJUI.

---

## 5b. Audit residual aturan bisnis (F2) — gate keputusan

Kontrak data / readiness (lihat juga `production-live-readiness-audit.md`):

| Topik | V3 saat ini (bukti teknis) | Status |
|---|---|---|
| Accurate real read-only | Live writes Accurate dilarang; read path bergantung gateway | BLOCKED / kontrak Outstanding belum penuh |
| SJ list-all | Belum tersedia sebagai sumber Delivery 8 kolom | BLOCKED |
| Delapan kolom Delivery | Inventaris 8× COL-delivery-* = BLOCKED | BLOCKED — butuh mapping Signer/Accurate |
| Status pembayaran finansial | `financial_payment_status=UNKNOWN`; gate ≠ settlement | Aturan V3 dipertahankan; SC-05 PENDING formal |
| Revisi/cancel SO | Perilaku Live vs V1 belum dipin di F2 | PENDING OWNER (lihat BR-F2 di bawah) |
| Authorization enforced | Production authz = **legacy** (PR #14 HOLD) | PENDING OWNER — jangan auto-activate |
| Grant manual per cabang | Scoped; no auto-grant | Aturan dipertahankan |
| Backup/restore | Prosedur ops di luar HTML shell | PENDING OWNER (prosedur tertulis) |

Tidak ada perubahan business rule di F2 selain menu yang sudah diputus.

---

## 6. Bukti visual

| Kelompok | File |
|---|---|
| Contact sheet | `/opt/cursor/artifacts/F-CONTACT-SHEETS.html` |
| Menu trio | `F-SC02-HANDOFF-menu-inbox.png`, `F-SC02-SANDBOX-menu.png`, `F-SC02-V3-menu-inbox.png` |
| Schedule trio | `F-SC-schedule-{HANDOFF,SANDBOX,V3}.png` (+ 1440) |
| Payments | `F-SC-payments-{HANDOFF,V3}.png` |
| Kontrol | `F-SC-control-SANDBOX.png`, `F-SC-overview-V3.png` |
| V3-extra | `F-SC-mesin-V3.png`, `F-SC-laporan-V3.png`, `F-SC-slip-V3.png`, `F-SC-history-V3.png` |
| Evidence JSON | `/tmp/epv3-fase-f-visual-evidence.json` |

---

## 7. Yang dibutuhkan dari Direktur

1. Lengkapi A/B/C/D untuk SC yang masih PENDING (SC-01, 03–07, MOD-kontrol; SC-02 sisa V3-extra).
2. Pin SHA HTML APPROVED (atau tunda) — handoff `d612eaa0…5bb0ba` masih CANDIDATE.
3. Klarifikasi istilah **“Pilihan”** (lihat BR-F2-01).
4. Konfirmasi nasib Overview / Laporan / Slip / History di sidebar.
5. Konfirmasi residual bisnis BR-F2-02…BR-F2-06 di bawah.

Setelah ditandatangani → baru boleh mengubah klasifikasi SC→SESUAI/BERBEDA DISETUJUI pada inventaris 202.

---

## 8. Pertanyaan F2 — format KEPUTUSAN DIREKTUR

### BR-F2-01 — Istilah “Pilihan”

```
KEPUTUSAN DIREKTUR DIBUTUHKAN

ID: BR-F2-01
Modul: Navigasi Live / filter sheet
Masalah: Arahan “hilangkan menu Pilihan” — di Live tidak ada item sidebar bernama Pilihan.
Aturan V1: (tidak diverifikasi sebagai menu terpisah di audit F2)
Aturan V3: “pilihan” = copy UI filter nilai kolom & “Kolom Tampil” (bukan nav)
Pilihan A: Konfirmasi tidak ada menu Pilihan → tidak ada aksi hapus tambahan
Pilihan B: Owner maksudkan kontrol lain (sebutkan label/lokasi) → hapus hanya kontrol itu
Rekomendasi: A — tahan filter/Kolom Tampil
Dampak: A aman operasional; B tanpa spesifikasi = risiko hapus kontrol pengguna
Pertanyaan kepada Direktur: Apakah “Pilihan” merujuk ke sesuatu di luar filter/Kolom Tampil? Jika ya, sebutkan layar + label persis.
```

Bukti: `/opt/cursor/artifacts/F2-pilihan-filter-not-menu.png`

### BR-F2-02 — V3-extra sisa di sidebar

```
KEPUTUSAN DIREKTUR DIBUTUHKAN

ID: BR-F2-02
Modul: Navigasi Live (SC-02 sisa)
Masalah: Master Mesin sudah keluar sidebar. Overview, Laporan Produksi, Cetak Slip Gaji, Log History masih ada.
Aturan V1: Final-7 fokus operasional inti (handoff)
Aturan V3: V3-extra operasional/payroll/history di sidebar
Pilihan A: Pertahankan keempat item di sidebar
Pilihan B: Final-7 only (pindahkan akses ke Pengaturan / deep-link berizin)
Rekomendasi: A sampai payroll/laporan punya jalur alternatif berizin
Dampak: B tanpa jalur alternatif memutus laporan/slip sehari-hari
Pertanyaan kepada Direktur: Apakah Overview / Laporan / Slip / History tetap di sidebar Live?
```

### BR-F2-03 — Delapan kolom Delivery + SJ list-all

```
KEPUTUSAN DIREKTUR DIBUTUHKAN

ID: BR-F2-03
Modul: Jadwal Pengiriman / Accurate SJ
Masalah: 8 kolom Delivery inventaris tetap BLOCKED; SJ list-all Accurate belum jadi sumber data Live.
Aturan V1: kolom pengiriman dari Accurate/SJ (kontrak historis)
Aturan V3: key/mapping absen → kolom tidak diisi palsu
Pilihan A: Tahan BLOCKED sampai signer Accurate + kontrak mapping
Pilihan B: Tampilkan placeholder/kolom kosong dengan label “belum terhubung”
Rekomendasi: A (jujur; tidak fabrikasi)
Dampak: A = gap operasional terlihat; B = risiko salah baca sebagai data valid
Pertanyaan kepada Direktur: Setujui tetap BLOCKED sampai mapping SJ list-all, atau izinkan UI placeholder eksplisit?
```

### BR-F2-04 — Label finansial UNKNOWN vs Belum/Sebagian/Lunas

```
KEPUTUSAN DIREKTUR DIBUTUHKAN

ID: BR-F2-04
Modul: Monitoring Penerimaan / SC-05
Masalah: Handoff/sandbox memakai label akuntansi; V3 memakai UNKNOWN sampai Outstanding Accurate.
Aturan V1 / handoff: Belum Bayar | Sebagian | Lunas (finansial) terpisah dari gate
Aturan V3: financial_payment_status=UNKNOWN; UNKNOWN≠PAID; gate produksi terpisah
Pilihan A: Pertahankan UNKNOWN sampai kontrak Outstanding
Pilihan B: Map ke Belum/Sebagian/Lunas setelah kontrak Outstanding disetujui
Rekomendasi: A sekarang; B hanya setelah kontrak data
Dampak: B tanpa kontrak = Lunas palsu
Pertanyaan kepada Direktur: Tetap UNKNOWN, atau jadwalkan mapping Outstanding dengan kontrak tertulis?
```

### BR-F2-05 — Authorization enforced vs legacy

```
KEPUTUSAN DIREKTUR DIBUTUHKAN

ID: BR-F2-05
Modul: Authz production
Masalah: Production authorization masih legacy; PR #14 HOLD; F2 melarang auto-activation enforced.
Aturan V1: (opsional enforced per lingkungan)
Aturan V3: legacy aktif; enforced belum diaktifkan di Live
Pilihan A: Tetap legacy sampai Owner + prosedur grant cabang siap
Pilihan B: Aktifkan enforced (butuh runbook grant manual per cabang + rollback)
Rekomendasi: A — jangan auto-activate
Dampak: B prematur = lockout operator / grant darurat
Pertanyaan kepada Direktur: Kapan (dan dengan checklist apa) enforced boleh diaktifkan?
```

### BR-F2-06 — Revisi/cancel SO + backup/restore

```
KEPUTUSAN DIREKTUR DIBUTUHKAN

ID: BR-F2-06
Modul: Inbox / SO lifecycle / ops
Masalah: Kontrak perilaku revisi/cancel SO Accurate→V3 dan prosedur backup/restore Live belum dipin di F2.
Aturan V1: bergantung ERP/Accurate (perlu konfirmasi Owner)
Aturan V3: tidak mengubah business rule di F2 tanpa approval
Pilihan A: Audit-only lanjut; dokumentasikan prosedur sebelum ubah produk
Pilihan B: Owner berikan kontrak tertulis sekarang (langkah revisi/cancel + RPO backup)
Rekomendasi: A kecuali Owner menyerahkan kontrak B
Dampak: mengubah tanpa kontrak = risiko mutasi SO / kehilangan data
Pertanyaan kepada Direktur: Apakah ada SOP tertulis revisi/cancel SO dan backup/restore yang harus diikuti V3 sekarang?
```
