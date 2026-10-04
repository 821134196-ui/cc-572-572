"""ORM models for the glassware loan & damage registry."""
from datetime import datetime
from sqlalchemy import (
    Integer, String, ForeignKey, DateTime, Text, Boolean, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


# ---------- 角色 ----------
ROLE_ADMIN = "admin"        # 管理员
ROLE_TEACHER = "teacher"    # 任课老师
ROLE_WASHER = "washer"      # 清洗 / 质检员

ROLE_NAMES = {
    ROLE_ADMIN: "管理员",
    ROLE_TEACHER: "任课老师",
    ROLE_WASHER: "清洗质检员",
}

# ---------- 实物状态 ----------
ST_AVAILABLE = "available"      # 可借库存
ST_LENT = "lent"                # 借出中
ST_TO_CHECK = "to_check"        # 归还完整，待检查
ST_TO_CLEAN = "to_clean"        # 待清洗
ST_WASHING = "washing"          # 清洗设备处理中
ST_DAMAGED = "damaged"          # 裂纹 / 破损，待处理
ST_MISSING = "missing"          # 缺失
ST_SCRAPPED = "scrapped"        # 报废 / 核销

STATUS_NAMES = {
    ST_AVAILABLE: "可借",
    ST_LENT: "借出中",
    ST_TO_CHECK: "待检查",
    ST_TO_CLEAN: "待清洗",
    ST_WASHING: "清洗中",
    ST_DAMAGED: "破损",
    ST_MISSING: "缺失",
    ST_SCRAPPED: "已核销",
}

# 归还登记的四种情况
RET_INTACT = "intact"     # 完整
RET_CRACKED = "cracked"   # 裂纹
RET_MISSING = "missing"   # 缺失
RET_DIRTY = "dirty"       # 待清洗

RETURN_NAMES = {
    RET_INTACT: "完整",
    RET_CRACKED: "裂纹",
    RET_MISSING: "缺失",
    RET_DIRTY: "待清洗",
}

# 破损免赔审核状态
WR_NONE = "none"
WR_PENDING = "pending"
WR_APPROVED = "approved"
WR_REJECTED = "rejected"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20))

    courses: Mapped[list["Course"]] = relationship(back_populates="teacher")


class Template(Base):
    """器皿品种；is_kit=True 时为套件品种（如蒸馏装置）。"""
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)   # 品种编码
    name: Mapped[str] = mapped_column(String(80))
    spec: Mapped[str] = mapped_column(String(120), default="")
    unit: Mapped[str] = mapped_column(String(10), default="件")
    is_kit: Mapped[bool] = mapped_column(Boolean, default=False)

    components: Mapped[list["KitComponent"]] = relationship(
        back_populates="kit_template", cascade="all, delete-orphan",
        foreign_keys="KitComponent.kit_template_id",
    )


class KitComponent(Base):
    """套件品种应包含的部件品种及数量。"""
    __tablename__ = "kit_components"
    id: Mapped[int] = mapped_column(primary_key=True)
    kit_template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    component_template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    qty: Mapped[int] = mapped_column(Integer, default=1)

    kit_template: Mapped["Template"] = relationship(
        back_populates="components", foreign_keys=[kit_template_id]
    )
    component_template: Mapped["Template"] = relationship(foreign_keys=[component_template_id])


class Item(Base):
    """每件实物器皿：独立编号 + 独立柜位。"""
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)  # 实物编号，贴码 / 扫码
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    location: Mapped[str] = mapped_column(String(40))           # 柜位，如 A柜-2层-03
    status: Mapped[str] = mapped_column(String(20), default=ST_AVAILABLE)
    # 套件实物的父件；非套件部件为空
    kit_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)

    template: Mapped["Template"] = relationship()
    kit_parent: Mapped["Item | None"] = relationship(
        remote_side="Item.id", back_populates="children"
    )
    children: Mapped[list["Item"]] = relationship(back_populates="kit_parent")


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))               # 实验课名称
    class_name: Mapped[str] = mapped_column(String(50))         # 班级
    lesson_at: Mapped[str] = mapped_column(String(30))          # 上课时间（节次）
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    teacher: Mapped["User"] = relationship(back_populates="courses")
    groups: Mapped[list["StudentGroup"]] = relationship(back_populates="course")


class StudentGroup(Base):
    __tablename__ = "student_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))               # 如 第3组
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))

    course: Mapped["Course"] = relationship(back_populates="groups")


class Loan(Base):
    """领用单：某老师的某节课，发给某个学生组。"""
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    group_id: Mapped[int] = mapped_column(ForeignKey("student_groups.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # active 仍有未结清件 / done 全部完好回库 / issue 有破损缺失
    status: Mapped[str] = mapped_column(String(20), default="active")
    note: Mapped[str] = mapped_column(Text, default="")

    course: Mapped["Course"] = relationship()
    group: Mapped["StudentGroup"] = relationship()
    teacher: Mapped["User"] = relationship()
    lines: Mapped[list["LoanLine"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan"
    )


class LoanLine(Base):
    """领用单中的一件实物；归还逐件登记，且只登记一次。"""
    __tablename__ = "loan_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    return_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    return_note: Mapped[str] = mapped_column(Text, default="")

    loan: Mapped["Loan"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()

    __table_args__ = (UniqueConstraint("loan_id", "item_id", name="uq_loan_item"),)


class DamageRecord(Base):
    """破损 / 缺失记录：可发现于归还或清洗后，始终关联到最近一次领用（上一节课）。"""
    __tablename__ = "damage_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"), nullable=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    damage_type: Mapped[str] = mapped_column(String(20))        # cracked / missing
    source: Mapped[str] = mapped_column(String(20))            # return / cleaning / stocktake
    description: Mapped[str] = mapped_column(Text, default="")
    photo_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    waiver_status: Mapped[str] = mapped_column(String(20), default=WR_NONE)
    waiver_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    waiver_reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    waiver_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    waiver_note: Mapped[str] = mapped_column(Text, default="")

    item: Mapped["Item"] = relationship()
    loan: Mapped["Loan | None"] = relationship()
    course: Mapped["Course | None"] = relationship()
    reporter: Mapped["User"] = relationship(foreign_keys=[reported_by])
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[waiver_reviewed_by])


class CleaningRecord(Base):
    """检查 / 清洗记录，含模拟清洗设备的任务号。"""
    __tablename__ = "cleaning_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"), nullable=True)
    washer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    device_job_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pass / fail
    note: Mapped[str] = mapped_column(Text, default="")

    item: Mapped["Item"] = relationship()
    loan: Mapped["Loan | None"] = relationship()
    washer: Mapped["User"] = relationship()


class Stocktake(Base):
    """盘点单。"""
    __tablename__ = "stocktakes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")

    lines: Mapped[list["StocktakeLine"]] = relationship(
        back_populates="stocktake", cascade="all, delete-orphan"
    )


class StocktakeLine(Base):
    """盘点逐行：系统快照数量/状态 与 实盘数量，差异永久保留。"""
    __tablename__ = "stocktake_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    stocktake_id: Mapped[int] = mapped_column(ForeignKey("stocktakes.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    system_status_snapshot: Mapped[str] = mapped_column(String(20))
    counted: Mapped[bool] = mapped_column(Boolean)             # 实物是否点到
    difference: Mapped[str] = mapped_column(String(20))        # match / loss / surplus
    resolution: Mapped[str] = mapped_column(Text, default="")  # 查明说明（不改领用记录）
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    stocktake: Mapped["Stocktake"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()
    resolver: Mapped["User | None"] = relationship(foreign_keys=[resolved_by])
