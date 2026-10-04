"""ORM 模型：器皿、套件、课程、学生组、领用、归还、清洗、破损、盘点。"""
from datetime import datetime
from sqlalchemy import (
    String, Integer, ForeignKey, DateTime, Text, Boolean, UniqueConstraint, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def now():
    return datetime.now()


# ---------- 用户与权限 ----------
# 角色：teacher 任课老师 / admin 实验室管理员 / reviewer 免赔审核员
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20))  # teacher / admin / reviewer


# ---------- 器皿目录与实物 ----------
class ItemTemplate(Base):
    """器皿型号；is_set=True 表示成套器材（如蒸馏装置套）。"""
    __tablename__ = "item_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    spec: Mapped[str] = mapped_column(String(100), default="")
    is_set: Mapped[bool] = mapped_column(Boolean, default=False)

    items: Mapped[list["Item"]] = relationship(back_populates="template")


class Item(Base):
    """每件实物玻璃器皿：独立编号 + 柜位。kit_id 指向所属套件实物（自引用）。"""
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("item_templates.id"))
    location_code: Mapped[str] = mapped_column(String(50), index=True)  # 柜位，如 A-01-03
    # AVAILABLE 可借 / LENT 已借出 / RETURNED 已还待检待洗 / CLEANING 清洗中
    # BROKEN 破损下架 / MISSING 缺失挂账 / RETIRED 报废
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE", index=True)
    kit_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    template: Mapped[ItemTemplate] = relationship(back_populates="items")
    kit: Mapped["Item | None"] = relationship(remote_side=[id], foreign_keys=[kit_id])


# ---------- 课程与学生组 ----------
class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    class_name: Mapped[str] = mapped_column(String(100))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    teacher: Mapped[User] = relationship()
    groups: Mapped[list["StudentGroup"]] = relationship(back_populates="course")


class StudentGroup(Base):
    __tablename__ = "student_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    name: Mapped[str] = mapped_column(String(100))
    members: Mapped[str] = mapped_column(String(300), default="")

    course: Mapped[Course] = relationship(back_populates="groups")


# ---------- 领用与归还 ----------
class Loan(Base):
    """一次按课程、按学生组的配发。"""
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    group_id: Mapped[int] = mapped_column(ForeignKey("student_groups.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # OPEN 借用中 / CLOSED 已结案
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")

    course: Mapped[Course] = relationship()
    group: Mapped[StudentGroup] = relationship()
    teacher: Mapped[User] = relationship(foreign_keys=[teacher_id])
    items: Mapped[list["LoanItem"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan"
    )


class LoanItem(Base):
    """领用单中的一件实物。同一领用单内每件只出现一次——重复扫码不会重复登记。"""
    __tablename__ = "loan_items"
    __table_args__ = (UniqueConstraint("loan_id", "item_id", name="uq_loan_item"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    # 归还检查结果：None 未还 / COMPLETE 完整 / DIRTY 待清洗 / CRACKED 裂纹 / MISSING 缺失
    return_result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    return_photo_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")

    loan: Mapped[Loan] = relationship(back_populates="items")
    item: Mapped[Item] = relationship()
    wash_records: Mapped[list["WashRecord"]] = relationship(back_populates="loan_item")


# ---------- 清洗（模拟清洗设备） ----------
class WashRecord(Base):
    __tablename__ = "wash_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    loan_item_id: Mapped[int] = mapped_column(ForeignKey("loan_items.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    machine_job_id: Mapped[str] = mapped_column(String(40), index=True)
    started_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # RUNNING 清洗中 / PASS 合格回库 / FAIL 清洗后发现破损
    result: Mapped[str] = mapped_column(String(20), default="RUNNING")
    note: Mapped[str] = mapped_column(Text, default="")

    loan_item: Mapped[LoanItem] = relationship(back_populates="wash_records")
    item: Mapped[Item] = relationship()


# ---------- 破损 / 缺失与免赔审核 ----------
class Damage(Base):
    __tablename__ = "damages"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"), nullable=True)
    # RETURN 归还时发现 / POST_WASH 清洗后发现 / STOCKTAKE 盘点发现
    source: Mapped[str] = mapped_column(String(20))
    # CRACK 裂纹破损 / MISSING 缺失 / OTHER 其他
    damage_type: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    photo_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reported_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # PENDING 待审核 / WAIVED 免赔 / CHARGED 已赔偿
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")

    item: Mapped[Item] = relationship()
    loan: Mapped["Loan | None"] = relationship()
    reporter: Mapped[User] = relationship(foreign_keys=[reported_by])
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])


# ---------- 盘点 ----------
class Stocktake(Base):
    __tablename__ = "stocktakes"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
    scope_location: Mapped[str | None] = mapped_column(String(50), nullable=True)  # None=全部柜位
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # OPEN 盘点中 / COUNTED 已录入实盘 / CLOSED 已处理
    status: Mapped[str] = mapped_column(String(20), default="OPEN")

    variances: Mapped[list["StocktakeVariance"]] = relationship(
        back_populates="stocktake", cascade="all, delete-orphan"
    )


class StocktakeVariance(Base):
    """盘点差异：长期保留，绝不回改领用记录。"""
    __tablename__ = "stocktake_variances"
    id: Mapped[int] = mapped_column(primary_key=True)
    stocktake_id: Mapped[int] = mapped_column(ForeignKey("stocktakes.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    item_code: Mapped[str] = mapped_column(String(50))
    # MISSING 系统有账、实物未盘到 / SURPLUS 实物多出来 / WRONG_LOCATION 实物在别的柜位
    kind: Mapped[str] = mapped_column(String(20))
    expected_location: Mapped[str] = mapped_column(String(50), default="")
    found_location: Mapped[str] = mapped_column(String(50), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    # OPEN 未处理 / RESOLVED 已处理（处理方式只追加，不改历史）
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    resolution: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    stocktake: Mapped[Stocktake] = relationship(back_populates="variances")
    item: Mapped["Item | None"] = relationship()
    resolver: Mapped["User | None"] = relationship(foreign_keys=[resolved_by])
