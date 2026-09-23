"""WebSocket 连接管理与执行消息广播。

普通页面 (/ws) 与大屏 (/ws/screen) 的连接都登记在这里，
执行进展对两类连接广播完全相同的投影，保证两处可见范围一致。
"""
import asyncio
import json
from .projection import project_snapshot, project_event


class ConnectionManager:
    def __init__(self):
        # ws -> {"memberId": str, "surface": "page"|"screen"}
        self.conns: dict = {}

    async def connect(self, ws, member_id: str, surface: str, code: str = None):
        await ws.accept()
        self.conns[ws] = {"memberId": member_id, "surface": surface, "code": code}

    def disconnect(self, ws):
        self.conns.pop(ws, None)

    def member_sockets(self, member_id: str):
        return [ws for ws, m in self.conns.items() if m["memberId"] == member_id]

    def screen_sockets(self, code: str):
        return [ws for ws, m in self.conns.items()
                if m["surface"] == "screen" and m["code"] == code]

    async def _send(self, ws, message: dict):
        try:
            await ws.send_text(json.dumps(message))
            return True
        except Exception:
            self.disconnect(ws)
            return False

    async def send_to(self, ws, message: dict):
        await self._send(ws, message)

    async def broadcast_execution(self, store):
        """把 store 当前快照广播给全部在线连接（页面 + 大屏同一份）。"""
        payload = {"type": "snapshot", **project_snapshot(store.snapshot())}
        dead = []
        for ws in list(self.conns):
            if not await self._send(ws, payload):
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_event(self, evt: dict):
        """单条增量事件广播。"""
        payload = project_event(evt)
        for ws in list(self.conns):
            await self._send(ws, payload)

    def run_coroutine(self, loop, coro):
        """供执行线程（非事件循环线程）调度协程。"""
        return asyncio.run_coroutine_threadsafe(coro, loop)


manager = ConnectionManager()
