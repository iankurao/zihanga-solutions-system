"""
One-time script to create or promote a Zehunger Solutions super admin account.

Usage (from project root):
  python -m backend.create_super_admin

You will be prompted for credentials. The account is created with role='super_admin'.
If the email already exists, the script will promote that account to super_admin instead.
"""

import sys
import getpass
from werkzeug.security import generate_password_hash
from backend.database import DatabaseConnection
from backend.passwords import password_problem

def main():
    print("\n=== Zehunger Solutions — Super Admin Setup ===\n")
    db = DatabaseConnection()

    existing = db.fetch_all("SELECT username, email, role FROM users WHERE role = 'super_admin'")
    if existing:
        print("Existing super admin accounts:")
        for u in existing:
            print(f"  - {u['username']} ({u['email']})")
        print()

    print("Enter details for the new super admin account.")
    print("(If the email already exists, that account will be promoted to super_admin.)\n")

    full_name = input("Full Name: ").strip()
    username  = input("Username : ").strip()
    email     = input("Email    : ").strip().lower()
    password  = getpass.getpass("Password : ")
    confirm   = getpass.getpass("Confirm  : ")

    if not all([full_name, username, email, password]):
        print("\nError: All fields are required.")
        sys.exit(1)

    if password != confirm:
        print("\nError: Passwords do not match.")
        sys.exit(1)

    problem = password_problem(password, email=email, username=username)
    if problem:
        print(f"\nError: {problem}.")
        sys.exit(1)

    existing_user = db.fetch_one("SELECT user_id, username FROM users WHERE email = %s", (email,))

    if existing_user:
        db.execute_query(
            "UPDATE users SET role = 'super_admin', is_active = TRUE WHERE email = %s",
            (email,)
        )
        print(f"\nAccount '{existing_user['username']}' promoted to super_admin successfully.")
    else:
        password_hash = generate_password_hash(password)
        db.execute_query(
            "INSERT INTO users (username, full_name, email, password_hash, role, is_active, created_at) VALUES (%s, %s, %s, %s, 'super_admin', TRUE, NOW())",
            (username, full_name, email, password_hash)
        )
        print(f"\nSuper admin account '{username}' created successfully.")

    print("\nYou can now log in at /login and you will be redirected to /zehunger.\n")

if __name__ == '__main__':
    main()
