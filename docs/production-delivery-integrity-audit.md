# Production Delivery Integrity Audit — Function First Iterasi 2

**Tanggal (WIB / Asia/Jakarta):** 2026-11-16
**Repository:** `eternalsabloncup-star/eternal-production-v3`
**Branch:** `cursor/epv3-production-schedule-83bf`
**BASE HEAD (preflight):** `0d98dca659bfbbcc7363b0336b7fa8111deb0f39`
**Worktree:** `/tmp/epv3-fase1b-wt`
**Authz Production:** `legacy` (enforced **tidak** diaktifkan)
**PR #15:** OPEN · **PR #14:** HOLD
**Git putaran ini:** checkpoint commit Function First Iterasi 2 (Delivery Integrity)

---

## 1. Canonical flow (Output → POD)

```
Output (operator, output_confirmed)
  → Verification (helper, output_helper_verified)  [ceiling ≤ net output per source event]
  → Packing (packing_batch)                        [ceiling ≤ min helper-verified − reject]
  → Loading (loading)                              [ceiling ≤ SJ line PCS ∩ packing sisa]
  → POD (pod + 4 attachments)                      [ceiling ≤ net loading − prior POD]
```

Sumber otoritas: `backend/app/services/production/engine.py`
Endpoint: `workflow.py` (`/outputs`, `/helper-verifications`, `/packing`, `/loading`, `/pod`).

---

## 2. Quantity semantics (satuan canonical = PCS fisik)

| Qty | Arti | Event / sumber | Catatan |
|---|---|---|---|
| Output | Qty fisik operator | `output_confirmed` ± `output_correction` | Bukan stok packing |
| Verified | Qty lolos pemeriksaan helper | `output_helper_verified` | Per source output; multi-warna = **min** pass |
| Reject | Qty ditolak terverifikasi | `reject_verified` | Mengurangi eligible packing |
| Packed | Qty kemasan / siap gudang | `packing_batch` (+ alias `packing_recorded`) | Print: dari verified; non-print: konfirmasi gudang ≤ PO |
| Loaded | Qty loading terkonfirmasi | `loading` − `loading_cancelled` | Multi-SJ per baris; UOM PCS wajib |
| Delivered | Qty diterima (POD) | `pod` | Wajib 4 attachment; ≠ bukti frontend saja |

**Invariant (PCS sebanding, tanpa reversal outstanding):**

`Delivered ≤ Loaded ≤ Packed ≤ Verified ≤ Output` (Verified = min across required color passes − reject).

Tidak ada konversi dus/PCS di kontrak packing — jangan mengarang kapasitas dus.

---

## 3. Gap & implementasi Iterasi 2

| ID | Severity | Root cause | Dampak | File/endpoint | Implementasi | Test evidence | Residual |
|---|---|---|---|---|---|---|---|
| DI-01 | **P0** | Packing menginvent `process=print` bila klasifikasi unknown dan flag fixture off | Barang unclassified bisa dipacking | `engine.record_packing` | Selalu 409 `_UNCLASSIFIED_PACKING` | `test_unknown_process_packing_always_rejected` | — |
| DI-02 | **P0** | Loading readiness unknown ikut opt-out fixture | Loading bisa lolos tanpa klasifikasi resmi | `engine._physical_readiness_qty` | Unknown selalu `unknown_process` | mixed + iter2 | Missing-line masih opt-out legacy fixture |
| DI-03 | **P0** | Mutasi delivery/output tidak memanggil `require_job_active` | Job cancelled masih bisa pack/load/POD | output/verify/pack/load/POD/cancel paths | `require_job_active` di mutasi | `test_cancelled_job_blocks_packing_loading_pod` | Baca histori tetap boleh |
| DI-04 | **P1** | Helper verify / packing: IntegrityError selalu 409, tidak return identical replay | Retry HTTP → 409 palsu / risiko UX | `record_helper_output_verification`, `record_packing` | Identical → 200 prior; mismatch → 409 | p1 helper + iter2 + mixed non-print replay | Concurrency race path diuji via IntegrityError return |
| DI-05 | P1 (existing) | Soft-cancel job setelah progress fisik = BLOCKED; tidak ada auto-reversal packing/loading/POD | Operator tidak bisa “batal bersih” setelah packing | `lifecycle.classify_cancel_gate` | Tidak diubah — tolak eksplisit | multi_sj cancel-after-POD | Reversal Accurate/stok out of scope |
| DI-06 | **BLOCKED P0** | Accurate SJ list-all belum terbukti | Coverage SJ terbatas | Accurate gateway | Tidak dikarang | — | Label **COVERAGE TERBATAS** |
| DI-07 | **BLOCKED P0** | Enforced Live | Authz cutover | PR #14 HOLD | Tidak diaktifkan | — | Staging enforced disposable saja |

---

## 4. Permission (legacy)

- Role tanpa grant / wrong branch → **403** (`test_permission_negative_packing_and_loading`).
- Tidak ada auto-grant pengguna existing.
- Mode Production tetap **legacy**.

---

## 5. Accurate

| Lapisan | Status |
|---|---|
| Fixture / stub SJ | Dipakai (pytest + browser mutation_server) |
| Sandbox write | Tidak dijalankan |
| Live write | **DILARANG** — tidak dilakukan |
| SJ list-all | **BLOCKED** — COVERAGE TERBATAS |

---

## 6. Browser E2E

- Script: `scripts/fase3_e2e_browser_mutation.mjs`
- API disposable: `:8013` · DB `epv3_e2e_bm_04ccee9116_test`
- Log: `/tmp/epv3-di-browser-mut3.log`
- Hasil: **11/11 PASS_MUTATION** (Output → Helper verify → Packing → Loading → POD + deny payment bypass)
- Partial / multi-SJ / retry: dibuktikan di API suite (`test_loading_pod_qty_chain_partial_multi_sj`, multi_sj suite) — browser harness satu jalur penuh, bukan semua cabang parsial UI.

---

## 7. Verdict putaran

**READY FOR STAGING** (smoke Owner) untuk jalur Delivery Integrity di mode legacy + fixture Accurate.
**NOT READY FOR LIVE** — Accurate SJ list-all + enforced masih BLOCKED.
