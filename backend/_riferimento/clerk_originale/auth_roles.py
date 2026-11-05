import asyncio
import os

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo import ReturnDocument

from clerk_auth import require_user, verify_session_token

ROLES = ["admin", "operatore", "in_attesa"]
DEFAULT_ROLE = "in_attesa"
ALLOWED = ("admin", "operatore")
RETIRED_ROLES: dict = {}
RANK = {r: len(ROLES) - i for i, r in enumerate(ROLES)}
ENV = "live" if os.environ.get("CLERK_PUBLISHABLE_KEY", "").startswith("pk_live_") else "preview"
IN_ENV = {"env": {"$in": [ENV, None]}}

db = None
users_router = APIRouter(prefix="/api")


def effective_role(role) -> str:
    role = RETIRED_ROLES.get(role, role)
    return role if role in ROLES else DEFAULT_ROLE


def _clerk_profile(user_id: str):
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAIL", "").split(",") if e.strip()}
    r = requests.get(f"https://api.clerk.com/v1/users/{user_id}", timeout=10,
                     headers={"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}", "User-Agent": "emergent-app"})
    r.raise_for_status()
    u = r.json()
    emails = u.get("email_addresses", [])
    is_admin = any(e["email_address"].lower() in admins and (e.get("verification") or {}).get("status") == "verified" for e in emails)
    email = next((e["email_address"] for e in emails if e["id"] == u.get("primary_email_address_id")), emails[0]["email_address"] if emails else "")
    name = " ".join(filter(None, [u.get("first_name"), u.get("last_name")])) or email
    return is_admin, email, name


async def member_for(uid: str) -> dict:
    member = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if member is None or not member.get("role"):
        is_admin, email, name = await asyncio.to_thread(_clerk_profile, uid)
        role = "admin" if is_admin else DEFAULT_ROLE
        await db.users.update_one({"user_id": uid, "role": {"$in": [None, ""]}}, {"$set": {"role": role, "email": email, "name": name}})
        member = await db.users.find_one_and_update(
            {"user_id": uid}, {"$setOnInsert": {"user_id": uid, "role": role, "email": email, "name": name}},
            upsert=True, projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if member.get("env") != ENV:
        await db.users.update_one({"user_id": uid}, {"$set": {"env": ENV}})
    return {**member, "env": ENV, "role": effective_role(member["role"])}


async def current_member(user: dict = Depends(require_user)) -> dict:
    return await member_for(user["user_id"])


async def require_approved(member: dict = Depends(current_member)) -> dict:
    if member["role"] not in ALLOWED:
        raise HTTPException(403, "Account in attesa di approvazione")
    return member


def require_role(*roles: str):
    async def check(member: dict = Depends(current_member)) -> dict:
        if member["role"] not in roles:
            raise HTTPException(403, "Non consentito")
        return member
    return check


async def ws_member(token: str) -> dict | None:
    try:
        claims = verify_session_token(token)
        m = await member_for(claims["sub"])
        return m if m["role"] in ALLOWED else None
    except Exception:
        return None


@users_router.get("/me")
async def me(member: dict = Depends(current_member)):
    return member


@users_router.get("/users")
async def list_users(admin: dict = Depends(require_role("admin"))):
    people = await db.users.find(IN_ENV, {"_id": 0}).to_list(1000)
    return {"roles": [r for r in ROLES if RANK[r] <= RANK[admin["role"]]],
            "users": [{**p, "role": effective_role(p.get("role"))} for p in people]}


class RoleIn(BaseModel):
    role: str


@users_router.patch("/users/{user_id}/role")
async def set_role(user_id: str, body: RoleIn, admin: dict = Depends(require_role("admin"))):
    if body.role not in ROLES or RANK[body.role] > RANK[admin["role"]]:
        raise HTTPException(403, "Non consentito")
    target = await db.users.find_one({"user_id": user_id, **IN_ENV}, {"_id": 0})
    if target is None:
        raise HTTPException(404, "Non trovato")
    if (effective_role(target.get("role")) == "admin" and body.role != "admin"
            and await db.users.count_documents({"role": "admin", **IN_ENV}) <= 1):
        raise HTTPException(409, "Deve restare almeno un amministratore")
    await db.users.update_one({"user_id": user_id}, {"$set": {"role": body.role}})
    return {"user_id": user_id, "role": body.role}


async def move_retired_roles():
    for old, new in RETIRED_ROLES.items():
        await db.users.update_many({"role": old}, {"$set": {"role": new}})
