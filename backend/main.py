"""FastAPI application: glassware loan, return, cleaning, damage, stocktake."""
import json
import os
import uuid
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import models as m
from . import schemas as s
from . import device
from .database import Base, engine, get_db, UPLOAD_DIR

Base.metadata.create_all(bind=engine)

app = FastAPI(title="中学实验室玻璃器皿领用与破损登记系统")

# 极简会话表（演示用）: token -> user_id
SESSIONS: dict[str, int] = {}


# ---------------- 权限 ----------------
def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> m.User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    token = authorization.removeprefix("Bearer ").strip()
    uid = SESSIONS.get(token)
    if uid is None:
        raise HTTPException(401, "登录已失效，请重新登录")
    user = db.get(m.User, uid)
    if not user:
        raise HTTPException(401, "用户不存在")
    return user


def require_roles(*roles: str):
    def dep(user: m.User = Depends(current_user)) -> m.User:
        if user.role not in roles:
            allow = "、".join(m.ROLE_NAMES[r] for r in roles)
            raise HTTPException(
                403, f"无权办理：本操作仅 {allow} 可执行（当前身份：{m.ROLE_NAMES[user.role]}）"
            )
        return user
    return dep


# ---------------- 序列化辅助 ----------------
def item_out(it: m.Item) -> s.ItemOut:
    return s.ItemOut(
        id=it.id, code=it.code, template_id=it.template_id,
        location=it.location, status=it.status, kit_id=it.kit_id,
        template_name=it.template.name, spec=it.template.spec,
        is_kit=it.template.is_kit,
    )


def loan_brief(loan: m.Loan) -> s.LoanOut:
    return s.LoanOut(
        id=loan.id, course_id=loan.course_id, group_id=loan.group_id,
        teacher_id=loan.teacher_id, lent_at=loan.lent_at,
        returned_at=loan.returned_at, status=loan.status, note=loan.note,
        course_name=loan.course.name, class_name=loan.course.class_name,
        lesson_at=loan.course.lesson_at, group_name=loan.group.name,
        teacher_name=loan.teacher.name,
    )


def line_out(line: m.LoanLine) -> s.LoanLineOut:
    it = line.item
    return s.LoanLineOut(
        id=line.id, item_id=it.id, item_code=it.code, item_status=it.status,
        template_name=it.template.name, spec=it.template.spec,
        location=it.location, kit_id=it.kit_id,
        return_status=line.return_status, returned_at=line.returned_at,
        return_note=line.return_note,
    )


def damage_out(d: m.DamageRecord, db: Session) -> s.DamageOut:
    course = d.course
    group_name = ""
    course_teacher_id = None
    if d.loan_id:
        ln = db.get(m.Loan, d.loan_id)
        if ln:
            group_name = ln.group.name
    if course:
        course_teacher_id = course.teacher_id
    return s.DamageOut(
        id=d.id, item_id=d.item_id, item_code=d.item.code,
        template_name=d.item.template.name, loan_id=d.loan_id,
        course_id=d.course_id,
        course_name=course.name if course else "",
        class_name=course.class_name if course else "",
        lesson_at=course.lesson_at if course else "",
        group_name=group_name, course_teacher_id=course_teacher_id,
        damage_type=d.damage_type, source=d.source, description=d.description,
        photo_path=d.photo_path, reported_by=d.reported_by,
        reporter_name=d.reporter.name, reported_at=d.reported_at,
        waiver_status=d.waiver_status, waiver_note=d.waiver_note,
        waiver_reviewed_by=d.waiver_reviewed_by,
        reviewer_name=d.reviewer.name if d.reviewer else "",
    )


def latest_loan_for_item(db: Session, item_id: int) -> m.Loan | None:
    """追溯一件器皿最近一次领用（上一节课）。"""
    line = db.scalars(
        select(m.LoanLine)
        .where(m.LoanLine.item_id == item_id)
        .order_by(m.LoanLine.id.desc())
        .limit(1)
    ).first()
    return db.get(m.Loan, line.loan_id) if line else None


# ---------------- 认证 ----------------
@app.post("/api/auth/login", response_model=dict)
def login(body: s.LoginIn, db: Session = Depends(get_db)):
    user = db.scalars(select(m.User).where(m.User.username == body.username)).first()
    if not user:
        raise HTTPException(404, f"账号 {body.username} 不存在（演示账号：admin / wang / zhao / sun）")
    token = uuid.uuid4().hex
    SESSIONS[token] = user.id
    return {"token": token, "user": s.UserOut.model_validate(user)}


@app.get("/api/me", response_model=s.UserOut)
def me(user: m.User = Depends(current_user)):
    return user


@app.get("/api/users", response_model=list[s.UserOut])
def list_users(db: Session = Depends(get_db)):
    return list(db.scalars(select(m.User).order_by(m.User.id)))


# ---------------- 目录 / 柜位 ----------------
@app.get("/api/templates", response_model=list[s.TemplateOut])
def list_templates(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(m.Template).order_by(m.Template.id)))


@app.get("/api/items", response_model=list[s.ItemOut])
def list_items(
    code: str | None = None,
    status: str | None = None,
    location: str | None = None,
    user: m.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """柜位页面：支持按编号 / 状态 / 柜位查实物。"""
    stmt = select(m.Item).order_by(m.Item.code)
    if code:
        stmt = stmt.where(m.Item.code.like(f"%{code.strip()}%"))
    if status:
        stmt = stmt.where(m.Item.status == status)
    if location:
        stmt = stmt.where(m.Item.location.like(f"%{location.strip()}%"))
    return [item_out(i) for i in db.scalars(stmt)]


@app.get("/api/items/{code}", response_model=dict)
def get_item(code: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    it = db.scalars(select(m.Item).where(m.Item.code == code)).first()
    if not it:
        raise HTTPException(404, f"查无此编号实物：{code}")
    # 套件实物：列出每个部件的实物与状态，逐件核对，不能只看整套数量
    components = []
    if it.kit_id is None and it.template.is_kit:
        children = db.scalars(
            select(m.Item).where(m.Item.kit_id == it.id).order_by(m.Item.id)
        ).all()
        present = 0
        for c in children:
            ok = c.status == m.ST_AVAILABLE
            present += ok
            components.append({
                "code": c.code, "name": c.template.name, "spec": c.template.spec,
                "location": c.location, "status": c.status,
                "status_name": m.STATUS_NAMES[c.status], "in_cabinet": ok,
            })
        expected = len(children)
    else:
        expected = present = None
    return {
        "item": item_out(it),
        "template_name": it.template.name,
        "spec": it.template.spec,
        "is_kit": it.template.is_kit,
        "status_name": m.STATUS_NAMES[it.status],
        "components": components,
        "kit_complete": (present == expected) if expected is not None else None,
        "kit_present": present,
        "kit_expected": expected,
    }


@app.get("/api/items/{code}/history", response_model=list[s.HistoryEvent])
def item_history(code: str, user: m.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """每件器皿的使用、清洗、破损、盘点履历。"""
    it = db.scalars(select(m.Item).where(m.Item.code == code)).first()
    if not it:
        raise HTTPException(404, f"查无此编号实物：{code}")
    events: list[s.HistoryEvent] = []
    for line in db.scalars(
        select(m.LoanLine).where(m.LoanLine.item_id == it.id)
    ):
        loan = db.get(m.Loan, line.loan_id)
        events.append(s.HistoryEvent(
            at=loan.lent_at, kind="loan",
            detail=(f"领用：{loan.course.name}（{loan.course.class_name} "
                    f"{loan.course.lesson_at}）{loan.group.name}，"
                    f"配发老师 {loan.teacher.name}"),
            operator=loan.teacher.name,
        ))
        if line.return_status:
            events.append(s.HistoryEvent(
                at=line.returned_at, kind="return",
                detail=f"归还登记：{m.RETURN_NAMES[line.return_status]}"
                       + (f"（{line.return_note}）" if line.return_note else ""),
            ))
    for c in db.scalars(
        select(m.CleaningRecord).where(m.CleaningRecord.item_id == it.id)
    ):
        if c.finished_at:
            events.append(s.HistoryEvent(
                at=c.finished_at, kind="cleaning",
                detail=f"清洗合格回库" if c.result == "pass"
                       else f"清洗后发现破损，停止回库（{c.note}）",
                operator=c.washer.name,
            ))
        else:
            events.append(s.HistoryEvent(
                at=c.started_at, kind="cleaning_start",
                detail=f"送入清洗设备，任务号 {c.device_job_id}",
                operator=c.washer.name,
            ))
    for d in db.scalars(
        select(m.DamageRecord).where(m.DamageRecord.item_id == it.id)
    ):
        src = {"return": "归还检查", "cleaning": "清洗后检查",
               "stocktake": "盘点", "inspection": "入库前检查"}.get(d.source, d.source)
        waiver = {"pending": "，免赔待审核", "approved": "，免赔已批准",
                  "rejected": "，免赔未批准"}.get(d.waiver_status, "")
        events.append(s.HistoryEvent(
            at=d.reported_at, kind="damage",
            detail=f"{src}登记{d.damage_type == 'missing' and '缺失' or '破损'}"
                   f"：{d.description}{waiver}",
            operator=d.reporter.name,
        ))
    for stl in db.scalars(
        select(m.StocktakeLine).where(m.StocktakeLine.item_id == it.id)
    ):
        st = db.get(m.Stocktake, stl.stocktake_id)
        if stl.difference == "match":
            txt = "账实相符"
        elif stl.difference == "loss":
            txt = "盘亏（实物未见），差异保留"
            if stl.resolution:
                txt += f"，已查明：{stl.resolution}"
        else:
            txt = "盘盈"
        events.append(s.HistoryEvent(
            at=st.created_at, kind="stocktake",
            detail=f"盘点《{st.name}》：{txt}",
        ))
    events.sort(key=lambda e: e.at)
    return events


# ---------------- 课程 / 学生组 ----------------
@app.get("/api/courses", response_model=list[s.CourseDetailOut])
def list_courses(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(m.Course).options(selectinload(m.Course.groups)).order_by(m.Course.id)
    if user.role == m.ROLE_TEACHER:
        stmt = stmt.where(m.Course.teacher_id == user.id)
    out = []
    for c in db.scalars(stmt):
        out.append(s.CourseDetailOut(
            id=c.id, name=c.name, class_name=c.class_name, lesson_at=c.lesson_at,
            teacher_id=c.teacher_id, teacher_name=c.teacher.name,
            groups=[s.GroupOut.model_validate(g) for g in c.groups],
        ))
    return out


# ---------------- 领用 ----------------
def resolve_kit_family(db: Session, item: m.Item) -> set[int]:
    """套件与其部件必须整体配发：扫码任一部件都带出整套。"""
    ids = {item.id}
    if item.kit_id is None and item.template.is_kit:
        for c in db.scalars(select(m.Item).where(m.Item.kit_id == item.id)):
            ids.add(c.id)
    elif item.kit_id is not None:
        ids.add(item.kit_id)
        for c in db.scalars(select(m.Item).where(m.Item.kit_id == item.kit_id)):
            ids.add(c.id)
    return ids


@app.post("/api/loans", response_model=s.LoanOut, status_code=201)
def create_loan(
    body: s.CreateLoanIn,
    user: m.User = Depends(require_roles(m.ROLE_TEACHER, m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    course = db.get(m.Course, body.course_id)
    group = db.get(m.StudentGroup, body.group_id)
    if not course or not group:
        raise HTTPException(404, "课程或学生组不存在")
    if group.course_id != course.id:
        raise HTTPException(400, "学生组不属于该课程")
    if user.role == m.ROLE_TEACHER and course.teacher_id != user.id:
        raise HTTPException(403, "只能为本节任课的课程配发器皿")

    if not body.item_codes:
        raise HTTPException(400, "请至少扫入一件器皿")

    family_ids: set[int] = set()
    for raw in body.item_codes:
        code = raw.strip()
        if not code:
            continue
        it = db.scalars(select(m.Item).where(m.Item.code == code)).first()
        if not it:
            raise HTTPException(404, f"编号 {code} 查无实物")
        family_ids |= resolve_kit_family(db, it)

    items = [db.get(m.Item, i) for i in sorted(family_ids)]
    conflicts = []
    for it in items:  # 同一件器皿不能借给两个组
        if it.status != m.ST_AVAILABLE:
            conflicts.append(f"{it.code}（{it.template.name}，当前：{m.STATUS_NAMES[it.status]}）")
    if conflicts:
        raise HTTPException(409, "以下器皿不在可借库存，无法配发：" + "、".join(conflicts))

    loan = m.Loan(course_id=course.id, group_id=group.id,
                  teacher_id=user.id, note=body.note)
    db.add(loan)
    db.flush()
    for it in items:
        it.status = m.ST_LENT
        db.add(m.LoanLine(loan_id=loan.id, item_id=it.id))
    db.commit()
    db.refresh(loan)
    return loan_brief(loan)


@app.get("/api/loans", response_model=list[s.LoanOut])
def list_loans(
    active: bool | None = None,
    user: m.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(m.Loan).order_by(m.Loan.id.desc())
    if active:
        stmt = stmt.where(m.Loan.status == "active")
    if user.role == m.ROLE_TEACHER:
        stmt = stmt.where(m.Loan.teacher_id == user.id)
    return [loan_brief(x) for x in db.scalars(stmt)]


@app.get("/api/loans/{loan_id}", response_model=dict)
def get_loan(
    loan_id: int,
    user: m.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    loan = db.get(m.Loan, loan_id)
    if not loan:
        raise HTTPException(404, "领用单不存在")
    if user.role == m.ROLE_TEACHER and loan.teacher_id != user.id:
        raise HTTPException(403, "只能查看本人课程的领用单")
    lines = [line_out(x) for x in db.scalars(
        select(m.LoanLine).where(m.LoanLine.loan_id == loan_id).order_by(m.LoanLine.id)
    )]
    # 套件逐件核对：明确提示缺了哪个部件，不能只按整套数量认定已还齐
    kit_groups = []
    parent_lines = [l for l in loan.lines
                    if l.item.kit_id is None and l.item.template.is_kit]
    for pl in sorted(parent_lines, key=lambda x: x.id):
        comps = []
        missing_parts, bad_parts = [], []
        for cl in sorted(
            [x for x in loan.lines if x.item.kit_id == pl.item_id],
            key=lambda x: x.id,
        ):
            state = "unreturned" if cl.return_status is None else cl.return_status
            comps.append({
                "line_id": cl.id, "item_code": cl.item.code,
                "name": cl.item.template.name, "spec": cl.item.template.spec,
                "state": state,
                "state_name": "未还" if cl.return_status is None
                              else m.RETURN_NAMES[cl.return_status],
            })
            if cl.return_status is None or cl.return_status == m.RET_MISSING:
                missing_parts.append(cl.item.template.name)
            if cl.return_status == m.RET_CRACKED:
                bad_parts.append(cl.item.template.name)
        parent_state = "unreturned" if pl.return_status is None else pl.return_status
        all_back = all(c["state"] in (m.RET_INTACT, m.RET_DIRTY) for c in comps)
        kit_groups.append({
            "parent_line_id": pl.id, "kit_code": pl.item.code,
            "kit_name": pl.item.template.name,
            "parent_state": parent_state,
            "parent_state_name": "未还" if pl.return_status is None
                                 else m.RETURN_NAMES[pl.return_status],
            "components": comps,
            "all_returned_good": all_back and parent_state in (m.RET_INTACT, m.RET_DIRTY),
            "missing_parts": missing_parts,
            "bad_parts": bad_parts,
            "warning": ("缺少部件：" + "、".join(missing_parts)) if missing_parts
                       else (("破损部件：" + "、".join(bad_parts)) if bad_parts else ""),
        })
    returned_cnt = sum(1 for x in loan.lines if x.return_status is not None)
    return {
        "loan": loan_brief(loan),
        "lines": lines,
        "kit_groups": kit_groups,
        "returned_count": returned_cnt,
        "total_count": len(loan.lines),
        "all_lines_returned": returned_cnt == len(loan.lines),
    }


@app.post("/api/loans/{loan_id}/return", response_model=dict)
def return_item(
    loan_id: int,
    body: s.ReturnIn,
    user: m.User = Depends(require_roles(m.ROLE_TEACHER, m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """逐件扫码归还。重复扫码同一件只记一次（返回首次登记记录，不覆盖）。"""
    loan = db.get(m.Loan, loan_id)
    if not loan:
        raise HTTPException(404, "领用单不存在")
    if user.role == m.ROLE_TEACHER and loan.teacher_id != user.id:
        raise HTTPException(403, "只能归还本人课程领用的器皿")
    if loan.status != "active":
        raise HTTPException(409, "该领用单已结清，不能再登记归还")

    line = db.scalars(
        select(m.LoanLine)
        .where(m.LoanLine.loan_id == loan_id, m.LoanLine.item.has(code=body.item_code.strip()))
    ).first()
    if not line:
        raise HTTPException(404, f"编号 {body.item_code} 不在本领用单中")

    if line.return_status is not None:  # 重复扫码归还只记一次
        raise HTTPException(
            409,
            f"重复扫码：{body.item_code}（{line.item.template.name}）已于 "
            f"{line.returned_at:%Y-%m-%d %H:%M} 登记为「{m.RETURN_NAMES[line.return_status]}」，"
            f"归还登记只记一次，不重复入账"
        )

    if body.return_status not in m.RETURN_NAMES:
        raise HTTPException(400, "归还状态应为 intact/cracked/missing/dirty")

    it = line.item
    now = datetime.now()
    line.return_status = body.return_status
    line.returned_at = now
    line.return_note = body.note
    damage = None

    if body.return_status == m.RET_INTACT:
        it.status = m.ST_TO_CHECK
    elif body.return_status == m.RET_DIRTY:
        it.status = m.ST_TO_CLEAN
    elif body.return_status in (m.RET_CRACKED, m.RET_MISSING):
        if body.return_status == m.RET_CRACKED:
            it.status = m.ST_DAMAGED
        else:
            it.status = m.ST_MISSING
        damage = m.DamageRecord(
            item_id=it.id, loan_id=loan.id, course_id=loan.course_id,
            damage_type=("missing" if body.return_status == m.RET_MISSING else "cracked"),
            source="return", description=body.note or "归还时登记",
            reported_by=user.id,
        )
        db.add(damage)
        db.flush()

    db.commit()
    return {
        "ok": True,
        "line": line_out(line),
        "item_status": it.status,
        "item_status_name": m.STATUS_NAMES[it.status],
        "damage_id": damage.id if damage else None,
        "kit_warning": _kit_warning(db, loan),
    }


def _kit_warning(db: Session, loan: m.Loan) -> str:
    warn = []
    for pl in [x for x in loan.lines
               if x.item.kit_id is None and x.item.template.is_kit]:
        miss = [c.item.template.name for c in loan.lines
                if c.item.kit_id == pl.item_id
                and (c.return_status is None or c.return_status == m.RET_MISSING)]
        if miss:
            warn.append(f"{pl.item.template.name}（{pl.item.code}）缺少部件：" + "、".join(miss))
    return "；".join(warn)


@app.post("/api/loans/{loan_id}/finish", response_model=s.LoanOut)
def finish_loan(
    loan_id: int,
    user: m.User = Depends(require_roles(m.ROLE_TEACHER, m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """实验结束核对完成后结单：逐件登记齐了才可结（缺件必须明确登记为缺失）。"""
    loan = db.get(m.Loan, loan_id)
    if not loan:
        raise HTTPException(404, "领用单不存在")
    if user.role == m.ROLE_TEACHER and loan.teacher_id != user.id:
        raise HTTPException(403, "只能结清本人课程的领用单")
    unreturned = [f"{x.item.code}（{x.item.template.name}）"
                  for x in loan.lines if x.return_status is None]
    if unreturned:
        raise HTTPException(
            409, "仍有器皿未逐件核对，不能按整套数量视为还齐：" + "、".join(unreturned)
                 + "。缺失的部件请逐件登记为「缺失」后再结单。"
        )
    issue = any(x.return_status in (m.RET_CRACKED, m.RET_MISSING) for x in loan.lines)
    loan.status = "issue" if issue else "done"
    loan.returned_at = datetime.now()
    db.commit()
    db.refresh(loan)
    return loan_brief(loan)


# ---------------- 照片（本地存储） ----------------
@app.post("/api/damages/{damage_id}/photo")
def upload_damage_photo(
    damage_id: int,
    file: UploadFile = File(...),
    user: m.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    dmg = db.get(m.DamageRecord, damage_id)
    if not dmg:
        raise HTTPException(404, "破损记录不存在")
    ext = os.path.splitext(file.filename or "")[1].lower()[:8] or ".jpg"
    name = f"damage_{damage_id}_{uuid.uuid4().hex[:8]}{ext}"
    data = file.file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "照片不能超过 8MB")
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    dmg.photo_path = f"/uploads/{name}"
    db.commit()
    return {"ok": True, "photo_path": dmg.photo_path}


# ---------------- 检查 / 清洗 ----------------
@app.get("/api/cleaning/queue", response_model=dict)
def cleaning_queue(
    user: m.User = Depends(require_roles(m.ROLE_WASHER, m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    def items_with(st):
        return [item_out(i) for i in db.scalars(
            select(m.Item).where(m.Item.status == st).order_by(m.Item.code))]

    washing = []
    for it in db.scalars(
        select(m.Item).where(m.Item.status == m.ST_WASHING).order_by(m.Item.code)
    ):
        rec = db.scalars(
            select(m.CleaningRecord)
            .where(m.CleaningRecord.item_id == it.id,
                   m.CleaningRecord.finished_at.is_(None))
            .order_by(m.CleaningRecord.id.desc())
        ).first()
        job = device.fetch(rec.device_job_id) if rec else None
        d = item_out(it).model_dump()
        d["device_job_id"] = rec.device_job_id if rec else None
        d["device_state"] = job["state"] if job else "UNKNOWN"
        d["device_ready"] = bool(job and job["state"] == device.FINISHED)
        washing.append(d)

    return {
        "to_check": items_with(m.ST_TO_CHECK),
        "to_clean": items_with(m.ST_TO_CLEAN),
        "washing": washing,
    }


@app.post("/api/inspect", response_model=dict)
def inspect_item(
    body: s.InspectIn,
    user: m.User = Depends(require_roles(m.ROLE_WASHER, m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """入库前目检（归还完整的件）。合格转待清洗；发现裂纹则登记破损并追溯上一节课。"""
    it = db.scalars(select(m.Item).where(m.Item.code == body.item_code.strip())).first()
    if not it:
        raise HTTPException(404, "查无此编号实物")
    if it.status != m.ST_TO_CHECK:
        raise HTTPException(409, f"该件当前为「{m.STATUS_NAMES[it.status]}」，不在待检查队列")
    if body.passed:
        it.status = m.ST_TO_CLEAN
        db.commit()
        return {"ok": True, "item_status": it.status,
                "item_status_name": m.STATUS_NAMES[it.status]}
    it.status = m.ST_DAMAGED
    loan = latest_loan_for_item(db, it.id)
    dmg = m.DamageRecord(
        item_id=it.id,
        loan_id=loan.id if loan else None,
        course_id=loan.course_id if loan else None,
        damage_type="cracked", source="inspection",
        description=body.note or "入库前目检发现裂纹", reported_by=user.id,
    )
    db.add(dmg)
    db.commit()
    return {"ok": True, "item_status": it.status,
            "traced_loan_id": loan.id if loan else None,
            "damage_id": dmg.id}


@app.post("/api/cleaning/start", response_model=dict)
def cleaning_start(
    body: s.CleanStartIn,
    user: m.User = Depends(require_roles(m.ROLE_WASHER, m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """送入模拟清洗设备。"""
    it = db.scalars(select(m.Item).where(m.Item.code == body.item_code.strip())).first()
    if not it:
        raise HTTPException(404, "查无此编号实物")
    if it.status != m.ST_TO_CLEAN:
        raise HTTPException(409, f"该件当前为「{m.STATUS_NAMES[it.status]}」，不能送入清洗")
    job = device.submit(it.code)
    it.status = m.ST_WASHING
    loan = latest_loan_for_item(db, it.id)
    rec = m.CleaningRecord(
        item_id=it.id, loan_id=loan.id if loan else None,
        washer_id=user.id, device_job_id=job["job_id"], note=body.note,
    )
    db.add(rec)
    db.commit()
    return {"ok": True, "device_job": job, "item_status": it.status}


@app.get("/api/cleaning/job/{job_id}")
def cleaning_job_status(
    job_id: str,
    user: m.User = Depends(require_roles(m.ROLE_WASHER, m.ROLE_ADMIN)),
):
    job = device.fetch(job_id)
    if not job:
        raise HTTPException(404, "设备无此任务号")
    return job


@app.post("/api/cleaning/complete", response_model=dict)
def cleaning_complete(
    body: s.CleanCompleteIn,
    user: m.User = Depends(require_roles(m.ROLE_WASHER, m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """设备程序结束后质检员判定：合格才能回可借库存；
    清洗后才发现破损的，登记破损并追溯到上一节课。"""
    rec = db.scalars(
        select(m.CleaningRecord).where(m.CleaningRecord.device_job_id == body.device_job_id)
    ).first()
    if not rec:
        raise HTTPException(404, "系统无此清洗任务号")
    if rec.finished_at:
        raise HTTPException(409, "该清洗任务已判定，不能重复提交")
    job = device.fetch(body.device_job_id)
    if not job or job["state"] != device.FINISHED:
        raise HTTPException(409, "清洗设备尚未完成程序，请稍候查询设备状态")

    it = rec.item
    rec.finished_at = datetime.now()
    rec.result = body.result
    rec.note = body.note
    loan = latest_loan_for_item(db, it.id)

    if body.result == "pass":
        # 检查与清洗合格后才能回到可借库存
        it.status = m.ST_AVAILABLE
        traced = None
    elif body.result == "fail":
        it.status = m.ST_DAMAGED
        dmg = m.DamageRecord(
            item_id=it.id,
            loan_id=loan.id if loan else None,
            course_id=loan.course_id if loan else None,
            damage_type="cracked", source="cleaning",
            description=body.note or "清洗后目检发现裂纹/破损",
            reported_by=user.id,
        )
        db.add(dmg)
        db.flush()
        traced = dmg.id
    else:
        raise HTTPException(400, "result 应为 pass / fail")

    db.commit()
    return {
        "ok": True, "item_code": it.code,
        "item_status": it.status,
        "item_status_name": m.STATUS_NAMES[it.status],
        "traced_loan_id": loan.id if loan else None,
        "traced_course": (f"{loan.course.name}（{loan.course.class_name} "
                          f"{loan.course.lesson_at}）{loan.group.name}"
                          if loan and body.result == "fail" else None),
        "damage_id": traced,
    }


# ---------------- 破损 / 免赔 ----------------
@app.get("/api/damages", response_model=list[s.DamageOut])
def list_damages(
    waiver: str | None = None,
    user: m.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(m.DamageRecord).order_by(m.DamageRecord.id.desc())
    if waiver:
        stmt = stmt.where(m.DamageRecord.waiver_status == waiver)
    return [damage_out(d, db) for d in db.scalars(stmt)]


@app.post("/api/damages/{damage_id}/waiver/request", response_model=s.DamageOut)
def request_waiver(
    damage_id: int,
    body: s.WaiverRequestIn,
    user: m.User = Depends(require_roles(m.ROLE_TEACHER, m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """任课老师可以为学生组提出免赔申请，但不能自行批准。"""
    dmg = db.get(m.DamageRecord, damage_id)
    if not dmg:
        raise HTTPException(404, "破损记录不存在")
    if dmg.waiver_status == m.WR_APPROVED:
        raise HTTPException(409, "该记录免赔已批准")
    dmg.waiver_status = m.WR_PENDING
    dmg.waiver_requested_at = datetime.now()
    if body.note:
        dmg.waiver_note = body.note
    db.commit()
    return damage_out(dmg, db)


@app.post("/api/damages/{damage_id}/waiver/review", response_model=s.DamageOut)
def review_waiver(
    damage_id: int,
    body: s.WaiverReviewIn,
    user: m.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """免赔审核：管理员可以审核；任课老师只能由非本节任课的老师/管理员办理。
    即：本节任课老师尝试自行免赔一律拒绝。"""
    dmg = db.get(m.DamageRecord, damage_id)
    if not dmg:
        raise HTTPException(404, "破损记录不存在")

    course = dmg.course
    if user.role == m.ROLE_WASHER:
        raise HTTPException(403, "清洗质检员无免赔审核权限")
    if user.role == m.ROLE_TEACHER:
        if not course:
            raise HTTPException(403, "该破损未关联课程，须由管理员审核免赔")
        if course.teacher_id == user.id:
            raise HTTPException(
                403,
                f"免赔申请必须由非本节任课老师审核：您是 "
                f"{course.name}（{course.class_name} {course.lesson_at}）的任课老师，"                f"不能自行免赔，请提交其他老师或管理员审核。"
            )
    elif user.role != m.ROLE_ADMIN:
        raise HTTPException(403, "无免赔审核权限")

    if dmg.waiver_status != m.WR_PENDING:
        raise HTTPException(409, "只能审核待审核状态的免赔申请")

    dmg.waiver_status = m.WR_APPROVED if body.approve else m.WR_REJECTED
    dmg.waiver_reviewed_by = user.id
    dmg.waiver_reviewed_at = datetime.now()
    dmg.waiver_note = (dmg.waiver_note + " " if dmg.waiver_note else "") + (
        f"[审核意见] {body.note}" if body.note else "[审核意见] （无）"
    )
    db.commit()
    return damage_out(dmg, db)


@app.post("/api/items/{code}/scrap", response_model=s.ItemOut)
def scrap_item(
    code: str,
    user: m.User = Depends(require_roles(m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """管理员对破损/缺失件做核销（领用记录保持不动）。"""
    it = db.scalars(select(m.Item).where(m.Item.code == code)).first()
    if not it:
        raise HTTPException(404, "查无此编号实物")
    if it.status not in (m.ST_DAMAGED, m.ST_MISSING):
        raise HTTPException(409, f"当前状态「{m.STATUS_NAMES[it.status]}」不可核销")
    it.status = m.ST_SCRAPPED
    db.commit()
    return item_out(it)


# ---------------- 盘点（管理员） ----------------
@app.post("/api/stocktakes", response_model=dict, status_code=201)
def create_stocktake(
    body: s.StocktakeCreateIn,
    user: m.User = Depends(require_roles(m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """建立盘点单时冻结系统快照；之后实物与系统不符，差异保留，不改领用记录。"""
    st = m.Stocktake(name=body.name, note=body.note, created_by=user.id)
    db.add(st)
    db.flush()
    for it in db.scalars(select(m.Item).order_by(m.Item.id)):
        db.add(m.StocktakeLine(
            stocktake_id=st.id, item_id=it.id,
            system_status_snapshot=it.status,
            counted=False, difference="loss",  # 初始默认盘亏，点到转 match
        ))
    db.commit()
    return stocktake_detail(st.id, user, db)


@app.get("/api/stocktakes", response_model=list[s.StocktakeOut])
def list_stocktakes(
    user: m.User = Depends(require_roles(m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    return [s.StocktakeOut.model_validate(x) for x in db.scalars(
        select(m.Stocktake).order_by(m.Stocktake.id.desc()))]


def _stocktake_line_out(l: m.StocktakeLine) -> s.StocktakeLineOut:
    return s.StocktakeLineOut(
        id=l.id, item_id=l.item_id, item_code=l.item.code,
        template_name=l.item.template.name, location=l.item.location,
        system_status_snapshot=l.system_status_snapshot,
        counted=l.counted, difference=l.difference,
        resolution=l.resolution, resolved_at=l.resolved_at,
    )


def _surplus_codes(st: m.Stocktake) -> list[str]:
    if st.note and st.note.startswith("{"):
        try:
            return json.loads(st.note).get("surplus", [])
        except json.JSONDecodeError:
            return []
    return []


def stocktake_detail(stocktake_id: int, user: m.User, db: Session) -> dict:
    st = db.get(m.Stocktake, stocktake_id)
    if not st:
        raise HTTPException(404, "盘点单不存在")
    lines = [_stocktake_line_out(x) for x in db.scalars(
        select(m.StocktakeLine)
        .where(m.StocktakeLine.stocktake_id == stocktake_id)
        .order_by(m.StocktakeLine.id)
    )]
    surplus = _surplus_codes(st)
    plain_note = "" if st.note and st.note.startswith("{") else (st.note or "")
    return {
        "stocktake": s.StocktakeOut.model_validate(st),
        "lines": lines,
        "surplus_codes": surplus,
        "summary": {
            "total": len(lines),
            "counted": sum(1 for x in lines if x.counted),
            "loss": sum(1 for x in lines if x.difference == "loss"),
            "surplus": len(surplus),
            "note": plain_note,
        },
    }


@app.get("/api/stocktakes/{sid}", response_model=dict)
def get_stocktake(sid: int, user: m.User = Depends(require_roles(m.ROLE_ADMIN)),
                  db: Session = Depends(get_db)):
    return stocktake_detail(sid, user, db)


@app.post("/api/stocktakes/{sid}/count", response_model=dict)
def stocktake_count(
    sid: int,
    body: s.StocktakeCountIn,
    user: m.User = Depends(require_roles(m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """扫到实物：逐件记为已盘。扫到系统里没有的编号记盘盈。"""
    st = db.get(m.Stocktake, sid)
    if not st:
        raise HTTPException(404, "盘点单不存在")
    if st.closed_at:
        raise HTTPException(409, "盘点单已关闭")
    code = body.item_code.strip()
    it = db.scalars(select(m.Item).where(m.Item.code == code)).first()
    if not it:
        try:
            meta = json.loads(st.note) if st.note.startswith("{") else {}
        except json.JSONDecodeError:
            meta = {}
        surplus = meta.get("surplus", [])
        if code not in surplus:
            surplus.append(code)
        st.note = json.dumps({"surplus": surplus}, ensure_ascii=False)
        db.commit()
        return {"ok": True, "surplus": True, "code": code,
                "message": f"编号 {code} 不在系统台账中，已记为盘盈（待核实来源）"}
    line = db.scalars(
        select(m.StocktakeLine)
        .where(m.StocktakeLine.stocktake_id == sid,
               m.StocktakeLine.item_id == it.id)
    ).first()
    if not line:
        raise HTTPException(409, "该件不在本次盘点快照内")
    line.counted = body.counted
    line.difference = "match" if body.counted else "loss"
    db.commit()
    return {"ok": True, "line": _stocktake_line_out(line)}


@app.post("/api/stocktake-lines/{line_id}/resolve", response_model=s.StocktakeLineOut)
def stocktake_resolve(
    line_id: int,
    body: s.StocktakeResolveIn,
    user: m.User = Depends(require_roles(m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """查明差异：写说明；可登记缺失并追溯上一节课。
    无论如何不回改领用/归还记录。"""
    line = db.get(m.StocktakeLine, line_id)
    if not line:
        raise HTTPException(404, "盘点行不存在")
    line.resolution = body.resolution
    line.resolved_by = user.id
    line.resolved_at = datetime.now()
    if body.report_loss and line.difference == "loss":
        it = line.item
        if it.status != m.ST_SCRAPPED:
            it.status = m.ST_MISSING
        loan = latest_loan_for_item(db, it.id)
        exists = db.scalars(select(m.DamageRecord).where(
            m.DamageRecord.item_id == it.id,
            m.DamageRecord.source == "stocktake",
        )).first()
        if not exists:
            db.add(m.DamageRecord(
                item_id=it.id,
                loan_id=loan.id if loan else None,
                course_id=loan.course_id if loan else None,
                damage_type="missing", source="stocktake",
                description=f"盘点盘亏：{body.resolution}", reported_by=user.id,
            ))
    db.commit()
    return _stocktake_line_out(line)


@app.post("/api/stocktakes/{sid}/close", response_model=s.StocktakeOut)
def stocktake_close(
    sid: int,
    user: m.User = Depends(require_roles(m.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """关闭盘点：未点到的实物保留为盘亏差异，不允许用盘点结果直接冲改领用记录。"""
    st = db.get(m.Stocktake, sid)
    if not st:
        raise HTTPException(404, "盘点单不存在")
    if st.closed_at:
        raise HTTPException(409, "盘点单已关闭")
    st.closed_at = datetime.now()
    db.commit()
    return s.StocktakeOut.model_validate(st)


# ---------------- 首页统计 ----------------
@app.get("/api/stats")
def stats(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    counts = {st: 0 for st in m.STATUS_NAMES}
    for it in db.scalars(select(m.Item)):
        counts[it.status] = counts.get(it.status, 0) + 1
    active_loans = len(list(db.scalars(select(m.Loan).where(m.Loan.status == "active"))))
    pending_waivers = len(list(db.scalars(
        select(m.DamageRecord).where(m.DamageRecord.waiver_status == m.WR_PENDING))))
    open_loss = len(list(db.scalars(
        select(m.StocktakeLine).where(
            m.StocktakeLine.difference == "loss",
            m.StocktakeLine.resolved_at.is_(None)))))
    return {
        "status_counts": counts,
        "active_loans": active_loans,
        "pending_waivers": pending_waivers,
        "open_loss_lines": open_loss,
    }


# ---------------- 前端 / 上传文件静态服务 ----------------
@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html"))


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "frontend")),
          name="frontend")
