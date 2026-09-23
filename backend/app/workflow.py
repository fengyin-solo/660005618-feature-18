"""DAG 定义生成与后台执行线程。

执行线程只更新 ExecutionStore 并广播事件；
事件循环引用在启动时捕获（修复旧实现在子线程调用 asyncio.get_event_loop()
拿不到主循环、实时推送静默失效的问题）。
"""
import random
import threading
import time
from collections import defaultdict, deque

from .store import store
from .wsmanager import manager

MAIN_LOOP = None  # 由 main.on_startup 注入
MAX_RETRIES = 3


def generate_dag_workflow(name: str):
    nodes = [
        {"id": "extract", "name": "数据提取", "deps": [], "duration": 2.0},
        {"id": "validate", "name": "数据校验", "deps": ["extract"], "duration": 1.5},
        {"id": "clean_a", "name": "清洗分支A", "deps": ["validate"], "duration": 1.8},
        {"id": "clean_b", "name": "清洗分支B", "deps": ["validate"], "duration": 1.2},
        {"id": "transform", "name": "数据转换", "deps": ["clean_a"], "duration": 3.0},
        {"id": "enrich", "name": "数据增强", "deps": ["clean_a", "clean_b"], "duration": 2.0},
        {"id": "aggregate", "name": "聚合计算", "deps": ["transform", "enrich"], "duration": 2.5},
        {"id": "quality", "name": "质量检查", "deps": ["aggregate"], "duration": 1.0},
        {"id": "export_db", "name": "入库", "deps": ["quality"], "duration": 1.8},
        {"id": "export_report", "name": "报表生成", "deps": ["quality"], "duration": 2.2},
        {"id": "notify", "name": "通知", "deps": ["export_db", "export_report"], "duration": 0.5},
    ]
    positions = [
        (0, 0), (0, 1), (-1, 2), (1, 2), (-1, 3),
        (0.5, 3), (-0.3, 4), (-0.3, 5), (-1, 6), (0.5, 6), (-0.3, 7)
    ]
    for i, n in enumerate(nodes):
        n["x"] = positions[i][0] * 2.5 + 2.5
        n["y"] = positions[i][1] * 0.9
        n["status"] = "PENDING"
        n["retries"] = 0
        n["startTime"] = None
        n["endTime"] = None

    edges = []
    for n in nodes:
        for d in n["deps"]:
            edges.append([d, n["id"]])

    # 注意：durations 是内部模拟参数，不进入只读投影
    return nodes, edges, {n["id"]: n["duration"] for n in nodes}


def _publish():
    """执行线程把当前快照推给全部连接（页面/大屏同一份投影）。"""
    if MAIN_LOOP is None:
        return
    try:
        manager.run_coroutine(MAIN_LOOP, manager.broadcast_execution(store))
    except RuntimeError:
        pass


def start_execution(run_id: int, workflow: dict, workers: int, strategy: str):
    store.reset(run_id, workflow, workers, strategy)
    _publish()
    t = threading.Thread(target=execute_workflow,
                         args=(run_id, workflow, workers, strategy), daemon=True)
    t.start()
    return t


def execute_workflow(run_id, workflow, workers, strategy):
    nodes = [dict(n) for n in workflow["nodes"]]
    edges = workflow["edges"]
    # 内部模拟参数从 workflow 定义单独获取（不经过只读投影）
    _, _, durations = generate_dag_workflow(workflow.get("name", "workflow"))

    in_degree = defaultdict(int)
    adj = defaultdict(list)
    for u, v in edges:
        in_degree[v] += 1
        adj[u].append(v)

    ready = deque([n["id"] for n in nodes if in_degree[n["id"]] == 0])
    node_map = {n["id"]: n for n in nodes}
    cb_state = defaultdict(lambda: {"failureCount": 0, "state": "CLOSED",
                                    "cooldownUntil": 0})
    failure_threshold = 3
    running = {}          # tid -> {end_time, will_fail}
    completed, failed = set(), set()

    def log(task_id, status, message):
        store.add_log(task_id, status, message)

    def sync_node(tid):
        store.update_node(node_map[tid])

    # strategy 仅作展示与预留（FIFO/优先级/最大并发），当前统一 FIFO 出队
    _ = strategy

    while ready or running:
        now = time.time()
        # 启动可运行任务
        while ready and len(running) < workers:
            tid = ready.popleft()
            node = node_map[tid]
            cb = cb_state[tid]
            if cb["state"] == "OPEN" and now < cb["cooldownUntil"]:
                ready.appendleft(tid)
                break
            if cb["state"] == "OPEN":
                cb["state"] = "HALF_OPEN"

            node["status"] = "RUNNING"
            node["startTime"] = node["startTime"] or now
            will_fail = random.random() < 0.12
            runtime = durations.get(tid, 1.5) * random.uniform(0.7, 1.3)
            running[tid] = {"end_time": now + runtime, "will_fail": will_fail}
            log(tid, "RUNNING", f"开始执行 {node['name']}")
            sync_node(tid)

        # 等待最近一个任务到期（避免忙等），也至少 0.3s 推送一帧
        if running:
            wait = max(0.1, min(0.3, min(i["end_time"] for i in running.values()) - time.time()))
            time.sleep(wait)
        else:
            time.sleep(0.1)
        now = time.time()

        finished_tids = []
        for tid, info in running.items():
            if now < info["end_time"]:
                continue
            node = node_map[tid]
            cb = cb_state[tid]
            if info["will_fail"] and node["retries"] < MAX_RETRIES:
                node["retries"] += 1
                node["status"] = "PENDING"
                node["startTime"] = None
                ready.appendleft(tid)
                cb["failureCount"] += 1
                log(tid, "FAILED", f"{node['name']} 失败，重试 {node['retries']}/{MAX_RETRIES}")
                if cb["failureCount"] >= failure_threshold:
                    cb["state"] = "OPEN"
                    cb["cooldownUntil"] = now + 5
                    log(tid, "CIRCUIT_OPEN", f"熔断！连续 {failure_threshold} 次失败，冷却 5s")
                store.touch_breaker(tid, cb["failureCount"], cb["state"], cb["cooldownUntil"])
            elif info["will_fail"]:
                # 重试耗尽：明确 FAILED，不再悬空
                node["status"] = "FAILED"
                node["endTime"] = now
                failed.add(tid)
                cb["failureCount"] += 1
                log(tid, "FAILED", f"{node['name']} 重试 {MAX_RETRIES} 次后仍失败，终止")
                store.touch_breaker(tid, cb["failureCount"], cb["state"], cb["cooldownUntil"])
            else:
                node["status"] = "SUCCESS"
                node["endTime"] = now
                completed.add(tid)
                cb["failureCount"] = 0
                cb["state"] = "CLOSED"
                log(tid, "SUCCESS", f"完成 {node['name']}")
                store.touch_breaker(tid, 0, "CLOSED", 0)
                for next_tid in adj[tid]:
                    in_degree[next_tid] -= 1
                    if in_degree[next_tid] == 0:
                        ready.append(next_tid)
            sync_node(tid)
            finished_tids.append(tid)

        for tid in finished_tids:
            del running[tid]

        # 熔断器冷却结束自动 HALF_OPEN -> CLOSED 复位探测由下次调度处理
        _publish()

    # 有任务失败（含其永远拿不到依赖的下游）即整单 FAILED
    status = "SUCCESS" if len(completed) == len(nodes) else "FAILED"
    store.finish(status)
    _publish()
