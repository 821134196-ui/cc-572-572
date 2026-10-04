"""FastAPI 主应用：玻璃器皿领用、归还、检查清洗、破损免赔、盘点、溯源。"""
import os
import shutil
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import models, schemas
from .database import Base, engine, get_db
from .security import make_token, current_user, require_roles
from .washer import WasherClient

Base.metadata.create_all(bind=engine)

app = FastAPI(title="中学实验室玻璃器皿领用与破损登记系统")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.abspath(
    os.environ.get("LAB_UPLOADS", os.path.join(os.path.dirname(__file__), "..", "..", "uploads"))
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

RESULT_NAMES = {"COMPLETE": "完整", "DIRTY": "待清洗", "CRACKED": "裂纹", "MISSING": "缺失"}
STATUS_NAMES = {
    "AVAILABLE": "可借", "LENT": "已借出", "RETURNED": "已还待检",
    "CLEANING": "清洗中", "BROKEN": "破损", "MISSING": "缺失", "RETIRED": "报废",
}


# ==================== 序列化 ====================
def item_dict(it: models.Item, db: Session) -> dict:
    tpl = it.template
    kit_code = db.get(models.Item, it.kit_id).code if it.kit_id else None
    return {
        "id": it.id, "code": it.code,
        "name": tpl.name if tpl else "",
        "spec": tpl.spec if tpl else "",
        "is_set": tpl.is_set if tpl else False,
        "location_code": it.location_code,
        "status": it.status, "status_name": STATUS_NAMES.get(it.status, it.status),
        "kit_code": kit_code,
        "photo_path": it.photo_path,
    }


def loan_brief(loan: models.Loan) -> dict:
    return {
        "id": loan.id,
        "course": loan.course.name,
        "class_name": loan.course.class_name,
        "group": loan.group.name,
        "teacher": loan.teacher.name,
        "status": loan.status,
        "issued_at": loan.issued_at.strftime("%Y-%m-%d %H:%M"),
        "closed_at": loan.closed_at.strftime("%Y-%m-%d %H:%M") if loan.closed_at else None,
        "note": loan.note,
    }


def loan_detail(loan: models.Loan, db: Session) -> dict:
    rows = []
    for li in loan.items:
        d = item_dict(li.item, db)
        d.update({
            "return_result": li.return_result,
            "return_result_name": RESULT_NAMES.get(li.return_result, "未还") if li.return_result else "未还",
            "returned_at": li.returned_at.strftime("%H:%M") if li.returned_at else None,
            "note": li.note,
            "return_photo_path": li.return_photo_path,
        })
        rows.append(d)

    # 套件核对：按所属套件分组，缺件/裂纹逐件列出，不能只按整套数量认定已还齐
    kit_groups: dict[str, dict] = {}
    standalone = []
    for li, d in zip(loan.items, rows):
        it = li.item
        root_id = it.kit_id or (it.id if it.template and it.template.is_set else None)
        if root_id is None:
            standalone.append(d["code"])
            continue
        root = db.get(models.Item, root_id)
        g = kit_groups.setdefault(root.code, {"kit_code": root.code, "parts": [], "missing": [],
                                              "cracked": [], "pending": [], "complete": True})
        g["parts"].append({"code": it.code, "name": d["name"], "result": li.return_result,
                           "result_name": d["return_result_name"]})
        if li.return_result in ("MISSING",):
            g["missing"].append(f'{it.code} {d["name"]}')
            g["complete"] = False
        elif li.return_result == "CRACKED":
            g["cracked"].append(f'{it.code} {d["name"]}')
            g["complete"] = False
        elif li.return_result is None:
            g["pending"].append(f'{it.code} {d["name"]}')
            g["complete"] = False

    kit_summaries = []
    for g in kit_groups.values():
        parts_root = next((p for p in g["parts"] if p["code"] == g["kit_code"]), None)
        kit_name = parts_root["name"] if parts_root else g["kit_code"]
        if g["missing"]:
            verdict = f'套件 {g["kit_code"]}（{kit_name}）缺件：{ "、".join(g["missing"]) }，不能按整套数量认定已还齐'
        elif g["cracked"]:
            verdict = f'套件 {g["kit_code"]}（{kit_name}）有裂纹部件：{ "、".join(g["cracked"]) }'
        elif g["pending"]:
            verdict = f'套件 {g["kit_code"]}（{kit_name}）尚有部件未归还：{ "、".join(g["pending"]) }'
        else:
            verdict = f'套件 {g["kit_code"]}（{kit_name}）{len(g["parts"])} 个部件均已归还（含待清洗）'
        g.update(kit_name=kit_name, verdict=verdict)
        kit_summaries.append(g)

    returned = sum(1 for li in loan.items if li.return_result is not None)
    return {
        **loan_brief(loan),
        "items": rows,
        "total": len(rows),
        "returned": returned,
        "all_scanned": returned == len(rows),
        "kit_summaries": kit_summaries,
        "standalone": standalone,
    }


# ==================== 认证 ====================
@app.post("/api/login")
def login(body: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if not user or user.password != body.password:
        raise HTTPException(401, "用户名或密码错误")
    role_names = {"teacher": "任课老师", "admin": "实验室管理员", "reviewer": "免赔审核员"}
    return {"token": make_token(user.username), "id": user.id,
            "username": user.username, "name": user.name,
            "role": user.role, "role_name": role_names.get(user.role, user.role)}


@app.get("/api/me")
def me(user: models.User = Depends(current_user)):
    return {"username": user.username, "name": user.name, "role": user.role}


# ==================== 器皿台账（管理员） ====================
@app.post("/api/templates")
def create_template(body: schemas.TemplateIn, db: Session = Depends(get_db),
                    user: models.User = Depends(require_roles("admin"))):
    tpl = models.ItemTemplate(name=body.name, spec=body.spec, is_set=body.is_set)
    db.add(tpl); db.commit(); db.refresh(tpl)
    return {"id": tpl.id}


@app.get("/api/templates")
def list_templates(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return [{"id": t.id, "name": t.name, "spec": t.spec, "is_set": t.is_set}
            for t in db.query(models.ItemTemplate).order_by(models.ItemTemplate.id).all()]


@app.post("/api/items")
def create_item(body: schemas.ItemIn, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles("admin"))):
    tpl = db.get(models.ItemTemplate, body.template_id)
    if not tpl:
        raise HTTPException(404, "器皿型号不存在")
    if db.query(models.Item).filter(models.Item.code == body.code).first():
        raise HTTPException(409, f"编号 {body.code} 已存在，每件器皿必须有独立编号")
    kit = None
    if body.kit_code:
        kit = db.query(models.Item).filter(models.Item.code == body.kit_code).first()
        if not kit:
            raise HTTPException(404, f"所属套件 {body.kit_code} 不存在")
    it = models.Item(code=body.code, template_id=tpl.id, location_code=body.location_code,
                     kit_id=kit.id if kit else None)
    db.add(it); db.commit()
    return {"id": it.id}


@app.get("/api/items")
def list_items(code: str | None = None, location: str | None = None,
               status: str | None = None, db: Session = Depends(get_db),
               user: models.User = Depends(current_user)):
    q = db.query(models.Item)
    if code:
        q = q.filter(models.Item.code.like(f"%{code}%"))
    if location:
        q = q.filter(models.Item.location_code.like(f"%{location}%"))
    if status:
        q = q.filter(models.Item.status == status)
    return [item_dict(it, db) for it in q.order_by(models.Item.code).all()]


@app.get("/api/items/{code}")
def get_item(code: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    it = db.query(models.Item).filter(models.Item.code == code).first()
    if not it:
        raise HTTPException(404, f"未找到编号 {code} 的实物")
    d = item_dict(it, db)
    # 套件部件清单：套件本体 template.is_set=True
    parts = []
    if it.template and it.template.is_set and not it.kit_id:
        members = db.query(models.Item).filter(
            (models.Item.kit_id == it.id) | (models.Item.id == it.id)).all()
        parts = [item_dict(m, db) for m in members]
    d["parts"] = parts
    return d


@app.post("/api/items/{code}/photo")
def upload_item_photo(code: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                      user: models.User = Depends(require_roles("admin", "teacher"))):
    it = db.query(models.Item).filter(models.Item.code == code).first()
    if not it:
        raise HTTPException(404, "器皿不存在")
    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    fname = f"item_{code}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
        shutil.copyfileobj(file.file, f)
    it.photo_path = f"/uploads/{fname}"
    db.commit()
    return {"photo_path": it.photo_path}


# ==================== 柜位（管理员按编号查实物） ====================
@app.get("/api/locations")
def list_locations(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    locs = db.query(models.Item.location_code).distinct().order_by(
        models.Item.location_code).all()
    result = []
    for (loc,) in locs:
        its = db.query(models.Item).filter(models.Item.location_code == loc).all()
        result.append({"location_code": loc, "count": len(its),
                       "available": sum(1 for i in its if i.status == "AVAILABLE")})
    return result


@app.get("/api/locations/{location}")
def location_detail(location: str, db: Session = Depends(get_db),
                    user: models.User = Depends(current_user)):
    its = db.query(models.Item).filter(models.Item.location_code == location).all()
    return {"location_code": location, "items": [item_dict(i, db) for i in its]}


# ==================== 课程与学生组（任课老师） ====================
@app.post("/api/courses")
def create_course(body: schemas.CourseIn, db: Session = Depends(get_db),
                  user: models.User = Depends(require_roles("teacher"))):
    c = models.Course(name=body.name, class_name=body.class_name, teacher_id=user.id)
    db.add(c); db.commit()
    return {"id": c.id}


@app.get("/api/courses")
def list_courses(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    q = db.query(models.Course)
    if user.role == "teacher":
        q = q.filter(models.Course.teacher_id == user.id)
    out = []
    for c in q.order_by(models.Course.id.desc()).all():
        out.append({"id": c.id, "name": c.name, "class_name": c.class_name,
                    "teacher": c.teacher.name, "groups": [
                        {"id": g.id, "name": g.name, "members": g.members} for g in c.groups]})
    return out


@app.post("/api/courses/{course_id}/groups")
def create_group(course_id: int, body: schemas.GroupIn, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles("teacher"))):
    course = db.get(models.Course, course_id)
    if not course:
        raise HTTPException(404, "课程不存在")
    if course.teacher_id != user.id:
        raise HTTPException(403, "只能给自己的课程建立学生组")
    g = models.StudentGroup(course_id=course_id, name=body.name, members=body.members)
    db.add(g); db.commit()
    return {"id": g.id}


# ==================== 配发领用（任课老师） ====================
@app.post("/api/loans")
def issue(body: schemas.IssueIn, db: Session = Depends(get_db),
          user: models.User = Depends(require_roles("teacher"))):
    course = db.get(models.Course, body.course_id)
    group = db.get(models.StudentGroup, body.group_id)
    if not course or not group or group.course_id != course.id:
        raise HTTPException(404, "课程或学生组不存在")
    if course.teacher_id != user.id:
        raise HTTPException(403, "只能为自己任教的课程配发器皿")

    # 同一件器皿不能借给两个组：只有 AVAILABLE 才能配发
    codes = []
    dup_scans = []
    for c in body.item_codes:
        c = c.strip()
        if c in codes:
            dup_scans.append(c)
            continue
        codes.append(c)

    blocked, items = [], []
    for code in codes:
        it = db.query(models.Item).filter(models.Item.code == code).first()
        if not it:
            raise HTTPException(404, f"编号 {code} 的器皿不存在")
        if it.status != "AVAILABLE":
            open_li = (db.query(models.LoanItem).join(models.Loan).filter(
                models.LoanItem.item_id == it.id, models.Loan.status == "OPEN").first())
            where = ""
            if open_li:
                where = f"，当前借用于 {open_li.loan.course.name} - {open_li.loan.group.name}"
            blocked.append({"code": code, "status": it.status,
                            "status_name": STATUS_NAMES.get(it.status, it.status), "where": where})
        else:
            items.append(it)
    if blocked:
        raise HTTPException(409, detail={
            "message": "同一件器皿不能同时借给两个组，以下器皿不可配发",
            "blocked": blocked})

    loan = models.Loan(course_id=course.id, group_id=group.id, teacher_id=user.id, note=body.note)
    db.add(loan); db.flush()
    for it in items:
        db.add(models.LoanItem(loan_id=loan.id, item_id=it.id))
        it.status = "LENT"
    db.commit()
    return {"loan_id": loan.id, "issued": len(items),
            "duplicate_scans_ignored": dup_scans}


@app.get("/api/loans")
def list_loans(status: str | None = None, db: Session = Depends(get_db),
               user: models.User = Depends(current_user)):
    q = db.query(models.Loan)
    if status:
        q = q.filter(models.Loan.status == status)
    if user.role == "teacher":
        q = q.filter(models.Loan.teacher_id == user.id)
    return [loan_brief(l) for l in q.order_by(models.Loan.id.desc()).all()]


@app.get("/api/loans/{loan_id}")
def get_loan(loan_id: int, db: Session = Depends(get_db),
             user: models.User = Depends(current_user)):
    loan = db.get(models.Loan, loan_id)
    if not loan:
        raise HTTPException(404, "领用单不存在")
    if user.role == "teacher" and loan.teacher_id != user.id:
        raise HTTPException(403, "只能查看自己课程的领用单")
    return loan_detail(loan, db)


@app.post("/api/loans/{loan_id}/return/{code}")
def return_item(loan_id: int, code: str, body: schemas.ReturnIn,
                db: Session = Depends(get_db),
                user: models.User = Depends(require_roles("teacher"))):
    loan = db.get(models.Loan, loan_id)
    if not loan or loan.status != "OPEN":
        raise HTTPException(404, "领用单不存在或已结案")
    if loan.teacher_id != user.id:
        raise HTTPException(403, "只能归还自己课程领用的器皿")
    if body.result not in RESULT_NAMES:
        raise HTTPException(400, "归还结果只能是 COMPLETE/DIRTY/CRACKED/MISSING")

    li = db.query(models.LoanItem).join(models.Item).filter(
        models.LoanItem.loan_id == loan.id, models.Item.code == code).first()
    if not li:
        raise HTTPException(404, f"{code} 不在本领用单中")

    # 重复扫码归还只记一次
    if li.return_result is not None:
        raise HTTPException(409, f"{code} 已于 {li.returned_at:%H:%M} 登记为"
                                f"“{RESULT_NAMES[li.return_result]}”，重复扫码只记一次，不重复记录")

    it = li.item
    li.return_result = body.result
    li.returned_at = datetime.now()
    li.note = body.note
    if body.photo_path:
        li.return_photo_path = body.photo_path

    damage = None
    if body.result == "COMPLETE":
        it.status = "RETURNED"  # 已还待管理员检查
    elif body.result == "DIRTY":
        it.status = "RETURNED"
    elif body.result == "CRACKED":
        it.status = "BROKEN"
        damage = models.Damage(item_id=it.id, loan_id=loan.id, source="RETURN",
                               damage_type="CRACK",
                               description=f"归还时发现裂纹。{body.note}",
                               photo_path=body.photo_path, reported_by=user.id)
    elif body.result == "MISSING":
        it.status = "MISSING"
        damage = models.Damage(item_id=it.id, loan_id=loan.id, source="RETURN",
                               damage_type="MISSING",
                               description=f"归还时确认部件缺失。{body.note}",
                               reported_by=user.id)
    if damage:
        db.add(damage)
    db.commit()

    # 重新计算套件核对提示
    detail = loan_detail(loan, db)
    kit_warnings = [k["verdict"] for k in detail["kit_summaries"] if not k["complete"]]
    return {"ok": True, "code": code, "result": body.result,
            "result_name": RESULT_NAMES[body.result],
            "item_status": it.status,
            "damage_id": damage.id if damage else None,
            "kit_warnings": kit_warnings,
            "returned": detail["returned"], "total": detail["total"]}


@app.post("/api/loans/{loan_id}/close")
def close_loan(loan_id: int, db: Session = Depends(get_db),
               user: models.User = Depends(require_roles("teacher"))):
    loan = db.get(models.Loan, loan_id)
    if not loan or loan.status != "OPEN":
        raise HTTPException(404, "领用单不存在或已结案")
    if loan.teacher_id != user.id:
        raise HTTPException(403, "只能结案自己的领用单")
    pending = [li.item.code for li in loan.items if li.return_result is None]
    if pending:
        raise HTTPException(409, f"仍有 {len(pending)} 件未逐件核对：{ '、'.join(pending) }，"
                                f"不能结案（缺失也要登记为“缺失”后才能结案）")
    loan.status = "CLOSED"
    loan.closed_at = datetime.now()
    db.commit()
    return {"ok": True, "loan": loan_detail(loan, db)}


# ==================== 上传照片（本地） ====================
@app.post("/api/upload")
def upload_photo(file: UploadFile = File(...),
                 user: models.User = Depends(require_roles("admin", "teacher"))):
    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename or 'photo.jpg'}"
    fname = fname.replace("/", "_").replace("\\", "_")
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"photo_path": f"/uploads/{fname}"}


# ==================== 检查与清洗（管理员 + 模拟清洗设备） ====================
@app.post("/api/items/{code}/inspect")
def inspect_item(code: str, body: schemas.InspectIn, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles("admin"))):
    it = db.query(models.Item).filter(models.Item.code == code).first()
    if not it:
        raise HTTPException(404, "器皿不存在")
    if it.status != "RETURNED":
        raise HTTPException(409, f"当前状态为{STATUS_NAMES.get(it.status)}，"
                                f"只有“已还待检”的器皿才能检查；检查与清洗合格后才能回到可借库存")
    if body.action == "PASS":
        it.status = "AVAILABLE"
    elif body.action == "NEED_WASH":
        it.status = "RETURNED"  # 保持待洗，等待送清洗机
    else:
        raise HTTPException(400, "action 只能是 PASS / NEED_WASH")
    db.commit()
    return {"ok": True, "code": code, "status": it.status,
            "status_name": STATUS_NAMES[it.status]}


@app.post("/api/wash/start")
def wash_start(body: schemas.WashStartIn, db: Session = Depends(get_db),
               user: models.User = Depends(require_roles("admin"))):
    jobs = []
    for code in body.item_codes:
        it = db.query(models.Item).filter(models.Item.code == code).first()
        if not it:
            raise HTTPException(404, f"器皿 {code} 不存在")
        if it.status != "RETURNED":
            raise HTTPException(409, f"{code} 当前为{STATUS_NAMES.get(it.status)}，"
                                    f"只有归还待检/待洗器皿能送入清洗机")
        # 关联到该件最近一次（也就是上一节课的）领用明细
        li = (db.query(models.LoanItem).filter(models.LoanItem.item_id == it.id)
              .order_by(models.LoanItem.id.desc()).first())
        job_id = WasherClient.start_job(code)
        rec = models.WashRecord(loan_item_id=li.id if li else None, item_id=it.id,
                                machine_job_id=job_id, started_by=user.id, note="")
        it.status = "CLEANING"
        db.add(rec); db.flush()
        jobs.append({"item_code": code, "job_id": job_id})
    db.commit()
    return {"jobs": jobs}


@app.post("/api/wash/{job_id}/complete")
def wash_complete(job_id: str, result: str = "PASS", db: Session = Depends(get_db),
                  user: models.User = Depends(require_roles("admin"))):
    """模拟清洗设备完成回调：PASS 合格回库；FAIL 清洗后发现破损，仍追到上一节课。"""
    if result not in ("PASS", "FAIL"):
        raise HTTPException(400, "result 只能是 PASS / FAIL")
    rec = db.query(models.WashRecord).filter(
        models.WashRecord.machine_job_id == job_id).first()
    if not rec:
        raise HTTPException(404, "清洗机任务不存在")
    if rec.result != "RUNNING":
        raise HTTPException(409, "该清洗任务已结束")

    WasherClient.finish_job(job_id, result)
    rec.finished_at = datetime.now()
    rec.result = result
    it = rec.item
    damage = None
    traced = None
    if result == "PASS":
        it.status = "AVAILABLE"  # 检查与清洗合格后才能回到可借库存
        rec.note = "清洗合格，回库"
    else:
        it.status = "BROKEN"
        rec.note = "清洗后目检发现破损"
        loan = rec.loan_item.loan if rec.loan_item else None
        if loan:
            traced = {"loan_id": loan.id, "course": loan.course.name,
                      "class_name": loan.course.class_name, "group": loan.group.name,
                      "teacher": loan.teacher.name,
                      "issued_at": loan.issued_at.strftime("%Y-%m-%d %H:%M")}
        damage = models.Damage(
            item_id=it.id, loan_id=loan.id if loan else None, source="POST_WASH",
            damage_type="CRACK",
            description=(f"清洗后才发现破损，追溯上一节课：{traced['course']} - "
                         f"{traced['group']}（{traced['issued_at']}）" if traced
                         else "清洗后发现破损，无历史领用记录"),
            reported_by=user.id)
        db.add(damage)
    db.commit()
    return {"ok": True, "job_id": job_id, "item_code": it.code,
            "result": result, "item_status": it.status,
            "damage_id": damage.id if damage else None, "traced_loan": traced}


@app.get("/api/wash")
def wash_list(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    out = []
    for r in db.query(models.WashRecord).order_by(models.WashRecord.id.desc()).limit(100).all():
        out.append({
            "id": r.id, "job_id": r.machine_job_id, "item_code": r.item.code,
            "result": r.result, "started_at": r.started_at.strftime("%Y-%m-%d %H:%M"),
            "finished_at": r.finished_at.strftime("%Y-%m-%d %H:%M") if r.finished_at else None,
            "note": r.note,
        })
    return out


# ==================== 破损登记与免赔审核 ====================
def damage_dict(d: models.Damage) -> dict:
    source_names = {"RETURN": "归还时发现", "POST_WASH": "清洗后发现", "STOCKTAKE": "盘点发现"}
    type_names = {"CRACK": "裂纹/破损", "MISSING": "缺失", "OTHER": "其他"}
    status_names = {"PENDING": "待审核", "WAIVED": "免赔", "CHARGED": "已赔偿"}
    return {
        "id": d.id, "item_code": d.item.code, "item_name": d.item.template.name,
        "source": d.source, "source_name": source_names.get(d.source, d.source),
        "damage_type": d.damage_type,
        "damage_type_name": type_names.get(d.damage_type, d.damage_type),
        "description": d.description, "photo_path": d.photo_path,
        "reported_by": d.reporter.name,
        "reported_at": d.reported_at.strftime("%Y-%m-%d %H:%M"),
        "status": d.status, "status_name": status_names.get(d.status, d.status),
        "reviewed_by": d.reviewer.name if d.reviewer else None,
        "reviewed_at": d.reviewed_at.strftime("%Y-%m-%d %H:%M") if d.reviewed_at else None,
        "review_note": d.review_note,
        "loan_id": d.loan_id,
    }


@app.get("/api/damages")
def list_damages(status: str | None = None, db: Session = Depends(get_db),
                 user: models.User = Depends(current_user)):
    q = db.query(models.Damage)
    if status:
        q = q.filter(models.Damage.status == status)
    return [damage_dict(d) for d in q.order_by(models.Damage.id.desc()).all()]


@app.post("/api/damages/{damage_id}/review")
def review_damage(damage_id: int, body: schemas.DamageReviewIn, db: Session = Depends(get_db),
                  # 免赔由非任课老师审核：任课老师角色直接被拒绝
                  user: models.User = Depends(require_roles("reviewer"))):
    d = db.get(models.Damage, damage_id)
    if not d:
        raise HTTPException(404, "破损登记不存在")
    if d.status != "PENDING":
        raise HTTPException(409, f"该登记已审核为“{'免赔' if d.status == 'WAIVED' else '已赔偿'}”，"
                                f"不能重复审核")
    if body.decision not in ("WAIVED", "CHARGED"):
        raise HTTPException(400, "decision 只能是 WAIVED / CHARGED")
    d.status = body.decision
    d.reviewed_by = user.id
    d.reviewed_at = datetime.now()
    d.review_note = body.note
    db.commit()
    return {"ok": True, "id": d.id, "status": d.status,
            "reviewed_by": user.name,
            "message": "免赔审核通过" if body.decision == "WAIVED" else "登记为照价赔偿"}


# ==================== 盘点（管理员） ====================
class CountEntry(schemas.BaseModel):
    item_code: str
    found_location: str | None = None


@app.post("/api/stocktakes")
def create_stocktake(body: schemas.StocktakeIn, db: Session = Depends(get_db),
                     user: models.User = Depends(require_roles("admin"))):
    st = models.Stocktake(label=body.label, scope_location=body.scope_location,
                          created_by=user.id, status="OPEN")
    db.add(st); db.commit()
    return {"id": st.id}


@app.get("/api/stocktakes")
def list_stocktakes(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    out = []
    for st in db.query(models.Stocktake).order_by(models.Stocktake.id.desc()).all():
        out.append({"id": st.id, "label": st.label, "scope": st.scope_location or "全部柜位",
                    "status": st.status,
                    "created_at": st.created_at.strftime("%Y-%m-%d %H:%M"),
                    "variance_open": sum(1 for v in st.variances if v.status == "OPEN"),
                    "variance_total": len(st.variances)})
    return out


@app.get("/api/stocktakes/{sid}")
def get_stocktake(sid: int, db: Session = Depends(get_db),
                  user: models.User = Depends(current_user)):
    st = db.get(models.Stocktake, sid)
    if not st:
        raise HTTPException(404, "盘点单不存在")
    # 账面上应当在柜的器皿（可借状态）
    q = db.query(models.Item).filter(models.Item.status == "AVAILABLE")
    if st.scope_location:
        q = q.filter(models.Item.location_code == st.scope_location)
    expected = [item_dict(i, db) for i in q.order_by(models.Item.code).all()]
    return {
        "id": st.id, "label": st.label, "scope": st.scope_location or "全部柜位",
        "status": st.status,
        "expected": expected,
        "variances": [variance_dict(v) for v in st.variances],
    }


def variance_dict(v: models.StocktakeVariance) -> dict:
    kind_names = {"MISSING": "账有物无（实物缺失）", "SURPLUS": "物有账无/账实状态不符",
                  "WRONG_LOCATION": "柜位不符"}
    return {
        "id": v.id, "item_code": v.item_code, "kind": v.kind,
        "kind_name": kind_names.get(v.kind, v.kind),
        "expected_location": v.expected_location, "found_location": v.found_location,
        "detail": v.detail, "status": v.status, "resolution": v.resolution,
        "resolved_by": v.resolver.name if v.resolver else None,
        "resolved_at": v.resolved_at.strftime("%Y-%m-%d %H:%M") if v.resolved_at else None,
    }


@app.post("/api/stocktakes/{sid}/count")
def stocktake_count(sid: int, entries: list[CountEntry], db: Session = Depends(get_db),
                    user: models.User = Depends(require_roles("admin"))):
    st = db.get(models.Stocktake, sid)
    if not st:
        raise HTTPException(404, "盘点单不存在")
    if st.status != "OPEN":
        raise HTTPException(409, "盘点已录入，不能重复录入（差异以首次盘点为准并保留）")

    # 账面应当在柜的器皿
    q = db.query(models.Item).filter(models.Item.status == "AVAILABLE")
    if st.scope_location:
        q = q.filter(models.Item.location_code == st.scope_location)
    expected = {i.code: i for i in q.all()}

    # 去重实盘扫码（重复扫码只记一次）
    seen: dict[str, CountEntry] = {}
    for e in entries:
        seen.setdefault(e.item_code.strip(), e)

    variances: list[models.StocktakeVariance] = []
    # 账有物无
    for code, it in expected.items():
        if code not in seen:
            variances.append(models.StocktakeVariance(
                stocktake_id=st.id, item_id=it.id, item_code=code, kind="MISSING",
                expected_location=it.location_code,
                detail=f"系统账面：{it.template.name}，应在柜位 {it.location_code}；本次未盘到实物。"
                       f"差异保留待查，不改动任何领用记录。"))
    # 逐件核对盘到的实物
    for code, e in seen.items():
        it = db.query(models.Item).filter(models.Item.code == code).first()
        if not it:
            variances.append(models.StocktakeVariance(
                stocktake_id=st.id, item_code=code, kind="SURPLUS",
                found_location=e.found_location or "",
                detail="盘到系统未登记编号的实物，需管理员核实补登台账。"))
            continue
        if code not in expected:
            state = STATUS_NAMES.get(it.status, it.status)
            open_loan = (db.query(models.Loan).join(models.LoanItem).filter(
                models.LoanItem.item_id == it.id, models.Loan.status == "OPEN").first())
            loan_txt = (f"，系统显示在用于 {open_loan.course.name}-{open_loan.group.name}"
                        if open_loan else "")
            variances.append(models.StocktakeVariance(
                stocktake_id=st.id, item_id=it.id, item_code=code, kind="SURPLUS",
                expected_location=it.location_code, found_location=e.found_location or "",
                detail=f"实物在柜，但系统状态为“{state}”{loan_txt}；保留差异，"
                       f"不得直接改掉或删除领用记录。"))
        elif e.found_location and e.found_location != it.location_code:
            variances.append(models.StocktakeVariance(
                stocktake_id=st.id, item_id=it.id, item_code=code, kind="WRONG_LOCATION",
                expected_location=it.location_code, found_location=e.found_location,
                detail=f"实物在柜位 {e.found_location} 盘到，账面柜位为 {it.location_code}。"))

    db.add_all(variances)
    st.status = "COUNTED"
    db.commit()
    return {"counted": len(seen), "expected": len(expected),
            "variances": [variance_dict(v) for v in variances]}


@app.post("/api/stocktakes/{sid}/variances/{vid}/resolve")
def resolve_variance(sid: int, vid: int, body: schemas.VarianceResolveIn,
                     db: Session = Depends(get_db),
                     user: models.User = Depends(require_roles("admin"))):
    """差异只允许追加处理说明并保留，不允许回改领用记录。"""
    v = db.get(models.StocktakeVariance, vid)
    if not v or v.stocktake_id != sid:
        raise HTTPException(404, "差异记录不存在")
    if v.status != "OPEN":
        raise HTTPException(409, "差异已处理")
    v.status = "RESOLVED"
    v.resolution = body.resolution
    v.resolved_by = user.id
    v.resolved_at = datetime.now()
    db.commit()
    return {"ok": True, "resolution": v.resolution}


# ==================== 单件器皿全生命周期溯源 ====================
@app.get("/api/items/{code}/history")
def item_history(code: str, db: Session = Depends(get_db),
                 user: models.User = Depends(current_user)):
    it = db.query(models.Item).filter(models.Item.code == code).first()
    if not it:
        raise HTTPException(404, f"未找到编号 {code} 的实物")

    loans = []
    for li in db.query(models.LoanItem).filter(models.LoanItem.item_id == it.id).order_by(
            models.LoanItem.id).all():
        loans.append({
            "loan_id": li.loan_id, "course": li.loan.course.name,
            "class_name": li.loan.course.class_name, "group": li.loan.group.name,
            "teacher": li.loan.teacher.name,
            "issued_at": li.loan.issued_at.strftime("%Y-%m-%d %H:%M"),
            "return_result": RESULT_NAMES.get(li.return_result, "未还")
            if li.return_result else "未还",
            "returned_at": li.returned_at.strftime("%Y-%m-%d %H:%M") if li.returned_at else None,
            "loan_status": li.loan.status,
        })

    washes = []
    for r in db.query(models.WashRecord).filter(models.WashRecord.item_id == it.id).all():
        washes.append({
            "job_id": r.machine_job_id,
            "started_at": r.started_at.strftime("%Y-%m-%d %H:%M"),
            "finished_at": r.finished_at.strftime("%Y-%m-%d %H:%M") if r.finished_at else None,
            "result": {"RUNNING": "清洗中", "PASS": "合格", "FAIL": "清洗后破损"}.get(
                r.result, r.result),
            "note": r.note,
        })

    damages = [damage_dict(d) for d in db.query(models.Damage).filter(
        models.Damage.item_id == it.id).all()]

    return {"item": item_dict(it, db), "loans": loans, "washes": washes, "damages": damages}


# ==================== 静态资源 / 前端 ====================
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
