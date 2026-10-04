#!/usr/bin/env python3
"""端到端演示：套件缺件 / 重复归还 / 同件不借两组 / 清洗后破损追溯 /
任课老师自行免赔被拒 / 盘点差异保留不改领用记录 / 岗位权限边界。

用法：python3 demo.py            （会自动重建数据库并临时启动服务，结束后自动关闭）
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

BASE = "http://127.0.0.1:8000"
ROOT = os.path.dirname(os.path.abspath(__file__))

C = {
    "reset": "\033[0m", "b": "\033[1m", "dim": "\033[2m",
    "green": "\033[32m", "red": "\033[31m", "cyan": "\033[36m",
    "yellow": "\033[33m", "gray": "\033[90m",
}


def banner(t):
    print(f"\n{'='*78}\n{C['b']}{C['cyan']}  {t}{C['reset']}\n{'='*78}")


def say(t):
    print(f"{C['dim']}› {t}{C['reset']}")


def ok(t):
    print(f"{C['green']}  ✔ {t}{C['reset']}")


def blocked(t):
    print(f"{C['yellow']}  ✘ 系统拒绝：{t}{C['reset']}")


def fail(t):
    print(f"{C['red']}  ✗ 异常：{t}{C['reset']}")


class Client:
    def __init__(self, name):
        self.name = name
        self.token = None

    def login(self, username):
        r = self.call("POST", "/api/auth/login", {"username": username}, auth=False)
        self.token = r["token"]
        role_name = {"admin": "管理员", "teacher": "任课老师",
                     "washer": "清洗质检员"}[r["user"]["role"]]
        say(f"{self.name} 登录成功（{r['user']['name']} / {role_name}）")
        return r["user"]

    def call(self, method, path, body=None, auth=True, raw=None, ctype="application/json"):
        url = BASE + path
        data = None
        headers = {}
        if raw is not None:
            data = raw
            headers["Content-Type"] = ctype
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                txt = resp.read().decode()
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                detail = json.loads(raw).get("detail", str(e))
            except json.JSONDecodeError:
                detail = f"服务端错误 {e.code}: {raw[:200]}"
            raise ApiError(e.code, detail)

    def post_photo(self, path, png: bytes, filename="crack.png"):
        boundary = "----labdemo" + str(time.time_ns())
        parts = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode() + png + f"\r\n--{boundary}--\r\n".encode()
        return self.call("POST", path, raw=parts,
                         ctype=f"multipart/form-data; boundary={boundary}")


class ApiError(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"[{code}] {detail}")


def expect_block(label, fn):
    try:
        fn()
        fail(label + " —— 本应被拒绝却成功了！")
        sys.exit(1)
    except ApiError as e:
        if e.code in (400, 401, 403, 409):
            blocked(f"{label}（HTTP {e.code}）\n      {e.detail}")
        else:
            raise


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def wait_up(timeout=20):
    for _ in range(timeout * 2):
        try:
            with urllib.request.urlopen(BASE + "/", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("服务未启动")


def main():
    banner("准备：重建演示数据库并启动服务")
    subprocess.run([sys.executable, "-m", "backend.seed"], cwd=ROOT, check=True,
                   capture_output=True)
    port = 8000
    while True:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                break
            port += 1
    logf = open("/tmp/demo-uvicorn.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, stdout=logf, stderr=logf,
    )
    global BASE
    BASE = f"http://127.0.0.1:{port}"
    try:
        wait_up()
        say(f"服务已启动：{BASE}")
        run_scenario()
    finally:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10)
        print(f"\n{C['gray']}（演示服务已关闭，日志 /tmp/demo-uvicorn.log；"
              f"正式使用请执行 ./run.sh 后浏览 http://127.0.0.1:8000）{C['reset']}")


def run_scenario():
    wang, zhao, sun, admin = Client("王老师"), Client("赵老师"), Client("孙师傅"), Client("管理员")
    wang.login("wang")
    zhao.login("zhao")
    sun.login("sun")
    admin.login("admin")

    # ============ 1. 配发：套件带出全部部件 ============
    banner("场景 1-a｜老师按课程给学生组配发：扫码套件父件，自动带出整套部件")
    loan1 = wang.call("POST", "/api/loans", {
        "course_id": 1, "group_id": 1, "item_codes": ["DST-01"],
        "note": "水的蒸馏 第1组",
    })
    detail1 = wang.call("GET", f"/api/loans/{loan1['id']}")
    names = [f"{l['item_code']}({l['template_name']})" for l in detail1["lines"]]
    ok(f"领用单 #{loan1['id']} 已配发 {detail1['total_count']} 件：" + "、".join(names))
    say("扫 1 个套件编号，系统把蒸馏烧瓶 / 冷凝管 / 温度计 3 个部件一起配发")

    banner("场景 1-b｜同一件器皿不能借给两个组（含套件部件）")
    expect_block(
        "赵老师把已借出的冷凝管 DST-01-C 再发给初一(1)班第1组",
        lambda: zhao.call("POST", "/api/loans", {
            "course_id": 2, "group_id": 5, "item_codes": ["DST-01-C"]}),
    )

    say("王老师同时给本节第2组配发两只烧杯")
    loan2 = wang.call("POST", "/api/loans", {
        "course_id": 1, "group_id": 2,
        "item_codes": ["BK-250-001", "BK-250-002"],
    })
    ok(f"领用单 #{loan2['id']}：BK-250-001、BK-250-002 发给第2组")

    # ============ 2. 逐件归还 + 套件缺件 ============
    banner("场景 2-a｜实验结束逐件核对：套件只还了 2/3，系统明确指出缺哪个部件")
    for code, stt in [("DST-01", "intact"), ("DST-01-F", "intact"), ("DST-01-C", "dirty")]:
        r = wang.call("POST", f"/api/loans/{loan1['id']}/return",
                      {"item_code": code, "return_status": stt})
        ok(f"{code} 登记：{r['line']['return_status']} → {r['item_status_name']}")

    say("老师想按“整套已还”直接结单…")
    expect_block(
        f"领用单 #{loan1['id']} 结单（温度计还没还）",
        lambda: wang.call("POST", f"/api/loans/{loan1['id']}/finish", {}),
    )
    d1 = wang.call("GET", f"/api/loans/{loan1['id']}")
    for kg in d1["kit_groups"]:
        print(f"{C['red']}      ⚠ 套件核对：{kg['kit_name']}（{kg['kit_code']}）→ {kg['warning']}{C['reset']}")

    say("逐件登记温度计为「缺失」（而不是按整套数量默认已还齐）…")
    r = wang.call("POST", f"/api/loans/{loan1['id']}/return",
                  {"item_code": "DST-01-T", "return_status": "missing",
                   "note": "学生称取温度计时不慎折断"})
    ok(f"DST-01-T 登记：缺失（破损记录 #{r['damage_id']}，关联本节课程与第1组）")
    print(f"{C['red']}      ⚠ 套件提示：{r['kit_warning']}{C['reset']}")
    fin = wang.call("POST", f"/api/loans/{loan1['id']}/finish", {})
    ok(f"领用单 #{fin['id']} 已结清，状态 = issue（含缺失，转破损处理）")

    banner("场景 2-b｜重复扫码归还只记一次")
    r = wang.call("POST", f"/api/loans/{loan2['id']}/return",
                  {"item_code": "BK-250-001", "return_status": "intact"})
    ok(f"BK-250-001 首次扫码归还：{r['item_status_name']}")
    expect_block(
        "BK-250-001 再扫一次",
        lambda: wang.call("POST", f"/api/loans/{loan2['id']}/return",
                          {"item_code": "BK-250-001", "return_status": "intact"}),
    )
    d2 = wang.call("GET", f"/api/loans/{loan2['id']}")
    n = sum(1 for l in d2["lines"] if l["return_status"] == "intact")
    ok(f"领用单明细中 BK-250-001 仍只有 {n} 条归还记录，没有重复入账")

    # ============ 3. 检查 / 清洗：清洗后才发现破损，追溯上一节课 ============
    banner("场景 3｜检查与清洗合格才能回库；清洗后才发现破损，追到上一节课")
    sun.call("POST", "/api/inspect", {"item_code": "BK-250-001", "passed": True})
    ok("BK-250-001 目检合格 → 待清洗")
    job = sun.call("POST", "/api/cleaning/start", {"item_code": "BK-250-001"})
    jid = job["device_job"]["job_id"]
    ok(f"已送入模拟清洗设备，任务号 {jid}")
    say("等待设备完成清洗程序（模拟约 6 秒）…")
    for _ in range(16):
        st = sun.call("GET", f"/api/cleaning/job/{jid}")
        if st["state"] == "FINISHED":
            break
        time.sleep(1)
    ok("设备上报 FINISHED，质检员目检发现瓶口裂纹 → 判定不合格")
    res = sun.call("POST", "/api/cleaning/complete",
                   {"device_job_id": jid, "result": "fail", "note": "清洗后目检发现瓶口裂纹"})
    print(f"{C['red']}      ⚠ BK-250-001 未回库存（状态：{res['item_status_name']}）；"
          f"系统自动追溯上一节课 → {res['traced_course']}（破损记录 #{res['damage_id']}）{C['reset']}")
    photo = wang.post_photo(f"/api/damages/{res['damage_id']}/photo", PNG_1X1)
    ok(f"破损照片已保存到本地：{photo['photo_path']}")

    # ============ 4. 免赔审核：任课老师不能自行免赔 ============
    banner("场景 4-a｜免赔由非任课老师审核：王老师提交申请")
    dmg = wang.call("POST", f"/api/damages/{res['damage_id']}/waiver/request",
                    {"note": "烧杯为老化裂纹，申请免赔"})
    ok(f"破损记录 #{dmg['id']} 免赔状态 → 待审核")

    banner("场景 4-b｜本节任课老师尝试自行免赔 → 拒绝；清洗质检员也无权审核")
    expect_block(
        "王老师（本节任课老师）自己批准免赔",
        lambda: wang.call("POST", f"/api/damages/{res['damage_id']}/waiver/review",
                          {"approve": True, "note": "同意免赔"}),
    )
    expect_block(
        "孙师傅（清洗质检员）批准免赔",
        lambda: sun.call("POST", f"/api/damages/{res['damage_id']}/waiver/review",
                         {"approve": True, "note": "同意"}),
    )

    banner("场景 4-c｜由非本节任课老师赵静审核")
    dmg = zhao.call("POST", f"/api/damages/{res['damage_id']}/waiver/review",
                    {"approve": True, "note": "核实为老化，批准免赔，不向学生追偿"})
    ok(f"免赔已批准；审核人：{dmg['reviewer_name']}（非本节任课老师）")

    # ============ 5. 盘点：账实不符，差异保留，不改领用记录 ============
    banner("场景 5-a｜管理员盘点：建立盘点单并冻结系统快照")
    stk = admin.call("POST", "/api/stocktakes", {"name": "2026年10月期中盘点"})
    sid = stk["stocktake"]["id"]
    ok(f"盘点单 #{sid}：冻结系统台账 {stk['summary']['total']} 件")

    say("逐件扫到实物（含各组正在使用的 DST-01 套件、破损托盘里的烧杯），"
        "唯独找不到 BK-250-002；扫到一个台账外编号")
    found = [l["item_code"] for l in stk["lines"]
             if l["item_code"] not in ("BK-250-002", "DST-01-T")]
    for code in found:
        admin.call("POST", f"/api/stocktakes/{sid}/count",
                   {"item_code": code, "counted": True})
    r = admin.call("POST", f"/api/stocktakes/{sid}/count",
                   {"item_code": "BK-999-999", "counted": True})
    blocked(f"扫到台账外编号 {r['code']} → {r['message']}")

    before = admin.call("GET", f"/api/loans/{loan2['id']}")
    before_line = [l for l in before["lines"] if l["item_code"] == "BK-250-002"][0]

    closed = admin.call("POST", f"/api/stocktakes/{sid}/close", {})
    detail = admin.call("GET", f"/api/stocktakes/{sid}")
    loss_lines = [l for l in detail["lines"] if l["difference"] == "loss"]
    ok(f"盘点关闭：保留 {len(loss_lines)} 条盘亏差异（"
       + "、".join(f"{l['item_code']} 快照状态[{l['system_status_snapshot']}]" for l in loss_lines)
       + f"），盘盈编号 {detail['surplus_codes']}")

    banner("场景 5-b｜查明差异：登记缺失并追溯上课，但领用记录一笔不动")
    for l in loss_lines:
        if l["item_code"] == "BK-250-002":
            r = admin.call("POST", f"/api/stocktake-lines/{l['id']}/resolve", {
                "resolution": "向第2组追查：学生课后打碎未报，藏于实验台后",
                "report_loss": True,
            })
            ok(f"BK-250-002：{r['resolution']}；已登记缺失并追溯最近一次领用")
        else:
            admin.call("POST", f"/api/stocktake-lines/{l['id']}/resolve", {
                "resolution": "与归还时缺失登记一致（温度计折断），免赔流程处理中",
                "report_loss": False,
            })
            ok("DST-01-T：差异与既有缺失登记对应，仅写查明说明")

    after = admin.call("GET", f"/api/loans/{loan2['id']}")
    after_line = [l for l in after["lines"] if l["item_code"] == "BK-250-002"][0]
    unchanged = (after_line["return_status"] is None and after["loan"]["status"] == "active")
    if unchanged:
        ok(f"领用单 #{loan2['id']} 原样保留：仍为「核对中」，BK-250-002 仍记「未还」——"
           f"盘点没有冲改任何领用/归还记录")
    else:
        fail("领用记录被盘点改动！")

    dmg_list = admin.call("GET", "/api/damages?waiver=none")
    traced = [d for d in dmg_list if d["item_code"] == "BK-250-002"]
    if traced:
        d = traced[0]
        ok(f"新增盘点缺失记录 #{d['id']}，追溯到上一节课："
           f"{d['course_name']}（{d['class_name']} {d['lesson_at']}）{d['group_name']}")

    # ============ 6. 岗位边界 ============
    banner("场景 6｜各岗位只能办理相应操作")
    expect_block("清洗质检员孙师傅尝试配发器皿",
                 lambda: sun.call("POST", "/api/loans",
                                  {"course_id": 2, "group_id": 5, "item_codes": ["TT-020-001"]}))
    expect_block("任课老师王老师尝试建立盘点单",
                 lambda: wang.call("POST", "/api/stocktakes", {"name": "擅自盘点"}))
    expect_block("未登录访问库存接口",
                 lambda: Client("匿名").call("GET", "/api/items"))

    # ============ 7. 柜位查实物 + 单件完整履历 ============
    banner("场景 7｜柜位页面按编号查实物：套件缺件一眼可见；每件器皿履历可溯")
    info = admin.call("GET", "/api/items/DST-01")
    print(f"      {info['template_name']}（{info['item']['code']}）"
          f"柜位 {info['item']['location']}，部件应到 {info['kit_expected']} / 在柜 {info['kit_present']}")
    for c in info["components"]:
        mark = "✔ 在柜" if c["in_cabinet"] else f"✘ {c['status_name']}"
        print(f"        - {c['code']} {c['name']:<8} 柜位 {c['location']:<16} {mark}")
    print(f"{C['red']}      ⚠ 套件未齐（温度计缺失），不能按整套数量认定已还齐{C['reset']}")

    hist = admin.call("GET", "/api/items/BK-250-001/history")
    say("BK-250-001 的使用 / 清洗 / 破损履历：")
    for e in hist:
        at = datetime.fromisoformat(e["at"].replace("Z", "")).strftime("%m-%d %H:%M")
        print(f"{C['gray']}        [{at}]{C['reset']} {e['detail']}")

    banner("全部场景演示完成")
    print(f"  {C['green']}1. 套件缺件明确提示到部件，缺件逐件登记后才结单{C['reset']}")
    print(f"  {C['green']}2. 重复扫码归还只记一次；同一件器皿不能借两个组{C['reset']}")
    print(f"  {C['green']}3. 检查+清洗合格才回库；清洗后破损自动追溯上一节课{C['reset']}")
    print(f"  {C['green']}4. 任课老师/质检员自行免赔均被拒，非本节任课老师审核通过{C['reset']}")
    print(f"  {C['green']}5. 盘点差异保留并查明，领用记录一笔未改{C['reset']}")
    print(f"  {C['green']}6. 各岗位操作边界由后端强制校验{C['reset']}")


if __name__ == "__main__":
    main()
