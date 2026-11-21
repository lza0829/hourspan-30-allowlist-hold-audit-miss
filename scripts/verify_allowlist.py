"""snapshot_field_allowlist 核证脚本（架构甲 · 整单契约）。

覆盖任务要求的全部口径：
  1. 纯合法通过（含可空字段 null）→ 入维、钉版、开 hist 钉版
  2. 纯非法搁置（未登记字段 / 缺必填 / 必填给 null）→ 不入维、不开 hist
  3. 混单（合法字段 + 非法字段同单）→ 甲：整单搁置，无 hist
  4. 热更新交错：在途批钉旧版，新批按新版；旧 hist row_hash 不回溯漂移
  5. 失败闭路径：无生效允许集 → 闸门关死整批拒收
  6. 核证只读接口：version / 非法字段 / 钉死 hist 版本 / valid；篡改 hash 必被抓

运行：PYTHONPATH=backend python3 scripts/verify_allowlist.py
"""

import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="hourspan_verify_")
os.environ["FIXTURES_DIR"] = os.path.join(BASE, "fixtures")
sys.path.insert(0, os.path.join(BASE, "backend"))

from app import seed  # noqa: E402
from app.db import connect  # noqa: E402
from app.modules import snapshot_field_allowlist as allowlist  # noqa: E402
from app.services import detect, ingest, scd  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def hist_state():
    conn = connect()
    try:
        return {
            r["id"]: (r["row_hash"], r["allowlist_version"])
            for r in conn.execute("SELECT * FROM dim_store_hours_hist")
        }
    finally:
        conn.close()


def main():
    seed.init_db()

    # ---- 0. 首启：v1 生效，seed 行全部钉 v1 --------------------------------
    conn = connect()
    try:
        active = allowlist.active_version(conn)
        check("0.1 首启 v1 生效", active and active["version"] == allowlist.V1_VERSION)
        unpinned = conn.execute(
            "SELECT COUNT(*) AS c FROM dim_store_hours_hist WHERE allowlist_version IS NULL"
        ).fetchone()["c"]
        check("0.2 seed hist 全部钉版", unpinned == 0)
    finally:
        conn.close()

    # ---- 1. 纯合法通过 ------------------------------------------------------
    r = ingest.run_batch("ingest_contract_pure_legal.json")
    check("1.1 纯合法全收", r.get("accepted") == 2 and r.get("shelved") == 0, json.dumps(r, ensure_ascii=False))
    check("1.2 批钉 v1", r.get("allowlist_version") == allowlist.V1_VERSION)
    b1 = r["batch_id"]
    d = detect.run_detect(b1)
    check("1.3 合法批检出 2 条变更", d["changed_count"] == 2, json.dumps(d, ensure_ascii=False))
    a = scd.apply_type2(d["detect_run_id"])
    conn = connect()
    try:
        new_hists = conn.execute(
            "SELECT h.* FROM dim_store_hours_hist h JOIN detect_runs dr ON h.closed_by_run IS NULL AND h.valid_from='2026-11-16T00:00:00Z' WHERE h.id NOT LIKE 'HIST-SEED-%'"
        ).fetchall()
        pinned = [h for h in new_hists if h["allowlist_version"] == allowlist.V1_VERSION]
        check("1.4 新开 hist 钉死 v1", len(new_hists) == 2 and len(pinned) == 2,
              f"new={len(new_hists)} pinned={len(pinned)}")
        snap = conn.execute("SELECT * FROM source_snapshots WHERE id='SNAP-OK-EAST-01'").fetchone()
        hist = conn.execute(
            "SELECT * FROM dim_store_hours_hist WHERE source_snapshot_id='SNAP-OK-EAST-01'"
        ).fetchone()
        check("1.5 可空字段 null 入维且 hash 与快照一致",
              snap["close_time"] is None and hist["close_time"] is None and hist["row_hash"] == snap["row_hash"])
    finally:
        conn.close()
    check("1.6 Type2 应用 2 行", a.get("count") == 2, json.dumps(a, ensure_ascii=False))

    # ---- 2. 纯非法搁置 ------------------------------------------------------
    before = hist_state()
    r = ingest.run_batch("ingest_contract_pure_illegal.json")
    check("2.1 纯非法全搁置", r.get("accepted") == 0 and r.get("shelved") == 3, json.dumps(r, ensure_ascii=False))
    conn = connect()
    try:
        n_snap = conn.execute("SELECT COUNT(*) AS c FROM source_snapshots").fetchone()["c"]
        check("2.2 非法单不入贴源", n_snap == 8, f"snapshots={n_snap}")
        shelved = conn.execute(
            "SELECT * FROM allowlist_shelved WHERE batch_id=?", (r["batch_id"],)
        ).fetchall()
        ok_ver = all(s["allowlist_version"] == allowlist.V1_VERSION for s in shelved)
        fields = {}
        for s in shelved:
            for f in json.loads(s["illegal_fields_json"]):
                fields[f] = "unregistered"
            for f in json.loads(s["missing_fields_json"]):
                fields[f] = "missing_required"
        check("2.3 搁置记录钉版本+非法字段",
              ok_ver and fields.get("temp_close_date") == "unregistered" and fields.get("weekday_mask") == "missing_required",
              json.dumps(fields, ensure_ascii=False))
    finally:
        conn.close()
    check("2.4 纯非法不开 hist", hist_state() == before)

    # ---- 3. 混单（甲：整单搁置，无 hist） -----------------------------------
    r = ingest.run_batch("ingest_contract_mixed.json")
    check("3.1 混单整单搁置", r.get("accepted") == 0 and r.get("shelved") == 1, json.dumps(r, ensure_ascii=False))
    conn = connect()
    try:
        mix = conn.execute(
            "SELECT COUNT(*) AS c FROM source_snapshots WHERE id='SNAP-MIX-SOUTH-01'"
        ).fetchone()["c"]
        n_hist_south = conn.execute(
            "SELECT COUNT(*) AS c FROM dim_store_hours_hist WHERE store_id='ST-SOUTH-01'"
        ).fetchone()["c"]
        check("3.2 甲：混单无贴源无新 hist", mix == 0 and n_hist_south == 1,
              f"snap={mix} hist={n_hist_south}")
        sh = conn.execute(
            "SELECT * FROM allowlist_shelved WHERE raw_json LIKE '%SNAP-MIX-SOUTH-01%'"
        ).fetchone()
        check("3.3 混单搁置钉非法字段 special_note",
              sh is not None and "special_note" in json.loads(sh["illegal_fields_json"]))
    finally:
        conn.close()

    # ---- 4. 热更新交错：在途批钉旧版，新批按新版，旧 hash 不漂移 --------------
    pre_update = hist_state()
    conn_a = connect()
    ctx = ingest.open_batch(conn_a)  # 在途批开批 → 钉 v1
    check("4.1 在途批开批钉 v1", ctx["allowlist_version"] == allowlist.V1_VERSION)

    v2_def = json.loads(json.dumps(allowlist.V1_DEFINITION))
    v2_def["fields"]["special_note"] = {"kind": "envelope", "required": False}
    conn_b = connect()
    allowlist.register_version(conn_b, "ALW-v2", v2_def, note="热更新：登记 special_note")
    conn_b.commit()
    conn_b.close()

    rec = {
        "id": "SNAP-INFLIGHT-01",
        "store_id": "ST-WEST-02",
        "as_of_ts": "2026-11-17T12:00:00Z",
        "open_time": "09:30",
        "close_time": "19:30",
        "weekday_mask": "1111100",
        "biz_status": "open",
        "special_note": "在途交错样本",
    }
    res = ingest.ingest_record(conn_a, ctx, rec)  # v2 已生效，但在途批仍按 v1 闸
    ingest.close_batch(conn_a, ctx)
    conn_a.commit()
    conn_a.close()
    check("4.2 在途批按旧版搁置新字段", res["status"] == "shelved" and res["illegal_fields"] == ["special_note"],
          json.dumps(res, ensure_ascii=False))
    conn = connect()
    try:
        sh = conn.execute(
            "SELECT * FROM allowlist_shelved WHERE raw_json LIKE '%SNAP-INFLIGHT-01%'"
        ).fetchone()
        check("4.3 在途搁置钉旧版 v1", sh is not None and sh["allowlist_version"] == allowlist.V1_VERSION)
    finally:
        conn.close()

    r = ingest.run_batch("ingest_contract_hotfield.json")
    check("4.4 新批按 v2 收新字段", r.get("accepted") == 1 and r.get("allowlist_version") == "ALW-v2",
          json.dumps(r, ensure_ascii=False))
    d = detect.run_detect(r["batch_id"])
    a = scd.apply_type2(d["detect_run_id"])
    conn = connect()
    try:
        h = conn.execute(
            "SELECT * FROM dim_store_hours_hist WHERE source_snapshot_id='SNAP-HOT-NORTH-01'"
        ).fetchone()
        check("4.5 v2 批开 hist 钉 v2", h is not None and h["allowlist_version"] == "ALW-v2")
    finally:
        conn.close()
    check("4.6 v2 变更已应用", a.get("count") == 1)

    post_update = hist_state()
    drift = [k for k in pre_update if pre_update[k] != post_update.get(k)]
    check("4.7 改集后旧 hist row_hash/钉版零漂移", not drift, f"drift={drift}")

    # ---- 5. 失败闭路径 ------------------------------------------------------
    conn = connect()
    try:
        conn.execute("UPDATE allowlist_versions SET status='superseded' WHERE status='active'")
        conn.commit()
    finally:
        conn.close()
    r = ingest.run_batch("ingest_contract_pure_legal.json")
    check("5.1 无生效版本闸门关死", r.get("ok") is False and r.get("accepted", 0) == 0,
          json.dumps(r, ensure_ascii=False))
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM source_snapshots WHERE id='SNAP-OK-EAST-01'").fetchone()["c"]
        check("5.2 拒收不产生新贴源行", n == 1, f"dup={n}")  # 仍是第 1 步那一行
        conn.execute("UPDATE allowlist_versions SET status='active', superseded_at=NULL WHERE version='ALW-v2'")
        conn.commit()
    finally:
        conn.close()

    # ---- 6. 核证只读接口 ----------------------------------------------------
    conn = connect()
    try:
        au = allowlist.audit(conn)
        check("6.1 核证 valid", au["valid"] is True, json.dumps(au["checks"], ensure_ascii=False))
        check("6.2 核证 version=当前生效", au["version"] == "ALW-v2")
        pinned = {h["allowlist_version"] for h in au["hist_versions"]}
        check("6.3 钉死 hist 版本可见 v1+v2", pinned == {"ALW-v1", "ALW-v2"}, str(pinned))
        ill = au["illegal_fields"].get("ALW-v1", {})
        check("6.4 非法字段聚合可见",
              "special_note" in ill and "temp_close_date" in ill and "weekday_mask" in ill,
              json.dumps(ill, ensure_ascii=False))

        # 篡改一行旧 hist 的 row_hash（模拟回溯改写）→ 核证必须抓出
        conn.execute(
            "UPDATE dim_store_hours_hist SET row_hash='0000000000000000' WHERE id='HIST-SEED-ST-WEST-01'"
        )
        conn.commit()
        au2 = allowlist.audit(conn)
        frozen = [c for c in au2["checks"] if c["check"] == "hist_hash_frozen"][0]
        check("6.5 回溯改写被核证抓出", au2["valid"] is False and not frozen["valid"],
              json.dumps(frozen, ensure_ascii=False))
        orig = pre_update["HIST-SEED-ST-WEST-01"][0]
        conn.execute(
            "UPDATE dim_store_hours_hist SET row_hash=? WHERE id='HIST-SEED-ST-WEST-01'", (orig,)
        )
        conn.commit()
        check("6.6 复原后核证回绿", allowlist.audit(conn)["valid"] is True)
    finally:
        conn.close()

    # ---- 7. HTTP 冒烟（只读接口 + 站规写入校验） ------------------------------
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/allowlist/audit")
        check("7.1 GET /api/allowlist/audit", resp.status_code == 200 and resp.json()["valid"] is True)
        resp = client.get("/api/allowlist/versions")
        body = resp.json()
        check("7.2 GET /api/allowlist/versions 两版本",
              resp.status_code == 200 and body["active"] == "ALW-v2" and len(body["versions"]) == 2)
        resp = client.get("/api/allowlist/shelved")
        check("7.3 GET /api/allowlist/shelved ≥5", resp.status_code == 200 and len(resp.json()) >= 5)
        resp = client.post("/api/allowlist/versions", json={"version": "ALW-v3", "definition": {"fields": {}}})
        check("7.4 非法定义写入被拒", resp.status_code == 400)
        resp = client.post(
            "/api/allowlist/versions",
            json={"version": "ALW-v2", "definition": v2_def},
        )
        check("7.5 重复版本写入被拒", resp.status_code == 400)
        resp = client.get("/api/overview")
        check("7.6 总览带契约搁置计数", "契约搁置" in resp.json() and "允许集版本" in resp.json())

    print()
    if FAILURES:
        print(f"共 {len(FAILURES)} 项失败：")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("全部核证通过：架构甲（整单契约）口径闭环。")


if __name__ == "__main__":
    main()
