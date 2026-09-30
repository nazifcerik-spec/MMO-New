"""Bootstrap a staff account (no default credentials exist).

Usage: MMO_BOOTSTRAP_PASSWORD=... python -m scripts.create_admin --email ops@example.com --role superadmin
If the env var is absent the password is read interactively."""

import argparse
import asyncio
import getpass
import os

from sqlalchemy import select

from app.db.session import dispose_engine, get_sessionmaker
from app.models.auth import User
from app.services import auth, rbac


async def main(email: str, role: str) -> None:
    password = os.environ.get("MMO_BOOTSTRAP_PASSWORD") or getpass.getpass("Password: ")
    async with get_sessionmaker()() as db:
        user = (await db.execute(select(User).where(User.email == auth.normalize_email(email)))).scalar_one_or_none()
        if user is None:
            user = await auth.register(db, email=email, password=password, locale="en", ip=None)
        await rbac.assign_role(db, user_id=user.id, role_code=role, actor_id=None, actor_rank=None)
        await db.commit()
        print(f"user {user.id} <{user.email}> has role {role}")
    await dispose_engine()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--email", required=True)
    p.add_argument("--role", default="superadmin")
    a = p.parse_args()
    asyncio.run(main(a.email, a.role))
