import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Overview() {
  const [ov, setOv] = useState(null);
  const [stores, setStores] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    Promise.all([api("/api/overview"), api("/api/stores")])
      .then(([o, s]) => { setOv(o); setStores(s); })
      .catch((e) => setErr(String(e.message || e)));
  }, []);

  const cards = ov
    ? [
        ["门店", ov["门店数"]],
        ["快照", ov["快照数"]],
        ["历史行", ov["历史行"]],
        ["当前镜", ov["当前镜"]],
        ["检测跑次", ov["检测跑次"]],
        ["核证条", ov["核证条"]],
        ["允许集版本", ov["允许集版本"]],
        ["契约搁置", ov["契约搁置"]],
      ]
    : [];

  return (
    <>
      <div data-plant="30-allowlist-hold-audit-miss" className="plant-mark" style={{display:"none"}} />
      <div className="topbar">
        <div>
          <h1>总览</h1>
          <p>贴源入档 → 变更检测 → Type2 开闭 → 当前镜 → 核证。门店名只是业务皮。</p>
        </div>
      </div>
      {err && <p className="error">{err}</p>}
      <div className="grid-cards">
        {cards.map(([k, v]) => (
          <div className="card" key={k}>
            <div className="label">{k}</div>
            <div className="value">{v ?? "-"}</div>
          </div>
        ))}
      </div>
      <div className="panel">
        <h2>门店营业档（当前镜）</h2>
        <div className="store-grid">
          {stores.map((s) => (
            <div className="store-tile" key={s.id}>
              <h3>{s.name}</h3>
              <div className="meta">{s.id} · {s.region} · 历史 {s.hist_count} 行</div>
              <div className="hours">
                {(s.open_time || "—")} – {(s.close_time || "—")}
              </div>
              <div style={{ marginTop: "0.45rem" }}>
                <span className={`badge ${s.biz_status || ""}`}>{s.biz_status || "无镜"}</span>
                <span className="muted" style={{ marginLeft: 8 }}>mask {s.weekday_mask}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
      {ov?.空桩 && (
        <div className="panel">
          <h2>邻题空桩（{ov.空桩.length}）</h2>
          <p className="muted">同仓换主链路时实现其一；底座 happy path 不依赖。</p>
          <p className="mono">{ov.空桩.join(" · ")}</p>
        </div>
      )}
    </>
  );
}
