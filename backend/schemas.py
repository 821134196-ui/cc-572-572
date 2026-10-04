"""Pydantic request/response schemas."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth ----
class LoginIn(BaseModel):
    username: str


class UserOut(ORMModel):
    id: int
    username: str
    name: str
    role: str


# ---- catalog ----
class TemplateOut(ORMModel):
    id: int
    code: str
    name: str
    spec: str
    unit: str
    is_kit: bool


class ComponentOut(BaseModel):
    template_id: int
    code: str
    name: str
    qty: int


class KitTemplateOut(TemplateOut):
    components: list[ComponentOut] = []


class ItemOut(ORMModel):
    id: int
    code: str
    template_id: int
    location: str
    status: str
    kit_id: int | None = None
    template_name: str = ""
    spec: str = ""
    is_kit: bool = False


# ---- course / group ----
class GroupOut(ORMModel):
    id: int
    name: str
    course_id: int


class CourseOut(ORMModel):
    id: int
    name: str
    class_name: str
    lesson_at: str
    teacher_id: int


class CourseDetailOut(CourseOut):
    teacher_name: str = ""
    groups: list[GroupOut] = []


# ---- loan ----
class LoanLineOut(ORMModel):
    id: int
    item_id: int
    item_code: str
    item_status: str
    template_name: str
    spec: str
    location: str
    kit_id: int | None
    return_status: str | None
    returned_at: datetime | None
    return_note: str


class LoanOut(ORMModel):
    id: int
    course_id: int
    group_id: int
    teacher_id: int
    lent_at: datetime
    returned_at: datetime | None
    status: str
    note: str
    course_name: str = ""
    class_name: str = ""
    lesson_at: str = ""
    group_name: str = ""
    teacher_name: str = ""


class CreateLoanIn(BaseModel):
    course_id: int
    group_id: int
    item_codes: list[str]
    note: str = ""


class ReturnIn(BaseModel):
    item_code: str
    return_status: str          # intact / cracked / missing / dirty
    note: str = ""


# ---- cleaning ----
class CleanStartIn(BaseModel):
    item_code: str
    note: str = ""


class CleanCompleteIn(BaseModel):
    device_job_id: str
    result: str                 # pass / fail
    note: str = ""


class InspectIn(BaseModel):
    item_code: str
    passed: bool
    note: str = ""


# ---- damage ----
class DamageOut(ORMModel):
    id: int
    item_id: int
    item_code: str
    template_name: str
    loan_id: int | None
    course_id: int | None
    course_name: str = ""
    class_name: str = ""
    lesson_at: str = ""
    group_name: str = ""
    course_teacher_id: int | None = None
    damage_type: str
    source: str
    description: str
    photo_path: str | None
    reported_by: int
    reporter_name: str = ""
    reported_at: datetime
    waiver_status: str
    waiver_note: str
    waiver_reviewed_by: int | None
    reviewer_name: str = ""


class WaiverRequestIn(BaseModel):
    note: str = ""


class WaiverReviewIn(BaseModel):
    approve: bool
    note: str = ""


# ---- stocktake ----
class StocktakeOut(ORMModel):
    id: int
    name: str
    created_by: int
    created_at: datetime
    closed_at: datetime | None
    note: str


class StocktakeLineOut(ORMModel):
    id: int
    item_id: int
    item_code: str
    template_name: str
    location: str
    system_status_snapshot: str
    counted: bool
    difference: str
    resolution: str
    resolved_at: datetime | None


class StocktakeCreateIn(BaseModel):
    name: str
    note: str = ""


class StocktakeCountIn(BaseModel):
    item_code: str
    counted: bool = True


class StocktakeResolveIn(BaseModel):
    resolution: str
    report_loss: bool = False   # 登记缺失（生成破损记录追溯上课），不改领用记录


# ---- history ----
class HistoryEvent(BaseModel):
    at: datetime
    kind: str
    detail: str
    operator: str = ""
