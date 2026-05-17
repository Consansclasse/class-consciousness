# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas Pydantic — contrats /adhesions.

Trois écrans côté frontend, trois schemas :

1. AdhesionCheckoutIn — POST /adhesions/checkout (form submission)
2. AdhesionCheckoutOut — réponse, donne l'URL Stripe à rediriger
3. AdhesionIntentStatusOut — GET /adhesions/intent/{id} (page /adherer/merci)

Pas de schema pour le webhook : c'est du raw bytes vérifié par signature.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from cc_api.models.adhesion_intent import AdhesionIntentStatus
from cc_api.models.membership import MembershipTier

# Tier → (libellé public, montant standard en centimes).
# Le palier MECENE est à montant variable (min 50 000 cents = 500 €) : on
# accepte un override `amount_eur_cents_override` pour ce seul cas.
TIER_DEFAULT_AMOUNTS_CENTS: dict[MembershipTier, int] = {
    MembershipTier.INDIVIDUAL: 900,
    MembershipTier.STRUCTURE: 9900,
    MembershipTier.MECENE: 50000,
}

TIER_LABELS: dict[MembershipTier, str] = {
    MembershipTier.INDIVIDUAL: "Adhésion individuelle — Conscience de classe",
    MembershipTier.STRUCTURE: "Adhésion structure — Conscience de classe",
    MembershipTier.MECENE: "Mécénat — Conscience de classe",
}


class AdhesionCheckoutIn(BaseModel):
    """Données soumises par le formulaire d'adhésion."""

    email: EmailStr
    display_name: str | None = Field(default=None, max_length=255)
    tier: MembershipTier
    solidaire: bool = False
    # Pour le palier MECENE uniquement : permet de monter au-dessus du défaut.
    amount_eur_cents_override: int | None = Field(default=None, ge=50000)
    # Consentement obligatoire — sans ça l'API refuse 422.
    # Le frontend doit présenter une case NON pré-cochée (exigence CNIL).
    consent_data: Literal[True]
    # Newsletter optionnelle — opt-in séparé.
    consent_newsletter: bool = False


class AdhesionCheckoutOut(BaseModel):
    """URL Stripe vers laquelle rediriger immédiatement le navigateur."""

    # Jeton opaque, jamais l'id séquentiel — sert d'identifiant à /adherer/merci.
    public_token: str
    redirect_url: str
    expires_at: datetime


class AdhesionIntentStatusOut(BaseModel):
    """État courant d'une intention — la page /adherer/merci la lit."""

    public_token: str
    status: AdhesionIntentStatus
    tier: MembershipTier
    amount_eur_cents: int
    paid_at: datetime | None
