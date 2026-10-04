"""清洗设备接口（模拟）。

真实环境中这里会调用超声波/洗瓶机厂商的 HTTP API；当前用内存任务表模拟：
- start_job：设备接单，返回机台任务号
- get_job：查询机台任务状态
- finish_job：模拟机台回调（机台清洗完成 / 清洗后目检发现裂纹）

业务规则：清洗后才发现破损（FAIL），仍通过 WashRecord.loan_item
追到上一节课的领用单，不因器皿已离开课堂而丢失责任链。
"""
import threading
from itertools import count

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_seq = count(1)


class WasherClient:
    @staticmethod
    def start_job(item_code: str) -> str:
        with _lock:
            job_id = f"WASH-{next(_seq):04d}"
            _jobs[job_id] = {"item_code": item_code, "state": "RUNNING"}
        return job_id

    @staticmethod
    def get_job(job_id: str) -> dict:
        with _lock:
            job = _jobs.get(job_id)
            if not job:
                return {"state": "UNKNOWN"}
            return dict(job)

    @staticmethod
    def finish_job(job_id: str, state: str) -> dict:
        """模拟机台推送完成结果：state=PASS 合格 / FAIL 清洗后发现破损。"""
        with _lock:
            if job_id not in _jobs:
                return {"state": "UNKNOWN"}
            _jobs[job_id]["state"] = state
            return dict(_jobs[job_id])
