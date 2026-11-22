"""allowlist_hold_audit · 契约搁置命中明细（读 / 核证）

口径（全局只此一种）：**甲 · 全量枚举**。
搁置成功当刻，命中明细与搁置单同事务写下：单据键 + `illegal_fields`（未登记 ∪
缺必填 ∪ 违可空 的全量并集）+ `allowlist_version`（当时站规世代）+ 时刻。三者
必须与搁置载荷、闸口 verdict、站规登记册一致；缺一则视为分叉。

本模块只读——不写任何表：
- hit_details：运营视角的搁置命中明细（按搁置单 1:1）。
- audit_hits：核证只读接口（基线所无）。逐单核：明细存在、字段与搁置载荷一致、
  世代与钉版一致且在登记册、按钉死站规重演闸的并集与明细逐字一致。
"""

import json

from app.modules import snapshot_field_allowlist as allowlist

STATUS = "implemented"


def _fetch(conn):
    """读取搁置单 LEFT JOIN 命中明细。缺明细的搁置单也返回（detail_ready=False）。"""
    return conn.execute(
        """SELECT s.id AS shelved_id, s.batch_id, s.store_id, s.as_of_ts,
                  s.allowlist_version AS pinned_version, s.created_at AS shelved_at,
                  s.illegal_fields_json, s.missing_fields_json, s.null_fields_json,
                  s.raw_json,
                  d.id AS detail_id, d.record_key, d.illegal_fields_json AS detail_fields_json,
                  d.illegal_count, d.allowlist_version AS detail_version,
                  d.created_at AS detail_at
           FROM allowlist_shelved s
           LEFT JOIN allowlist_hold_details d ON d.shelved_id = s.id
           ORDER BY s.id"""
    ).fetchall()


def hit_details(conn) -> dict:
    """搁置命中明细（全量枚举）。每条搁置单对应一条明细；缺明细则 detail_ready=False。"""
    rows = _fetch(conn)
    details = []
    for r in rows:
        ready = r["detail_id"] is not None
        fields = json.loads(r["detail_fields_json"]) if ready else []
        details.append(
            {
                "shelved_id": r["shelved_id"],
                "record_key": r["record_key"] if ready else None,
                "illegal_fields": fields,
                "illegal_count": r["illegal_count"] if ready else 0,
                "allowlist_version": (
                    r["detail_version"] if ready else r["pinned_version"]
                ),
                "created_at": r["detail_at"] if ready else r["shelved_at"],
                "detail_ready": ready,
            }
        )
    enumerated_n = sum(1 for d in details if d["detail_ready"])
    return {"details": details, "enumerated_n": enumerated_n, "total_n": len(details)}


def audit_hits(conn) -> dict:
    """核证只读接口（基线所无）：逐搁置单核命中明细与载荷/站规/重演闸的一致性。

    检查项：
      1. detail_present        —— 每张搁置单都有明细（缺 → detail_missing）
      2. fields_match_shelved  —— 明细字段 == 搁置三数组并集（分叉 → fields_diverged）
      3. version_pinned        —— 明细版本 == 搁置钉版且在登记册（→ version_diverged / version_unknown）
      4. regate_enumerated     —— 按钉死站规重演闸，全量并集与明细逐字一致（→ regate_mismatch）
    只读，不写表。valid = 四项皆无违规且至少核过一张单（或本无搁置单）。
    """
    rows = _fetch(conn)
    by_version = {v["version"]: v for v in allowlist.list_versions(conn)}

    detail_missing, fields_diverged, version_diverged, regate_mismatch = [], [], [], []

    for r in rows:
        sid = r["shelved_id"]
        pinned = r["pinned_version"]
        if r["detail_id"] is None:
            detail_missing.append(
                {"shelved_id": sid, "error": "detail_missing", "allowlist_version": pinned}
            )
            continue

        detail_fields = json.loads(r["detail_fields_json"])
        shelved_union = sorted(
            set(json.loads(r["illegal_fields_json"]))
            | set(json.loads(r["missing_fields_json"]))
            | set(json.loads(r["null_fields_json"]))
        )
        if detail_fields != shelved_union or r["illegal_count"] != len(detail_fields):
            fields_diverged.append(
                {
                    "shelved_id": sid,
                    "error": "fields_diverged",
                    "detail": detail_fields,
                    "shelved_union": shelved_union,
                    "detail_count": r["illegal_count"],
                }
            )

        if r["detail_version"] != pinned:
            version_diverged.append(
                {
                    "shelved_id": sid,
                    "error": "version_diverged",
                    "detail_version": r["detail_version"],
                    "pinned_version": pinned,
                }
            )
        elif pinned not in by_version:
            version_diverged.append(
                {"shelved_id": sid, "error": "version_unknown", "allowlist_version": pinned}
            )
            continue

        # 重演闸：按搁置钉死的站规定义对原始记录重跑闸口，全量并集须与明细逐字一致。
        definition = by_version[pinned]["definition"]
        try:
            raw = json.loads(r["raw_json"])
        except (TypeError, ValueError):
            regate_mismatch.append({"shelved_id": sid, "error": "raw_unparseable"})
            continue
        reread = allowlist.enumerated_illegal_fields(
            allowlist.gate_record(definition, raw)
        )
        if reread != detail_fields:
            regate_mismatch.append(
                {
                    "shelved_id": sid,
                    "error": "regate_mismatch",
                    "expected": reread,
                    "detail": detail_fields,
                }
            )

    checks = [
        {
            "check": "detail_present",
            "valid": not detail_missing,
            "scanned": len(rows),
            "violations": detail_missing[:20],
        },
        {
            "check": "fields_match_shelved",
            "valid": not fields_diverged,
            "scanned": len(rows),
            "violations": fields_diverged[:20],
        },
        {
            "check": "version_pinned",
            "valid": not version_diverged,
            "scanned": len(rows),
            "violations": version_diverged[:20],
        },
        {
            "check": "regate_enumerated",
            "valid": not regate_mismatch,
            "scanned": len(rows),
            "violations": regate_mismatch[:20],
        },
    ]
    return {
        "architecture": allowlist.ARCHITECTURE,
        "verdict_standard": "甲 · 全量枚举（illegal_fields 列出全部非法字段，缺一即失败）",
        "shelved_total": len(rows),
        "verified_total": sum(1 for r in rows if r["detail_id"] is not None),
        "checks": checks,
        "valid": all(c["valid"] for c in checks),
    }
