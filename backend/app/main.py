import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import auth
from .dag import generate_dag_workflow
from .engine import Broker, ExecutionStore
from .presentation import PresentationRegistry
from .visibility import PUBLIC_CONTRACT

TIME_SCALE = float(os.environ.get("DAG_TIME_SCALE", "1.0"))
FAILURE_RATE = float(os.environ.get("DAG_FAILURE_RATE", "0.12"))

broker = Broker()
store = ExecutionStore(broker, time_scale=TIME_SCALE, failure_rate=FAILURE_RATE)
presentations = PresentationRegistry(broker)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def prune_loop():
        while True:
            await asyncio.sleep(10)
            presentations.prune_stale()
    task = asyncio.create_task(prune_loop())
    yield
    task.cancel()


app = FastAPI(title="DAG Workflow Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class LoginRequest(BaseModel):
    username: str
    password: str


class WorkflowCreate(BaseModel):
    name: str = "data-pipeline"


class RunRequest(BaseModel):
    workflowId: int
    workers: int = 3
    strategy: str = "fifo"


# ---------------- 身份 ----------------

@app.post("/api/auth/login")
def login(req: LoginRequest):
    s = auth.login(req.username, req.password)
    return {"token": s.token, "user": auth.public_session(s)}


@app.get("/api/me")
def me(s: auth.Session = Depends(auth.require_session)):
    return auth.public_session(s)


@app.get("/api/contract")
def contract(s: auth.Session = Depends(auth.require_session)):
    """只读视图可见字段约定（普通页面与大屏一致）。"""
    return PUBLIC_CONTRACT


# ---------------- 工作流 / 执行 ----------------

@app.post("/api/workflow")
def create_workflow(req: WorkflowCreate, s: auth.Session = Depends(auth.require_write)):
    dag = generate_dag_workflow(req.name)
    return {"id": 1, "name": req.name, "nodes": dag["nodes"], "edges": dag["edges"]}


@app.post("/api/run")
async def run_workflow(req: RunRequest, s: auth.Session = Depends(auth.require_write)):
    if store.running:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="当前有任务正在执行，请等待结束后再发起")
    asyncio.create_task(store.run(req.workflowId, req.workers, req.strategy))
    # 等待引擎发出首个事件，保证调用方立刻能看到 running 快照
    await asyncio.sleep(0.05)
    return {"seq": broker.latest_seq, "execution": store.snapshot()}


@app.get("/api/execution")
def execution(s: auth.Session = Depends(auth.require_session)):
    """当前执行快照；大屏与普通页面共用同一序列化，可见范围一致。"""
    return {"seq": broker.latest_seq, "execution": store.snapshot()}


# ---------------- 投屏 ----------------

@app.post("/api/presentation/start")
def presentation_start(s: auth.Session = Depends(auth.require_session)):
    if s.scope == "screen":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="大屏视图不能再次发起投屏")
    try:
        p = presentations.start(s)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    screen = auth.issue_session(s.username, s.role, s.display_name,
                                scope="screen", presentation_id=p.id)
    return {"presentation": p.public(), "screenToken": screen.token,
            "screenUrl": f"#/screen?token={screen.token}"}


@app.post("/api/presentation/stop")
def presentation_stop(s: auth.Session = Depends(auth.require_session)):
    try:
        p = presentations.stop(s)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    return {"ok": True, "presentationId": p.id}


@app.get("/api/presentation/active")
def presentation_active(s: auth.Session = Depends(auth.require_session)):
    return {"presentation": presentations.public()}


@app.post("/api/presentation/screen-token")
def presentation_screen_token(s: auth.Session = Depends(auth.require_session)):
    """投屏进行中时，为任意成员补开一块只读大屏（多人可同时观看同一份执行）。"""
    p = presentations.active
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前没有进行中的投屏")
    # 复用该成员已有的大屏令牌，避免重复堆积
    existing = next((t for t, sess in auth.SESSIONS.items()
                     if sess.scope == "screen" and sess.presentation_id == p.id
                     and sess.username == s.username), None)
    token = existing or auth.issue_session(
        s.username, s.role, s.display_name, scope="screen", presentation_id=p.id).token
    return {"presentation": p.public(), "screenToken": token,
            "screenUrl": f"#/screen?token={token}"}


# ---------------- WebSocket ----------------

WS_POLICY_VIOLATION = 4403
WS_UNAUTHORIZED = 4401
HEARTBEAT_TTL = 20.0


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    session = auth.resolve(ws.query_params.get("token"))
    if session is None:
        await ws.close(code=WS_UNAUTHORIZED)
        return

    queue = broker.subscribe()
    joined_presentation = False
    reader_alive = True
    force_close_reason = None

    async def reader():
        nonlocal reader_alive
        try:
            while True:
                msg = await ws.receive_json()
                mtype = msg.get("type")
                if mtype == "ping":
                    presentations.heartbeat(session)
                    await ws.send_json({"type": "pong", "at": msg.get("at")})
                elif mtype == "hello":
                    await handle_hello(msg)
        except Exception:
            reader_alive = False

    async def handle_hello(msg: dict) -> None:
        nonlocal joined_presentation, force_close_reason
        last_seq = int(msg.get("lastSeq", 0))
        active = presentations.active

        # 大屏连接必须绑定到进行中的投屏
        if session.scope == "screen":
            if active is None or session.presentation_id != active.id:
                force_close_reason = "投屏已结束或不存在，大屏只读视图已关闭"
                await ws.send_json({"type": "presentation_end",
                                    "data": {"reason": force_close_reason}})
                return
            presentations.join(session)
            joined_presentation = True
        elif msg.get("watchPresentation") and active is not None:
            # 普通页面成员选择观看同一块大屏
            presentations.join(session)
            joined_presentation = True

        # 在线名单快照
        await ws.send_json({"type": "presence",
                            "data": {"presentation": presentations.public()}})

        # 断线重连：优先回放缺失事件，缺口过大再下发全量快照
        missed, need_snapshot = broker.replay(last_seq)
        if need_snapshot:
            await ws.send_json({"type": "snapshot", "seq": broker.latest_seq,
                                "data": store.snapshot()})
        else:
            for evt in missed:
                await ws.send_json(evt)

    try:
        reader_task = asyncio.create_task(reader())
        while reader_alive and force_close_reason is None:
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            # 大屏只接收本次投屏生命周期内的信息
            if session.scope == "screen" and evt["type"] == "presentation_end":
                await ws.send_json(evt)
                break
            await ws.send_json(evt)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        reader_task.cancel()
        broker.unsubscribe(queue)
        if joined_presentation:
            presentations.leave(session)
