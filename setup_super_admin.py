#!/usr/bin/env python3
"""
Zehunger Super Admin Setup Script
Run once to create the super admin account.

Usage:
  python setup_super_admin.py           # interactive setup
  python setup_super_admin.py --test    # dry-run (no changes made)
"""

import sys
import os
import getpass
import re

# Ensure .pythonlibs is on path (Replit environment)
sys.path.insert(0, '/home/runner/workspace/.pythonlibs/lib/python3.11/site-packages')

import psycopg2
from werkzeug.security import generate_password_hash

DATABASE_URL = os.getenv('DATABASE_URL', '')

DB_HOST = os.getenv('PGHOST', 'localhost')
DB_USER = os.getenv('PGUSER', 'postgres')
DB_PASSWORD = os.getenv('PGPASSWORD', '')
DB_NAME = os.getenv('PGDATABASE', 'bsf_farm')
DB_PORT = os.getenv('PGPORT', '5432')


def connect():
    return psycopg2.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT,
    )


def validate_email(email):
    return re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email) is not None


def validate_password(password):
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number."
    if not re.search(r'[@$!%*?&]', password):
        return False, "Password must contain at least one special character (@$!%*?&)."
    return True, ""


def prompt_input(label, secret=False, validator=None, error_msg=None):
    while True:
        try:
            if secret and sys.stdin.isatty():
                value = getpass.getpass(f"  {label}: ")
            else:
                value = input(f"  {label}: ").strip()
        except EOFError:
            print("\n  [ERROR] Unexpected end of input. Aborting.\n")
            sys.exit(1)

        if not value:
            print(f"  [!] {label} cannot be empty. Please try again.")
            continue

        if validator:
            result = validator(value)
            if isinstance(result, tuple):
                ok, msg = result
            else:
                ok, msg = result, error_msg or "Invalid value."
            if not ok:
                print(f"  [!] {msg} Please try again.")
                continue

        return value


def run(test_mode=False):
    print()
    print("=" * 55)
    print("  Zehunger Solutions — Super Admin Account Setup")
    print("=" * 55)

    if test_mode:
        print("\n  [TEST MODE] No changes will be written to the database.\n")
    else:
        print("\n  Fill in the details for the super admin account.\n")

    username = prompt_input("Username (no spaces)")
    full_name = prompt_input("Full Name")
    email = prompt_input(
        "Email Address",
        validator=lambda v: (validate_email(v), "Please enter a valid email address.")
    )
    password = prompt_input(
        "Password",
        secret=True,
        validator=validate_password,
    )
    confirm = prompt_input("Confirm Password", secret=True)

    if password != confirm:
        print("\n  [ERROR] Passwords do not match. Aborting.\n")
        sys.exit(1)

    print()

    if test_mode:
        print("  [TEST] Checking database connection...", end=" ")
        try:
            conn = connect()
            conn.close()
            print("OK")
        except Exception as e:
            print(f"FAILED\n  [ERROR] {e}\n")
            sys.exit(1)

        print("  [TEST] Inputs collected:")
        print(f"         Username  : {username}")
        print(f"         Full Name : {full_name}")
        print(f"         Email     : {email}")
        print(f"         Password  : {'*' * len(password)}")
        print()
        print("  [TEST] Password validation: PASSED")
        print("  [TEST] Email validation   : PASSED")
        print()
        print("  Dry run complete. Re-run without --test to create the account.")
        print()
        return

    # --- Live mode ---
    print("  Connecting to database...", end=" ")
    try:
        conn = connect()
        print("OK")
    except Exception as e:
        print(f"FAILED\n  [ERROR] {e}\n")
        sys.exit(1)

    cursor = conn.cursor()

    # Check for existing super admin
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'super_admin'")
    existing = cursor.fetchone()[0]
    if existing > 0:
        cursor.execute("SELECT username, email FROM users WHERE role = 'super_admin'")
        rows = cursor.fetchall()
        print("\n  [WARNING] A super admin account already exists:")
        for row in rows:
            print(f"            username={row[0]}, email={row[1]}")
        answer = input("\n  Do you want to create another one? (yes/no): ").strip().lower()
        if answer != 'yes':
            print("\n  Aborted. No changes made.\n")
            cursor.close()
            conn.close()
            sys.exit(0)

    # Check for duplicate username / email
    cursor.execute("SELECT 1 FROM users WHERE username = %s", (username,))
    if cursor.fetchone():
        print(f"\n  [ERROR] Username '{username}' is already taken.\n")
        cursor.close()
        conn.close()
        sys.exit(1)

    cursor.execute("SELECT 1 FROM users WHERE email = %s", (email,))
    if cursor.fetchone():
        print(f"\n  [ERROR] Email '{email}' is already registered.\n")
        cursor.close()
        conn.close()
        sys.exit(1)

    # Create the account
    print("  Creating super admin account...", end=" ")
    try:
        password_hash = generate_password_hash(password)
        cursor.execute(
            """
            INSERT INTO users (username, full_name, email, password_hash, role, is_active, created_at)
            VALUES (%s, %s, %s, %s, 'super_admin', TRUE, NOW())
            """,
            (username, full_name, email, password_hash),
        )
        conn.commit()
        print("OK")
    except Exception as e:
        conn.rollback()
        print(f"FAILED\n  [ERROR] {e}\n")
        cursor.close()
        conn.close()
        sys.exit(1)

    # Verify
    cursor.execute(
        "SELECT user_id, username, full_name, email, role, is_active FROM users WHERE email = %s",
        (email,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    print()
    print("  Super admin account created successfully!")
    print()
    print(f"    User ID   : {row[0]}")
    print(f"    Username  : {row[1]}")
    print(f"    Full Name : {row[2]}")
    print(f"    Email     : {row[3]}")
    print(f"    Role      : {row[4]}")
    print(f"    Active    : {row[5]}")
    print()
    print("  You can now log in at /login using the email and password above.")
    print("=" * 55)
    print()


if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    run(test_mode=test_mode)
