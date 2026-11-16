# Reskin HTML Final — Iterasi 2 (Global Shell)

**Diperbarui:** 2026-11-16 (Asia/Jakarta)  
**HEAD basis:** `8410a1be2b6cf1f52948e543967c8aae3aeeadab`  
**Status:** WIP lokal · Iter2 + visual polish · **NO COMMIT**  
**Authz:** legacy · PR #15 OPEN · PR #14 HOLD

## Visual polish (lanjutan Iter2)
- Root cause menu “putih”: base `.navbtn span:last-child` memberi background abu pada **label** (bukan hanya badge).
- Reset: label/icon transparan; hanya `.nav-count` berlatar `#1a4036`.
- Active tetap `#214c3c` + inset `#32ca8b`; idle transparan di sidebar gelap.
- Collapsed rail 65px · ikon ~17px · `title` tooltip · handle menempel.
- Header 68px tanpa overflow (sinkronisasi panjang disembunyikan ≤1440; API/Gateway tetap).
- Jadwal: chrome dipadatkan; notice panjang / sheet-guidance disembunyikan ke Panduan; KPI 5 kolom satu baris di desktop; `sheetwrap` lebih tinggi.

## Design tokens Global Shell (Handoff → V3)

| Token | Handoff Final | V3 sebelum Iter2 | Target Iter2 |
|-------|---------------|------------------|--------------|
| Sidebar BG | `#102d27` | putih `#fff` | `#102d27` |
| Sidebar width | `226px` / shrink `65px` | `218–226px` / collapse `0` | `226px` / rail `65px` |
| Nav text | `#bfd6cd` | `#4f6573` | `#bfd6cd` |
| Nav active | `#214c3c` + inset `#32ca8b` | hijau muda `#e9f5ef` | Final |
| Brandmark | `#158a62` 32px r9 | `#055b42` 34px r10 | Final |
| Topbar | `68px` putih | `47–65px` | `68px` |
| Collapse control | panah di tepi sidebar | `#v44-sidebar-handle` fixed mengambang | absolute menempel sisi `.side` |
| Font shell | 13px | 13px (+ readable floor) | tidak diubah kontrak |

## Perbandingan Handoff vs V3

| Aspek | HTML Final | V3 sebelum | Iter2 |
|-------|------------|-----------|-------|
| Sidebar gelap | ya | tidak | **ya** |
| Collapse icon-rail | ya (`shrink` 65px) | hilang total (width 0) | **rail 65px**, nav tetap klik |
| Handle | menempel sidebar / topbar collapse | fixed ke konten | **di dalam aside**, `right:-13px` |
| Header crumb + cabang + user | topbar Final | crumb + sync saja | crumb halaman + chip cabang + chip sesi dari `__V3_AUTH__` |
| Status gateway | dari backend | label jujur MEMERIKSA/BELUM | **dipertahankan** (tidak diada-adakan) |
| Menu set | ringkas Final | V3 lengkap (Overview…Pengaturan) | **semua menu V3 tetap** |
| Toolbar Jadwal | KPI lalu tools | sheetbar di atas overview | overview/bucket/KPI **di atas** sheetbar; spacing dipadatkan |
| F3-039 penuh | — | BLOCKED | tetap **BLOCKED** |

## Risiko residual
- Nama label nav V3 ≠ salinan teks Final (tetap grup OPERASIONAL/MONITORING/LAPORAN).
- Modul selain shell (Inbox sheet Final, dll.) belum di-reskin.
- Accurate Gateway kosong → acceptance fungsional inbox/SJ tidak diklaim.
