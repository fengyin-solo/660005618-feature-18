"""成员身份与权限。

演示环境用预置成员 + X-Member-Id 头标识调用方（无真实登录），
但权限判定在服务端强制执行，前端的只读控制只是体验层。
"""
from fastapi import Header, HTTPException

# 预置成员：两种角色。operator 可重跑，viewer 是只读成员。
MEMBERS = {
    "u-alice": {"id": "u-alice", "name": "Alice（值班工程师）", "role": "operator"},
    "u-bob": {"id": "u-bob", "name": "Bob（数据工程师）", "role": "operator"},
    "u-carol": {"id": "u-carol", "name": "Carol（只读成员）", "role": "viewer"},
    "u-dave": {"id": "u-dave", "name": "Dave（只读成员）", "role": "viewer"},
}

# 越权被挡下时给出的理由（message 直接展示给用户）
DENY_REASONS = {
    "viewer_readonly": "只读成员无权触发执行或重跑，可联系 operator 代操作",
    "screen_surface": "大屏为只读视图，变更操作已被禁止",
    "presenting_locked": "你正在投屏，大屏期间操作已锁定；停止投屏后恢复",
}


def require_member(x_member_id: str = Header(default="u-alice")) -> dict:
    """解析调用方身份，未知成员返回 401。"""
    member = MEMBERS.get(x_member_id)
    if not member:
        raise HTTPException(status_code=401, detail={"code": "unknown_member",
                                                     "message": "未知成员身份"})
    return member


def assert_can_run(member: dict, surface: str, is_presenting: bool):
    """变更类操作（创建/执行/重跑）的统一闸门。

    - viewer：任何通道都不允许；
    - 大屏通道：任何角色都不允许（受控只读视图）；
    - operator 投屏期间：普通通道也暂锁，取消投放后恢复。
    """
    if member["role"] != "operator":
        raise HTTPException(status_code=403, detail={
            "code": "viewer_readonly", "message": DENY_REASONS["viewer_readonly"],
            "member": member["id"], "role": member["role"]})
    if surface == "screen":
        raise HTTPException(status_code=403, detail={
            "code": "screen_surface", "message": DENY_REASONS["screen_surface"],
            "member": member["id"]})
    if is_presenting:
        raise HTTPException(status_code=403, detail={
            "code": "presenting_locked", "message": DENY_REASONS["presenting_locked"],
            "member": member["id"]})
