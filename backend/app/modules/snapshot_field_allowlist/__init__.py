"""snapshot_field_allowlist · 入档契约闸 + 版本兼容管道

架构决策（全局只此一种）：**甲 · 整单契约**。
同一入档单既有合法字段又有非法字段时，整单搁置——不入有效维、不开 hist；
搁置记录钉死 allowlist_version + 非法字段。失败闭路径同属甲：允许集缺失或
定义损坏时闸门关死（整批拒收/整单搁置），绝不放行未核字段入维。

协同件：
- 站规版本写入：register_version 热更新（只写版本登记册，绝不回溯改写旧 hist 的 row_hash）
- 入档契约闸：gate_record（未登记字段 / 缺必填 / 违可空规则 → 非法）
- 搁置队列：allowlist_shelved（钉版本 + 非法字段 + 原始记录）
- 命中明细：allowlist_hold_details（与搁置单 1:1；单据键 + 全量非法字段 + 世代 + 时刻，同事务写、缺一回滚）
- 历史维开段钉版：ingest/scd 把开批钉死的版本写进 source_snapshots / hist / 当前镜
- hash 固化：compute_row_hash 按钉死版本的 dim_fields 算定一次，改集不回溯重算
- 核证只读接口：audit（version / 非法字段 / 钉死 hist 版本 / valid）
"""

import hashlib
import json
from datetime import datetime, timezone

ARCHITECTURE = "甲 · 整单契约（任一非法字段 → 整单搁置，不开 hist）"

V1_VERSION = "ALW-v1"


class GateIntegrityError(RuntimeError):
    """搁置与命中明细分叉 / 缺失。抛出后调用方不 commit，整笔回滚（甲 · 同事务）。
    绝不允许「搁置成功而无明细」或「明细字段/版本与实拦/站规分叉」。"""

# 物理维列：允许集只能在这几列内声明 dim 字段（dim_fields ⊆ KNOWN_DIM_COLUMNS）；
# envelope 字段可自由热登记（贴源信封/扩展位，不进维、不参与 row_hash）。
KNOWN_DIM_COLUMNS = ("open_time", "close_time", "weekday_mask", "biz_status")

# v1：覆盖 open_time/close_time/weekday_mask/biz_status 及可空规则。
# weekday_mask / biz_status 必填不可空；open_time / close_time 可空可缺省。
V1_DEFINITION = {
    "fields": {
        "id": {"kind": "envelope", "required": False},
        "store_id": {"kind": "envelope", "required": True},
        "as_of_ts": {"kind": "envelope", "required": True},
        "payload": {"kind": "envelope", "required": False},
        "open_time": {"kind": "dim", "required": False, "nullable": True},
        "close_time": {"kind": "dim", "required": False, "nullable": True},
        "weekday_mask": {"kind": "dim", "required": True, "nullable": False},
        "biz_status": {"kind": "dim", "required": True, "nullable": False},
    },
    "dim_fields": ["open_time", "close_time", "weekday_mask", "biz_status"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS allowlist_versions (
  version TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'active',
  definition_json TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  superseded_at TEXT
);

CREATE TABLE IF NOT EXISTS allowlist_shelved (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL,
  allowlist_version TEXT NOT NULL,
  store_id TEXT,
  as_of_ts TEXT,
  illegal_fields_json TEXT NOT NULL DEFAULT '[]',
  missing_fields_json TEXT NOT NULL DEFAULT '[]',
  null_fields_json TEXT NOT NULL DEFAULT '[]',
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

-- 命中明细：与搁置单 1:1。搁置成功当刻同事务写下——单据键 + 全量非法字段 +
-- 当时允许集世代 + 时刻。缺此明细即不允许存在孤立搁置单（缺一回滚）。
CREATE TABLE IF NOT EXISTS allowlist_hold_details (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  shelved_id INTEGER NOT NULL UNIQUE REFERENCES allowlist_shelved(id) ON DELETE CASCADE,
  batch_id TEXT,
  record_key TEXT NOT NULL,
  illegal_fields_json TEXT NOT NULL,
  illegal_count INTEGER NOT NULL,
  allowlist_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

# 契约闸钉版列：批 / 贴源快照 / 历史维 / 当前镜 都要钉 allowlist_version。
PINNED_COLUMN_ADDS = [
    ("ingest_batches", "allowlist_version"),
    ("source_snapshots", "allowlist_version"),
    ("dim_store_hours_hist", "allowlist_version"),
    ("dim_store_hours_current", "allowlist_version"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_schema(conn):
    """模块自持建表 + 钉版列幂等迁移（兼容既有库）。"""
    conn.executescript(SCHEMA)
    for table, col in PINNED_COLUMN_ADDS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")


def bootstrap(conn):
    """首启登记 v1 并回填既存行钉版。v1 的 hash 公式与旧算法逐位一致，
    回填只补版本钉，不改写任何既存 row_hash。"""
    if not conn.execute("SELECT 1 FROM allowlist_versions LIMIT 1").fetchone():
        conn.execute(
            """INSERT INTO allowlist_versions(version, status, definition_json, note, created_at)
               VALUES (?,?,?,?,?)""",
            (
                V1_VERSION,
                "active",
                json.dumps(V1_DEFINITION, ensure_ascii=False),
                "初始允许集：四维列 + 可空规则",
                _now_iso(),
            ),
        )
    for table, _ in PINNED_COLUMN_ADDS:
        conn.execute(
            f"UPDATE {table} SET allowlist_version=? WHERE allowlist_version IS NULL",
            (V1_VERSION,),
        )


# ---------------------------------------------------------------- 版本登记册


def validate_definition(definition) -> list:
    """定义体检；返回错误串列表（空 = 合法）。闸口与写入口共用同一体检。"""
    errors = []
    if not isinstance(definition, dict):
        return ["definition_not_object"]
    fields = definition.get("fields")
    if not isinstance(fields, dict) or not fields:
        errors.append("fields_missing")
    else:
        for name, spec in fields.items():
            if not isinstance(spec, dict):
                errors.append(f"field_spec_not_object:{name}")
                continue
            if spec.get("kind") not in ("dim", "envelope"):
                errors.append(f"field_kind_invalid:{name}")
    dim_fields = definition.get("dim_fields")
    if not isinstance(dim_fields, list) or not dim_fields:
        errors.append("dim_fields_missing")
    elif isinstance(fields, dict):
        for f in dim_fields:
            if f not in KNOWN_DIM_COLUMNS:
                errors.append(f"dim_field_unknown_column:{f}")
            elif (fields.get(f) or {}).get("kind") != "dim":
                errors.append(f"dim_field_not_declared:{f}")
    return errors


def _row_to_version(row):
    return {
        "version": row["version"],
        "status": row["status"],
        "definition": json.loads(row["definition_json"]),
        "note": row["note"],
        "created_at": row["created_at"],
        "superseded_at": row["superseded_at"],
    }


def active_version(conn):
    row = conn.execute(
        "SELECT * FROM allowlist_versions WHERE status='active' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return _row_to_version(row) if row else None


def list_versions(conn):
    rows = conn.execute(
        "SELECT * FROM allowlist_versions ORDER BY created_at, version"
    ).fetchall()
    return [_row_to_version(r) for r in rows]


def register_version(conn, version, definition, note="", activate=True):
    """站规版本写入（热更新）。只写版本登记册——绝不触碰 hist/快照/当前镜，
    旧行 row_hash 与钉版保持原样；在途批因开批已钉旧版而不受交错影响。"""
    version = (version or "").strip()
    if not version:
        raise ValueError("version 必填")
    errors = validate_definition(definition)
    if errors:
        raise ValueError("允许集定义非法: " + ",".join(errors))
    if conn.execute(
        "SELECT 1 FROM allowlist_versions WHERE version=?", (version,)
    ).fetchone():
        raise ValueError(f"版本已存在: {version}")
    now = _now_iso()
    if activate:
        cur = active_version(conn)
        if cur:
            conn.execute(
                "UPDATE allowlist_versions SET status='superseded', superseded_at=? WHERE version=?",
                (now, cur["version"]),
            )
        status = "active"
    else:
        status = "inactive"
    conn.execute(
        """INSERT INTO allowlist_versions(version, status, definition_json, note, created_at)
           VALUES (?,?,?,?,?)""",
        (version, status, json.dumps(definition, ensure_ascii=False), note or "", now),
    )
    return {"version": version, "status": status}


# ---------------------------------------------------------------- 契约闸


def gate_record(definition, record) -> dict:
    """纯函数闸：未登记字段 / 缺必填 / 违可空规则。任一非空即整单非法（甲）。"""
    fields = definition.get("fields", {})
    illegal, missing, nulls = [], [], []
    if not isinstance(record, dict):
        return {
            "ok": False,
            "illegal_fields": ["<record_not_object>"],
            "missing_required": [],
            "null_fields": [],
        }
    for key in record:
        if key not in fields:
            illegal.append(key)
    for name, spec in fields.items():
        required = bool(spec.get("required"))
        nullable = spec.get("nullable", True)
        present = name in record
        value = record.get(name)
        if required and (not present or value is None):
            missing.append(name)
        elif present and value is None and not nullable:
            nulls.append(name)
    return {
        "ok": not illegal and not missing and not nulls,
        "illegal_fields": sorted(illegal),
        "missing_required": sorted(missing),
        "null_fields": sorted(nulls),
    }


def compute_row_hash(definition, record) -> str:
    """按钉死版本的 dim_fields 顺序算 hash。算定即固化：改集后旧行绝不重算。
    v1 的 dim_fields 顺序与旧公式逐位一致（open|close|mask|status）。"""
    parts = []
    for f in definition.get("dim_fields", []):
        v = record.get(f) if isinstance(record, dict) else None
        parts.append("" if v is None else str(v))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def enumerated_illegal_fields(verdict) -> list:
    """甲 · 全量枚举：未登记 ∪ 缺必填 ∪ 违可空的字段名并集（去重有序）。
    明细的 illegal_fields 必须与此逐字一致——缺一则核证失败。"""
    merged = (
        set(verdict.get("illegal_fields") or [])
        | set(verdict.get("missing_required") or [])
        | set(verdict.get("null_fields") or [])
    )
    return sorted(merged)


def record_key_of(record) -> str:
    """单据键：优先快照 id，缺省退化为「门店@时刻」。"""
    if isinstance(record, dict):
        rid = record.get("id")
        if rid:
            return str(rid)
        store = record.get("store_id") or "?"
        as_of = record.get("as_of_ts") or "?"
        return f"{store}@{as_of}"
    return "<record_not_object>"


def shelve(conn, *, batch_id, version, record, verdict, created_at):
    """整单进搁置队列（甲）：搁置单 + 命中明细**同事务**写入。

    搁置单如实钉 allowlist_version + 非法/缺必填/违可空三数组 + 原始记录；
    随后按 verdict 全量枚举写明细（单据键 / illegal_fields / illegal_count /
    allowlist_version / created_at），并回读对撞。任一步不一致 → 抛
    GateIntegrityError，调用方不 commit 即整笔回滚，绝不落孤立搁置单。
    """
    illegal = list(verdict.get("illegal_fields") or [])
    missing = list(verdict.get("missing_required") or [])
    nulls = list(verdict.get("null_fields") or [])
    cur = conn.execute(
        """INSERT INTO allowlist_shelved(
             batch_id, allowlist_version, store_id, as_of_ts,
             illegal_fields_json, missing_fields_json, null_fields_json,
             raw_json, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            batch_id,
            version,
            record.get("store_id") if isinstance(record, dict) else None,
            record.get("as_of_ts") if isinstance(record, dict) else None,
            json.dumps(illegal, ensure_ascii=False),
            json.dumps(missing, ensure_ascii=False),
            json.dumps(nulls, ensure_ascii=False),
            json.dumps(record, ensure_ascii=False, default=str),
            created_at,
        ),
    )
    shelved_id = cur.lastrowid

    # 全量枚举明细：并集去重；count 必须等于实拦字段数。
    detail_fields = enumerated_illegal_fields(verdict)
    detail = {
        "shelved_id": shelved_id,
        "batch_id": batch_id,
        "record_key": record_key_of(record),
        "illegal_fields": detail_fields,
        "illegal_count": len(detail_fields),
        "allowlist_version": version,
        "created_at": created_at,
    }
    conn.execute(
        """INSERT INTO allowlist_hold_details(
             shelved_id, batch_id, record_key, illegal_fields_json,
             illegal_count, allowlist_version, created_at
           ) VALUES (?,?,?,?,?,?,?)""",
        (
            shelved_id,
            batch_id,
            detail["record_key"],
            json.dumps(detail_fields, ensure_ascii=False),
            detail["illegal_count"],
            version,
            created_at,
        ),
    )

    # 同事务回读对撞：明细必须与搁置载荷逐项一致，否则整笔回滚。
    row = conn.execute(
        "SELECT * FROM allowlist_hold_details WHERE shelved_id=?", (shelved_id,)
    ).fetchone()
    stored_shelved = conn.execute(
        "SELECT * FROM allowlist_shelved WHERE id=?", (shelved_id,)
    ).fetchone()
    if row is None or stored_shelved is None:
        raise GateIntegrityError("搁置明细缺失：搁置单已写但明细未落（甲 · 缺一回滚）")
    stored_fields = json.loads(row["illegal_fields_json"])
    shelved_union = sorted(
        set(json.loads(stored_shelved["illegal_fields_json"]))
        | set(json.loads(stored_shelved["missing_fields_json"]))
        | set(json.loads(stored_shelved["null_fields_json"]))
    )
    if stored_fields != shelved_union:
        raise GateIntegrityError(
            f"搁置明细与载荷分叉：detail={stored_fields} union={shelved_union}"
        )
    if json.loads(row["illegal_fields_json"]) != detail_fields:
        raise GateIntegrityError("搁置明细字段与实拦分叉（甲 · 全量枚举）")
    if row["illegal_count"] != len(detail_fields):
        raise GateIntegrityError("搁置明细 count 与实拦个数不符")
    if row["allowlist_version"] != version or stored_shelved["allowlist_version"] != version:
        raise GateIntegrityError("搁置明细版本与钉死站规分叉")
    if row["record_key"] != detail["record_key"]:
        raise GateIntegrityError("搁置明细单据键分叉")
    if row["created_at"] != created_at or stored_shelved["created_at"] != created_at:
        raise GateIntegrityError("搁置明细时刻分叉")
    return detail


# ---------------------------------------------------------------- 核证（只读）


def _recheck_rows(rows, by_version, label):
    """按每行钉死的版本重算 row_hash，与存储值对拍。任何回溯改写都会在此现形。"""
    bad = []
    for row in rows:
        ver = row["allowlist_version"]
        v = by_version.get(ver)
        if not ver or not v:
            bad.append(
                {label: row["id"], "error": "version_unknown", "allowlist_version": ver}
            )
            continue
        expect = compute_row_hash(v["definition"], dict(row))
        if expect != row["row_hash"]:
            bad.append(
                {
                    label: row["id"],
                    "error": "hash_drift",
                    "allowlist_version": ver,
                    "stored": row["row_hash"],
                    "recomputed": expect,
                }
            )
    return bad


def audit(conn) -> dict:
    """允许集核证只读接口：version、非法字段、钉死 hist 版本、valid。
    只读——不写任何表。"""
    versions = list_versions(conn)
    by_version = {v["version"]: v for v in versions}
    active = [v for v in versions if v["status"] == "active"]
    checks = []

    checks.append(
        {
            "check": "active_version_single",
            "valid": len(active) == 1,
            "detail": f"生效版本数={len(active)}",
        }
    )

    hist_rows = conn.execute("SELECT * FROM dim_store_hours_hist").fetchall()
    hist_bad = _recheck_rows(hist_rows, by_version, "hist_id")
    checks.append(
        {
            "check": "hist_hash_frozen",
            "valid": not hist_bad,
            "scanned": len(hist_rows),
            "violations": hist_bad[:20],
        }
    )

    snap_rows = conn.execute("SELECT * FROM source_snapshots").fetchall()
    snap_bad = _recheck_rows(snap_rows, by_version, "snapshot_id")
    checks.append(
        {
            "check": "snapshot_hash_frozen",
            "valid": not snap_bad,
            "scanned": len(snap_rows),
            "violations": snap_bad[:20],
        }
    )

    mirrors = conn.execute("SELECT * FROM dim_store_hours_current").fetchall()
    hist_by_id = {h["id"]: h for h in hist_rows}
    mirror_bad = []
    for m in mirrors:
        h = hist_by_id.get(m["hist_id"])
        if not h:
            mirror_bad.append({"store_id": m["store_id"], "error": "hist_missing"})
            continue
        if m["allowlist_version"] != h["allowlist_version"]:
            mirror_bad.append(
                {
                    "store_id": m["store_id"],
                    "error": "version_mismatch",
                    "mirror": m["allowlist_version"],
                    "hist": h["allowlist_version"],
                }
            )
        if m["row_hash"] != h["row_hash"]:
            mirror_bad.append({"store_id": m["store_id"], "error": "hash_mismatch"})
    checks.append(
        {
            "check": "mirror_pin_consistent",
            "valid": not mirror_bad,
            "scanned": len(mirrors),
            "violations": mirror_bad[:20],
        }
    )

    shelved = conn.execute("SELECT * FROM allowlist_shelved ORDER BY id").fetchall()
    shelved_bad = []
    for s in shelved:
        empty_verdict = (
            json.loads(s["illegal_fields_json"])
            == json.loads(s["missing_fields_json"])
            == json.loads(s["null_fields_json"])
            == []
        )
        if s["allowlist_version"] not in by_version or empty_verdict:
            shelved_bad.append(
                {
                    "shelved_id": s["id"],
                    "error": "version_unknown" if s["allowlist_version"] not in by_version else "empty_verdict",
                    "allowlist_version": s["allowlist_version"],
                }
            )
    checks.append(
        {
            "check": "shelved_wellformed",
            "valid": not shelved_bad,
            "scanned": len(shelved),
            "violations": shelved_bad[:20],
        }
    )

    # 非法字段分布（按钉死版本 × 字段 × 类别聚合）
    illegal_agg = {}
    for s in shelved:
        ver = s["allowlist_version"]
        bucket = illegal_agg.setdefault(ver, {})
        for kind, col in (
            ("unregistered", "illegal_fields_json"),
            ("missing_required", "missing_fields_json"),
            ("null_not_allowed", "null_fields_json"),
        ):
            for f in json.loads(s[col]):
                entry = bucket.setdefault(
                    f, {"unregistered": 0, "missing_required": 0, "null_not_allowed": 0}
                )
                entry[kind] += 1

    # 钉死 hist 版本分布
    hist_agg = {}
    for h in hist_rows:
        entry = hist_agg.setdefault(
            h["allowlist_version"],
            {"allowlist_version": h["allowlist_version"], "rows": 0, "current": 0},
        )
        entry["rows"] += 1
        entry["current"] += h["is_current"]

    return {
        "architecture": ARCHITECTURE,
        "version": active[0]["version"] if active else None,
        "versions": [
            {
                "version": v["version"],
                "status": v["status"],
                "dim_fields": v["definition"].get("dim_fields", []),
                "created_at": v["created_at"],
                "superseded_at": v["superseded_at"],
                "note": v["note"],
            }
            for v in versions
        ],
        "illegal_fields": illegal_agg,
        "shelved_total": len(shelved),
        "hist_versions": sorted(
            hist_agg.values(), key=lambda x: x["allowlist_version"] or ""
        ),
        "checks": checks,
        "valid": all(c["valid"] for c in checks),
    }
