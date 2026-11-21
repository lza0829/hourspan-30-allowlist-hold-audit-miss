import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Settings() {
  const [settings, setSettings] = useState({});
  const [stubs, setStubs] = useState([]);
  const [versions, setVersions] = useState([]);
  const [active, setActive] = useState("");
  const [arch, setArch] = useState("");
  const [vname, setVname] = useState("");
  const [note, setNote] = useState("");
  const [draft, setDraft] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const reload = () =>
    Promise.all([api("/api/settings"), api("/api/stubs"), api("/api/allowlist/versions")])
      .then(([s, st, al]) => {
        setSettings(s);
        setStubs(st.stubs || []);
        setVersions(al.versions || []);
        setActive(al.active || "");
        setArch(al.architecture || "");
        const cur = (al.versions || []).find((v) => v.version === al.active);
        if (cur && !draft) setDraft(JSON.stringify(cur.definition, null, 2));
      })
      .catch((e) => setErr(String(e.message || e)));

  useEffect(() => { reload(); }, []);

  const submit = async () => {
    setErr(""); setMsg("");
    let definition;
    try {
      definition = JSON.parse(draft);
    } catch (e) {
      setErr(`definition 不是合法 JSON：${e.message || e}`);
      return;
    }
    try {
      const r = await api("/api/allowlist/versions", {
        method: "POST",
        body: JSON.stringify({ version: vname, definition, note }),
      });
      setMsg(JSON.stringify(r, null, 2));
      setVname(""); setNote("");
      await reload();
    } catch (e) {
      setErr(String(e.message || e));
    }
  };

  return (
    <>
      <div className="topbar">
        <div>
          <h1>站规</h1>
          <p>端口 6200 / 11200 · 公有仓 lza0829/hourspan-* · 禁门店运营 CRUD 皮。</p>
        </div>
      </div>
      {err && <p className="error">{err}</p>}
      {msg && <pre className="msg">{msg}</pre>}
      <div className="panel">
        <h2>允许集版本（入档契约闸 · {arch}）</h2>
        <p className="muted">
          热更新只写版本登记册：在途批仍钉开批时的旧版，旧 hist 的 row_hash 不回溯改写。当前生效：
          <span className="mono">{active || "无"}</span>
        </p>
        <table>
          <thead>
            <tr><th>版本</th><th>状态</th><th>维度字段</th><th>登记时间</th><th>废止时间</th><th>备注</th></tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.version}>
                <td className="mono">{v.version}</td>
                <td><span className={`badge ${v.status === "active" ? "ok" : ""}`}>{v.status}</span></td>
                <td className="mono">{(v.definition.dim_fields || []).join(",")}</td>
                <td>{v.created_at}</td>
                <td>{v.superseded_at || "—"}</td>
                <td>{v.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h2>热更新允许集（站规版本写入）</h2>
        <div className="actions" style={{ alignItems: "flex-start" }}>
          <input
            value={vname}
            onChange={(e) => setVname(e.target.value)}
            placeholder="新版本号，如 ALW-v2"
            style={{ width: 160, padding: "0.4rem 0.6rem", borderRadius: 8, border: "1px solid var(--line)", background: "#0c2226", color: "var(--text)" }}
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="备注"
            style={{ width: 220, padding: "0.4rem 0.6rem", borderRadius: 8, border: "1px solid var(--line)", background: "#0c2226", color: "var(--text)" }}
          />
          <button onClick={submit}>登记并生效</button>
        </div>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={14}
          className="mono"
          style={{ width: "100%", marginTop: "0.6rem", padding: "0.6rem", borderRadius: 8, border: "1px solid var(--line)", background: "#0c2226", color: "var(--text)" }}
        />
      </div>
      <div className="panel">
        <h2>设置</h2>
        <table>
          <thead><tr><th>键</th><th>值</th></tr></thead>
          <tbody>
            {Object.entries(settings).map(([k, v]) => (
              <tr key={k}><td>{k}</td><td className="mono">{v}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h2>空桩清单</h2>
        <ul>
          {stubs.map((s) => (
            <li key={s} className="mono">{s}</li>
          ))}
        </ul>
      </div>
    </>
  );
}
