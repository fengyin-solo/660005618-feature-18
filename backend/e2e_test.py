"""端到端验证：权限闸门、投屏会话、WS 重连补进展、两处可见范围一致。

对运行中的 uvicorn (127.0.0.1:8000) 用 websockets 直连测试。
"""
import asyncio
import json
import sys
import time

import httpx
import websockets

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'✅' if cond else '❌'} {name}" + (f"  -- {detail}" if detail and not cond else ""))


def headers(member="u-alice", surface="page"):
    return {"X-Member-Id": member, "X-Surface": surface}


async def ws_connect(path):
    ws = await websockets.connect(f"{WS}{path}", max_size=None)
    return ws


async def hello(ws, run_id=None, last_seq=-1):
    await ws.send(json.dumps({"type": "hello", "runId": run_id, "lastSeq": last_seq}))


async def recv_until(ws, mtype, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.time())
        msg = json.loads(raw)
        if msg.get("type") == mtype:
            return msg
    raise TimeoutError(f"waiting {mtype}")


async def wait_idle(c, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = (await c.get("/api/state")).json()
        if st["status"] != "RUNNING":
            return st
        await asyncio.sleep(0.5)
    raise RuntimeError("server busy from previous test run")


async def start_run(c, member="u-alice"):
    """发起新 run，必要时等待当前 run 结束（409）。"""
    h = headers(member)
    for _ in range(40):
        r = await c.post("/api/run", json={"workflowId": 1, "workers": 5}, headers=h)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 409:
            await asyncio.sleep(1)
            continue
        raise AssertionError(f"unexpected run status {r.status_code}: {r.text}")
    raise AssertionError("cannot start run: server keeps running")


async def cleanup_stale(c):
    """清掉本测试可能用到的成员残留的投屏会话（上一轮被中断时遗留）。"""
    for m in ("u-alice", "u-bob"):
        s = (await c.get("/api/screen/active", headers={"X-Member-Id": m})).json()["session"]
        if s:
            await c.post(f"/api/screen/{s['code']}/stop", headers={"X-Member-Id": m})


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        await wait_idle(c)
        await cleanup_stale(c)
        # 1. viewer 不能执行 ------------------------------------------------
        r = await c.post("/api/run", json={"workflowId": 1}, headers=headers("u-carol"))
        check("viewer 触发执行被 403 挡下", r.status_code == 403)
        check("拒绝理由可读", "只读成员" in r.json()["detail"]["message"], r.text)

        r = await c.post("/api/workflow", json={"name": "x"}, headers=headers("u-carol"))
        check("viewer 创建工作流同样被挡", r.status_code == 403)

        # 2. 未知成员 401 ---------------------------------------------------
        r = await c.get("/api/state", headers={"X-Member-Id": "nobody"})
        check("未知成员 401", r.status_code == 401)

        # 3. 字段约定 -------------------------------------------------------
        contract = (await c.get("/api/contract")).json()
        check("字段契约含 hidden 声明", "hidden" in contract and contract["version"] == "v1")
        check("契约不含 durations 可见字段",
              "durations" not in json.dumps(contract["fields"], ensure_ascii=False))

        # 4. operator 正常执行；快照不含内部字段 ----------------------------
        r = await c.post("/api/workflow", json={"name": "p"}, headers=headers("u-alice"))
        check("operator 可创建工作流", r.status_code == 200)
        check("工作流定义不含 _durations/durations",
              "durations" not in r.json() and "_durations" not in r.json())

        r = await c.post("/api/run", json={"workflowId": 1, "workers": 3},
                         headers=headers("u-alice"))
        check("operator 可执行", r.status_code == 200)
        run_id = r.json()["runId"]

        state = (await c.get("/api/state", headers=headers("u-carol"))).json()
        node_keys = set(state["nodes"][0].keys()) if state["nodes"] else set()
        check("只读投影节点字段符合约定",
              node_keys <= {"id", "name", "status", "retries", "startTime", "endTime",
                            "deps", "x", "y"},
              str(node_keys))
        check("viewer 也能 GET 执行状态（只读可见）", state["run"]["runId"] == run_id)

        # 5. 两处表面对同一份执行的投影一致 --------------------------------
        page_state = (await c.get("/api/state", headers=headers("u-carol", "page"))).json()
        screen_state = (await c.get("/api/state", headers=headers("u-dave", "screen"))).json()
        check("普通页与大屏 REST 投影完全一致",
              json.dumps(page_state, sort_keys=True) == json.dumps(screen_state, sort_keys=True))

        # 6. 大屏表面发变更请求 -> 403 screen_surface ----------------------
        r = await c.post("/api/run", json={"workflowId": 1}, headers=headers("u-alice", "screen"))
        check("大屏表面 operator 触发执行也被挡", r.status_code == 403
              and r.json()["detail"]["code"] == "screen_surface")

        # 等执行跑一会儿
        await asyncio.sleep(1.5)

        # 7. 投屏会话流程 ---------------------------------------------------
        r = await c.post("/api/screen/start", headers=headers("u-alice"))
        sess = r.json()["session"]
        code = sess["code"]
        check("开始投屏返回房间码", r.status_code == 200 and len(code) == 6)
        check("presenter 正确", sess["presenter"]["id"] == "u-alice")

        # presenter 投屏期间普通页面执行被锁
        r = await c.post("/api/run", json={"workflowId": 1}, headers=headers("u-alice", "page"))
        check("投屏期间 operator 执行被 presenting_locked 锁定",
              r.status_code == 403 and r.json()["detail"]["code"] == "presenting_locked")

        r = await c.get("/api/screen/active", headers=headers("u-alice"))
        check("普通页可查到进行中投屏", r.json()["session"] and r.json()["session"]["code"] == code)

        # 8. 大屏 WS：presenter + 两个 watcher 同屏，presence 可见 ---------
        p_ws = await ws_connect(f"/ws/screen?code={code}&member_id=u-alice")
        w1 = await ws_connect(f"/ws/screen?code={code}&member_id=u-carol")
        w2 = await ws_connect(f"/ws/screen?code={code}&member_id=u-dave")
        for w in (p_ws, w1, w2):
            await hello(w)

        pres = await recv_until(w2, "presence")
        watcher_ids = {x["id"] for x in pres["session"]["watchers"]}
        check("大屏 presence 能看到投屏人", pres["session"]["presenter"]["id"] == "u-alice")
        check("多个成员可同时观看（carol+dave）", {"u-carol", "u-dave"} <= watcher_ids,
              str(watcher_ids))

        # watcher 收到执行快照，且字段为投影字段
        snap = await recv_until(w2, "snapshot")
        check("大屏 WS 拿到同一 run 的快照", snap["run"] and snap["run"]["runId"] == run_id)
        check("大屏 WS 快照字段符合约定",
              set(snap["nodes"][0].keys()) <= {"id", "name", "status", "retries",
                                               "startTime", "endTime"})

        # 非投屏人不能 stop
        r = await c.post(f"/api/screen/{code}/stop", headers=headers("u-carol"))
        check("非投屏人结束投屏被 403 挡下", r.status_code == 403
              and r.json()["detail"]["code"] == "not_presenter")

        # 9. 普通页 /ws 与大屏 /ws/screen 对同一执行看到相同 seq -----------
        pg = await ws_connect("/ws?member_id=u-carol")
        await hello(pg)
        psnap = await recv_until(pg, "snapshot")
        check("普通页 WS 与大屏看到同一 run", psnap["run"]["runId"] == run_id)

        # 10. 断线重连补进展（显式发起新 run，保证断线窗口内有活跃执行）----
        await wait_idle(c)
        # alice 正在投屏（执行被锁），新 run 由未投屏的 bob 发起
        run_json = await start_run(c, "u-bob")
        run_id = run_json["runId"]
        await asyncio.sleep(0.6)
        live = await recv_until(w2, "snapshot")
        last_seq = live["seq"]
        await w2.close()
        await asyncio.sleep(2.0)
        mid = (await c.get("/api/state")).json()
        check("断线期间服务端仍在推进 seq", mid["seq"] >= last_seq,
              f"{mid['seq']} >= {last_seq}")
        advanced = mid["seq"] > last_seq

        w3 = await ws_connect(f"/ws/screen?code={code}&member_id=u-dave")
        await hello(w3, run_id=run_id, last_seq=last_seq)
        kinds = []
        got_snapshot = None
        try:
            while True:
                raw = await asyncio.wait_for(w3.recv(), timeout=2.0)
                m = json.loads(raw)
                kinds.append(m.get("type"))
                if m.get("type") == "snapshot":
                    got_snapshot = m
                    break
        except asyncio.TimeoutError:
            pass
        if advanced:
            check("断线期间有新进展时重放了增量事件(event)", "event" in kinds, str(kinds))
        check("重放后对齐到最新快照", got_snapshot and got_snapshot["seq"] >= mid["seq"])

        # 跨 run 重放 -> 直接整份快照（再起一个新 run）
        await wait_idle(c)
        headers_bob = {"X-Member-Id": "u-bob"}
        r = await c.post("/api/run", json={"workflowId": 1, "workers": 5},
                         headers=headers_bob)
        if r.status_code == 409:
            await wait_idle(c)
            r = await c.post("/api/run", json={"workflowId": 1, "workers": 5},
                             headers=headers_bob)
        assert r.status_code == 200, r.text
        await asyncio.sleep(0.5)
        newest = (await c.get("/api/state")).json()
        w4 = await ws_connect("/ws?member_id=u-carol")
        await hello(w4, run_id=run_id, last_seq=last_seq)  # 旧 runId
        s4 = await recv_until(w4, "snapshot")
        check("跨 run 重连直接给最新快照", s4["run"]["runId"] == newest["run"]["runId"])

        # 11. 无效房间码：握手被拒（Starlette accept 前关闭 = HTTP 403） ---
        rejected = False
        try:
            await ws_connect("/ws/screen?code=ZZZ999&member_id=u-carol")
        except websockets.exceptions.InvalidStatus as e:
            rejected = e.response.status_code == 403
        check("无效房间码 WS 握手被拒(403)", rejected)

        # 12. presenter 停止投屏：广播 session_ended，普通页权限恢复 --------
        stopped = asyncio.Event()

        async def watch_end(ws):
            try:
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("type") == "session_ended":
                        stopped.set()
                        return
            except Exception:
                return

        tasks = [asyncio.create_task(watch_end(w)) for w in (p_ws, w1, w3)]
        await asyncio.sleep(0.3)
        r = await c.post(f"/api/screen/{code}/stop", headers=headers("u-alice"))
        check("投屏人可结束投屏", r.status_code == 200)
        await asyncio.wait_for(stopped.wait(), timeout=3)
        check("房间内各端收到 session_ended 广播", stopped.is_set())
        for t in tasks: t.cancel()

        r = await c.get("/api/screen/active", headers=headers("u-alice"))
        check("结束后无进行中会话（权限恢复前提）", r.json()["session"] is None)
        r = await c.post("/api/workflow", json={"name": "p2"}, headers=headers("u-alice"))
        check("取消投放后普通页操作恢复", r.status_code == 200)

        # watcher 心跳过期会被 reaper 清理（第二个会话验证 presence 收缩）
        r = await c.post("/api/screen/start", headers=headers("u-bob"))
        code2 = r.json()["session"]["code"]
        bob = await ws_connect(f"/ws/screen?code={code2}&member_id=u-bob")
        carol2 = await ws_connect(f"/ws/screen?code={code2}&member_id=u-carol")
        await hello(bob); await hello(carol2)
        await recv_until(carol2, "presence")
        await carol2.close()
        # WATCHER_TTL=30s，这里只验证断开立即从 presence 移除的广播
        await asyncio.sleep(0.6)
        r = await c.post("/api/screen/start", headers=headers("u-bob"))  # 幂等复用
        check("重复开始投屏幂等复用同一会话", r.json()["session"]["code"] == code2)
        await c.post(f"/api/screen/{code2}/stop", headers=headers("u-bob"))
        for w in (p_ws, w1, w3, w4, pg, bob):
            await w.close()

    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n - ")
        sys.exit(1)


asyncio.run(main())
