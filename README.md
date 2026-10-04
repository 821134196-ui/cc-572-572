# 中学实验室玻璃器皿领用与破损登记系统

老师按课程给学生组配发器皿，实验结束后逐件扫码核对归还；管理员负责台账、柜位、检查清洗与盘点；
每件器皿的使用、清洗、破损记录可按独立编号全程溯源。

技术栈：Python 3.11 + FastAPI + SQLAlchemy 2 + SQLite，前端 Vue 3 + Vite，照片存本地，
清洗设备为可替换的模拟接口（`backend/app/washer.py`）。

## 一条本地命令启动

```bash
./run.sh
```

自动完成：创建 Python 虚拟环境装依赖 → `npm install` 并构建前端 → 初始化演示数据 →
启动服务（API 与前端同一端口）。打开 http://localhost:8000 即可使用，API 文档在 `/docs`。

重置演示数据：

```bash
rm backend/lab.db && ./run.sh
```

自动演示四个关键业务场景（自动建库、起服务、跑完即关）：

```bash
./demo.sh
```

## 演示账号（密码同用户名）

| 账号 | 姓名 | 岗位 | 可办理 |
|---|---|---|---|
| `teacher1` | 王老师 | 任课老师 | 建课程/学生组、按组配发、逐件登记归还、登记破损 |
| `admin1` | 陈管理员 | 实验室管理员 | 器皿台账与柜位、归还检查、送清洗机、盘点 |
| `reviewer1` | 赵主任 | 免赔审核员（非任课老师） | 破损/缺失的免赔或赔偿审核 |
| `teacher2` | 李老师 | 任课老师 | 用于演示老师之间数据隔离 |

## 已落实的业务规则

1. **每件器皿独立编号 + 柜位**；领用关联课程与学生组。柜位页可按编号/柜位查实物，套件逐件列出。
2. **同一件器皿不能借给两个组**：非 `AVAILABLE` 状态配发会被 409 拒绝，并提示当前借用的课程/组。
3. **归还逐件扫码核对**：完整 / 待清洗 / 裂纹 / 缺失四种结果；
   **套件缺件明确提示到具体部件**，不能只按整套数量认定已还齐；缺失也必须登记后才能结案。
4. **重复扫码只记一次**：配发时单内重复扫码忽略；归还重复登记返回 409 并提示首次登记时间。
5. **检查与清洗合格后才能回到可借库存**：归还后为"已还待检"，管理员检查合格直接回库，
   需清洗的送模拟清洗机，机台回调合格才回库。
6. **清洗后才发现破损仍追到上一节课**：`WashRecord → LoanItem → Loan`
   保留责任链，破损登记自动带出课程、班级、学生组、任课老师与配发时间。
7. **免赔由非任课老师审核**：任课老师（及管理员）调用审核接口均返回 403，只有审核员可批，
   且同一登记不能重复审核。
8. **盘点差异保留**：账有物无、物有账无/状态不符、柜位不符三类差异长期保存，
   只能追加处理说明，**不改写或删除任何领用记录**；盘点单录入后不可重复录入。
9. **岗位分离（RBAC）**：各接口按 teacher / admin / reviewer 角色限制，越权返回 403。
10. **照片存本地**（`uploads/`，经 `/uploads/` 提供访问），可在器皿台账或归还时上传。

## 目录结构

```
backend/
  app/
    main.py       # 全部 API 与业务规则（领用/归还/清洗/免赔/盘点/溯源）
    models.py     # SQLAlchemy 模型
    schemas.py    # 请求模型
    security.py   # 令牌认证 + 角色依赖
    washer.py     # 清洗设备模拟接口（start_job/get_job/finish_job）
    database.py   # SQLite 连接
  seed.py         # 演示数据（含蒸馏装置套 DS-9001，本体+5个独立编号部件）
  demo.py         # 四场景端到端脚本
frontend/
  src/App.vue     # 全部页面：柜位查询/台账/配发/逐件归还/检查清洗/免赔/盘点/溯源
run.sh            # 一条命令启动
demo.sh           # 一条命令跑演示
```

## 关键接口（见 /docs）

- `POST /api/loans` 配发；`POST /api/loans/{id}/return/{code}` 逐件归还；`POST /api/loans/{id}/close` 结案
- `POST /api/items/{code}/inspect` 检查；`POST /api/wash/start`、`POST /api/wash/{job}/complete` 清洗机
- `GET  /api/items/{code}/history` 单件器皿使用/清洗/破损全生命周期
- `POST /api/damages/{id}/review` 免赔审核（仅 reviewer）
- `POST /api/stocktakes`、`POST /api/stocktakes/{id}/count`、`.../variances/{vid}/resolve` 盘点
- `POST /api/upload`、`POST /api/items/{code}/photo` 照片本地存储
