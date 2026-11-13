# Slice 1I — V1 business-rule parity (quantity integrity + capability registry)

## Baseline

`bbd180f` → this slice on `cursor/v49-live-phase1-3e4e` (Draft PR #2).

## Root causes fixed

1. **Packing event mismatch** — producers write `packing_batch`; team-task derive looked for `packing_recorded` → packing never marked done.
2. **Multi-color physical inflation** — packing / derive summed all `output_confirmed` passes → 2×5000 became 10000 packable.
3. **Live FLOW31 fallback** — Live mode could still synthesize tasks when official sync failed.
4. **Gap ERP V1 UI** — unconditional `BELUM` rows without evidence.

## Canonical contracts

| Concern | Rule |
|---|---|
| Packing event | Write `packing_batch`; consumers accept `{packing_batch, packing_recorded}` |
| Physical cups | `color_pass == 1` (+ corrections) only |
| Work-pass / payroll | Prefer `qty_pass_ops` |
| POD remaining | `loaded − prior pod` per SJ |
| POD multi-evidence | **BLOCKED** — single `evidence_ref` cannot prove 2 photos + 2 signatures without schema |

## Frontend

- Live Tugas Tim: official API only; explicit unavailable notice (no FLOW31).
- Capability registry in Pengaturan → Gap ERP V1.
- Jadwal sticky No PO + Pelanggan.

## No migration / no VPS / no merge
