import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.security.encryption import encryption
from app.db.session import async_session_maker
from app.modules.connections.models import ProviderAccount
from app.modules.trello.models import TrelloOAuthState


async def rotate_encrypted_values() -> int:
    """Re-encrypt persisted provider credentials and pending OAuth verifiers."""
    if not settings.encryption_fallback_keys:
        raise RuntimeError("Set the previous ENCRYPTION_KEY in ENCRYPTION_FALLBACK_KEYS first.")

    async with async_session_maker() as session:
        accounts = (await session.scalars(select(ProviderAccount))).all()
        oauth_states = (await session.scalars(select(TrelloOAuthState))).all()

        for account in accounts:
            account.encrypted_token = encryption.rotate(account.encrypted_token)
        for oauth_state in oauth_states:
            oauth_state.encrypted_code_verifier = encryption.rotate(
                oauth_state.encrypted_code_verifier
            )

        await session.commit()
        return len(accounts) + len(oauth_states)


def main() -> None:
    count = asyncio.run(rotate_encrypted_values())
    print(f"Re-encrypted {count} stored values with the primary encryption key.")


if __name__ == "__main__":
    main()
