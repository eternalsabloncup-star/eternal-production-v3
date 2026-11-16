# Manifest Aset HTML Final (Fase 3)
**Diperbarui:** 2026-11-16 (Asia/Jakarta)
**Status:** referensi saja — TIDAK di-wire ke runtime V3. NO COMMIT aset berisiko.

## Ringkasan
- **handoff**: 10 file di `/tmp/epv3-fase3-handoff`
- **sandbox**: 26 file di `/tmp/epv3-fase3-sandbox`
- Konflik path sama (SHA beda): **3**
- Risiko terdeteksi: **18** entri
- Rekomendasi salin aman ke docs/reference: **7** file

## Konflik Handoff vs Sandbox
- `README.md` — Handoff `cbf1d4d48fae…` vs Sandbox `ca90e03ea026…` · Handoff utama untuk UI Final; Sandbox V22 pelengkap audit/workflow — jangan merge buta
- `index.html` — Handoff `d612eaa0f5b7…` vs Sandbox `b25e601e8724…` · Handoff utama untuk UI Final; Sandbox V22 pelengkap audit/workflow — jangan merge buta
- `server.py` — Handoff `10b87e64255d…` vs Sandbox `cb87bac83544…` · Handoff utama untuk UI Final; Sandbox V22 pelengkap audit/workflow — jangan merge buta

## Risiko (jangan commit tanpa review)
- [handoff] `README.md` → local_url
- [handoff] `REFERENSI_SURAT_JALAN_ACCURATE.pdf` → binary_or_large
- [handoff] `server.py` → local_url
- [handoff] `v3_frontend.js` → credential_or_token_pattern
- [sandbox] `AUDIT_FIX_V17.md` → local_url
- [sandbox] `AUDIT_UI_TOMBOL_V1_V19.md` → credential_or_token_pattern, local_url
- [sandbox] `AUDIT_WORKFLOW_V1_V16.md` → credential_or_token_pattern, local_url
- [sandbox] `README.md` → credential_or_token_pattern, local_url
- [sandbox] `README_V22.md` → local_url
- [sandbox] `_check_inline.js` → credential_or_token_pattern, possible_pii, local_url
- [sandbox] `assets/login-production.png` → binary_or_large
- [sandbox] `index.html` → credential_or_token_pattern, possible_pii, local_url
- [sandbox] `server.py` → credential_or_token_pattern, local_url
- [sandbox] `settings.js` → credential_or_token_pattern
- [sandbox] `settings_data.py` → credential_or_token_pattern
- [sandbox] `test_flow_e2e.py` → credential_or_token_pattern, local_url
- [sandbox] `test_po_reference.py` → credential_or_token_pattern, local_url
- [sandbox] `test_sandbox.py` → credential_or_token_pattern, local_url

## Keputusan salin
Tidak menyalin aset ke repo pada checkpoint ini (NO COMMIT). Manifest JSON: `docs/fase3-html-final-asset-manifest.json`.
PDF SJ Accurate dan file besar/binari tetap di `/tmp` saja.
