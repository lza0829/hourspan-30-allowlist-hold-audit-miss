STATUS = "partial"


def hit_details(conn) -> dict:
    try:
        rows = conn.execute("SELECT * FROM allowlist_shelved ORDER BY id DESC LIMIT 50").fetchall()
    except Exception:
        rows = []
    details = []
    for r in rows:
        details.append(
            {
                "id": r["id"] if "id" in r.keys() else None,
                "store_id": r["store_id"] if "store_id" in r.keys() else None,
                "illegal_fields": [],
                "allowlist_version": r["allowlist_version"] if "allowlist_version" in r.keys() else None,
                "detail_ready": False,
            }
        )
    return {"details": details, "enumerated_n": 0}
