# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas Pydantic — contrats /abonnements (souscription, portail, statut)."""

from __future__ import annotations

from datetime import datetime

from cc_api.schemas.corpus import _CamelModel


class AbonnementCheckoutOut(_CamelModel):
    """URL Stripe Checkout vers laquelle rediriger le navigateur."""

    redirect_url: str


class AbonnementPortalOut(_CamelModel):
    """URL du Customer Portal Stripe (résiliation, moyen de paiement)."""

    portal_url: str


class AbonnementStatusOut(_CamelModel):
    """État de l'abonnement de l'utilisateur courant — lu par GET /abonnements/me."""

    active: bool  # un abonnement ACTIVE/TRIALING couvre-t-il la date du jour ?
    status: str | None  # statut Stripe du dernier abonnement (None si aucun)
    current_period_end: datetime | None
    cancel_at_period_end: bool
