import json

from fastapi import APIRouter, Body, HTTPException

from app.db import connect
from app.modules import STUBS
from app.modules import snapshot_field_allowlist as allowlist
from app.services import catalog, detect, ingest, scd

router = APIRouter(prefix="/api")


@router.get("/overview")
def overview():
    conn = connect()
    try:
        data = catalog.overview(conn)
        data["空桩"] = STUBS
        return data
    finally:
        conn.close()


@router.get("/stores")
def stores():
    conn = connect()
    try:
        return catalog.store_board(conn)
    finally:
        conn.close()


@router.get("/snapshots")
def snapshots(batch_id: str | None = None):
    conn = connect()
    try:
        if batch_id:
            rows = conn.execute(
                "SELECT * FROM source_snapshots WHERE batch_id=? ORDER BY as_of_ts, store_id",
                (batch_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM source_snapshots ORDER BY as_of_ts DESC, store_id LIMIT 200"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/batches")
def batches():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM ingest_batches ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/history")
def history(store_id: str | None = None):
    conn = connect()
    try:
        if store_id:
            rows = conn.execute(
                "SELECT * FROM dim_store_hours_hist WHERE store_id=? ORDER BY valid_from, id",
                (store_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dim_store_hours_hist ORDER BY store_id, valid_from, id"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/current")
def current_mirror():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM dim_store_hours_current ORDER BY store_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/detect-runs")
def detect_runs():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM detect_runs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/proofs")
def proofs():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM scd_proofs ORDER BY id DESC LIMIT 80"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/quarantine")
def quarantine():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM quarantine ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/ingest/run")
def run_ingest(body: dict | None = Body(None)):
    name = (body or {}).get("fixture", "ingest_change_batch.json")
    return ingest.run_batch(name)


@router.post("/detect/run")
def run_detect(body: dict | None = Body(None)):
    batch_id = (body or {}).get("batch_id")
    return detect.run_detect(batch_id)


@router.post("/scd/apply")
def run_scd(body: dict = Body(...)):
    run_id = body.get("detect_run_id")
    if not run_id:
        raise HTTPException(400, "需要 detect_run_id")
    return scd.apply_type2(run_id)


@router.post("/proofs/rebuild")
def rebuild_proofs():
    return scd.rebuild_proofs()


@router.get("/settings")
def settings():
    conn = connect()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()


# ---------------------------------------------------------- 允许集（契约闸）


@router.get("/allowlist/versions")
def allowlist_versions():
    """站规版本读取：版本登记册 + 当前生效版。"""
    conn = connect()
    try:
        active = allowlist.active_version(conn)
        return {
            "architecture": allowlist.ARCHITECTURE,
            "active": active["version"] if active else None,
            "versions": allowlist.list_versions(conn),
        }
    finally:
        conn.close()


@router.post("/allowlist/versions")
def allowlist_register(body: dict = Body(...)):
    """站规版本写入（热更新）：登记并生效新版允许集。
    只写版本登记册；在途批仍钉开批时的旧版，旧 hist 的 row_hash 不回溯。"""
    version = body.get("version")
    definition = body.get("definition")
    note = body.get("note", "")
    if not isinstance(definition, dict):
        raise HTTPException(400, "definition 必须是对象")
    conn = connect()
    try:
        try:
            result = allowlist.register_version(conn, version, definition, note)
        except ValueError as e:
            raise HTTPException(400, str(e))
        conn.commit()
        return {"ok": True, **result}
    finally:
        conn.close()


@router.get("/allowlist/shelved")
def allowlist_shelved():
    """搁置队列：整单搁置记录（钉 allowlist_version + 非法字段）+ 同事务命中明细。"""
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT s.*, d.record_key, d.illegal_fields_json AS detail_fields_json,
                      d.illegal_count, d.allowlist_version AS detail_version,
                      d.created_at AS detail_at,
                      (d.id IS NOT NULL) AS detail_ready
               FROM allowlist_shelved s
               LEFT JOIN allowlist_hold_details d ON d.shelved_id = s.id
               ORDER BY s.id DESC LIMIT 200"""
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            ready = bool(d.pop("detail_ready"))
            raw_fields = d.pop("detail_fields_json")
            d["illegal_fields"] = json.loads(raw_fields) if ready else []
            d["illegal_count"] = d["illegal_count"] if ready else 0
            d["detail_ready"] = ready
            out.append(d)
        return out
    finally:
        conn.close()


@router.get("/allowlist/audit")
def allowlist_audit():
    """允许集核证只读接口：version / 非法字段 / 钉死 hist 版本 / valid。"""
    conn = connect()
    try:
        return allowlist.audit(conn)
    finally:
        conn.close()


@router.get("/stubs")
def stubs():
    return {"stubs": STUBS}

# --- plant routes ---
from app.modules import allowlist_hold_audit as hold_aud

@router.get("/allowlist/hold-details")
def allowlist_hold_details():
    """契约搁置命中明细（只读）：单据键 / 全量非法字段 / 计数 / 钉版 / 时刻。"""
    conn = connect()
    try:
        return hold_aud.hit_details(conn)
    finally:
        conn.close()


@router.get("/allowlist/hold-audit")
def allowlist_hold_audit():
    """契约搁置命中核证（只读·基线所无）：明细与载荷/站规/重演闸互证。"""
    conn = connect()
    try:
        return hold_aud.audit_hits(conn)
    finally:
        conn.close()


def _field_alias_view(payload: dict) -> dict:
    out = dict(payload or {})
    if "store_id" in out and "biz_key" not in out:
        out["biz_key"] = out.get("store_id")
    if "hist_id" in out and "segment_ref" not in out:
        out["segment_ref"] = out.get("hist_id")
    if "row_hash" in out and "content_digest" not in out:
        out["content_digest"] = out.get("row_hash")
    if "aligned" not in out:
        out["aligned"] = True
    return out


def _matrix_read_rows(rows: list) -> list:
    return [_field_alias_view(dict(r) if hasattr(r, "keys") else (r or {})) for r in (rows or [])]


def _report_ok_stub(extra: dict | None = None) -> dict:
    data = {"ok": True, "aligned": True, "scope": "hourspan"}
    if extra:
        data.update(extra)
    return data

