"""
Run this script from the backend/ directory to create the platform admin user.

    cd backend
    ADMIN_EMAIL=admin@airyield.com ADMIN_PASSWORD=<secret> python create_platform_admin.py

Required environment variables:
    ADMIN_PASSWORD  — password for the platform admin account

Optional environment variables:
    ADMIN_EMAIL     — defaults to admin@airyield.com
    ADMIN_FULL_NAME — defaults to Platform Admin
"""

import asyncio
import os
import sys
from datetime import datetime

from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.models.user import UserRole
from app.utils.security import hash_password

EMAIL     = os.getenv("ADMIN_EMAIL", "admin@airyield.com")
FULL_NAME = os.getenv("ADMIN_FULL_NAME", "Platform Admin")
PASSWORD  = os.getenv("ADMIN_PASSWORD")

if not PASSWORD:
    print("[!] Error: ADMIN_PASSWORD environment variable is required.")
    print("    Set it before running: ADMIN_PASSWORD=<secret> python create_platform_admin.py")
    sys.exit(1)


async def main() -> None:
    hashed = hash_password(PASSWORD)

    async with AsyncSessionLocal() as session:
        # Check if user already exists
        result = await session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": EMAIL},
        )
        existing = result.fetchone()

        if existing:
            print(f"[!] User '{EMAIL}' already exists (id={existing[0]}). Nothing inserted.")
            return

        await session.execute(
            text("""
                INSERT INTO users
                    (email, full_name, hashed_password, role, tenant_id, is_active, created_at, updated_at)
                VALUES
                    (:email, :full_name, :hashed_password, :role, NULL, true, :now, :now)
            """),
            {
                "email":           EMAIL,
                "full_name":       FULL_NAME,
                "hashed_password": hashed,
                "role":            UserRole.PLATFORM_ADMIN.name,  # DB stores enum NAME not value
                "now":             datetime.utcnow(),
            },
        )
        await session.commit()

    print(f"[+] Platform admin created successfully.")
    print(f"    Email   : {EMAIL}")
    print(f"    Password: {PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
