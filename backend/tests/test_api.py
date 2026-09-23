import asyncio

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app, broker, presentations, store


@pytest.fixture(autouse=True)
def reset_state():
    auth.SESSIONS.clear()
    presentations.active = None
    broker._events.clear()
    broker._seq = 0
    broker._subs.clear()
    store.state = store._idle_state()
    store.running = False
    yield
    auth.SESSIONS.clear()
    presentations.active = None


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": username})
    assert r.status_code == 200, r.text
    d = r.json()
    return {"Authorization": f"Bearer {d['token']}"}


def test_requires_login(client):
    assert client.get("/api/execution").status_code == 401
    assert client.post("/api/run", json={"workflowId": 1}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code == 401


def test_viewer_cannot_run_with_reason(client):
    h = login(client, "viewer")
    r = client.post("/api/run", json={"workflowId": 1, "workers": 2}, headers=h)
    assert r.status_code == 403
    assert "只读成员" in r.json()["detail"]
    # 创建工作流同样被挡
    assert client.post("/api/workflow", json={"name": "x"}, headers=h).status_code == 403


def test_operator_can_run(client):
    h = login(client, "operator")
    r = client.post("/api/run", json={"workflowId": 1, "workers": 3}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["execution"]["phase"] == "running"
    # 重复执行 -> 409
    r2 = client.post("/api/run", json={"workflowId": 1, "workers": 3}, headers=h)
    assert r2.status_code == 409


def test_visibility_contract_fields_only(client):
    h = login(client, "operator")
    client.post("/api/run", json={"workflowId": 1, "workers": 3}, headers=h)
    snap = client.get("/api/execution", headers=h).json()["execution"]
    assert "seq" in client.get("/api/execution", headers=h).json()
    allowed = {"workflow", "logs", "circuitBreakers", "completed", "phase",
               "runSeq", "startedAt", "updatedAt", "stats"}
    assert set(snap) <= allowed
    assert "_durations" not in snap
    wf = snap["workflow"]
    assert set(wf) <= {"id", "name", "nodes", "edges"}
    assert set(wf["nodes"][0]) <= {"id", "name", "deps", "x", "y",
                                   "status", "startTime", "endTime", "retries"}
    assert snap["stats"]["total"] == 11
    assert snap["stats"]["running"] >= 1


def test_presentation_lifecycle_and_multi_viewers(client):
    op = login(client, "operator")
    v = login(client, "viewer")

    # viewer 不能发起？—— 需求只要求大屏只读；登录成员都可投屏，验证 operator 发起
    r = client.post("/api/presentation/start", headers=op)
    assert r.status_code == 200, r.text
    d = r.json()
    screen_token = d["screenToken"]
    pid = d["presentation"]["id"]
    assert d["presentation"]["presenter"]["username"] == "operator"

    # 同时只能有一块大屏
    r2 = client.post("/api/presentation/start", headers=v)
    assert r2.status_code == 409 and "正在投屏" in r2.json()["detail"]

    # 大屏令牌被识别为 scope=screen
    screen_h = {"Authorization": f"Bearer {screen_token}"}
    me = client.get("/api/me", headers=screen_h).json()
    assert me["scope"] == "screen" and me["canWrite"] is False

    # 投屏身份尝试重跑 -> 403 且理由说明只读
    r = client.post("/api/run", json={"workflowId": 1}, headers=screen_h)
    assert r.status_code == 403 and "投屏" in r.json()["detail"]
    r = client.post("/api/workflow", json={"name": "x"}, headers=screen_h)
    assert r.status_code == 403

    # 大屏可读执行快照
    assert client.get("/api/execution", headers=screen_h).status_code == 200

    # viewer 不能结束别人的投屏
    r = client.post("/api/presentation/stop", headers=v)
    assert r.status_code == 403

    # 投屏人结束投放后，大屏令牌被吊销，普通页面权限不受影响
    assert client.post("/api/presentation/stop", headers=op).status_code == 200
    assert client.get("/api/me", headers=screen_h).status_code == 401
    assert client.get("/api/me", headers=op).status_code == 200
    # operator 普通页面仍可发起执行（权限恢复原样）
    assert client.post("/api/run", json={"workflowId": 1}, headers=op).status_code == 200


def test_presence_via_ws_multiple_viewers(client):
    op = login(client, "operator")
    v = login(client, "viewer")
    start = client.post("/api/presentation/start", headers=op).json()
    screen_token = start["screenToken"]
    pid = start["presentation"]["id"]

    with client.websocket_connect(f"/ws?token={screen_token}") as screen_ws, \
         client.websocket_connect(f"/ws?token=" + _raw_token(v)) as v_ws:
        screen_ws.send_json({"type": "hello", "lastSeq": 0})
        pres = _recv_until(screen_ws, "presence")
        names = [m["username"] for m in pres["data"]["presentation"]["members"]]
        assert "operator" in names

        v_ws.send_json({"type": "hello", "lastSeq": 0, "watchPresentation": True})
        # viewer 加入后名单广播，两条连接上都应能收到含两人的 presence
        pres2 = _recv_until_members(v_ws, {"operator", "viewer"})
        assert pres2["data"]["presentation"]["viewerCount"] == 1
        _recv_until_members(screen_ws, {"operator", "viewer"})

    # 两个连接关闭后，viewer 自动离名单（投屏人保留）
    with client.websocket_connect(f"/ws?token={screen_token}") as ws2:
        ws2.send_json({"type": "hello", "lastSeq": 0})
        pres3 = _recv_until_members(ws2, {"operator"}, exact=True)
        assert {m["username"] for m in pres3["data"]["presentation"]["members"]} == {"operator"}


def test_ws_unauthenticated_and_replay(client):
    with client.websocket_connect("/ws?token=bad") as ws:
        # 服务端在校验 token 后以 4401 关闭连接
        with pytest.raises(Exception) as ei:
            ws.receive_json()
        assert getattr(ei.value, "code", 4401) in (4401, 1005, 1006)

    op = login(client, "operator")
    token = _raw_token(op)
    client.post("/api/run", json={"workflowId": 1, "workers": 3}, headers=op)

    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({"type": "hello", "lastSeq": 0})
        first = ws.receive_json()
        assert first["type"] in ("presence",)
        snap = _recv_until(ws, "snapshot")
        assert snap["data"]["phase"] == "running"
        seq = snap["seq"]
        # 心跳
        ws.send_json({"type": "ping", "at": 1})
        pong = ws.receive_json()
        assert pong["type"] == "pong"

    # 模拟断线重连：带上 lastSeq，应只收到增量 execution 事件
    with client.websocket_connect(f"/ws?token={token}") as ws2:
        ws2.send_json({"type": "hello", "lastSeq": seq})
        ws2.receive_json()  # presence
        evt = ws2.receive_json()
        assert evt["type"] == "execution" and evt["seq"] > seq


def test_screen_ws_closed_when_presentation_ends(client):
    op = login(client, "operator")
    start = client.post("/api/presentation/start", headers=op).json()
    screen_token = start["screenToken"]
    with client.websocket_connect(f"/ws?token={screen_token}") as ws:
        ws.send_json({"type": "hello", "lastSeq": 0})
        ws.receive_json()  # presence
        ws.receive_json()  # snapshot
        # 投屏人在普通页面结束投放
        assert client.post("/api/presentation/stop", headers=op).status_code == 200
        end = _recv_until(ws, "presentation_end")
        assert "结束投放" in end["data"]["reason"]


def _raw_token(headers):
    return headers["Authorization"].removeprefix("Bearer ")


def _recv_until(ws, mtype, timeout=5):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = ws.receive_json()
        if msg["type"] == mtype:
            return msg
    raise AssertionError(f"未收到 {mtype} 事件")


def _recv_until_members(ws, expected: set, exact: bool = False):
    for _ in range(50):
        msg = ws.receive_json()
        if msg.get("type") == "presence" and msg["data"]["presentation"]:
            names = {m["username"] for m in msg["data"]["presentation"]["members"]}
            if (names == expected) if exact else (expected <= names):
                return msg
    raise AssertionError(f"未收到成员为 {expected} 的 presence")
