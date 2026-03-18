"""
Session-based authentication service.

Provides login, logout, and token verification with password hashing,
session tracking, and configurable token expiry.
"""

import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, NamedTuple
from contextlib import contextmanager

from sqlalchemy import (
    create_engine, Column, String, DateTime, Integer, LargeBinary, Boolean
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session as SQLSession
from sqlalchemy.pool import StaticPool

Base = declarative_base()


class User(Base):
    """User account with hashed password."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(LargeBinary, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<User id={self.id} username={self.username}>"


class SessionToken(Base):
    """Active session tokens."""
    __tablename__ = "session_tokens"

    token = Column(String(128), primary_key=True, index=True)
    user_id = Column(String(36), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(512), nullable=True)

    def __repr__(self):
        return f"<SessionToken user_id={self.user_id} token={self.token[:16]}...>"


class VerifyResult(NamedTuple):
    """Result of token verification."""
    valid: bool
    user_id: Optional[str] = None
    username: Optional[str] = None
    reason: Optional[str] = None


class AuthService:
    """Session-based authentication service."""

    def __init__(self, db_path: str = ":memory:", token_expiry_hours: int = 24):
        """
        Initialize auth service.

        Args:
            db_path: SQLite database path (":memory:" for in-memory)
            token_expiry_hours: Session token lifetime in hours
        """
        self.token_expiry_hours = token_expiry_hours

        # Create engine with connection pooling
        engine_kwargs = {}
        if db_path == ":memory:":
            engine_kwargs["poolclass"] = StaticPool
            engine_kwargs["connect_args"] = {"check_same_thread": False}

        self.engine = create_engine(f"sqlite:///{db_path}", **engine_kwargs)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    @contextmanager
    def _get_session(self) -> SQLSession:
        """Context manager for database sessions."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _hash_password(password: str) -> bytes:
        """Hash password using PBKDF2-SHA256."""
        salt = secrets.token_bytes(32)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return salt + key

    @staticmethod
    def _verify_password(password: str, password_hash: bytes) -> bool:
        """Verify password against hash."""
        salt = password_hash[:32]
        stored_key = password_hash[32:]
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return key == stored_key

    @staticmethod
    def _generate_token() -> str:
        """Generate a cryptographically secure session token."""
        return secrets.token_urlsafe(96)

    def register(self, user_id: str, username: str, email: str, password: str) -> bool:
        """
        Register a new user.

        Args:
            user_id: Unique user identifier (UUID recommended)
            username: Username for login
            email: Email address
            password: Plaintext password (will be hashed)

        Returns:
            True if successful, False if user already exists
        """
        with self._get_session() as session:
            existing = session.query(User).filter(
                (User.username == username) | (User.email == email)
            ).first()

            if existing:
                return False

            user = User(
                id=user_id,
                username=username,
                email=email,
                password_hash=self._hash_password(password),
                is_active=True
            )
            session.add(user)
            return True

    def login(
        self,
        username: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Authenticate user and create session.

        Args:
            username: Username
            password: Plaintext password
            ip_address: Client IP address for audit trail
            user_agent: Client user agent for audit trail

        Returns:
            Tuple of (success, token, error_message)
        """
        with self._get_session() as session:
            user = session.query(User).filter(
                (User.username == username) & (User.is_active == True)
            ).first()

            if not user or not self._verify_password(password, user.password_hash):
                return False, None, "Invalid credentials"

            # Create session token
            token = self._generate_token()
            expires_at = datetime.now(timezone.utc) + timedelta(hours=self.token_expiry_hours)

            session_token = SessionToken(
                token=token,
                user_id=user.id,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent
            )
            session.add(session_token)
            return True, token, None

    def verify(self, token: str) -> VerifyResult:
        """
        Verify session token and return user info.

        Args:
            token: Session token

        Returns:
            VerifyResult with validation status and user info
        """
        if not token:
            return VerifyResult(valid=False, reason="Missing token")

        with self._get_session() as session:
            session_token = session.query(SessionToken).filter(
                SessionToken.token == token
            ).first()

            if not session_token:
                return VerifyResult(valid=False, reason="Token not found")

            # Handle timezone-naive datetime from SQLite
            expires_at = session_token.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if datetime.now(timezone.utc) > expires_at:
                session.delete(session_token)
                return VerifyResult(valid=False, reason="Token expired")

            user = session.query(User).filter(User.id == session_token.user_id).first()
            if not user or not user.is_active:
                session.delete(session_token)
                return VerifyResult(valid=False, reason="User not found or inactive")

            return VerifyResult(
                valid=True,
                user_id=user.id,
                username=user.username
            )

    def logout(self, token: str) -> bool:
        """
        Revoke session token.

        Args:
            token: Session token to revoke

        Returns:
            True if token was revoked, False if not found
        """
        with self._get_session() as session:
            session_token = session.query(SessionToken).filter(
                SessionToken.token == token
            ).first()

            if session_token:
                session.delete(session_token)
                return True
            return False

    def revoke_user_sessions(self, user_id: str) -> int:
        """
        Revoke all sessions for a user (e.g., on password change).

        Args:
            user_id: User ID

        Returns:
            Number of sessions revoked
        """
        with self._get_session() as session:
            count = session.query(SessionToken).filter(
                SessionToken.user_id == user_id
            ).delete()
            return count

    def cleanup_expired_tokens(self) -> int:
        """
        Delete expired session tokens.

        Returns:
            Number of tokens deleted
        """
        with self._get_session() as session:
            count = session.query(SessionToken).filter(
                SessionToken.expires_at < datetime.now(timezone.utc)
            ).delete()
            return count
