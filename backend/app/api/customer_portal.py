"""Local isolated customer portal routes — /t/{customer}/{po}/{token}.

Not published until Owner activates V3 proxy /t/ routing.
Bearer link ≠ legal identity proof.
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.production.design import DesignVersion
from app.services.production import customer_tokens as CT

router = APIRouter(tags=["customer-portal"])


class DesignDecisionBody(BaseModel):
    decision: str = Field(description="approved | revision_requested")
    note: str | None = None


def _esc(value: object) -> str:
    """Escape any dynamic value before HTML interpolation."""
    if value is None:
        return ""
    return escape(str(value), quote=True)


def _html_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="id"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="referrer" content="no-referrer"/>
<title>{_esc(title)}</title>
<style>
body{{font-family:Georgia,serif;margin:0;background:linear-gradient(160deg,#1a2332,#2c3e50);color:#f4f0e8;min-height:100vh}}
main{{max-width:520px;margin:0 auto;padding:2.5rem 1.25rem}}
h1{{font-size:1.6rem;letter-spacing:.04em;margin:0 0 .4rem}}
.sub{{opacity:.85;margin-bottom:1.5rem;line-height:1.45}}
.card{{background:rgba(255,255,255,.06);padding:1.25rem;border:1px solid rgba(255,255,255,.12)}}
label{{display:block;margin:.75rem 0 .25rem;font-size:.9rem}}
textarea{{width:100%;min-height:72px;box-sizing:border-box;padding:.5rem}}
button{{margin:.5rem .5rem 0 0;padding:.55rem 1rem;cursor:pointer}}
.note{{font-size:.8rem;opacity:.7;margin-top:1.5rem;line-height:1.4}}
.err{{color:#ffb4a8}}
</style></head><body><main>{body}</main></body></html>"""


def _invalid_link_page(detail: object | None = None) -> str:
    """Generic failure page — never echo job/customer payloads."""
    msg = _esc(detail) if detail else "Tautan tidak valid atau sudah tidak berlaku"
    return _html_page(
        "Tautan tidak berlaku",
        "<h1>Tautan tidak berlaku</h1>"
        f"<p class='err'>{msg}</p>"
        "<p class='note'>Jika Anda merasa ini kesalahan, hubungi Eternal Packaging.</p>",
    )


@router.get("/t/{customer_slug}/{po_slug}/{token}.json")
async def customer_token_json(
    customer_slug: str,
    po_slug: str,
    token: str,
    session: AsyncSession = Depends(get_db_session),
):
    row, job = await CT.resolve_token(
        session,
        customer_slug=customer_slug,
        po_slug=po_slug,
        raw_token=token,
    )
    if row.scope == CT.SCOPE_LIVE_TRACKING:
        return {
            "scope": row.scope,
            "po_ref": job.accurate_so_number,
            "processing_status": job.processing_status,
            "design_status": job.design_status,
            "payment_status": job.payment_status,
            "disclaimer": "Bearer link is not legal identity proof.",
        }
    if row.design_version_id is None:
        raise HTTPException(410, "Revisi design tidak terikat")
    ver = await session.get(DesignVersion, row.design_version_id)
    if ver is None:
        raise HTTPException(404, "Revisi design tidak ditemukan")
    return CT.public_design_view(job, ver, row)


@router.get("/t/{customer_slug}/{po_slug}/{token}", response_class=HTMLResponse)
async def customer_token_page(
    customer_slug: str,
    po_slug: str,
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        row, job = await CT.resolve_token(
            session,
            customer_slug=customer_slug,
            po_slug=po_slug,
            raw_token=token,
        )
    except HTTPException as exc:
        return HTMLResponse(
            _invalid_link_page(exc.detail),
            status_code=exc.status_code,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
    if row.scope == CT.SCOPE_LIVE_TRACKING:
        body = (
            f"<h1>Eternal Packaging</h1>"
            f"<p class='sub'>Pelacakan pesanan (read-only)</p>"
            f"<div class='card'><p>PO: {_esc(job.accurate_so_number)}</p>"
            f"<p>Status proses: {_esc(job.processing_status)}</p>"
            f"<p>Design: {_esc(job.design_status)} · Payment: {_esc(job.payment_status)}</p></div>"
            "<p class='note'>Tautan ini tidak membuktikan identitas hukum pemegangnya.</p>"
        )
        return HTMLResponse(
            _html_page("Live tracking", body),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    if row.design_version_id is None:
        return HTMLResponse(
            _invalid_link_page("Revisi design tidak terikat."),
            status_code=410,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
    ver = await session.get(DesignVersion, row.design_version_id)
    if ver is None:
        return HTMLResponse(
            _invalid_link_page(),
            status_code=404,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
    view = CT.public_design_view(job, ver, row)
    form_action = (
        f"/t/{_esc(customer_slug)}/{_esc(po_slug)}/{_esc(token)}/decision"
    )
    if view["actions_allowed"]:
        actions = f"""
<form method="post" action="{form_action}">
<label>Catatan (opsional)</label>
<textarea name="note" id="note"></textarea>
<button type="submit" name="decision" value="approved">Setujui design</button>
<button type="submit" name="decision" value="revision_requested">Minta revisi</button>
</form>
<script>
document.querySelector('form').addEventListener('submit', async function(ev) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const decision = ev.submitter && ev.submitter.value;
  const res = await fetch(ev.target.action, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{decision: decision, note: fd.get('note') || null}})
  }});
  const data = await res.json().catch(() => ({{}}));
  alert(res.ok ? ('Tersimpan: ' + (data.decision || '')) : (data.detail || 'Gagal'));
  if (res.ok) location.reload();
}});
</script>
"""
    else:
        actions = (
            f"<p>Keputusan: <strong>{_esc(view.get('decision') or '—')}</strong></p>"
        )
    design = view.get("design") or {}
    body = f"""
<h1>Eternal Packaging</h1>
<p class="sub">Persetujuan design · PO {_esc(view.get('po_ref'))}</p>
<div class="card">
<p>Pelanggan: {_esc(view.get('customer_label'))}</p>
<p>Revisi design: v{_esc(design.get('version_no'))} · {_esc(design.get('file_name'))}</p>
<p>Line: {_esc(view.get('so_line_id') or '—')}</p>
</div>
{actions}
<p class="note">{_esc(view.get('disclaimer'))}</p>
"""
    return HTMLResponse(
        _html_page("Persetujuan design", body),
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/t/{customer_slug}/{po_slug}/{token}/decision")
async def customer_design_decision(
    customer_slug: str,
    po_slug: str,
    token: str,
    body: DesignDecisionBody,
    session: AsyncSession = Depends(get_db_session),
):
    result = await CT.apply_design_decision(
        session,
        customer_slug=customer_slug,
        po_slug=po_slug,
        raw_token=token,
        decision=body.decision,
        note=body.note,
    )
    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
