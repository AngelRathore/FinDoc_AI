"""Grant or revoke the admin role for an existing account from the DB operator shell."""
import argparse

from sqlalchemy import select

from core.config import settings
from db.session import get_engine
from models.user import User, UserRole
from services.auth import normalize_email


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="email address of the account to update")
    parser.add_argument("role", choices=[role.value for role in UserRole])
    args = parser.parse_args()
    if not settings.database_url:
        parser.error("DATABASE_URL is not configured")

    from sqlalchemy.orm import Session

    with Session(get_engine()) as db:
        user = db.scalar(select(User).where(User.email == normalize_email(args.email)))
        if user is None:
            parser.error("No account exists with that email")
        user.role = args.role
        db.commit()
    print(f"Updated role for {normalize_email(args.email)} to {args.role}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
