"""只读视图可见字段约定（普通页面与大屏共用同一份白名单）。

设计约定：
- 只读成员（viewer 角色）与大屏投屏视图可见的字段事先约定在下方 PUBLIC_CONTRACT；
- 普通页面与大屏对同一份执行使用同一个 public_execution() 序列化，
  保证两处可见范围完全一致，区别只在“能否操作”，不在“能看到什么”；
- _durations、故障注入等引擎内部字段不对任何客户端开放。
"""
from typing import Any

LOG_TAIL_LIMIT = 50

PUBLIC_CONTRACT = {
    "execution": [
        "workflow", "logs", "circuitBreakers", "completed",
        "phase", "runSeq", "startedAt", "updatedAt", "stats",
    ],
    "workflow": ["id", "name", "nodes", "edges"],
    "node": ["id", "name", "deps", "x", "y", "status", "startTime", "endTime", "retries"],
    "log": ["taskId", "status", "timestamp", "message"],
    "circuitBreaker": ["taskId", "failureCount", "state", "cooldownUntil"],
    "stats": [
        "total", "pending", "running", "success", "failed",
        "progressPercent", "elapsedSeconds",
    ],
}

PHASES = ("idle", "running", "completed")


def _pick(src: dict, keys: list[str]) -> dict:
    return {k: src.get(k) for k in keys if k in src}


def public_workflow(workflow: dict | None) -> dict | None:
    if not workflow:
        return None
    return {
        "id": workflow["id"],
        "name": workflow["name"],
        "nodes": [_pick(n, PUBLIC_CONTRACT["node"]) for n in workflow.get("nodes", [])],
        "edges": [list(e) for e in workflow.get("edges", [])],
    }


def public_execution(state: dict) -> dict[str, Any]:
    """把引擎内部状态序列化为对外只读视图（唯一出口，普通页/大屏一致）。"""
    nodes = (state.get("workflow") or {}).get("nodes") or []
    counts = {"PENDING": 0, "RUNNING": 0, "SUCCESS": 0, "FAILED": 0, "TIMEOUT": 0}
    for n in nodes:
        counts[n.get("status", "PENDING")] = counts.get(n.get("status", "PENDING"), 0) + 1
    total = len(nodes)
    done = counts["SUCCESS"]
    progress = round(done * 100 / total, 1) if total else 0.0
    started_at = state.get("startedAt")
    updated_at = state.get("updatedAt")
    elapsed = round(updated_at - started_at, 2) if started_at and updated_at else None

    return {
        "workflow": public_workflow(state.get("workflow")),
        "logs": [_pick(l, PUBLIC_CONTRACT["log"]) for l in state.get("logs", [])[-LOG_TAIL_LIMIT:]],
        "circuitBreakers": [
            _pick(cb, PUBLIC_CONTRACT["circuitBreaker"]) for cb in state.get("circuitBreakers", [])
        ],
        "completed": bool(state.get("completed")),
        "phase": state.get("phase", "idle"),
        "runSeq": state.get("runSeq", 0),
        "startedAt": started_at,
        "updatedAt": updated_at,
        "stats": {
            "total": total,
            "pending": counts["PENDING"],
            "running": counts["RUNNING"],
            "success": counts["SUCCESS"],
            "failed": counts["FAILED"] + counts["TIMEOUT"],
            "progressPercent": progress,
            "elapsedSeconds": elapsed,
        },
    }
