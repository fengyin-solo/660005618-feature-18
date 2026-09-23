"""执行状态仓库：保存当前/最近一次执行的全量快照与增量事件环形缓冲。

- 执行线程在后台更新状态并推进 seq；
- WS 重连时凭 (runId, lastSeq) 补断线期间落下的事件；
  缺口已超出缓冲（或跨 run）则整份快照重放。
"""
import threading
import time
from collections import deque

EVENT_BUFFER_SIZE = 500


class ExecutionStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._snap = None            # 内部全量快照（含 durations 等内部字段）
        self._events = deque(maxlen=EVENT_BUFFER_SIZE)
        self._seq = 0                # 单调递增，0 表示尚无事件

    # ---- 执行线程侧写操作 -------------------------------------------------
    def reset(self, run_id: int, workflow: dict, workers: int, strategy: str):
        with self._lock:
            now = time.time()
            self._events.clear()
            self._seq = 0
            self._snap = {
                "runId": run_id,
                "status": "RUNNING",
                "workers": workers,
                "strategy": strategy,
                "startedAt": now,
                "finishedAt": None,
                "workflow": {"id": workflow["id"], "name": workflow["name"]},
                "nodes": workflow["nodes"],
                "edges": workflow["edges"],
                "logs": [],
                "circuitBreakers": [],
                "cbMap": {},
                "seq": 0,
            }
            self._append_event_locked({"type": "run_status", "status": "RUNNING"})
        return self.snapshot()

    def update_node(self, node: dict):
        with self._lock:
            for n in self._snap["nodes"]:
                if n["id"] == node["id"]:
                    n.update({k: node.get(k) for k in
                              ("status", "retries", "startTime", "endTime")})
                    break
            self._append_event_locked({"type": "node_update", "node": dict(node)})

    def add_log(self, task_id: str, status: str, message: str):
        with self._lock:
            entry = {"taskId": task_id, "status": status,
                     "timestamp": time.time(), "message": message}
            self._snap["logs"].append(entry)
            # 服务端只留最近 500 条，投影再按需截断
            if len(self._snap["logs"]) > 500:
                self._snap["logs"] = self._snap["logs"][-500:]
            self._append_event_locked({"type": "log", "log": entry})

    def touch_breaker(self, task_id: str, failure_count: int, state: str,
                      cooldown_until: float):
        with self._lock:
            cb = {"taskId": task_id, "failureCount": failure_count,
                  "state": state, "cooldownUntil": cooldown_until}
            self._snap["cbMap"][task_id] = cb
            self._snap["circuitBreakers"] = list(self._snap["cbMap"].values())
            self._append_event_locked({"type": "breaker", "breaker": dict(cb)})

    def finish(self, status: str):
        with self._lock:
            self._snap["status"] = status
            self._snap["finishedAt"] = time.time()
            self._append_event_locked({"type": "run_status", "status": status})

    def _append_event_locked(self, evt: dict):
        self._seq += 1
        evt["seq"] = self._seq
        evt["runId"] = self._snap["runId"]
        evt.setdefault("ts", time.time())
        self._events.append(evt)
        self._snap["seq"] = self._seq

    # ---- 接口侧读操作 -----------------------------------------------------
    def snapshot(self):
        with self._lock:
            return json_clone(self._snap) if self._snap else None

    def events_since(self, run_id, last_seq: int):
        """返回 (mode, payloads)。

        mode='events'：调用方的 run 仍为当前 run 且缺口在缓冲内，逐条补；
        mode='snapshot'：跨 run / 缺口丢失 / 首次连接，整份快照重放。
        """
        with self._lock:
            if not self._snap:
                return "snapshot", None
            if run_id != self._snap["runId"]:
                return "snapshot", self.snapshot()
            if last_seq < 0 or last_seq >= self._seq:
                return "snapshot", self.snapshot()
            buffered = list(self._events)
            if buffered[0]["seq"] > last_seq + 1:
                return "snapshot", self.snapshot()  # 缺口已被环形缓冲覆盖
            missed = [e for e in buffered if e["seq"] > last_seq]
            return "events", missed


def json_clone(obj):
    import copy
    return copy.deepcopy(obj)


store = ExecutionStore()
