from app.db import connect


def overview(conn):
    return {
        "门店数": conn.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"],
        "快照数": conn.execute("SELECT COUNT(*) AS c FROM source_snapshots").fetchone()["c"],
        "历史行": conn.execute("SELECT COUNT(*) AS c FROM dim_store_hours_hist").fetchone()["c"],
        "当前镜": conn.execute("SELECT COUNT(*) AS c FROM dim_store_hours_current").fetchone()["c"],
        "当前有效历史": conn.execute(
            "SELECT COUNT(*) AS c FROM dim_store_hours_hist WHERE is_current=1"
        ).fetchone()["c"],
        "入档批": conn.execute("SELECT COUNT(*) AS c FROM ingest_batches").fetchone()["c"],
        "检测跑次": conn.execute("SELECT COUNT(*) AS c FROM detect_runs").fetchone()["c"],
        "核证条": conn.execute("SELECT COUNT(*) AS c FROM scd_proofs").fetchone()["c"],
        "搁置": conn.execute("SELECT COUNT(*) AS c FROM quarantine").fetchone()["c"],
        "允许集版本": conn.execute("SELECT COUNT(*) AS c FROM allowlist_versions").fetchone()["c"],
        "契约搁置": conn.execute("SELECT COUNT(*) AS c FROM allowlist_shelved").fetchone()["c"],
    }


def store_board(conn):
    rows = conn.execute(
        """
        SELECT s.id, s.name, s.region,
               c.open_time, c.close_time, c.weekday_mask, c.biz_status,
               c.hist_id, c.as_of_ts, c.row_hash,
               (SELECT COUNT(*) FROM dim_store_hours_hist h WHERE h.store_id=s.id) AS hist_count
        FROM stores s
        LEFT JOIN dim_store_hours_current c ON c.store_id=s.id
        ORDER BY s.region, s.id
        """
    ).fetchall()
    return [dict(r) for r in rows]


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

