# SPDX-License-Identifier: AGPL-3.0-or-later
"""Service d'authentification — magic-link sans mot de passe.

Flux : l'utilisateur saisit son email → un `AuthToken` à usage unique (TTL
15 min) est créé, seul son hash SHA-256 est stocké → le lien part par email.
Cliquer le lien consomme le token et ouvre une session.

En dev (pas de SMTP configuré), l'email n'est pas expédié : le lien est
journalisé et renvoyé à l'appelant pour faciliter les tests locaux. En prod,
il part par SMTP via fastapi-mail.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.core.logging import get_logger
from cc_api.core.settings import settings
from cc_api.models.auth_token import AuthToken
from cc_api.models.user import User

log = get_logger(__name__)

# Durée de validité d'un magic-link (cf. docstring de models/auth_token.py).
_TOKEN_TTL = timedelta(minutes=15)


class AuthError(Exception):
    """Magic-link invalide : inexistant, expiré ou déjà consommé."""


def _hash_token(token: str) -> str:
    """SHA-256 hex du token brut — seul le hash est stocké en base."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _get_or_create_user(session: AsyncSession, email: str) -> User:
    """Récupère le User par email, ou le crée SANS consentement.

    `consent_data_at` reste NULL ici : demander un lien ne prouve rien
    (n'importe qui peut saisir l'adresse d'autrui). Le consentement n'est
    horodaté qu'à la vérification du lien — quand le contrôle de l'adresse est
    prouvé. Un compte créé mais jamais vérifié reste donc inerte.
    """
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    user = User(email=email)
    session.add(user)
    await session.flush()
    log.info("auth.user_created", user_id=user.id)
    return user


async def _send_magic_link_email(email: str, link: str) -> None:
    """Expédie le magic-link par SMTP.

    En dev, aucun envoi : le lien est journalisé pour les essais locaux. Hors
    dev sans SMTP configuré, lève AuthError — le token n'est alors JAMAIS ni
    journalisé ni renvoyé au client.
    """
    if not settings.smtp_configured:
        if settings.is_dev:
            log.info("auth.magic_link.dev", email=email, link=link)
            return
        log.error("auth.magic_link.smtp_unconfigured")
        raise AuthError("service d'envoi d'email indisponible")
    config = ConnectionConfig(
        MAIL_USERNAME=settings.smtp_user or "",
        MAIL_PASSWORD=settings.smtp_password or "",
        MAIL_FROM=settings.smtp_from,
        MAIL_PORT=settings.smtp_port,
        MAIL_SERVER=settings.smtp_host or "",
        MAIL_STARTTLS=settings.smtp_starttls,
        MAIL_SSL_TLS=False,
        USE_CREDENTIALS=bool(settings.smtp_user),
    )
    message = MessageSchema(
        subject="Votre lien de connexion — Conscience de classe",
        recipients=[email],
        body=(
            "Bonjour,\n\n"
            "Pour vous connecter, ouvrez ce lien (valable 15 minutes) :\n\n"
            f"{link}\n\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.\n"
        ),
        subtype=MessageType.plain,
    )
    await FastMail(config).send_message(message)
    # L'email est volontairement hors du log — hygiène RGPD : on évite
    # d'enrichir la surface des journaux d'identifiants personnels.
    log.info("auth.magic_link.sent")


async def request_magic_link(session: AsyncSession, email: str) -> str | None:
    """Crée un magic-link pour `email` et l'envoie.

    Renvoie le lien uniquement en environnement dev (facilite les tests
    locaux) ; sinon None — hors dev, le lien ne transite QUE par email, jamais
    par la réponse HTTP.
    """
    user = await _get_or_create_user(session, email)
    # Purge opportuniste des tokens expirés — évite leur accumulation (pas de cron).
    await session.execute(
        delete(AuthToken).where(AuthToken.expires_at < datetime.now(UTC))
    )
    raw_token = secrets.token_urlsafe(32)
    session.add(
        AuthToken(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(UTC) + _TOKEN_TTL,
        )
    )
    await session.commit()

    link = f"{settings.public_web_base}/connexion/verifier?token={raw_token}"
    await _send_magic_link_email(email, link)
    return link if settings.is_dev else None


async def verify_magic_link(session: AsyncSession, token: str) -> User:
    """Consomme un magic-link et renvoie le User.

    La consommation est atomique : un `UPDATE … WHERE used_at IS NULL AND
    expires_at > now()` ne marque la ligne qu'une fois — un double-clic, même
    concurrent, ne peut pas ouvrir deux sessions. En cas d'échec le message est
    volontairement générique (pas d'oracle inconnu / expiré / déjà utilisé).

    Au premier succès, `consent_data_at` est horodaté ici : cliquer le lien
    reçu par email prouve le contrôle de l'adresse — c'est le vrai consentement.
    """
    now = datetime.now(UTC)
    result = await session.execute(
        update(AuthToken)
        .where(
            AuthToken.token_hash == _hash_token(token),
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(AuthToken.user_id)
    )
    row = result.first()
    if row is None:
        raise AuthError("lien de connexion invalide ou expiré")

    user = await session.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        raise AuthError("lien de connexion invalide ou expiré")
    if user.consent_data_at is None:
        user.consent_data_at = now
    await session.commit()
    log.info("auth.verified", user_id=user.id)
    return user
