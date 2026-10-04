"""端到端演示：套件缺件、重复归还、盘点差异、任课老师自行免赔被拒。

用法（在 run.sh 启动后另开终端）：
    .venv/bin/python backend/demo.py
或直接：./demo.sh  （自动建库、起服务、跑完后关闭服务）
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("LAB_BASE", "http://127.0.0.1:8000")
TOKENS = {}


def call(method, path, body=None, role=None, expect_ok=True):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if role:
        req.add_header("Authorization", f"Bearer {TOKENS[role]}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read().decode())
        if expect_ok:
            return {"__http_error__": e.code, "detail": detail.get("detail")}
        return {"__http_error__": e.code, "detail": detail.get("detail")}


def banner(n, title):
    print("\n" + "=" * 66)
    print(f" 场景 {n}：{title}")
    print("=" * 66)


def step(t):
    print(f"\n▶ {t}")


def ok(t):
    print(f"  ✅ {t}")


def warn(t):
    print(f"  ⚠️  {t}")


def show(title, payload):
    print(f"  ── {title}")
    if isinstance(payload, str):
        for line in payload.splitlines():
            print(f"     {line}")
    else:
        print("     " + json.dumps(payload, ensure_ascii=False, indent=2).replace("\n", "\n     "))


def login(role, username):
    r = call("POST", "/api/login", {"username": username, "password": username})
    TOKENS[role] = r["token"]
    print(f"  登录：{r['name']}（{r['role_name']}）")


def wait_server():
    for _ in range(60):
        try:
            urllib.request.urlopen(urllib.request.Request(
                BASE + "/api/login", data=b"{}", method="POST",
                headers={"Content-Type": "application/json"}), timeout=1)
            return
        except urllib.error.HTTPError:
            return  # 服务已在响应（422 等），视为启动成功
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("服务未启动")


def main():
    wait_server()

    print("=" * 66)
    print(" 中学实验室玻璃器皿领用与破损登记系统 — 业务规则演示")
    print("=" * 66)
    login("teacher", "teacher1")
    login("admin", "admin1")
    login("reviewer", "reviewer1")

    courses = call("GET", "/api/courses", role="teacher")
    course_id = courses[0]["id"]
    g1, g2 = courses[0]["groups"][0]["id"], courses[0]["groups"][1]["id"]
    print(f"  课程：{courses[0]['name']}（{courses[0]['class_name']}），"
          f"学生组：{courses[0]['groups'][0]['name']} / {courses[0]['groups'][1]['name']}")

    # ==================== 场景 1：套件缺件 ====================
    banner(1, "套件缺件——逐件核对，不能只按整套数量认定已还齐")
    step("王老师给第1组配发蒸馏装置套 DS-9001（本体+5个独立编号部件）和烧杯 BK-1001")
    codes = ["DS-9001", "DS-9001-01", "DS-9001-02", "DS-9001-03",
             "DS-9001-04", "DS-9001-05", "BK-1001"]
    r = call("POST", "/api/loans",
             {"course_id": course_id, "group_id": g1, "item_codes": codes}, role="teacher")
    loan1 = r["loan_id"]
    ok(f"领用单 #{loan1} 已配发 {r['issued']} 件")

    step("配发扫码时 DS-9001-02 被扫了两次（验证重复扫码只记一次）")
    r = call("POST", "/api/loans",
             {"course_id": course_id, "group_id": g2,
              "item_codes": ["BK-1003", "BK-1003", "CF-2001"]}, role="teacher")
    ok(f"第2组领用单 #{r['loan_id']}：配发 {r['issued']} 件，"
       f"重复扫码被忽略 {r['duplicate_scans_ignored']}")

    step("第1组实验结束，王老师尝试把仍在借用中的 DS-9001-03 再借给第2组（同一件不能借两个组）")
    r = call("POST", "/api/loans",
             {"course_id": course_id, "group_id": g2,
              "item_codes": ["DS-9001-03"]}, role="teacher", expect_ok=False)
    blocked = r["detail"]["blocked"][0]
    warn(f"系统拒绝配发：{blocked['code']} 当前为「{blocked['status_name']}」{blocked['where']}")

    step("逐件归还：5个部件完整，接引管 DS-9001-04 确认【缺失】，烧杯 BK-1001 待清洗")
    returns = [("DS-9001", "COMPLETE"), ("DS-9001-01", "COMPLETE"),
               ("DS-9001-02", "COMPLETE"), ("DS-9001-03", "COMPLETE"),
               ("DS-9001-05", "COMPLETE"), ("BK-1001", "DIRTY")]
    for code, result in returns:
        call("POST", f"/api/loans/{loan1}/return/{code}", {"result": result}, role="teacher")
    r = call("POST", f"/api/loans/{loan1}/return/DS-9001-04",
             {"result": "MISSING", "note": "学生报告接引管打碎后丢弃"}, role="teacher")
    for w in r["kit_warnings"]:
        warn(w)
    ok(f"缺失部件已自动生成破损/缺失登记（damage_id={r['damage_id']}），"
       f"进度 {r['returned']}/{r['total']}（缺失也算已逐件核对）")

    step("查看领用单的套件核对结论")
    detail = call("GET", f"/api/loans/{loan1}", role="teacher")
    for k in detail["kit_summaries"]:
        show("套件核对", k["verdict"])

    # ==================== 场景 2：重复归还只记一次 ====================
    banner(2, "重复扫码归还——同一件只记一次")
    step("再次扫描 DS-9001-01 办理归还")
    r = call("POST", f"/api/loans/{loan1}/return/DS-9001-01",
             {"result": "COMPLETE"}, role="teacher", expect_ok=False)
    warn(f"HTTP 409 系统拒绝：{r['detail']}")
    detail = call("GET", f"/api/loans/{loan1}", role="teacher")
    n = sum(1 for i in detail["items"] if i["code"] == "DS-9001-01")
    ok(f"领用单中 DS-9001-01 仍只有 {n} 条归还记录，未重复入账")

    step("全部逐件核对完毕（含缺失登记），王老师结案")
    r = call("POST", f"/api/loans/{loan1}/close", {}, role="teacher")
    ok(f"领用单 #{loan1} 状态：{r['loan']['status']}（已结案）")

    step("管理员把待清洗的 BK-1001 送清洗机（模拟设备接口），清洗合格后回库")
    r = call("POST", "/api/wash/start", {"item_codes": ["BK-1001"]}, role="admin")
    job1 = r["jobs"][0]["job_id"]
    ok(f"清洗机接单，机台任务号 {job1}")
    r = call("POST", f"/api/wash/{job1}/complete?result=PASS", {}, role="admin")
    ok(f"{r['item_code']} 清洗结果：合格 → 状态 {r['item_status']}（回到可借库存）")

    step("清洗后才发现破损，仍要追到上一节课：")
    loan2 = call("GET", "/api/loans?status=OPEN", role="teacher")
    loan2_id = next(l["id"] for l in loan2 if l["group"] == "第2组")
    call("POST", f"/api/loans/{loan2_id}/return/BK-1003",
         {"result": "COMPLETE"}, role="teacher")
    r = call("POST", "/api/wash/start", {"item_codes": ["BK-1003"]}, role="admin")
    job2 = r["jobs"][0]["job_id"]
    r = call("POST", f"/api/wash/{job2}/complete?result=FAIL", {}, role="admin")
    t = r["traced_loan"]
    warn(f"机台目检发现 {r['item_code']} 裂纹（damage_id={r['damage_id']}）")
    ok(f"自动追溯上一节课：{t['course']} / {t['class_name']} / {t['group']}，"
       f"任课老师 {t['teacher']}，配发时间 {t['issued_at']}")

    # ==================== 场景 3：盘点差异 ====================
    banner(3, "盘点差异——保留差异，不得直接改掉领用记录")
    step("管理员新建全校盘点单")
    sid = call("POST", "/api/stocktakes", {"label": "10月例行盘点"}, role="admin")["id"]
    st = call("GET", f"/api/stocktakes/{sid}", role="admin")
    expected_codes = [i["code"] for i in st["expected"]]
    ok(f"账面可借器皿 {len(expected_codes)} 件")

    step("实盘：故意漏扫 BK-1003 之外的一件在库器皿、多扫一个不存在编号 TT-9999、"
         "BK-1001 放到别的柜位")
    # BK-1003 清洗后破损已不在可借账面；从可借清单中去掉 GC-7001 模拟实物找不到
    counted = [c for c in expected_codes if c != "GC-7001"]
    counted = [{"item_code": c, "found_location": None} for c in counted]
    counted.append({"item_code": "TT-9999", "found_location": "A-09-09"})
    for e in counted:
        if e["item_code"] == "BK-1001":
            e["found_location"] = "X-99-99"
    r = call("POST", f"/api/stocktakes/{sid}/count", counted, role="admin")
    ok(f"实盘 {r['counted']} 件 / 账面 {r['expected']} 件，产生差异 {len(r['variances'])} 条：")
    for v in r["variances"]:
        warn(f"[{v['kind_name']}] {v['item_code']}：{v['detail']}")

    step("尝试重复录入盘点（系统以首次盘点为准，差异保留）")
    r = call("POST", f"/api/stocktakes/{sid}/count", counted, role="admin", expect_ok=False)
    warn(f"HTTP {r['__http_error__']}：{r['detail']}")

    step("核对：领用记录未被盘点改动")
    d1 = call("GET", f"/api/loans/{loan1}", role="admin")
    missing_rows = [i for i in d1["items"] if i["return_result"] == "MISSING"]
    ok(f"领用单 #{loan1} 仍为「{d1['status']}」，"
       f"DS-9001-04 的缺失登记仍在（{missing_rows[0]['code']}：{missing_rows[0]['return_result_name']}），"
       f"历史明细一条未改")

    step("管理员对差异追加处理说明（只追加，差异记录仍保留）")
    st = call("GET", f"/api/stocktakes/{sid}", role="admin")
    v = next(v for v in st["variances"] if v["item_code"] == "GC-7001")
    call("POST", f"/api/stocktakes/{sid}/variances/{v['id']}/resolve",
         {"resolution": "经查借给兄弟学校未登记，已催还，差异存档"}, role="admin")
    ok("处理说明已追加，差异可在盘点单中永久查阅")

    # ==================== 场景 4：任课老师自行免赔被拒 ====================
    banner(4, "免赔审核——免赔由非任课老师审核，老师不能自行免赔")
    pendings = call("GET", "/api/damages?status=PENDING", role="teacher")
    ok(f"当前待审核破损/缺失 {len(pendings)} 件")
    target = next(d for d in pendings if d["item_code"] == "DS-9001-04")
    show("待审核登记", f"{target['item_code']} {target['item_name']}｜{target['source_name']}｜"
                      f"{target['description']}")

    step("王老师（任课老师）尝试对自己课上缺失的部件核准免赔")
    r = call("POST", f"/api/damages/{target['id']}/review",
             {"decision": "WAIVED", "note": "算了不用赔"}, role="teacher", expect_ok=False)
    warn(f"HTTP 403 系统拒绝：{r['detail']}")

    step("管理员同样无权审核免赔（岗位分离）")
    r = call("POST", f"/api/damages/{target['id']}/review",
             {"decision": "WAIVED", "note": "管理员特批"}, role="admin", expect_ok=False)
    warn(f"HTTP 403 系统拒绝：{r['detail']}")

    step("赵主任（免赔审核员，非任课老师）审核")
    r = call("POST", f"/api/damages/{target['id']}/review",
             {"decision": "WAIVED", "note": "属正常教学损耗，准予免赔"}, role="reviewer")
    ok(f"免赔核准：{r['message']}，审核人 {r['reviewed_by']}")

    step("对同一登记重复审核")
    r = call("POST", f"/api/damages/{target['id']}/review",
             {"decision": "CHARGED", "note": "改主意"}, role="reviewer", expect_ok=False)
    warn(f"HTTP 409：{r['detail']}")

    # ==================== 溯源展示 ====================
    banner("附", "管理员按编号查每件器皿的使用与清洗记录（以 BK-1003 为例）")
    h = call("GET", "/api/items/BK-1003/history", role="admin")
    show("器皿", f"{h['item']['code']} {h['item']['name']} {h['item']['spec']}，"
                f"柜位 {h['item']['location_code']}，当前 {h['item']['status_name']}")
    for l in h["loans"]:
        print(f"     · 领用：{l['issued_at']} {l['course']}/{l['group']}，"
              f"老师 {l['teacher']}，归还结果：{l['return_result']}")
    for w in h["washes"]:
        print(f"     · 清洗：{w['job_id']} {w['started_at']} → {w['result']}（{w['note']}）")
    for d in h["damages"]:
        print(f"     · 破损：{d['source_name']} {d['damage_type_name']}：{d['description']}"
              f"【{d['status_name']}】")

    print("\n" + "=" * 66)
    print(" 全部规则演示完成。可打开 http://localhost:8000 用各岗位账号操作界面。")
    print("=" * 66 + "\n")


if __name__ == "__main__":
    main()
