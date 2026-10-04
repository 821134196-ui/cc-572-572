"""极简令牌认证与基于角色的依赖。

角色：
  teacher  任课老师：建课程/学生组、按组配发、登记归还
  admin    实验室管理员：器皿台账、柜位、检查、送清洗机、盘点
  reviewer 免赔审核员（非任课老师）：审核破损/缺失的免赔或赔偿
"""
import base64
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from .database import get_db
from .models import User


def make_token(username: str) -> str:
    return base64.b64encode(f"lab::{username}".encode()).decode()


def parse_token(token: str) -> str:
    try:
        raw = base64.b64decode(token.encode()).decode()
    except Exception:
        raise HTTPException(401, "令牌无效")
    if not raw.startswith("lab::"):
        raise HTTPException(401, "令牌无效")
    return raw[5:]


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "未登录")
    username = parse_token(authorization.split(" ", 1)[1])
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(401, "用户不存在")
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            names = {"teacher": "任课老师", "admin": "管理员", "reviewer": "免赔审核员"}
            allow = "、".join(names.get(r, r) for r in roles)
            raise HTTPException(403, f"权限不足：本操作仅 {allow} 可办理，各岗位只能办理相应操作")
        return user
    return dep
