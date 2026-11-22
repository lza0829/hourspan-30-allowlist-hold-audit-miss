import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Proofs() {
  const [rows, setRows] = useState([]);
  const [companion, setCompanion] = useState(null);
  const [holdAudit, setHoldAudit] = useState(null);
  const [audit, setAudit] = useState(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const reload = () =>
    Promise.all([
      api("/api/proofs"),
      api("/api/allowlist/audit"),
      api("/api/allowlist/hold-details"),
      api("/api/allowlist/hold-audit"),
    ])
      .then(([p, a, hd, ha]) => {
        setRows(p);
        setAudit(a);
        setCompanion(hd);
        setHoldAudit(ha);
      })
      .catch((e) => setErr(String(e.message || e)));

  useEffect(() => { reload(); }, []);

  const rebuild = async () => {
    setErr("");
    try {
      const r = await api("/api/proofs/rebuild", { method: "POST", body: "{}" });
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
          <h1>核证</h1>
          <p>当前镜 hist_id / row_hash 必须与 is_current 历史行一致；允许集核证只读接口互证钉版与 hash 固化。</p>
        </div>
      </div>
      <div className="panel">
        <div className="actions">
          <button onClick={rebuild}>重建核证</button>
          <button className="secondary" onClick={reload}>刷新</button>
        </div>
        {msg && <pre className="msg">{msg}</pre>}
        {err && <p className="error">{err}</p>}
      </div>
      {audit && (
        <div className="panel">
          <h2>
            允许集核证（只读）{" "}
            <span className={`badge ${audit.valid ? "ok" : "bad"}`}>
              {audit.valid ? "valid" : "invalid"}
            </span>
          </h2>
          <p className="muted">
            {audit.architecture} · 当前生效版本 <span className="mono">{audit.version || "无"}</span>
            {" "}· 搁置 {audit.shelved_total} 单
          </p>
          <h2>钉死 hist 版本</h2>
          <table>
            <thead><tr><th>允许集版本</th><th>hist 行数</th><th>其中当前行</th></tr></thead>
            <tbody>
              {audit.hist_versions.map((h) => (
                <tr key={h.allowlist_version}>
                  <td className="mono">{h.allowlist_version}</td>
                  <td>{h.rows}</td>
                  <td>{h.current}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>非法字段（搁置队列聚合）</h2>
          <table>
            <thead><tr><th>钉版</th><th>字段</th><th>未登记</th><th>缺必填</th><th>违可空</th></tr></thead>
            <tbody>
              {Object.entries(audit.illegal_fields).flatMap(([ver, fields]) =>
                Object.entries(fields).map(([f, kinds]) => (
                  <tr key={`${ver}:${f}`}>
                    <td className="mono">{ver}</td>
                    <td className="mono">{f}</td>
                    <td>{kinds.unregistered || ""}</td>
                    <td>{kinds.missing_required || ""}</td>
                    <td>{kinds.null_not_allowed || ""}</td>
                  </tr>
                ))
              )}
              {!Object.keys(audit.illegal_fields).length && (
                <tr><td colSpan={5} className="muted">暂无非法字段记录</td></tr>
              )}
            </tbody>
          </table>
          <h2>逐项核证</h2>
          <table>
            <thead><tr><th>检查</th><th>结论</th><th>扫描</th><th>明细</th></tr></thead>
            <tbody>
              {audit.checks.map((c) => (
                <tr key={c.check}>
                  <td className="mono">{c.check}</td>
                  <td>
                    <span className={`badge ${c.valid ? "ok" : "bad"}`}>
                      {c.valid ? "通过" : "失败"}
                    </span>
                  </td>
                  <td>{c.scanned ?? "—"}</td>
                  <td className="mono">
                    {c.detail || (c.violations && c.violations.length
                      ? JSON.stringify(c.violations)
                      : "—")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      
      <div className="panel">
        <h2>
          契约搁置命中明细（甲 · 全量枚举）{" "}
          {holdAudit && (
            <span className={`badge ${holdAudit.valid ? "ok" : "bad"}`}>
              {holdAudit.valid ? "valid" : "invalid"}
            </span>
          )}
        </h2>
        {holdAudit && (
          <p className="muted">
            {holdAudit.verdict_standard} · 已核 {holdAudit.verified_total}/{holdAudit.shelved_total} 单
          </p>
        )}
        <table>
          <thead>
            <tr><th>搁置单</th><th>单据键</th><th>非法字段（全量）</th><th>计数</th><th>钉版</th><th>时刻</th></tr>
          </thead>
          <tbody>
            {(companion?.details || []).map((d) => (
              <tr key={d.shelved_id}>
                <td>{d.shelved_id}</td>
                <td className="mono">{d.record_key || "—"}</td>
                <td className="mono">{(d.illegal_fields || []).join(", ") || "—"}</td>
                <td>{d.illegal_count}</td>
                <td className="mono">{d.allowlist_version}</td>
                <td>{d.created_at}</td>
              </tr>
            ))}
            {!companion?.details?.length && (
              <tr><td colSpan={6} className="muted">暂无命中明细</td></tr>
            )}
          </tbody>
        </table>
        {holdAudit && (
          <table>
            <thead><tr><th>检查</th><th>结论</th><th>扫描</th><th>明细</th></tr></thead>
            <tbody>
              {holdAudit.checks.map((c) => (
                <tr key={c.check}>
                  <td className="mono">{c.check}</td>
                  <td>
                    <span className={`badge ${c.valid ? "ok" : "bad"}`}>
                      {c.valid ? "通过" : "失败"}
                    </span>
                  </td>
                  <td>{c.scanned ?? "—"}</td>
                  <td className="mono">
                    {c.violations && c.violations.length ? JSON.stringify(c.violations) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="panel">
        <h2>scd_proofs</h2>
        <table>
          <thead>
            <tr>
              <th>id</th><th>门店</th><th>hist</th><th>mirror_hist</th><th>hash</th><th>valid</th><th>detail</th><th>时间</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>{r.store_id}</td>
                <td className="mono">{r.hist_id}</td>
                <td className="mono">{r.mirror_hist_id}</td>
                <td className="mono">{r.row_hash}</td>
                <td>
                  <span className={`badge ${r.valid ? "ok" : "bad"}`}>
                    {r.valid ? "通过" : "失败"}
                  </span>
                </td>
                <td className="mono">{r.detail_json}</td>
                <td>{r.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
