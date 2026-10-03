"""
workspace_routes.py — Workspace CRUD and member management.

Security:
  - Cross-workspace access returns 404 (not 403) to prevent enumeration.
  - Only workspace Owners can delete workspaces or change member roles.
  - Admins can invite members.
  - All workspace operations are audit-logged.
"""
import logging
import uuid
from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import User, Workspace, WorkspaceMember, AuditLog, UserSettings
from core.rbac import get_current_user, get_workspace_member

logger = logging.getLogger("datapilot.workspaces")
router = APIRouter(prefix="/workspaces", tags=["workspaces"])

VALID_ROLES = {"Owner", "Admin", "Member", "Viewer"}

def _enforce_workspace_limit(user: User, db: Session) -> None:
    """A user may own as many workspaces as the best active plan among their owned workspaces allows."""
    from core.subscriptions import UNLIMITED
    from core.usage import effective_plan

    owned = db.query(Workspace).filter(Workspace.owner_id == user.user_id).all()
    if not owned:
        return
    allowed = 1
    for ws in owned:
        _, limits, _, _ = effective_plan(ws.workspace_id, db)
        value = int(limits.get("workspace_count", 1))
        if value == UNLIMITED:
            return
        allowed = max(allowed, value)
    if len(owned) >= allowed:
        raise HTTPException(status_code=429, detail={"error": "PLAN_LIMIT_EXCEEDED", "metric": "workspace_count",
                                                     "limit": allowed, "current": len(owned),
                                                     "message": "Your plan's workspace limit has been reached.",
                                                     "upgrade_prompt": True})



# ─────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────

class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    plan_tier: str = "free"

    @field_validator('plan_tier')
    @classmethod
    def validate_plan_tier(cls, v):
        allowed = {"free", "pro", "team", "business", "enterprise"}
        if v not in allowed:
            raise ValueError(f"plan_tier must be one of: {', '.join(sorted(allowed))}")
        return v


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    plan_tier: Optional[str] = None


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "Member"


class UpdateMemberRoleRequest(BaseModel):
    role: str


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _workspace_to_dict(ws: Workspace, member: WorkspaceMember) -> dict:
    return {
        "workspace_id": ws.workspace_id,
        "name": ws.name,
        "slug": ws.slug,
        "plan_tier": ws.plan_tier,
        "owner_id": ws.owner_id,
        "your_role": member.role,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }


def _audit(db: Session, user_id: str, workspace_id: str, event_type: str, description: str):
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        user_id=user_id,
        workspace_id=workspace_id,
        event_type=event_type,
        description=description,
    ))


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("")
def list_workspaces(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all workspaces the current user is a member of."""
    memberships = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.user_id
    ).all()

    if not memberships:
        return {"workspaces": [], "total": 0}

    # Single IN query — avoids N+1 pattern
    workspace_ids = [m.workspace_id for m in memberships]
    workspaces_by_id = {
        ws.workspace_id: ws
        for ws in db.query(Workspace).filter(Workspace.workspace_id.in_(workspace_ids)).all()
    }

    result = []
    for m in memberships:
        ws = workspaces_by_id.get(m.workspace_id)
        if ws:
            result.append(_workspace_to_dict(ws, m))

    return {"workspaces": result, "total": len(result)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: CreateWorkspaceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new workspace. Current user becomes Owner."""
    # Plans are only changed by verified billing events (Stripe webhooks) or platform
    # admins.  A client-supplied plan_tier is never trusted.
    if payload.plan_tier and payload.plan_tier != "free":
        raise HTTPException(status_code=403, detail="Workspace plans can only be changed through billing.")
    _enforce_workspace_limit(user, db)
    ws_id = str(uuid.uuid4())
    workspace = Workspace(
        workspace_id=ws_id,
        name=payload.name,
        plan_tier="free",
        owner_id=user.user_id,
    )
    db.add(workspace)

    member = WorkspaceMember(
        workspace_id=ws_id,
        user_id=user.user_id,
        role="Owner",
    )
    db.add(member)

    _audit(db, user.user_id, ws_id, "WORKSPACE_CREATED",
           f"User {user.email} created workspace '{payload.name}'.")
    db.commit()

    return {
        "success": True,
        "workspace": _workspace_to_dict(workspace, member),
    }


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get workspace details. Returns 404 if not a member (prevents enumeration)."""
    member = get_workspace_member(user, workspace_id, db)
    ws = db.query(Workspace).filter(Workspace.workspace_id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return {"workspace": _workspace_to_dict(ws, member)}


@router.put("/{workspace_id}")
def update_workspace(
    workspace_id: str,
    payload: UpdateWorkspaceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update workspace settings. Requires Admin or Owner."""
    member = get_workspace_member(user, workspace_id, db, required_role="Admin")
    ws = db.query(Workspace).filter(Workspace.workspace_id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    if payload.name:
        ws.name = payload.name
    if payload.plan_tier and payload.plan_tier != ws.plan_tier:
        raise HTTPException(status_code=403, detail="Workspace plans can only be changed through billing.")

    _audit(db, user.user_id, workspace_id, "WORKSPACE_UPDATED",
           f"Workspace updated by {user.email}.")
    db.commit()

    return {"success": True, "workspace": _workspace_to_dict(ws, member)}


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete workspace. Requires Owner."""
    get_workspace_member(user, workspace_id, db, required_role="Owner")
    ws = db.query(Workspace).filter(Workspace.workspace_id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    _audit(db, user.user_id, workspace_id, "WORKSPACE_DELETED",
           f"Workspace '{ws.name}' deleted by {user.email}.")
    db.delete(ws)
    db.commit()

    # Delete the workspace's datasets/objects durably in the background.
    from core import jobs

    job_id = jobs.enqueue("workspace_cleanup", {"workspace_id": workspace_id},
                          workspace_id=workspace_id, user_id=user.user_id, max_attempts=5)
    if jobs.execution_mode() == "inline":
        jobs.run_inline(job_id)

    return {"success": True, "message": "Workspace deleted."}


# ─────────────────────────────────────────────────────────────
# Member Management
# ─────────────────────────────────────────────────────────────

@router.get("/{workspace_id}/members")
def list_members(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all workspace members. Requires at least Viewer role."""
    get_workspace_member(user, workspace_id, db, required_role="Viewer")

    members = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id
    ).all()

    result = []
    for m in members:
        member_user = db.query(User).filter(User.user_id == m.user_id).first()
        if member_user:
            result.append({
                "user_id": m.user_id,
                "email": member_user.email,
                "full_name": member_user.full_name,
                "role": m.role,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            })

    return {"members": result, "total": len(result)}


@router.post("/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
def invite_member(
    workspace_id: str,
    payload: InviteMemberRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Invite a user to the workspace. Requires Admin or Owner."""
    inviter = get_workspace_member(user, workspace_id, db, required_role="Admin")

    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {VALID_ROLES}")
    if payload.role in {"Owner", "Admin"} and inviter.role != "Owner":
        raise HTTPException(status_code=403, detail="Only workspace Owners can grant Owner or Admin roles.")

    from core.subscriptions import UNLIMITED
    from core.usage import effective_plan

    _, limits, features, _ = effective_plan(workspace_id, db)
    if not features.get("can_invite_members", False):
        raise HTTPException(status_code=402, detail={"error": "FEATURE_NOT_IN_PLAN", "feature": "can_invite_members",
                                                     "message": "Inviting members is not included in your plan.",
                                                     "upgrade_prompt": True})
    member_limit = int(limits.get("member_count", UNLIMITED))
    current_members = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id).count()
    if member_limit != UNLIMITED and current_members >= member_limit:
        raise HTTPException(status_code=429, detail={"error": "PLAN_LIMIT_EXCEEDED", "metric": "member_count",
                                                     "limit": member_limit, "current": current_members,
                                                     "message": "Your plan's member limit has been reached.",
                                                     "upgrade_prompt": True})

    # Find target user
    target = db.query(User).filter(User.email == payload.email).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found. They must register first.")

    # Check not already a member
    existing = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == target.user_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="User is already a workspace member.")

    new_member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=target.user_id,
        role=payload.role,
    )
    db.add(new_member)

    _audit(db, user.user_id, workspace_id, "WORKSPACE_MEMBER_ADDED",
           f"{user.email} invited {payload.email} as {payload.role}.")
    db.commit()

    return {
        "success": True,
        "message": f"{payload.email} added as {payload.role}.",
        "member": {
            "user_id": target.user_id,
            "email": target.email,
            "role": payload.role,
        }
    }


@router.put("/{workspace_id}/members/{target_user_id}")
def update_member_role(
    workspace_id: str,
    target_user_id: str,
    payload: UpdateMemberRoleRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a member's role. Requires Owner."""
    get_workspace_member(user, workspace_id, db, required_role="Owner")

    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {VALID_ROLES}")

    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == target_user_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")

    # Cannot demote yourself if you're the last owner
    if target_user_id == user.user_id and payload.role != "Owner":
        owner_count = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == "Owner",
        ).count()
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last Owner from a workspace.")

    old_role = member.role
    member.role = payload.role

    _audit(db, user.user_id, workspace_id, "WORKSPACE_MEMBER_ROLE_CHANGED",
           f"{user.email} changed {target_user_id} role from {old_role} to {payload.role}.")
    db.commit()

    return {"success": True, "message": f"Role updated to {payload.role}."}


@router.delete("/{workspace_id}/members/{target_user_id}")
def remove_member(
    workspace_id: str,
    target_user_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a member from workspace. Requires Admin or Owner. Members can remove themselves."""
    current_member = get_workspace_member(user, workspace_id, db)

    # Allow self-removal or Admin/Owner to remove others
    from core.rbac import ROLE_HIERARCHY
    if target_user_id != user.user_id:
        if ROLE_HIERARCHY.get(current_member.role, 0) < ROLE_HIERARCHY["Admin"]:
            raise HTTPException(status_code=403, detail="Insufficient permissions to remove members.")

    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == target_user_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")

    # Cannot remove last owner
    if member.role == "Owner":
        owner_count = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == "Owner",
        ).count()
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last Owner from a workspace.")

    db.delete(member)
    _audit(db, user.user_id, workspace_id, "WORKSPACE_MEMBER_REMOVED",
           f"{user.email} removed user {target_user_id} from workspace.")
    db.commit()

    return {"success": True, "message": "Member removed from workspace."}
