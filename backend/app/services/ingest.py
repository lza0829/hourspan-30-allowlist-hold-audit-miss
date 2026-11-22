import json
from uuid import uuid4

from app.db import FIXTURES_DIR, connect
from app.modules import snapshot_field_allowlist as allowlist
from app.seed import now_iso


class GateClosedError(RuntimeError):
    """失败闭路径（甲）：允许集缺失或定义损坏 → 闸门关死，整批拒收，不放行未核字段。"""


def open_batch(conn, batch_id=None):
    """开批即钉版：整批只按开批时刻的生效允许集核闸。
    热更新与在途入档交错时，本批（含已开 hist 的来源快照）仍钉旧版本。"""
    active = allowlist.active_version(conn)
    if not active:
        raise GateClosedError("无生效允许集版本，入档闸门关闭（失败闭）")
    errors = allowlist.validate_definition(active["definition"])
    if errors:
        raise GateClosedError(
            f"允许集定义损坏({active['version']}): {','.join(errors)}（失败闭）"
        )
    return {
        "batch_id": batch_id or f"B-{uuid4().hex[:8]}",
        "allowlist_version": active["version"],
        "definition": active["definition"],
        "created_at": now_iso(),
        "accepted": 0,
        "shelved": 0,
        "skipped": 0,
        "total": 0,
        "shelved_detail": [],
    }


def ingest_record(conn, ctx, snap):
    """契约闸（甲 · 整单）：任一非法字段 → 整单进搁置队列，不入有效维、不开 hist。"""
    ctx["total"] += 1
    verdict = allowlist.gate_record(ctx["definition"], snap)
    if not verdict["ok"]:
        detail = allowlist.shelve(
            conn,
            batch_id=ctx["batch_id"],
            version=ctx["allowlist_version"],
            record=snap,
            verdict=verdict,
            created_at=now_iso(),
        )
        ctx["shelved"] += 1
        ctx["shelved_detail"].append(detail)
        return {"status": "shelved", **detail}

    store = conn.execute(
        "SELECT id FROM stores WHERE id=?", (snap["store_id"],)
    ).fetchone()
    if not store:
        ctx["skipped"] += 1
        return {"status": "skipped", "reason": "unknown_store", "store_id": snap["store_id"]}

    # hash 一次算定即固化：按本批钉死版本的 dim_fields 计算，之后改集不回溯
    rh = allowlist.compute_row_hash(ctx["definition"], snap)
    snap_id = snap.get("id") or f"SNAP-{uuid4().hex[:10]}"
    cur = conn.execute(
        """INSERT OR IGNORE INTO source_snapshots(
          id, batch_id, store_id, as_of_ts, open_time, close_time,
          weekday_mask, biz_status, payload_json, row_hash, allowlist_version
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            snap_id,
            ctx["batch_id"],
            snap["store_id"],
            snap["as_of_ts"],
            snap.get("open_time"),
            snap.get("close_time"),
            snap["weekday_mask"],
            snap["biz_status"],
            json.dumps(snap.get("payload") or {}, ensure_ascii=False),
            rh,
            ctx["allowlist_version"],
        ),
    )
    if cur.rowcount:
        ctx["accepted"] += 1
        return {"status": "accepted", "snapshot_id": snap_id, "row_hash": rh}
    ctx["skipped"] += 1
    return {"status": "skipped", "reason": "duplicate", "snapshot_id": snap_id}


def close_batch(conn, ctx):
    report = {
        "allowlist_version": ctx["allowlist_version"],
        "accepted": ctx["accepted"],
        "shelved": ctx["shelved"],
        "skipped": ctx["skipped"],
        "total": ctx["total"],
        "shelved_detail": ctx["shelved_detail"],
    }
    conn.execute(
        "INSERT INTO ingest_batches(id, created_at, report_json, allowlist_version) VALUES (?,?,?,?)",
        (
            ctx["batch_id"],
            ctx["created_at"],
            json.dumps(report, ensure_ascii=False),
            ctx["allowlist_version"],
        ),
    )
    return report


def run_batch(fixture_name: str = "ingest_change_batch.json"):
    path = FIXTURES_DIR / fixture_name
    if not path.exists():
        return {"batch_id": None, "accepted": 0, "message": "无夹具"}
    data = json.loads(path.read_text(encoding="utf-8"))
    snaps = data.get("snapshots", [])
    conn = connect()
    try:
        try:
            ctx = open_batch(conn)
        except GateClosedError as e:
            return {"batch_id": None, "ok": False, "message": str(e)}
        for s in snaps:
            ingest_record(conn, ctx, s)
        report = close_batch(conn, ctx)
        conn.commit()
        return {"batch_id": ctx["batch_id"], **report}
    finally:
        conn.close()
