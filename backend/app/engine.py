"""执行引擎：状态存储 + 事件总线 + asyncio 模拟执行器。

- 服务端始终保存最近一次执行的完整状态，新连接/重连都能拿到当前进展；
- 每次状态变化带单调递增 seq，WS 客户端带 lastSeq 重连时回放缺失事件，
  缺口超出保留窗口则下发完整快照（type=snapshot）；
- 引擎完全运行在 FastAPI 的事件循环上，避免跨线程调度问题。
"""
import asyncio
import random
import time
from collections import defaultdict, deque

from .dag import generate_dag_workflow
from .visibility import public_execution

EVENT_WINDOW = 2000
FAILURE_THRESHOLD = 3
MAX_RETRIES = 3


class Broker:
    def __init__(self):
        self._subs: set[asyncio.Queue] = set()
        self._events: deque[dict] = deque(maxlen=EVENT_WINDOW)
        self._seq = 0

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, event_type: str, data: dict) -> dict:
        self._seq += 1
        evt = {"type": event_type, "seq": self._seq, "data": data, "at": time.time()}
        self._events.append(evt)
        dead = []
        for q in self._subs:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subs.discard(q)
        return evt

    def replay(self, last_seq: int) -> tuple[list[dict], bool]:
        """返回 (缺失事件, 是否缺口过大需要全量快照)。"""
        if not self._events:
            return [], last_seq > 0
        oldest = self._events[0]["seq"]
        if last_seq <= 0:
            return [], True
        if last_seq < oldest - 1:
            return [], True
        missed = [e for e in self._events if e["seq"] > last_seq and e["type"] == "execution"]
        return missed, False

    @property
    def latest_seq(self) -> int:
        return self._seq


class ExecutionStore:
    def __init__(self, broker: Broker, time_scale: float = 1.0,
                 failure_rate: float = 0.12, tick: float = 0.3):
        self.broker = broker
        self.time_scale = time_scale
        self.failure_rate = failure_rate
        self.tick = tick
        self.lock = asyncio.Lock()
        self.running = False
        self.state: dict = self._idle_state()

    def _idle_state(self) -> dict:
        return {
            "workflow": None, "logs": [], "circuitBreakers": [],
            "completed": False, "phase": "idle", "runSeq": 0,
            "startedAt": None, "updatedAt": None,
        }

    def snapshot(self) -> dict:
        return public_execution(self.state)

    def _emit(self) -> None:
        self.state["updatedAt"] = time.time()
        self.broker.publish("execution", self.snapshot())

    async def run(self, workflow_id: int, workers: int, strategy: str) -> dict:
        async with self.lock:
            if self.running:
                raise RuntimeError("当前有任务正在执行，请等待结束后再发起")
            self.running = True
        try:
            await self._execute(workflow_id, workers, strategy)
        finally:
            self.running = False

    async def _execute(self, workflow_id: int, workers: int, strategy: str) -> None:
        dag = generate_dag_workflow("workflow")
        nodes = dag["nodes"]
        durations = dag["durations"]
        edges = dag["edges"]
        in_degree = defaultdict(int)
        adj = defaultdict(list)
        for u, v in edges:
            in_degree[v] += 1
            adj[u].append(v)

        ready: deque[str] = deque([n["id"] for n in nodes if in_degree[n["id"]] == 0])
        node_map = {n["id"]: n for n in nodes}
        logs = []
        cb_state = defaultdict(lambda: {"failureCount": 0, "state": "CLOSED", "cooldownUntil": 0.0})
        running_tasks: dict[str, dict] = {}
        completed = set()
        now = time.time()

        self.state = {
            "workflow": {"id": workflow_id, "name": "workflow", "nodes": nodes, "edges": edges},
            "logs": logs, "circuitBreakers": [], "completed": False,
            "phase": "running", "runSeq": (self.state.get("runSeq") or 0) + 1,
            "startedAt": now, "updatedAt": now,
        }
        logs.append({"taskId": "-", "status": "RUNNING", "timestamp": now,
                     "message": f"流水线开始执行（{workers} workers / {strategy}）"})
        self._emit()

        def cb_public():
            return [dict(taskId=k, **v) for k, v in cb_state.items() if v["failureCount"] > 0
                    or v["state"] != "CLOSED"]

        while ready or running_tasks:
            while ready and len(running_tasks) < workers:
                tid = ready.popleft()
                node = node_map[tid]
                cb = cb_state[tid]
                if cb["state"] == "OPEN" and time.time() < cb["cooldownUntil"]:
                    ready.appendleft(tid)
                    break
                if cb["state"] == "OPEN":
                    cb["state"] = "HALF_OPEN"

                node["status"] = "RUNNING"
                node["startTime"] = node["startTime"] or time.time()
                will_fail = random.random() < self.failure_rate
                runtime = durations.get(tid, 1.5) * random.uniform(0.7, 1.3) * self.time_scale
                running_tasks[tid] = {"end_time": time.time() + runtime, "will_fail": will_fail}
                logs.append({"taskId": tid, "status": "RUNNING", "timestamp": time.time(),
                             "message": f"开始执行 {node['name']}"})

            await asyncio.sleep(self.tick * self.time_scale)
            now = time.time()
            finished = []
            for tid, info in running_tasks.items():
                if now < info["end_time"]:
                    continue
                node = node_map[tid]
                if info["will_fail"] and node["retries"] < MAX_RETRIES:
                    node["retries"] += 1
                    node["status"] = "PENDING"
                    ready.appendleft(tid)
                    cb = cb_state[tid]
                    cb["failureCount"] += 1
                    logs.append({"taskId": tid, "status": "FAILED", "timestamp": now,
                                 "message": f"{node['name']} 执行失败，重试 {node['retries']}/{MAX_RETRIES}"})
                    if cb["failureCount"] >= FAILURE_THRESHOLD:
                        cb["state"] = "OPEN"
                        cb["cooldownUntil"] = now + 5 * self.time_scale
                        logs.append({"taskId": tid, "status": "CIRCUIT_OPEN", "timestamp": now,
                                     "message": f"{node['name']} 熔断：连续失败 {FAILURE_THRESHOLD} 次，冷却中"})
                else:
                    node["status"] = "SUCCESS"
                    node["endTime"] = now
                    completed.add(tid)
                    cb_state[tid]["failureCount"] = 0
                    cb_state[tid]["state"] = "CLOSED"
                    logs.append({"taskId": tid, "status": "SUCCESS", "timestamp": now,
                                 "message": f"完成 {node['name']}"})
                    for next_tid in adj[tid]:
                        in_degree[next_tid] -= 1
                        if in_degree[next_tid] == 0:
                            ready.append(next_tid)
                finished.append(tid)
            for tid in finished:
                del running_tasks[tid]

            self.state["circuitBreakers"] = cb_public()
            self._emit()
            if len(completed) == len(nodes):
                break

        self.state["phase"] = "completed"
        self.state["completed"] = True
        logs.append({"taskId": "-", "status": "SUCCESS", "timestamp": time.time(),
                     "message": "整条流水线执行结束"})
        self._emit()
