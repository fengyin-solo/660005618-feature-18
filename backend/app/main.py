import asyncio
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import workflow as wf
from .authz import MEMBERS, require_member, assert_can_run
from .projection import FIELD_CONTRACT, project_snapshot, project_event
from .screens import sessions
from .store import store
from .workflow import generate_dag_workflow, start_execution
from .wsmanager import manager

app = FastAPI(title="DAG Workflow Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

_RUN_ID = 0
_WF_ID = 0


class WorkflowCreate(BaseModel):
    name: str = "data-pipeline"


class RunRequest(BaseModel):
    workflowId: int
    workers: int = 3
    strategy: str = "fifo"


@app.on_event("startup")
async def _startup():
    # 捕获主事件循环，供后台执行线程广播使用
    wf.MAIN_LOOP = asyncio.get_event_loop()

    async def reaper():
        while True:
            await asyncio.sleep(5)
            for evt in sessions.reap():
                targets = manager.screen_sockets(evt["code"])
                if evt["type"] == "session_ended":
                    msg = {"type": "session_ended", "code": evt["code"],
                           "reason": evt["reason"]}
                else:
                    s = sessions.get(evt["code"])
                    msg = evt if s is None else {**evt, "session": sessions.public(s)}
                for ws in targets:
                    await manager.send_to(ws, msg)

    asyncio.create_task(reaper())


# ---------- 只读接口（operator / viewer 均可） ------------------------------

@app.get("/api/members")
def list_members():
    return {"members": list(MEMBERS.values())}


@app.get("/api/contract")
def field_contract():
    """大屏只读成员可见字段的事先约定（普通页面与大屏共用）。"""
    return FIELD_CONTRACT


@app.get("/api/state")
def current_state(member: dict = Depends(require_member)):
    return project_snapshot(store.snapshot())


@app.get("/api/screen/active")
def active_screen(member: dict = Depends(require_member)):
    """当前成员正在投屏的会话（普通页据此锁定/恢复操作按钮）。"""
    s = sessions.active_session_of(member["id"])
    return {"session": sessions.public(s) if s else None}


# ---------- 变更接口（受权限闸门约束） --------------------------------------

@app.post("/api/workflow")
def create_workflow(req: WorkflowCreate,
                    member: dict = Depends(require_member),
                    x_surface: str = Header(default="page")):
    assert_can_run(member, x_surface,
                   sessions.active_session_of(member["id"]) is not None)
    global _WF_ID
    _WF_ID += 1
    nodes, edges, _durations = generate_dag_workflow(req.name)
    # 定义也只返回约定字段（durations 等内部模拟参数不外泄）
    return {"id": _WF_ID, "name": req.name,
            "nodes": [{k: n[k] for k in
                       ("id", "name", "deps", "x", "y", "status",
                        "startTime", "endTime", "retries")} for n in nodes],
            "edges": edges}


@app.post("/api/run")
def run_workflow(req: RunRequest,
                 member: dict = Depends(require_member),
                 x_surface: str = Header(default="page")):
    assert_can_run(member, x_surface,
                   sessions.active_session_of(member["id"]) is not None)
    cur = store.snapshot()
    if cur and cur.get("status") == "RUNNING":
        raise HTTPException(status_code=409, detail={
            "code": "already_running",
            "message": f"已有执行中的流水线（run {cur.get('runId')}），请等待结束后再重跑"})
    global _RUN_ID
    _RUN_ID += 1
    nodes, edges, _ = generate_dag_workflow("workflow")
    workflow_def = {"id": req.workflowId, "name": "workflow",
                    "nodes": nodes, "edges": edges}
    start_execution(_RUN_ID, workflow_def, req.workers, req.strategy)
    return {**project_snapshot(store.snapshot()), "runId": _RUN_ID}


# ---------- 投屏会话（任何角色可投；投屏只锁定自己的执行权限） --------------

@app.post("/api/screen/start")
async def screen_start(member: dict = Depends(require_member)):
    s = sessions.start(member["id"])
    return {"session": sessions.public(s)}


@app.post("/api/screen/{code}/stop")
async def screen_stop(code: str, member: dict = Depends(require_member)):
    result = sessions.stop(code, member["id"])
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "no_session",
                                                     "message": "投屏会话不存在或已结束"})
    if result is False:
        raise HTTPException(status_code=403, detail={
            "code": "not_presenter",
            "message": "只有投屏人本人可以结束投屏"})
    for ws in manager.screen_sockets(code):
        await manager.send_to(ws, {"type": "session_ended", "code": code,
                                   "reason": "stopped_by_presenter"})
    return {"session": sessions.public(result)}


# ---------- WebSocket -------------------------------------------------------

async def _hello_sync(ws):
    """首个文本帧约定为 {"type":"hello","runId":..,"lastSeq":..}。

    断线重连补进展：缺口在事件缓冲内则逐条重放后对齐快照；
    跨 run / 缺口丢失 / 首次连接则整份快照重放。
    """
    run_id, last_seq = None, -1
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=15)
        msg = json.loads(raw)
        run_id = msg.get("runId")
        last_seq = int(msg.get("lastSeq", -1))
    except Exception:
        pass

    if run_id is None or last_seq < 0:
        await manager.send_to(ws, {"type": "snapshot",
                                   **project_snapshot(store.snapshot())})
        return

    mode, payload = store.events_since(run_id, last_seq)
    if mode == "events":
        for evt in payload:
            await manager.send_to(ws, project_event(evt))
        await manager.send_to(ws, {"type": "snapshot",
                                   **project_snapshot(store.snapshot())})
    else:
        await manager.send_to(ws, {"type": "snapshot",
                                   **project_snapshot(payload)})


@app.websocket("/ws")
async def ws_page(ws: WebSocket, member_id: str = "u-alice"):
    if member_id not in MEMBERS:
        await ws.close(code=4401)
        return
    await manager.connect(ws, member_id, "page")
    try:
        await _hello_sync(ws)
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=30)
                msg = json.loads(raw)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            except Exception:
                continue
            if msg.get("type") == "ping":
                await manager.send_to(ws, {"type": "pong"})
    finally:
        manager.disconnect(ws)


@app.websocket("/ws/screen")
async def ws_screen(ws: WebSocket, code: str, member_id: str = "u-alice"):
    if member_id not in MEMBERS:
        await ws.close(code=4401)
        return
    s = sessions.get(code)
    if not s:
        await ws.close(code=4404)
        return
    await manager.connect(ws, member_id, "screen", code)
    is_presenter = (s["presenterId"] == member_id)
    try:
        if is_presenter:
            sessions.touch_presenter(code)
        else:
            s, _ = sessions.upsert_watcher(code, member_id)

        await manager.send_to(ws, {"type": "presence", "code": code,
                                   "session": sessions.public(s)})
        await _hello_sync(ws)

        async def announce():
            for other in manager.screen_sockets(code):
                if other is ws:
                    continue
                await manager.send_to(other, {"type": "presence", "code": code,
                                              "session": sessions.public(s)})

        await announce()

        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=30)
                msg = json.loads(raw)
            except asyncio.TimeoutError:
                msg = {"type": "ping"}
            except WebSocketDisconnect:
                break
            except Exception:
                continue
            if msg.get("type") == "ping":
                if is_presenter:
                    sessions.touch_presenter(code)
                else:
                    sessions.touch_watcher(code, member_id)
                await manager.send_to(ws, {"type": "pong"})
    finally:
        manager.disconnect(ws)
        cur = sessions.get(code)
        if cur:
            if is_presenter:
                sessions.mark_presenter_disconnected(code)
            else:
                sessions.remove_watcher(code, member_id)
            for other in manager.screen_sockets(code):
                await manager.send_to(other, {"type": "presence", "code": code,
                                              "session": sessions.public(cur)})
