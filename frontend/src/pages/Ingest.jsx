import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Ingest() {
  const [batches, setBatches] = useState([]);
  const [snaps, setSnaps] = useState([]);
  const [shelved, setShelved] = useState([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const reload = () =>
    Promise.all([api("/api/batches"), api("/api/snapshots"), api("/api/allowlist/shelved")])
      .then(([b, s, sh]) => { setBatches(b); setSnaps(s); setShelved(sh); })
      .catch((e) => setErr(String(e.message || e)));

  useEffect(() => { reload(); }, []);

  const run = async () => {
    setErr("");
    try {
      const r = await api("/api/ingest/run", { method: "POST", body: "{}" });
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
          <h1>入档</h1>
          <p>契约闸（甲 · 整单）：快照须落在开批钉死的允许集版本内；任一非法字段 → 整单进搁置队列，不入有效维、不开 hist。</p>
        </div>
      </div>
      <div className="panel">
        <div className="actions">
          <button onClick={run}>跑变更夹具入档</button>
          <button className="secondary" onClick={reload}>刷新</button>
        </div>
        {msg && <pre className="msg">{msg}</pre>}
        {err && <p className="error">{err}</p>}
      </div>
      <div className="panel">
        <h2>入档批</h2>
        <table>
          <thead><tr><th>批号</th><th>允许集</th><th>时间</th><th>报告</th></tr></thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.id}>
                <td className="mono">{b.id}</td>
                <td className="mono">{b.allowlist_version || "—"}</td>
                <td>{b.created_at}</td>
                <td className="mono">{b.report_json}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h2>搁置队列（契约闸拦下）</h2>
        <table>
          <thead>
            <tr>
              <th>id</th><th>批号</th><th>钉版</th><th>门店</th><th>未登记字段</th><th>缺必填</th><th>违可空</th><th>时间</th>
            </tr>
          </thead>
          <tbody>
            {shelved.map((s) => (
              <tr key={s.id}>
                <td>{s.id}</td>
                <td className="mono">{s.batch_id}</td>
                <td className="mono">{s.allowlist_version}</td>
                <td>{s.store_id || "—"}</td>
                <td className="mono">{s.illegal_fields_json}</td>
                <td className="mono">{s.missing_fields_json}</td>
                <td className="mono">{s.null_fields_json}</td>
                <td>{s.created_at}</td>
              </tr>
            ))}
            {!shelved.length && <tr><td colSpan={8} className="muted">暂无搁置记录</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h2>快照（近 200）</h2>
        <table>
          <thead>
            <tr>
              <th>快照</th><th>门店</th><th>as_of</th><th>开-闭</th><th>mask</th><th>状态</th><th>hash</th><th>允许集</th>
            </tr>
          </thead>
          <tbody>
            {snaps.map((s) => (
              <tr key={s.id}>
                <td className="mono">{s.id}</td>
                <td>{s.store_id}</td>
                <td>{s.as_of_ts}</td>
                <td>{s.open_time}–{s.close_time}</td>
                <td className="mono">{s.weekday_mask}</td>
                <td><span className={`badge ${s.biz_status}`}>{s.biz_status}</span></td>
                <td className="mono">{s.row_hash}</td>
                <td className="mono">{s.allowlist_version || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
