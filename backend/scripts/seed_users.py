"""
Seed 3 hardcoded users: Andrés (admin), Iván (admin), Liz (contador).
Run: python -m scripts.seed_users
"""
import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from core.auth import hash_password

USERS = [
    {"name": "Andrés Sanjuan", "email": "andres@roddos.com", "role": "admin", "password": "roddos2026"},
    {"name": "Iván Echeverri", "email": "ivan@roddos.com", "role": "admin", "password": "roddos2026"},
    {"name": "Liz", "email": "liz@roddos.com", "role": "contador", "password": "roddos2026"},
]


async def seed():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    for user in USERS:
        existing = await db.users.find_one({"email": user["email"]})
        if existing:
            print(f"  skip {user['email']} (already exists)")
            continue

        await db.users.insert_one({
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "password_hash": hash_password(user["password"]),
        })
        print(f"  created {user['email']} ({user['role']})")

    client.close()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
