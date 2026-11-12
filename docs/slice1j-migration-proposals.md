# Slice 1J — Migration proposals (BLOCKED FOR OWNER APPROVAL)

**Do not execute against VPS / staging / operational DBs.**

Baseline: `887ac2a` → Slice 1J on `cursor/v49-live-phase1-3e4e`.

Alembic head (current): `20261112_0006_slice1a_classification`.

---

## 1. POD multi-attachment evidence — BLOCKED

### Why

`ProductionEvent.evidence_ref` is a single `String(512)`. V1 requires:

- 2 delivery photos
- sender signature
- recipient signature
- recipient name (already on `reason` / `receiver_name`)

No attachment table, checksum, or file-ownership model exists. Encoding four opaque strings into one field does **not** prove integrity.

### Minimal schema proposal

```text
production_attachments
  id PK
  job_id FK → production_jobs
  event_id FK → production_events NULLABLE  -- bind after POD commit
  purpose  ENUM/str: pod_photo_1|pod_photo_2|pod_sig_sender|pod_sig_recipient|…
  storage_key  str  -- object store key owned by V3
  content_sha256  str
  content_type  str
  byte_size  int
  uploaded_by  int
  created_at  timestamptz

# Optional: ProductionEvent.pod_bundle_id FK for atomic POD groups
```

### Backfill / rollback

- Backfill: none required (new evidence only).
- Rollback: drop table; keep legacy `evidence_ref` readers.
- `record_pod` must require four attachment IDs with proven ownership before commit.

### Dependency

Object storage + upload API with authz/branch isolation (not present).

---

## 2. Screener Screen Kecil / Besar — BLOCKED field

### Why

`PrepState` / `PrepEvent` / `ScheduleAssignment` have no `screen_size` column. Frontend must not store size only in localStorage.

### Minimal schema proposal

```text
ALTER prep_states ADD screen_size VARCHAR(16) NULL;  -- kecil|besar
ALTER prep_events ADD screen_size VARCHAR(16) NULL;
-- Optional on schedule_assignments if size is planned at scheduling time
ALTER schedule_assignments ADD screen_size VARCHAR(16) NULL;
```

### Backfill

NULL = unknown (fail-closed for size-required reports; screener qty still works).

### Rollback

Drop columns; ignore size in API.

---

## 3. SLA working-day calendar — BLOCKED

### Why

No holiday / working-day table. Hardcoding 1/3/5 as universal promises is forbidden without Owner contract.

### Minimal schema proposal

```text
working_calendars (id, branch_id NULL=global, name, timezone)
working_calendar_days (calendar_id, day DATE, kind: work|holiday|exception, note)
production_sla_targets (job_id or so_line, basis_date, target_workdays, due_date, source: accurate_estimate|internal)
```

Accurate estimated delivery remains distinct from internal production deadline.

---

## 4. Payroll official posting — BLOCKED

Rates + compute-run APIs exist. Financial posting / wage mutation / operational payroll runs against real money require a separate Owner financial authorization contract — out of scope until approved.
