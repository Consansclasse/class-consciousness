# SPDX-License-Identifier: AGPL-3.0-or-later
"""Service d'authentification — email + mot de passe.

Flux : inscription (email + mot de passe + consentement) → email de confirmation
→ la connexion par mot de passe n'est ouverte qu'une fois l'email vérifié.
Réinitialisation du mot de passe par email. Aucun magic-link.

Les tokens d'email (vérification, réinitialisation) sont à usage unique : seul
leur hash SHA-256 est stocké, et leur `purpose` borne ce qu'ils peuvent
consommer. Les mots de passe sont hachés en Argon2id (`core/security`).

En dev (pas de SMTP), l'email n'est pas expédié : le lien est journalisé et
renvoyé à l'appelant pour faciliter les tests. En prod sans SMTP, lever
`AuthError` — un lien ne doit jamais transiter par la réponse HTTP en prod.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.core.logging import get_logger
from cc_api.core.security import hash_password, verify_password
from cc_api.core.settings import settings
from cc_api.models.auth_token import AuthToken, TokenPurpose
from cc_api.models.user import User

log = get_logger(__name__)

# Durées de validité des tokens email. Vérification d'adresse : confortable
# (24 h). Réinitialisation de mot de passe : court (1 h), surface réduite.
_VERIFY_TTL = timedelta(hours=24)
_RESET_TTL = timedelta(hours=1)

# Hash factice : on le « vérifie » quand l'email est inconnu pour égaliser le
# temps de réponse — empêche d'inférer l'existence d'un compte par timing.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


class AuthError(Exception):
    """Échec d'authentification — identifiants invalides, token expiré, etc."""


class PasswordlessAccountError(AuthError):
    """Le compte n'a pas de mot de passe (créé par don) : impossible de le changer
    ici — passer par « mot de passe oublié » pour en définir un."""


def _hash_token(token: str) -> str:
    """SHA-256 hex du token brut — seul le hash est stocké en base."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _issue_token(
    session: AsyncSession, user_id: int, purpose: TokenPurpose, ttl: timedelta
) -> str:
    """Crée un token email à usage unique et renvoie sa valeur brute.

    Purge opportuniste des tokens expirés (pas de cron) avant émission.
    """
    await session.execute(
        delete(AuthToken).where(AuthToken.expires_at < datetime.now(UTC))
    )
    raw = secrets.token_urlsafe(32)
    session.add(
        AuthToken(
            user_id=user_id,
            token_hash=_hash_token(raw),
            purpose=purpose,
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    return raw


async def _consume_token(
    session: AsyncSession, token: str, purpose: TokenPurpose
) -> int | None:
    """Consomme atomiquement un token du `purpose` attendu → renvoie le user_id.

    `UPDATE … WHERE used_at IS NULL AND expires_at > now() AND purpose = :p` ne
    marque la ligne qu'une fois : un double-clic, même concurrent, ne consomme
    pas deux fois. Renvoie None si le token est inconnu, expiré, déjà utilisé ou
    d'un autre purpose.
    """
    result = await session.execute(
        update(AuthToken)
        .where(
            AuthToken.token_hash == _hash_token(token),
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > datetime.now(UTC),
        )
        .values(used_at=datetime.now(UTC))
        .returning(AuthToken.user_id)
    )
    row = result.first()
    return int(row.user_id) if row is not None else None


async def _send_email(email: str, subject: str, body: str, link: str) -> None:
    """Expédie un email transactionnel contenant `link`.

    En dev sans SMTP : journalise et renvoie (le lien est rendu à l'appelant
    pour les tests). En prod sans SMTP : `AuthError` — le lien ne doit jamais
    transiter par la réponse HTTP. L'email reste hors des logs (hygiène RGPD).
    """
    if not settings.smtp_configured:
        if settings.is_dev:
            log.info("auth.email.dev", email=email, link=link)
            return
        log.error("auth.email.smtp_unconfigured")
        raise AuthError("service d'envoi d'email indisponible")
    config = ConnectionConfig(
        MAIL_USERNAME=settings.smtp_user or "",
        MAIL_PASSWORD=SecretStr(settings.smtp_password or ""),
        MAIL_FROM=settings.smtp_from,
        MAIL_PORT=settings.smtp_port,
        MAIL_SERVER=settings.smtp_host or "",
        MAIL_STARTTLS=settings.smtp_starttls,
        MAIL_SSL_TLS=False,
        USE_CREDENTIALS=bool(settings.smtp_user),
    )
    message = MessageSchema(
        subject=subject,
        recipients=[email],  # type: ignore[list-item]
        body=body,
        subtype=MessageType.plain,
    )
    await FastMail(config).send_message(message)
    log.info("auth.email.sent")


def _verify_link(token: str) -> str:
    return f"{settings.public_web_base}/verify-email?token={token}"


def _reset_link(token: str) -> str:
    return f"{settings.public_web_base}/reset-password?token={token}"


async def register(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None,
    consent_newsletter: bool,
) -> str | None:
    """Inscrit un compte et envoie l'email de vérification.

    Idempotent et sans oracle d'énumération (le router répond toujours de façon
    générique) :
    - email neuf → compte non vérifié créé, email de vérification envoyé ;
    - email connu mais non vérifié (inscription inachevée, ou compte créé par un
      don) → mot de passe (re)posé, nouvel email de vérification ;
    - email déjà vérifié → aucun envoi (on ne révèle pas le compte).

    Renvoie le lien de vérification en dev uniquement, sinon None.
    """
    now = datetime.now(UTC)
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if user is not None and user.email_verified_at is not None:
        await session.commit()
        log.info("auth.register.already_active", user_id=user.id)
        return None

    if user is None:
        user = User(email=email)
        session.add(user)
        await session.flush()
        log.info("auth.user_created", user_id=user.id)

    user.password_hash = hash_password(password)
    if display_name:
        user.display_name = display_name
    # Consentement RGPD horodaté à l'inscription (la case a été cochée).
    if user.consent_data_at is None:
        user.consent_data_at = now
    if consent_newsletter and user.consent_newsletter_at is None:
        user.consent_newsletter_at = now

    raw = await _issue_token(session, user.id, TokenPurpose.VERIFY_EMAIL, _VERIFY_TTL)
    link = _verify_link(raw)
    await session.commit()
    await _send_email(
        email,
        "Confirmez votre adresse — Conscience de classe",
        "Bonjour,\n\nConfirmez votre adresse pour activer votre compte "
        f"(lien valable 24 heures) :\n\n{link}\n\n"
        "Si vous n'êtes pas à l'origine de cette inscription, ignorez ce message.\n",
        link,
    )
    return link if settings.is_dev else None


async def verify_email(session: AsyncSession, token: str) -> User:
    """Consomme un token de vérification et marque l'email comme vérifié.

    Au succès, ouvre l'accès : `email_verified_at` est horodaté (cliquer le lien
    prouve le contrôle de l'adresse).
    """
    user_id = await _consume_token(session, token, TokenPurpose.VERIFY_EMAIL)
    if user_id is None:
        raise AuthError("lien de vérification invalide ou expiré")
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AuthError("lien de vérification invalide ou expiré")
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    await session.commit()
    log.info("auth.email_verified", user_id=user.id)
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """Valide email + mot de passe → renvoie le User, ou lève AuthError.

    Message générique sur identifiants invalides (pas d'oracle email/mot de
    passe). Un compte sans mot de passe (créé par don) ou non vérifié est
    refusé. Le temps de réponse est égalisé même si l'email est inconnu.
    """
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None or user.password_hash is None or user.deleted_at is not None:
        verify_password(_DUMMY_HASH, password)  # égalise le timing
        raise AuthError("identifiants invalides")
    if not verify_password(user.password_hash, password):
        raise AuthError("identifiants invalides")
    if user.email_verified_at is None:
        raise AuthError("email non vérifié")
    return user


async def request_password_reset(session: AsyncSession, email: str) -> str | None:
    """Envoie un email de réinitialisation si le compte existe et est vérifié.

    Réponse toujours générique côté router (pas d'oracle). Renvoie le lien en
    dev uniquement, sinon None.
    """
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if (
        user is None
        or user.password_hash is None
        or user.email_verified_at is None
        or user.deleted_at is not None
    ):
        return None
    raw = await _issue_token(session, user.id, TokenPurpose.RESET_PASSWORD, _RESET_TTL)
    link = _reset_link(raw)
    await session.commit()
    await _send_email(
        email,
        "Réinitialisation de votre mot de passe — Conscience de classe",
        "Bonjour,\n\npour choisir un nouveau mot de passe, ouvrez ce lien "
        f"(valable 1 heure) :\n\n{link}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.\n",
        link,
    )
    return link if settings.is_dev else None


async def reset_password(session: AsyncSession, token: str, new_password: str) -> User:
    """Consomme un token de reset et remplace le mot de passe.

    Réinitialiser prouve aussi le contrôle de l'adresse : un email non encore
    vérifié l'est alors implicitement.
    """
    user_id = await _consume_token(session, token, TokenPurpose.RESET_PASSWORD)
    if user_id is None:
        raise AuthError("lien de réinitialisation invalide ou expiré")
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AuthError("lien de réinitialisation invalide ou expiré")
    user.password_hash = hash_password(new_password)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    await session.commit()
    log.info("auth.password_reset", user_id=user.id)
    return user


async def update_profile(
    session: AsyncSession, user_id: int, *, display_name: str | None
) -> User:
    """Met à jour le profil de l'utilisateur connecté (nom affiché).

    `display_name` vide ou blanc est normalisé à `None`.
    """
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AuthError("compte introuvable")
    normalized = display_name.strip() if display_name else None
    user.display_name = normalized or None
    await session.commit()
    log.info("auth.profile_updated", user_id=user.id)
    return user


async def change_password(
    session: AsyncSession,
    user_id: int,
    *,
    current_password: str,
    new_password: str,
) -> User:
    """Change le mot de passe d'un utilisateur connecté, après ré-authentification.

    Lève `PasswordlessAccountError` si le compte n'a pas de mot de passe (don),
    `AuthError` si le mot de passe actuel est faux ou si le nouveau est identique.
    """
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AuthError("compte introuvable")
    if user.password_hash is None:
        raise PasswordlessAccountError("ce compte n'a pas de mot de passe")
    if not verify_password(user.password_hash, current_password):
        raise AuthError("mot de passe actuel incorrect")
    if verify_password(user.password_hash, new_password):
        raise AuthError("le nouveau mot de passe doit différer de l'ancien")
    user.password_hash = hash_password(new_password)
    await session.commit()
    log.info("auth.password_changed", user_id=user.id)
    return user


async def delete_account(session: AsyncSession, user_id: int) -> None:
    """Supprime le compte de l'utilisateur connecté (soft-delete RGPD `deleted_at`).

    Idempotent : un compte déjà supprimé ou introuvable est un no-op.
    """
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return
    user.deleted_at = datetime.now(UTC)
    await session.commit()
    log.info("auth.account_deleted", user_id=user_id)
