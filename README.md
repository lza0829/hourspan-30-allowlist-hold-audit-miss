# 时档（HourSpan）

**骨架：** 门店营业属性贴源入档 → 业务键变更检测 → Type2 历史行开闭 → 当前镜投影 → 历史与当前互证

- 领域：数据工程（去皮=维表 SCD / 历史开闭 / 当前镜 / 核证；不是门店后台 CRUD）
- 端口：前端 **6200**，接口 **11200**（避开 Chrome 封锁的 6000–6063）
- 公有仓前缀：`lza0829/hourspan-NN-*`
- 栈：Python 3.12 + FastAPI + SQLite；前端 **React + Vite**
- 避让：勿撞筑层分层汇总、价舱改价调度、信汇多源去重、变流 CDC 游标、格湾占用态

本地冒烟：

```powershell
cd claude-workspace/hourspan/_scaffold/backend
pip install -r requirements.txt
$env:DATA_DIR="$PWD/data"; $env:FIXTURES_DIR="$PWD/../fixtures"
python -m uvicorn app.main:app --host 127.0.0.1 --port 11200

cd ../frontend
npm install
npm run dev
```

或：`docker compose up -d --build`（6200 / 11200）

## 入档契约闸 · snapshot_field_allowlist（架构甲 · 整单契约）

快照生效字段必须落在开批钉死的允许集版本内（覆盖 open_time/close_time/weekday_mask/biz_status 及可空规则）。
**同一入档单既有合法字段又有非法字段时：整单搁置**——不入有效维、不开 hist，搁置记录钉
`allowlist_version` + 非法字段。失败闭路径同属甲：无生效版本/定义损坏 → 闸门关死，整批拒收。

- 开批即钉版：热更新与在途入档交错时，在途批（含已开 hist）仍钉旧版
- 新开 hist 钉死所用版本；hash 一次算定即固化，改集绝不回溯改写旧 hist 的 row_hash
- **命中明细（甲 · 全量枚举）**：搁置成功当刻与搁置单**同事务**写下单据键 + `illegal_fields`（未登记 ∪ 缺必填 ∪ 违可空 的全量并集）+ `allowlist_version` + 时刻；明细分叉/缺失整笔回滚，绝不「搁置成功而无明细」
- 接口：`GET/POST /api/allowlist/versions`（站规版本读/写·热更新）、`GET /api/allowlist/shelved`（搁置队列·含命中明细）、
  `GET /api/allowlist/audit`（核证只读：version / 非法字段 / 钉死 hist 版本 / valid）、
  `GET /api/allowlist/hold-details`（命中明细只读）、`GET /api/allowlist/hold-audit`（命中核证只读：明细↔载荷↔站规↔重演闸互证）
- 核证脚本：`PYTHONPATH=backend python3 scripts/verify_allowlist.py`
  （纯合法通过 / 纯非法搁置 / 混单无 hist / 热更新零漂移 / 失败闭 / 篡改必抓 / 命中明细全量枚举与回滚，47 项全绿）

