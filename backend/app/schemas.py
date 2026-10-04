"""Pydantic 请求/响应模式。"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 认证 ----------
class LoginIn(BaseModel):
    username: str
    password: str


# ---------- 课程 / 学生组 ----------
class CourseIn(BaseModel):
    name: str
    class_name: str


class GroupIn(BaseModel):
    name: str
    members: str = ""


# ---------- 器皿 ----------
class TemplateIn(BaseModel):
    name: str
    spec: str = ""
    is_set: bool = False


class ItemIn(BaseModel):
    code: str
    template_id: int
    location_code: str
    kit_code: str | None = None  # 所属套件实物编号


# ---------- 领用 / 归还 ----------
class IssueIn(BaseModel):
    course_id: int
    group_id: int
    item_codes: list[str]
    note: str = ""


class ReturnIn(BaseModel):
    result: str  # COMPLETE / DIRTY / CRACKED / MISSING
    note: str = ""
    photo_path: str | None = None


class InspectIn(BaseModel):
    action: str  # PASS 检查合格回库 / NEED_WASH 需清洗
    note: str = ""


class WashStartIn(BaseModel):
    item_codes: list[str]


class DamageReviewIn(BaseModel):
    decision: str  # WAIVED 免赔 / CHARGED 赔偿
    note: str = ""


# ---------- 盘点 ----------
class StocktakeIn(BaseModel):
    label: str
    scope_location: str | None = None


class StocktakeCountIn(BaseModel):
    item_codes: list[str]


class VarianceResolveIn(BaseModel):
    resolution: str
