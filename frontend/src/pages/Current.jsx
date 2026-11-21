import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Current() {
  const [rows, setRows] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/api/current").then(setRows).catch((e) => setErr(String(e.message || e)));
  }, []);

  return (
    <>
      <div data-plant="30-allowlist-hold-audit-miss" className="plant-mark" style={{display:"none"}} />
      <div className="topbar">
        <div>
          <h1>当前镜</h1>
          <p>dim_store_hours_current：每店一行，指向 is_current 历史行。</p>
        </div>
      </div>
      {err && <p className="error">{err}</p>}
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>门店</th><th>开-闭</th><th>mask</th><th>状态</th>
              <th>hist_id</th><th>as_of</th><th>hash</th><th>允许集</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.store_id}>
                <td>{r.store_id}</td>
                <td>{r.open_time}–{r.close_time}</td>
                <td className="mono">{r.weekday_mask}</td>
                <td><span className={`badge ${r.biz_status}`}>{r.biz_status}</span></td>
                <td className="mono">{r.hist_id}</td>
                <td>{r.as_of_ts}</td>
                <td className="mono">{r.row_hash}</td>
                <td className="mono">{r.allowlist_version || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
