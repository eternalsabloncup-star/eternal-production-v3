# Reskin HTML Final — Iterasi 1 (Jadwal + Kontrol)

**Diperbarui:** 2026-11-16 (Asia/Jakarta)  
**HEAD basis:** `ac6be39b2ede2b2ee40261277b351dbb07b600b1`  
**Status:** WIP lokal · **NO COMMIT** pada putaran ini  
**Authz:** legacy · PR #15 OPEN · PR #14 HOLD

## Design tokens (Handoff Final → target)

| Token | Handoff Final | V3 sebelum | Target Iter1 |
|-------|---------------|------------|--------------|
| `--green` | `#13845c` | `#087b55` | `--final-green:#13845c` (scoped `#v3-app`) |
| Dark / thead | `#0b5139` / `#00563f` | `#055b42` / `#00513b` | `--final-dark` / `--final-thead:#00563f` |
| BG | `#f5f7f8` | `#f3f7f7` | tetap global; kartu KPI putih |
| Sidebar | gelap `#102d27` 226px | putih 218px | **belum** (modul shell = iter berikutnya) |
| KPI | `.final-kpi` card 12px radius, label 10px upper, value ~23px | strip kompak `.v44-production-metric` | kartu Final 5 kolom |
| Sheet thead | hijau tua + teks putih | abu / hijau sticky campuran | thead Final pada `section-schedule` |
| Font | 13px Inter | 13px Inter | sama |

## Perbandingan modul

| Aspek | HTML Final | V3 sekarang | Perubahan Iter1 |
|-------|------------|-------------|-----------------|
| Judul | Jadwal Produksi | Sheet Jadwal Produksi | → **Jadwal Produksi** |
| Kontrol | 4 kartu KPI halaman | strip + Status Kerja di live-runtime | kartu Final: Total Qty SO, Terjadwal, Sudah Cetak, Belum Selesai, Status Kerja; chip sekunder Belum Dijadwalkan + Baris Cetak |
| Menu Kontrol terpisah | tidak di Handoff FE ringkas | digabung di Jadwal | **dipertahankan** akses via `#scheduleOverview` / `#v3-kontrol-qty` |
| Sticky ID/Nama | ada | ada | tidak diubah kontrak |
| Bucket HOLD/filter | sandbox spreadsheet | live buckets | fungsi dipertahankan |
| Sumber angka | demo FE handoff | PG summary anti double-count | **tidak diubah** |

## Bukti yang masih PARSIAL
- Sidebar gelap Final belum diterapkan (risiko navigasi global).
- F3-039 reskin penuh tetap BLOCKED.
- Sticky body Inbox/SJ tetap bergantung Accurate.
