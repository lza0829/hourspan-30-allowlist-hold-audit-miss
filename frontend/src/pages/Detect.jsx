import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Detect() {
  const [runs, setRuns] = useState([]);
  const [batchId, setBatchId] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const reload = () =>
    api("/api/detect-runs").then(setRuns).catch((e) => setErr(String(e.message || e)));

  useEffect(() => { reload(); }, []);

  const run = async () => {
    setErr("");
    try {
      const body = batchId.trim() ? { batch_id: batchId.trim() } : {};
      const r = await api("/api/detect/run", { method: "POST", body: JSON.stringify(body) });
      setMsg(JSON.stringify(r, null, 2));
      await reload();
    } catch (e) {
      setErr(String(e.message || e));
    }
  };

  return (
    <>
      <div data-plant="30-allowlist-hold-audit-miss" className="plant-mark" style={{display:"none"}} />
      <div className="topbar">
        <div>
          <h1>变更检测</h1>
          <p>对照当前镜与快照 row_hash，产出变更清单（new / attr_change）。</p>
        </div>
      </div>
      <div className="panel">
        <div className="actions">
          <input
            value={batchId}
            onChange={(e) => setBatchId(e.target.value)}
            placeholder="可选 batch_id，空=各店最新快照"
            style={{ minWidth: 280, padding: "0.4rem 0.6rem", borderRadius: 8, border: "1px solid var(--line)", background: "#0c2226", color: "var(--text)" }}
          />
          <button onClick={run}>跑检测</button>
          <button className="secondary" onClick={reload}>刷新</button>
        </div>
        {msg && <pre className="msg">{msg}</pre>}
        {err && <p className="error">{err}</p>}
      </div>
      <div className="panel">
        <h2>检测跑次</h2>
        <table>
          <thead><tr><th>跑次</th><th>批</th><th>时间</th><th>变更数</th><th>报告摘要</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.id}</td>
                <td className="mono">{r.batch_id || "—"}</td>
                <td>{r.created_at}</td>
                <td>{r.changed_count}</td>
                <td className="mono">{(r.report_json || "").slice(0, 120)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
