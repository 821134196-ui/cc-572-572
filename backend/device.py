"""模拟超声波清洗机接口。

真实环境里这里会是 HTTP/串口 SDK；本文件用内存任务表模拟设备行为：
- submit(): 设备接收任务，返回任务号，状态 RECEIVED
- fetch(): 轮询设备，模拟清洗在约 6 秒后完成
"""
import itertools
import threading
from datetime import datetime, timedelta

RECEIVED = "RECEIVED"
FINISHED = "FINISHED"

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_seq = itertools.count(1)


def submit(item_code: str) -> dict:
    """把一件器皿送入清洗设备。"""
    job_id = f"WASH-{next(_seq):05d}"
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "item_code": item_code,
            "state": RECEIVED,
            "submitted_at": datetime.now(),
            "finish_at": datetime.now() + timedelta(seconds=6),
        }
    return dict(_jobs[job_id])


def fetch(job_id: str) -> dict | None:
    """查询设备任务状态（模拟设备上报）。"""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if job["state"] == RECEIVED and datetime.now() >= job["finish_at"]:
            job["state"] = FINISHED
            # 模拟设备机检：清洗完成，等待质检员目检判定
            job["device_report"] = "清洗程序结束，请目检"
        return dict(job)
