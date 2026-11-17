# Register Persetujuan HTML Final — Rancangan

**Status register:** `APPROVED` (acuan UI — Handoff SHA dipin Owner sprint)
**Tanggal dibuat (WIB / Asia/Jakarta):** 2026-11-17
**Revisi F2 (WIB):** 2026-11-17 — keputusan menu parsial tercatat
**Revisi Blocker Sprint (WIB):** 2026-11-17 — Direktur pin Handoff sebagai HTML APPROVED acuan UI
**Tanggal approval:** 2026-11-17 (Asia/Jakarta)
**Penandatangan Direktur:** Owner decision (Blocker Resolution Sprint)

**V3 HEAD acuan:** `36abda196e8a627dc9d6ed5d4778830feb5a0201`
**WIP F2:** sidebar Live tanpa Master Mesin (`production.html`, belum commit)
**PR #15:** OPEN · **PR #14:** HOLD · **Authz production:** legacy

Paket keputusan: [`production-html-final-approval-decision-package.md`](./production-html-final-approval-decision-package.md)

> Dokumen ini adalah **rancangan**. Mengisi kolom approval tanpa keputusan Direktur = pemalsuan stamp — **dilarang**.
> F2: Handoff SHA tetap **CANDIDATE** sampai Direktur pin SHA + pengecualian secara eksplisit.

---

## 1. Versi HTML kandidat

| Field | Nilai |
|---|---|
| Versi / label | Eternal Packaging V3 — Final Handoff (CANDIDATE) |
| Path | `/tmp/epv3-fase3-handoff/index.html` |
| SHA-256 | `d612eaa0f5b75037a80f20d92861916d30e10b8fc8b8ef600b02d8738d5bb0ba` |
| Aset JS | `v3_frontend.js` |
| Kontrak | `INTEGRATION_CONTRACT.md` |
| Status saat ini | **APPROVED** sebagai acuan UI (runtime V3 tetap) |

| Field | Nilai |
|---|---|
| Versi / label | Eternal Production Sandbox V2.x |
| Path | `/tmp/epv3-fase3-sandbox/index.html` |
| SHA-256 | `b25e601e872442f332ced1c45eddb29f86f012d75fa5e6981991f9031d2dd25a` |
| Status | Prototipe lokal / historis — **bukan** kandidat APPROVED default |

| Field | Nilai |
|---|---|
| Implementasi Live | `frontend/public/production.html` + `live-runtime.js` |
| Git SHA | `36abda196e8a627dc9d6ed5d4778830feb5a0201` |
| Peran | Evidence implementasi — **bukan** aturan otomatis |

**SHA APPROVED (Owner pin):**
`d612eaa0f5b75037a80f20d92861916d30e10b8fc8b8ef600b02d8738d5bb0ba` (handoff)
**Keputusan Owner:** handoff APPROVED sebagai acuan UI; V3 runtime dipertahankan; sandbox bukan acuan.

---

## 2. Delapan keputusan (isi oleh Direktur)

| ID | Pilihan (A/B/C/D) | Catatan Owner | Status |
|---|---|---|---|
| SC-01 Struktur shell | **C (+A UI)** | V3 runtime; handoff = acuan UI APPROVED | **OWNER** |
| SC-02 Set menu | **D** | Master Mesin keluar sidebar; Overview/Laporan/Slip/History tetap; Filter & Kolom Tampil tetap | **OWNER** |
| SC-03 Paket JS | **C** | Tetap live-runtime | **OWNER** (implisit runtime) |
| SC-04 Demo/fixture Live | **C** | Zero-demo Live | **OWNER** (implisit) |
| SC-05 Label finansial | **D** | Accurate/outstanding terverifikasi → Belum/Sebagian/Lunas; fallback **UNKNOWN** | **OWNER** |
| SC-06 Artefak mengikat | **D** | Handoff contract + docs V3 | **OWNER** (implisit) |
| SC-07 Stamp APPROVED | pin handoff | SHA `d612eaa0…5bb0ba` | **OWNER** |
| MOD-kontrol | **C** | Jangan port Kontrol sandbox → Live | **OWNER** |

Kode: **A** handoff · **B** sandbox · **C** V3 · **D** kombinasi (wajib rinci).

**Usulan agent (bukan approval penuh):** SC-01 C(+A) · SC-02 D (Master Mesin out of sidebar; sisanya pending) · SC-03 C · SC-04 C · SC-05 C · SC-06 D · SC-07 pin handoff SHA · MOD-kontrol C.

---

## 3. Fitur yang dikecualikan dari “persamaan visual penuh”

Sampai Owner mengubah:

1. Label finansial **UNKNOWN** (bukan Lunas/PAID palsu) hingga Outstanding Accurate dikontrak.
2. Halaman **Kontrol Produksi** sandbox (simulasi legacy) — tidak di-port ke Live.
3. Menu **Workflow End-to-End** sandbox — preview-only.
4. Mutasi demo / fixture sebagai jalur Live.
5. Delapan kolom Delivery BLOCKED (Accurate) — di luar HTML shell.

---

## 4. Menu V3 yang dipertahankan (usulan)

**Final-7**
- Inbox Accurate
- Monitoring Penerimaan
- Jadwal Produksi
- Tugas Tim
- Jadwal Pengiriman
- Monitoring Buffer
- Pengaturan

**V3-extra operasional**
- Overview — masih di sidebar (**PENDING** Final-7-only)
- Master Mesin — **F2 Owner:** dihilangkan dari sidebar Live; halaman + API + Pengaturan tab **dipertahankan**
- Laporan Produksi — masih di sidebar (**PENDING**)
- Cetak Slip Gaji — masih di sidebar (**PENDING**)
- Log History — masih di sidebar (**PENDING**)

**Keputusan Owner menu Live (Blocker Sprint):**
☑ **Lain:** Final-7 + Overview + Laporan + Slip + History; Master Mesin **tidak** di sidebar; akses mesin via Pengaturan / `go('machineMaster')` / API

**Filter / Kolom Tampil / “Pilihan”:** dipertahankan (bukan menu hapus).

---

## 5. Referensi aturan bisnis terbaru (tidak dinegosiasikan oleh visual)

- Prepare Screen ∥ Prepare Cup
- Sample gate per baris PRINT
- Payment gate ≠ settlement Accurate; UNKNOWN ≠ PAID
- Buffer Live tanpa fixture
- Permission + branch scoped
- Qty Helper = PrepState helper; Prasyarat tugas = `reason` backend
- Idempotency / qty integrity

---

## 6. Jejak approval (diisi saat disetujui)

| Field | Nilai |
|---|---|
| Nama Direktur | |
| Tanggal & zona waktu | |
| SHA HTML APPROVED | |
| Pengecualian tertulis | |
| Tanda tangan / konfirmasi tertulis | |
| Status akhir | `APPROVED` (UI acuan Handoff SHA di atas; pengecualian: UNKNOWN finansial tanpa outstanding terverifikasi; 8 kolom Delivery tanpa data = "Belum terhubung"; Kontrol sandbox tidak di Live) |

---

## 7. Pernyataan

Register ini **tidak** mengubah klasifikasi 8 SOURCE CONFLICT pada inventaris 202 sampai baris di atas berstatus APPROVED oleh Direktur.
