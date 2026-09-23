"""投屏会话与在线名单（presence）。

- 同一时刻只允许一块活跃大屏，后发起者得到 409 与原因；
- 投屏人(presenter)、观看成员(viewers)分开记录，支持多人同时观看；
- 成员掉线（WS 关闭）自动从名单移除，重连后恢复；
- 结束投屏吊销大屏令牌并广播 presentation_end。
"""
import time
from dataclasses import dataclass, field

from . import auth


@dataclass
class Member:
    username: str
    display_name: str
    role: str
    joined_at: float = field(default_factory=time.time)
    last_beat: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {"username": self.username, "displayName": self.display_name,
                "role": self.role, "joinedAt": self.joined_at}


class Presentation:
    def __init__(self, presentation_id: str, presenter: auth.Session):
        self.id = presentation_id
        self.presenter_username = presenter.username
        self.presenter_display = presenter.display_name
        self.created_at = time.time()
        self.members: dict[str, Member] = {}   # username -> Member（含投屏人）
        self.members[presenter.username] = Member(
            presenter.username, presenter.display_name, presenter.role)

    def public(self) -> dict:
        return {
            "id": self.id,
            "presenter": {"username": self.presenter_username, "displayName": self.presenter_display},
            "members": [m.public() for m in
                        sorted(self.members.values(), key=lambda m: m.joined_at)],
            "viewerCount": max(0, len(self.members) - 1),
            "startedAt": self.created_at,
        }


class PresentationRegistry:
    def __init__(self, broker):
        self.broker = broker
        self.active: Presentation | None = None

    def start(self, presenter: auth.Session) -> Presentation:
        if self.active is not None:
            raise LookupError(f"已有成员「{self.active.presenter_display}」正在投屏，"
                              "同一时刻只支持一块大屏")
        import secrets
        pid = secrets.token_hex(6)
        self.active = Presentation(pid, presenter)
        self._broadcast()
        return self.active

    def stop(self, session: auth.Session) -> Presentation:
        p = self._require(session)
        if session.scope != "screen" and session.username != p.presenter_username:
            raise PermissionError("只有投屏人可以结束投放")
        ended = p
        self.active = None
        auth.revoke_screen_sessions(p.id)
        self.broker.publish("presentation_end",
                            {"presentationId": p.id,
                             "reason": f"投屏人「{p.presenter_display}」已结束投放"})
        return ended

    def _require(self, session: auth.Session) -> Presentation:
        if self.active is None:
            raise KeyError("当前没有进行中的投屏")
        if session.scope == "screen":
            if session.presentation_id != self.active.id:
                raise PermissionError("大屏凭证不属于本次投屏")
        return self.active

    def join(self, session: auth.Session) -> Presentation:
        p = self._require(session)
        m = p.members.get(session.username)
        if m is None:
            p.members[session.username] = Member(session.username, session.display_name, session.role)
        else:
            m.last_beat = time.time()
        self._broadcast()
        return p

    def leave(self, session: auth.Session) -> None:
        p = self.active
        if p is None:
            return
        if session.scope == "screen" and session.presentation_id != p.id:
            return
        if session.username in p.members and session.username != p.presenter_username:
            del p.members[session.username]
            self._broadcast()

    def heartbeat(self, session: auth.Session) -> None:
        p = self.active
        if p and session.username in p.members:
            p.members[session.username].last_beat = time.time()

    def prune_stale(self, ttl: float = 20.0) -> None:
        """清理心跳超时的成员（投屏人掉线不自动结束，留待其重连或主动结束）。"""
        p = self.active
        if not p:
            return
        now = time.time()
        stale = [u for u, m in p.members.items()
                 if u != p.presenter_username and now - m.last_beat > ttl]
        if stale:
            for u in stale:
                p.members.pop(u, None)
            self._broadcast()

    def _broadcast(self) -> None:
        self.broker.publish("presence",
                            {"presentation": self.active.public() if self.active else None})

    def public(self) -> dict | None:
        return self.active.public() if self.active else None
