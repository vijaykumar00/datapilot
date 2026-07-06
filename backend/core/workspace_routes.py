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
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import User, Workspace, WorkspaceMember, AuditLog, UserSettings
from core.rbac import get_current_user, get_workspace_member

logger = logging.getLogger("datapilot.workspaces")
router = APIRouter(prefix="/workspaces", tags=["workspaces"])

VALID_ROLES = {"Owner", "Admin", "Member", "Viewer"}


# ─────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────

class CreateWorkspaceRequest(BaseModel):
    name: str
    plan_tier: str = "free"


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

    result = []
    for m in memberships:
        ws = db.query(Workspace).filter(Workspace.workspace_id == m.workspace_id).first()
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
    ws_id = str(uuid.uuid4())
    workspace = Workspace(
        workspace_id=ws_id,
        name=payload.name,
        plan_tier=payload.plan_tier,
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
    if payload.plan_tier:
        ws.plan_tier = payload.plan_tier

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
    get_workspace_member(user, workspace_id, db, required_role="Admin")

    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {VALID_ROLES}")

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
