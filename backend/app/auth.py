"""演示用身份与权限模型。

- 两个预置成员：operator（可执行/重跑）、viewer（只读成员）；
- 投屏时签发 scope=screen 的受限令牌：任何“会改变执行”的接口一律拒绝；
- 权限失败统一返回中文理由，便于大屏/普通页直接向用户说明。
"""
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, WebSocket, status

# username -> role。密码仅用于演示登录，真实系统应由用户体系提供。
USERS = {
    "operator": {"password": "operator", "role": "operator", "displayName": "值班工程师"},
    "viewer": {"password": "viewer", "role": "viewer", "displayName": "只读成员"},
}
ROLE_LABELS = {"operator": "可执行", "viewer": "只读"}

# token -> Session
SESSIONS: dict[str, "Session"] = {}


@dataclass
class Session:
    token: str
    username: str
    display_name: str
    role: str          # operator / viewer
    scope: str         # user（普通页面）/ screen（大屏投屏）
    presentation_id: str | None = None
    created_at: float = 0.0

    @property
    def can_write(self) -> bool:
        return self.scope == "user" and self.role == "operator"


def login(username: str, password: str) -> Session:
    u = USERS.get(username)
    if not u or u["password"] != password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return issue_session(username, u["role"], u["displayName"], scope="user")


def issue_session(username: str, role: str, display_name: str,
                  scope: str = "user", presentation_id: str | None = None) -> Session:
    s = Session(
        token=secrets.token_urlsafe(24), username=username, display_name=display_name,
        role=role, scope=scope, presentation_id=presentation_id, created_at=time.time(),
    )
    SESSIONS[s.token] = s
    return s


def revoke_session(token: str) -> None:
    SESSIONS.pop(token, None)


def resolve(token: str | None) -> Session | None:
    if not token:
        return None
    return SESSIONS.get(token)


def revoke_screen_sessions(presentation_id: str) -> None:
    """结束投屏时吊销该大屏的全部受限令牌，取消后无法再以大屏身份操作。"""
    for tok in [t for t, s in SESSIONS.items()
                if s.scope == "screen" and s.presentation_id == presentation_id]:
        SESSIONS.pop(tok, None)


def _extract(token: str | None) -> str | None:
    if token and token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def require_session(authorization: str | None = Header(default=None)) -> Session:
    s = resolve(_extract(authorization))
    if not s:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已失效，请重新登录")
    return s


def require_write(s: Session = Depends(require_session)) -> Session:
    """FastAPI 依赖：只放行普通页面上的 operator，其余角色/投屏一律拒绝并说明理由。"""
    if s.scope == "screen":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前是投屏大屏（只读视图），不允许触发执行或重跑；请在普通页面操作",
        )
    if s.role != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号是只读成员（viewer），没有执行/重跑权限",
        )
    return s


def public_session(s: Session) -> dict:
    return {
        "username": s.username, "displayName": s.display_name,
        "role": s.role, "roleLabel": ROLE_LABELS.get(s.role, s.role),
        "scope": s.scope, "canWrite": s.can_write,
        "presentationId": s.presentation_id,
    }


async def ws_session(ws: WebSocket) -> Session | None:
    return resolve(ws.query_params.get("token"))
