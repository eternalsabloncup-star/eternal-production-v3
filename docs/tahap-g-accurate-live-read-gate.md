# Tahap G — Accurate Live Read Gateway Unblock

**Tanggal (WIB / Asia/Jakarta):** 2026-11-17  
**HEAD baseline:** `36abda1` · **PR #15 OPEN** · **PR #14 HOLD**  
**Mode:** lokal + instruksi operator · **NO COMMIT / NO DEPLOY / NO LIVE WRITES**

## Verdict singkat

**GATEWAY STATUS: BLOCKED** untuk Live Read dari Cloud Agent ini.  
Secrets Accurate **tersimpan & bound** di Cursor App Secrets, tetapi **tidak di-inject** ke VM agent (`CLOUD_AGENT_INJECTED_SECRET_NAMES` hanya `ETERNAL_ACTIONS_TOKEN`). Port `127.0.0.1:8091` **CLOSED**.

## Service yang benar

| Item | Nilai |
|---|---|
| Kode | `accurate-gateway/` (FastAPI read-only) |
| Entrypoint | `accurate-gateway/app/main.py` → uvicorn port **8091** |
| Compose | `docker-compose.yml` service `accurate-gateway` → `127.0.0.1:8091` |
| Health | `GET /health` (no auth) |
| Auth data | `Authorization: Bearer <GATEWAY_M2M_TOKEN>` |
| Endpoints | `/sales-orders`, `/sales-orders/{key}`, `/receipts/{id}`, `/delivery-notes/{id}` |
| Mode | `GATEWAY_MODE=fixture` (CI) · `live` (opsional, fail-closed tanpa creds) |

## Matrix secrets (nilai tidak dicetak)

| Name | Agent env | Cursor App Secret bound | Dibutuhkan Live |
|---|---|---|---|
| `ACCURATE_API_TOKEN` | MISSING | yes | ya |
| `ACCURATE_SIGNATURE_SECRET` | MISSING | yes | ya |
| `GATEWAY_M2M_TOKEN` | MISSING | yes | ya |
| `V3_ACCURATE_READ_GATEWAY_TOKEN` | MISSING | yes | ya (= M2M) |
| `V3_ACCURATE_READ_GATEWAY_URL` | MISSING | yes | ya (`http://127.0.0.1:8091` same-host) |
| `GATEWAY_MODE` | MISSING | n/a | harus `live` untuk probe |
| `ACCURATE_DATABASE_ID` | MISSING | bound (opsional) | pin opsional |

## Perbaikan lokal Tahap G (tanpa credentials nyata)

1. Gateway DN normalize: pass-through Final-8 field jika Accurate mengirim (phone/outlet/printed/signers) — **tidak mengarang**.
2. V3 ops SO-link: memetakan field tersebut ke baris Delivery; kosong → **Belum terhubung**.
3. Contract tests Final-8 + fail-closed live probe.
4. Runbook operator di bawah (read-only vs change).

## Instruksi operator (VPS / staging) — jangan mengubah VPS tanpa approval

### A. Read-only (aman sekarang)

```bash
# Di host V3 (setelah gateway unit ada):
curl -sS http://127.0.0.1:8091/health
# Harapkan JSON: mode, live_credentials_present, live_verified=false, read_only=true
# Jangan cetak EnvironmentFile / token.
```

### B. Mengubah service (butuh approval Owner)

1. Buat `/etc/epv3/epv3.env` mode `600` (placeholder di bawah — isi dari Cursor Secrets, **bukan** chat).
2. Pastikan `GATEWAY_M2M_TOKEN` **sama** dengan `V3_ACCURATE_READ_GATEWAY_TOKEN`.
3. Pastikan `V3_JWT_SECRET` ≠ `V3_PASSWORD_PEPPER`.
4. Systemd `EnvironmentFile=/etc/epv3/epv3.env` untuk `epv3-accurate-gateway` + `epv3-api`.
5. Bind gateway `127.0.0.1:8091` saja.
6. Restart unit → cek `/health` → `mode=live`, `live_credentials_present=true`.
7. Di host itu: `GATEWAY_MODE=live python3 scripts/phase5_live_probe.py` (sanitized evidence only).

### Placeholder env (jangan isi di chat/PR)

```
GATEWAY_MODE=live
GATEWAY_HOST=127.0.0.1
GATEWAY_PORT=8091
GATEWAY_M2M_TOKEN=<FROM_CURSOR_SECRET>
V3_ACCURATE_READ_GATEWAY_TOKEN=<SAME_AS_GATEWAY_M2M_TOKEN>
V3_ACCURATE_READ_GATEWAY_URL=http://127.0.0.1:8091
ACCURATE_API_TOKEN=<FROM_CURSOR_SECRET>
ACCURATE_SIGNATURE_SECRET=<FROM_CURSOR_SECRET>
ACCURATE_ACCOUNT_BASE=https://account.accurate.id
# ACCURATE_DATABASE_ID=<optional pin>
V3_JWT_SECRET=<FROM_CURSOR_SECRET>
V3_PASSWORD_PEPPER=<FROM_CURSOR_SECRET_DIFFERENT>
V3_ACCURATE_EVIDENCE_ENFORCE=true
```

## Final-8 Delivery mapping status

| Field | Gateway normalize | V3 ops | Status |
|---|---|---|---|
| customer_phone | pass-through jika Accurate kirim | SO-link map / else Belum terhubung | **READY when DN supplies** |
| outlet | pass-through / branch name | sama | **READY when DN supplies** |
| sj_printed_at | printDate/printedAt/lastPrintDate | sama | **READY when DN supplies** |
| item_outlets | line outlet (jika ada) → agregasi ops | Belum terhubung jika kosong | **NEEDS Accurate line outlet** |
| warehouse_signer | pass-through key kandidat | sama | **NEEDS Accurate field proof** |
| goods_checker | pass-through key kandidat | sama | **NEEDS Accurate field proof** |
| courier_signer | pass-through key kandidat | sama | **NEEDS Accurate field proof** |
| recipient_signer | pass-through key kandidat | sama | **NEEDS Accurate field proof** |

**SJ list-all:** tetap **tidak ada** — hanya `GET /delivery-notes/{id}` + SO `links.delivery_note_ids`.

**Outstanding / status pembayaran finansial:** tidak ada endpoint receivable di gateway — fallback **UNKNOWN** sampai feed Accurate dikontrak (hook V3 sudah ada).

**BR-F2-06R:** PENDING — alur faktur tidak diubah.

## Satu tindakan Owner berikutnya (paling penting)

**Inject tujuh secret Accurate/M2M/URL ke Cloud Agent environment ini** (atau salin ke `/etc/epv3/epv3.env` di host staging V3 + start `epv3-accurate-gateway` di `127.0.0.1:8091`), lalu jalankan ulang Tahap G / `phase5_live_probe.py` di lingkungan yang punya credentials — **tanpa** paste nilai ke chat.
