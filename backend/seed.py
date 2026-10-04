"""初始化数据库并写入演示数据。

账号（免密，选择身份登录，便于课堂演示）：
  admin  周敏  管理员
  wang   王磊  任课老师（初二3班《水的蒸馏》）
  zhao   赵静  任课老师（初一1班《粗盐溶解与过滤》），非本节任课老师
  sun    孙师傅 清洗质检员
"""
import os
from sqlalchemy import select
from .database import Base, engine, SessionLocal
from . import models as m


def run():
    if os.path.exists(engine.url.database):
        os.remove(engine.url.database)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    admin = m.User(username="admin", name="周敏", role=m.ROLE_ADMIN)
    wang = m.User(username="wang", name="王磊", role=m.ROLE_TEACHER)
    zhao = m.User(username="zhao", name="赵静", role=m.ROLE_TEACHER)
    sun = m.User(username="sun", name="孙师傅", role=m.ROLE_WASHER)
    db.add_all([admin, wang, zhao, sun])
    db.flush()

    # ---- 品种目录 ----
    def tmpl(code, name, spec="", unit="件", is_kit=False):
        t = m.Template(code=code, name=name, spec=spec, unit=unit, is_kit=is_kit)
        db.add(t)
        return t

    bk250 = tmpl("BK250", "烧杯", "250mL 玻璃")
    bk100 = tmpl("BK100", "烧杯", "100mL 玻璃")
    flask250 = tmpl("CF250", "锥形瓶", "250mL")
    tube = tmpl("TT20", "试管", "20×200mm")
    funnel = tmpl("FN60", "漏斗", "60mm 短颈")
    grad = tmpl("GC100", "量筒", "100mL")

    dist_flask = tmpl("DF250", "蒸馏烧瓶", "250mL 具支管")
    condenser = tmpl("CD300", "冷凝管", "300mm 直形")
    thermo = tmpl("TH100", "温度计", "0-100℃ 红水")
    db.flush()

    distill = tmpl("KIT-DST", "蒸馏装置", "初中蒸馏演示套件", unit="套", is_kit=True)
    db.flush()
    for comp_t, qty in [(dist_flask, 1), (condenser, 1), (thermo, 1)]:
        db.add(m.KitComponent(kit_template_id=distill.id,
                              component_template_id=comp_t.id, qty=qty))

    # ---- 实物（独立编号 + 独立柜位） ----
    def item(code, t, location, kit_id=None):
        x = m.Item(code=code, template_id=t.id, location=location, kit_id=kit_id)
        db.add(x)
        return x

    for i in range(1, 7):
        item(f"BK-250-{i:03d}", bk250, f"A柜-1层-{i:02d}")
    for i in range(1, 5):
        item(f"BK-100-{i:03d}", bk100, f"A柜-2层-{i:02d}")
        item(f"CF-250-{i:03d}", flask250, f"B柜-1层-{i:02d}")
        item(f"GC-100-{i:03d}", grad, f"B柜-2层-{i:02d}")
        item(f"FN-060-{i:03d}", funnel, f"C柜-1层-{i:02d}")
    for i in range(1, 11):
        item(f"TT-020-{i:03d}", tube, f"C柜-2层-{i:02d}")

    # 蒸馏套件 ×2：套件父件 + 3 个部件实物，逐件编号、逐件柜位
    def make_distill_kit(n):
        parent = item(f"DST-{n:02d}", distill, f"D柜-{n}层-套件位")
        db.flush()
        item(f"DST-{n:02d}-F", dist_flask, f"D柜-{n}层-烧瓶位", kit_id=parent.id)
        item(f"DST-{n:02d}-C", condenser, f"D柜-{n}层-冷凝管位", kit_id=parent.id)
        item(f"DST-{n:02d}-T", thermo, f"D柜-{n}层-温度计位", kit_id=parent.id)
        return parent

    make_distill_kit(1)
    make_distill_kit(2)
    db.flush()

    # ---- 课程与学生组 ----
    c1 = m.Course(name="水的蒸馏", class_name="初二(3)班", lesson_at="周三第3节",
                  teacher_id=wang.id)
    c2 = m.Course(name="粗盐溶解与过滤", class_name="初一(1)班",
                  lesson_at="周二第5节", teacher_id=zhao.id)
    db.add_all([c1, c2])
    db.flush()
    for g in ["第1组", "第2组", "第3组", "第4组"]:
        db.add(m.StudentGroup(name=g, course_id=c1.id))
    for g in ["第1组", "第2组", "第3组", "第4组"]:
        db.add(m.StudentGroup(name=g, course_id=c2.id))

    db.commit()
    db.close()
    print("种子数据已写入：4 个账号、2 门课、8 个学生组、蒸馏套件 2 套及散件若干。")


if __name__ == "__main__":
    run()
