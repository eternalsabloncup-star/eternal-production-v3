# Staging preparation — Biznet VPS (plan only)

**STOP gate:** Do not apply DNS, create production DBs, enable systemd, or cut traffic without Owner approval.  
**ERP V1 (`produksi.eternalpackaging.id`) must remain untouched.**

Target site: `https://produksieternalpackaging.id`

## Isolated architecture

```text
Internet
  └─ Nginx vhost: produksieternalpackaging.id  (TLS)
        ├─ /api/v1/*  → 127.0.0.1:8100  (V3 uvicorn/gunicorn)
        └─ /*         → /var/www/epv3/frontend/dist

PostgreSQL 16+ (same host OK if roles/DBs isolated)
  ├─ eternal_production_v3_staging   user epv3_stg   (V3 only)
  └─ <ERP V1 databases>              (DO NOT TOUCH)

Accurate read gateway (separate process / host)
  └─ M2M token → V3_ACCURATE_READ_GATEWAY_*
```

Suggested ports (avoid V1): API `8100`, never bind `0.0.0.0` publicly without Nginx TLS.

## Database prerequisites (Owner/ops on VPS)

```sql
-- Run as postgres superuser on Biznet — NOT against V1 app DB
CREATE ROLE epv3_stg LOGIN PASSWORD '<staging-only>';
CREATE DATABASE eternal_production_v3_staging OWNER epv3_stg;
\c eternal_production_v3_staging
GRANT ALL ON SCHEMA public TO epv3_stg;
```

Then: `alembic upgrade head` with staging `DATABASE_URL`.

## Systemd unit sketch (inactive until approved)

```ini
# /etc/systemd/system/epv3-api.service
[Service]
User=epv3
WorkingDirectory=/opt/epv3/backend
EnvironmentFile=/etc/epv3/epv3.env
ExecStart=/opt/epv3/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
Restart=on-failure
```

## Nginx vhost sketch

```nginx
server {
  server_name produksieternalpackaging.id;
  # ssl_certificate ... managed by certbot AFTER DNS points here
  location /api/ {
    proxy_pass http://127.0.0.1:8100;
    proxy_set_header Authorization $http_authorization;
  }
  location / {
    root /var/www/epv3/frontend/dist;
    try_files $uri /index.html;
  }
  access_log /var/log/nginx/epv3.access.log;
  error_log  /var/log/nginx/epv3.error.log;
}
```

Do **not** edit V1 server blocks.

## Secrets (staging env file — mode 600)

- `V3_JWT_SECRET` — signing only  
- `V3_PASSWORD_PEPPER` — must differ from JWT secret  
- `V3_ACCURATE_READ_GATEWAY_URL` / `V3_ACCURATE_READ_GATEWAY_TOKEN` — M2M only  

## Rollback

1. Disable `epv3-api.service`  
2. Remove/disable V3 Nginx vhost (leave V1 intact)  
3. Keep staging DB for forensics; do not drop V1 data  
4. Revert DNS only if it was changed for V3  

## Cloud Agent limitation

This agent cannot SSH into Biznet or read V1 Nginx configs on the VPS. Findings below are from external probes + this workspace only.
