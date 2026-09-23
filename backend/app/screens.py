"""大屏投屏会话。

一个会话 = 一个投屏人(presenter) + 若干同时观看的成员(watchers)。
- watcher 在线状态靠大屏 WS 心跳维护（30s 无心跳视为离开放映室）；
- 谁在投屏(presenter)对所有 watcher 实时可见，presence 变化即广播；
- presenter 显式停止后会话关闭，广播 session_ended，普通页权限随即恢复；
- presenter 的大屏连接异常断开时给 60s 宽限，重连可续上；宽限期满自动收档。
"""
import random
import string
import time

from .authz import MEMBERS

WATCHER_TTL = 30          # 心跳超时
PRESENTER_GRACE = 60      # 投屏人断线宽限


def _code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choices(alphabet, k=6))


class ScreenSessions:
    def __init__(self):
        self._sessions = {}   # code -> session

    def start(self, presenter_id: str):
        """开始投屏；同一成员已有会话则复用（重复点击不产生垃圾会话）。"""
        for s in self._sessions.values():
            if s["presenterId"] == presenter_id and s["status"] == "active":
                return s
        code = _code()
        while code in self._sessions:
            code = _code()
        now = time.time()
        self._sessions[code] = {
            "code": code,
            "presenterId": presenter_id,
            "status": "active",
            "startedAt": now,
            "presenterLastSeen": now,
            "watchers": {},  # memberId -> lastSeen
        }
        return self._sessions[code]

    def get(self, code):
        s = self._sessions.get(code)
        if not s or s["status"] != "active":
            return None
        return s

    def active_session_of(self, member_id):
        for s in self._sessions.values():
            if s["presenterId"] == member_id and s["status"] == "active":
                return s
        return None

    def touch_presenter(self, code):
        s = self.get(code)
        if s:
            s["presenterLastSeen"] = time.time()

    def mark_presenter_disconnected(self, code):
        s = self.get(code)
        if s:
            s["presenterLastSeen"] = time.time()

    def upsert_watcher(self, code, member_id):
        s = self.get(code)
        is_new = False
        if s is not None and member_id != s["presenterId"]:
            is_new = member_id not in s["watchers"]
            s["watchers"][member_id] = time.time()
        return s, is_new

    def touch_watcher(self, code, member_id):
        s = self.get(code)
        if s and member_id in s["watchers"]:
            s["watchers"][member_id] = time.time()

    def remove_watcher(self, code, member_id):
        s = self.get(code)
        if s and s["watchers"].pop(member_id, None) is not None:
            return True
        return False

    def stop(self, code, member_id):
        s = self.get(code)
        if not s:
            return None
        if s["presenterId"] != member_id:
            return False
        s["status"] = "stopped"
        s["endedAt"] = time.time()
        return s

    def reap(self):
        """清理过期 watcher；presenter 宽限期满则收档。返回变更事件列表。"""
        events = []
        now = time.time()
        for code, s in list(self._sessions.items()):
            if s["status"] != "active":
                continue
            stale = [m for m, t in s["watchers"].items()
                     if now - t > WATCHER_TTL]
            for m in stale:
                s["watchers"].pop(m, None)
                events.append({"type": "presence", "code": code,
                               "session": self.public(s), "left": m})
            if now - s["presenterLastSeen"] > PRESENTER_GRACE:
                s["status"] = "expired"
                s["endedAt"] = now
                events.append({"type": "session_ended", "code": code,
                               "reason": "presenter_offline_timeout"})
        # 只保留最近的已结束会话记录一小段时间，避免字典无限增长
        self._sessions = {c: s for c, s in self._sessions.items()
                          if s["status"] == "active"
                          or now - s.get("endedAt", now) < 120}
        return events

    def public(self, s):
        """对外的会话视图（可给所有成员看）。"""
        p = MEMBERS.get(s["presenterId"], {"name": s["presenterId"]})
        return {
            "code": s["code"],
            "status": s["status"],
            "startedAt": s["startedAt"],
            "presenter": {"id": s["presenterId"], "name": p["name"],
                          "role": p.get("role")},
            "presenterOnline": time.time() - s["presenterLastSeen"] < PRESENTER_GRACE,
            "watchers": [{"id": m, "name": MEMBERS.get(m, {"name": m})["name"]}
                         for m in sorted(s["watchers"])],
        }


sessions = ScreenSessions()
