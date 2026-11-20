"""
Create a sign-in account, or set a new password for one that exists.

    PYTHONPATH=. python backend/scripts/create_user.py someone@firm.co.uk "Their Name"

The password is asked for on the screen (not shown, not saved anywhere but as a hash in the users table).
"""

import getpass
import sys

from backend.app.core.database import SessionLocal, engine
from backend.app.models.database import User
from backend.app.services.shared.auth import create_or_update_user


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    email = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else None
    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("Use at least 8 characters.")
        sys.exit(1)
    if getpass.getpass("Password again: ") != password:
        print("The two passwords are different.")
        sys.exit(1)
    User.__table__.create(bind=engine, checkfirst=True)
    db = SessionLocal()
    user = create_or_update_user(db, email, password, name)
    print(f"Account ready: {user.email}")


if __name__ == "__main__":
    main()
