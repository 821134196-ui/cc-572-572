"""初始化数据库并灌入演示数据。

账号（密码与用户名相同）：
  teacher1  王老师（任课老师，初三化学）
  teacher2  李老师（任课老师，初二物理）
  admin1    陈管理员（实验室管理员）
  reviewer1 赵主任（免赔审核员，非任课老师）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.database import Base, engine, SessionLocal
from app import models

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# ---------- 用户 ----------
users = {
    "teacher1": models.User(username="teacher1", password="teacher1",
                            name="王老师", role="teacher"),
    "teacher2": models.User(username="teacher2", password="teacher2",
                            name="李老师", role="teacher"),
    "admin1": models.User(username="admin1", password="admin1",
                          name="陈管理员", role="admin"),
    "reviewer1": models.User(username="reviewer1", password="reviewer1",
                             name="赵主任", role="reviewer"),
}
db.add_all(users.values())
db.flush()

# ---------- 器皿型号 ----------
tpls = {
    "beaker": models.ItemTemplate(name="烧杯", spec="250mL"),
    "flask": models.ItemTemplate(name="锥形瓶", spec="250mL"),
    "tube": models.ItemTemplate(name="试管", spec="20×200mm"),
    "funnel": models.ItemTemplate(name="玻璃漏斗", spec="90mm"),
    "stand": models.ItemTemplate(name="铁架台", spec="带铁圈铁夹"),
    "burner": models.ItemTemplate(name="酒精灯", spec="150mL"),
    "grad": models.ItemTemplate(name="量筒", spec="100mL"),
    "distill": models.ItemTemplate(name="蒸馏装置套", spec="初中版 5 件套", is_set=True),
    "disthead": models.ItemTemplate(name="蒸馏头", spec="24#"),
    "condenser": models.ItemTemplate(name="冷凝管", spec="直形 300mm"),
    "adapter": models.ItemTemplate(name="接引管", spec="24#"),
    "receiver": models.ItemTemplate(name="接收瓶", spec="100mL"),
}
db.add_all(tpls.values())
db.flush()


def add_item(code, tpl, loc, kit=None):
    it = models.Item(code=code, template_id=tpl.id, location_code=loc,
                     kit_id=kit.id if kit else None)
    db.add(it)
    db.flush()
    return it


# ---------- 单件器皿 ----------
items = {}
items["BK-1001"] = add_item("BK-1001", tpls["beaker"], "A-01-01")
items["BK-1002"] = add_item("BK-1002", tpls["beaker"], "A-01-01")
items["BK-1003"] = add_item("BK-1003", tpls["beaker"], "A-01-02")
items["CF-2001"] = add_item("CF-2001", tpls["flask"], "A-02-01")
items["CF-2002"] = add_item("CF-2002", tpls["flask"], "A-02-01")
items["TT-3001"] = add_item("TT-3001", tpls["tube"], "A-03-01")
items["TT-3002"] = add_item("TT-3002", tpls["tube"], "A-03-01")
items["TT-3003"] = add_item("TT-3003", tpls["tube"], "A-03-02")
items["FN-4001"] = add_item("FN-4001", tpls["funnel"], "A-04-01")
items["FN-4002"] = add_item("FN-4002", tpls["funnel"], "A-04-01")
items["ST-5001"] = add_item("ST-5001", tpls["stand"], "B-01-01")
items["AL-6001"] = add_item("AL-6001", tpls["burner"], "B-02-01")
items["AL-6002"] = add_item("AL-6002", tpls["burner"], "B-02-01")
items["GC-7001"] = add_item("GC-7001", tpls["grad"], "A-05-01")
items["GC-7002"] = add_item("GC-7002", tpls["grad"], "A-05-01")

# ---------- 蒸馏装置套 DS-9001（套件本体 + 5 个部件，各有独立编号与柜位） ----------
kit = add_item("DS-9001", tpls["distill"], "C-01-00")
items["DS-9001"] = kit
items["DS-9001-01"] = add_item("DS-9001-01", tpls["flask"], "C-01-01", kit)
items["DS-9001-02"] = add_item("DS-9001-02", tpls["disthead"], "C-01-02", kit)
items["DS-9001-03"] = add_item("DS-9001-03", tpls["condenser"], "C-01-03", kit)
items["DS-9001-04"] = add_item("DS-9001-04", tpls["adapter"], "C-01-04", kit)
items["DS-9001-05"] = add_item("DS-9001-05", tpls["receiver"], "C-01-05", kit)

# ---------- 课程与学生组 ----------
course = models.Course(name="水的净化与蒸馏", class_name="初三(2)班",
                       teacher_id=users["teacher1"].id)
db.add(course); db.flush()
g1 = models.StudentGroup(course_id=course.id, name="第1组", members="张明、王芳、刘洋")
g2 = models.StudentGroup(course_id=course.id, name="第2组", members="陈晨、赵磊、孙丽")
db.add_all([g1, g2]); db.flush()

db.commit()
print("种子数据完成：")
print(f"  用户 {db.query(models.User).count()} 名；"
      f"器皿实物 {db.query(models.Item).count()} 件；"
      f"课程 {db.query(models.Course).count()} 个；"
      f"学生组 {db.query(models.StudentGroup).count()} 个")
print("  账号: teacher1/teacher1 teacher2/teacher2 admin1/admin1 reviewer1/reviewer1")
