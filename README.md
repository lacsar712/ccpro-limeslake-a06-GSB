# LimeSlake-01 · 石灰熟化池作业板

厂区熟化池平面图作业基线（Flask + Jinja + Stimulus）。主界面是按厂区排布的池位瓦片，点选后在右侧抽屉登记峰值温度并改状态——不是侧栏双列表 CRUD。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web | Flask 3 · Blueprints · Flask-Login · Jinja2 · Stimulus CDN |
| 数据 | SQLAlchemy · PostgreSQL 15 |
| 部署 | Docker Compose · Gunicorn |

## 路径与端口

- **项目路径**：`d:\work\document\bytecode\claudeCodePro\LimeSlake\LimeSlake-01`
- **Web**：http://localhost:4730
- **PostgreSQL**：localhost:6130

## 演示账号

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `123456` | 管理员 |
| `worker` | `123456` | 操作工 |

登录页已预填 `admin` / `123456`。启动时 entrypoint 会建表并写入种子数据（示范厂区：**东湾石灰厂**）。

## 主界面

- **熟化池平面图**（`/board/`）：CSS 网格池位瓦片，按状态着色（注水中 / 熟化中 / 已出灰）；瓦片右上角角标显示最近批次的投放凭条数
- 顶部厂区切换芯片（多厂时切换）
- 点击瓦片 → 右侧抽屉展示最近 `SlakeBatch` 及其投放凭链，可登记峰值温度并变更池状态
- 顶栏挂「平面图」与「投放凭」（`/vouchers/`：按批次下拉查看凭链、新增投放凭）
- 主导航不再挂「熟化池列表 / 批次列表」；旧 `/ponds/`、`/batches/` 路由仍保留但不作为作业入口

## 业务规则

### 投放凭（熟化剂投放凭据）

- 字段：熟化批次、凭号（同批次从 1 起、不得重复）、药剂名、投放公斤（须为正）、投放时刻、投放人
- **仅熟化中**（`slaking`）批次可写投放凭；注水中不可写、已出灰批次禁止再写
- 写入或改写峰值温度前，投放凭必须备齐：
  1. 至少 1 条；
  2. 凭号从 1 起连续（1、2、3…）；
  3. 最近一次投放时刻晚于批次开班时刻。
- 缺凭 / 断号 / 投放不晚于开班，一律中文拒绝；所有峰值写入口（平面图抽屉、批次登记/编辑旧表单）走同一道规则，无旁路
- 同批次同凭号有数据库唯一约束兜底：两名操作工并发抢交同一凭号时只落一笔，后提交者收到中文提示，平面图仍可正常打开

### 出灰

熟化池状态不可设为「已出灰」（`drawn`），除非该池**最近一条** `SlakeBatch` 的 `peakTempC` 已记录且 **≥ 60℃**（峰值本身又须先过投放凭门槛）。

规则实现：`app/services/rules.py`

## 快速启动

```bash
cd d:\work\document\bytecode\claudeCodePro\LimeSlake\LimeSlake-01
docker compose up --build
```

浏览器打开 http://localhost:4730

停止：

```bash
docker compose down
```

## 目录结构

```
LimeSlake-01/
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── wsgi.py
├── app/
│   ├── __init__.py          # 工厂 + seed
│   ├── models.py
│   ├── services/rules.py
│   └── blueprints/{auth,board,ponds,batches}
├── templates/
│   └── board/floor.html     # 平面图 + 抽屉
└── static/
```
