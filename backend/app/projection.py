"""只读视图投影：普通页面与大屏对同一份执行只暴露这里声明的字段。

两处入口（/api/state、/ws、/ws/screen）都必须经过 project_snapshot()，
保证同一块大屏与普通页面看到的可见范围完全一致。
修改可见字段 = 先改 CONTRACT，再改投影，二者即“事先约定”。
"""

# v1 字段约定：大屏只读成员可见的字段清单
FIELD_CONTRACT = {
    "version": "v1",
    "description": "执行监控只读视图字段约定（普通页面与大屏一致）",
    "actions": ["view"],
    "fields": {
        "run": ["runId", "status", "workers", "strategy", "startedAt",
                "finishedAt", "seq"],
        "workflow": ["id", "name"],
        "node": ["id", "name", "status", "retries", "startTime", "endTime"],
        "edge": ["[sourceId, targetId]"],
        "log": ["taskId", "status", "timestamp", "message"],
        "circuitBreaker": ["taskId", "failureCount", "state", "cooldownUntil"],
    },
    "hidden": [
        "durations（任务模拟耗时等内部编排参数，只读成员不可见）",
        "will_fail / runtime（调度器内部模拟字段）",
    ],
}

# 节点允许透出的键（同时剔除 x/y 坐标等非约定字段）
_NODE_KEYS = ("id", "name", "status", "retries", "startTime", "endTime")
_LOG_KEYS = ("taskId", "status", "timestamp", "message")
_CB_KEYS = ("taskId", "failureCount", "state", "cooldownUntil")


def project_snapshot(snap: dict) -> dict:
    """把内部快照裁剪为只读投影。snap 为 None 时返回 IDLE 空视图。"""
    if not snap:
        return {"run": None, "status": "IDLE", "workflow": None,
                "nodes": [], "edges": [], "logs": [], "circuitBreakers": [],
                "seq": 0, "completed": False}
    wf = snap.get("workflow") or {}
    return {
        "run": {
            "runId": snap.get("runId"),
            "status": snap.get("status", "IDLE"),
            "workers": snap.get("workers"),
            "strategy": snap.get("strategy"),
            "startedAt": snap.get("startedAt"),
            "finishedAt": snap.get("finishedAt"),
            "seq": snap.get("seq", 0),
        },
        "status": snap.get("status", "IDLE"),
        "completed": snap.get("status") in ("SUCCESS", "FAILED"),
        "workflow": {"id": wf.get("id"), "name": wf.get("name")},
        "nodes": [{k: n.get(k) for k in _NODE_KEYS} for n in snap.get("nodes", [])],
        "edges": [[u, v] for u, v in snap.get("edges", [])],
        "logs": [{k: l.get(k) for k in _LOG_KEYS} for l in snap.get("logs", [])],
        "circuitBreakers": [{k: c.get(k) for k in _CB_KEYS}
                            for c in snap.get("circuitBreakers", [])],
        "seq": snap.get("seq", 0),
    }


def project_event(evt: dict) -> dict:
    """增量事件投影：node 级事件同样走字段白名单。"""
    if evt.get("type") == "node_update":
        node = evt.get("node") or {}
        return {"type": "event", "seq": evt["seq"], "runId": evt.get("runId"),
                "kind": "node_update", "ts": evt.get("ts"),
                "node": {k: node.get(k) for k in _NODE_KEYS}}
    if evt.get("type") == "log":
        log = evt.get("log") or {}
        return {"type": "event", "seq": evt["seq"], "runId": evt.get("runId"),
                "kind": "log", "ts": evt.get("ts"),
                "log": {k: log.get(k) for k in _LOG_KEYS}}
    if evt.get("type") == "breaker":
        cb = evt.get("breaker") or {}
        return {"type": "event", "seq": evt["seq"], "runId": evt.get("runId"),
                "kind": "breaker", "ts": evt.get("ts"),
                "breaker": {k: cb.get(k) for k in _CB_KEYS}}
    if evt.get("type") == "run_status":
        return {"type": "event", "seq": evt["seq"], "runId": evt.get("runId"),
                "kind": "run_status", "ts": evt.get("ts"),
                "status": evt.get("status")}
    # 未知事件原样只带最小信封
    return {"type": "event", "seq": evt.get("seq"), "runId": evt.get("runId"),
            "kind": evt.get("type")}
