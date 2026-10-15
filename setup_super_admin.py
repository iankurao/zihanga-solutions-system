#!/usr/bin/env python3
"""Create or promote a super admin account.

Kept for old instructions; it runs the same command as

    python -m backend.create_super_admin

so there is one way to create an administrator, with the app's password
rules. `--test` only checks the database connection and lists existing
super admins, changing nothing.
"""
import sys


def main(argv):
    if '--test' in argv:
        from backend.database import DatabaseConnection

        admins = DatabaseConnection().fetch_all(
            "SELECT username, email, is_active FROM users WHERE role = 'super_admin' ORDER BY username")
        print(f"Database reachable. {len(admins)} super admin account(s):")
        for admin in admins:
            print(f"  - {admin['username']} ({admin['email']}){'' if admin['is_active'] else ' - inactive'}")
        return 0
    from backend.create_super_admin import main as create

    create()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
