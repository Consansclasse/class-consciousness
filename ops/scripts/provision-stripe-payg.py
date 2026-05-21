# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provisionne le pay-as-you-go Stripe : un Billing Meter + un Price metered.

Le modèle économique refacture le coût LLM marginal de l'assistant RAG. Côté
Stripe, cela tient en deux objets, créés une fois par compte (test puis live) :

1. un **Meter** qui agrège (`sum`) les tokens déclarés par `billing.meter_event` ;
2. un **Price** récurrent mensuel adossé à ce meter, facturé par tranche de
   1000 tokens (`transform_quantity.divide_by = 1000`, arrondi au plafond).

Idempotent : si un meter actif porte déjà le même `event_name`, il est réutilisé
(Stripe interdit deux meters actifs de même nom). Le Price, lui, est immuable —
le script en crée un neuf à chaque exécution et affiche son id : reportez-le
dans `STRIPE_PRICE_PAYG`.

Usage (depuis apps/api pour disposer du SDK Stripe du projet) :

    STRIPE_SECRET_KEY=sk_test_… \
      uv run python ../../ops/scripts/provision-stripe-payg.py \
      --price-cents 50 --currency eur

`--price-cents` = prix HT, en centimes, pour 1000 tokens facturables.
"""

from __future__ import annotations

import argparse
import os
import sys

import stripe


def _find_active_meter(event_name: str) -> stripe.billing.Meter | None:
    """Renvoie le meter actif portant `event_name`, ou None."""
    for meter in stripe.billing.Meter.list(status="active", limit=100).auto_paging_iter():
        if meter.event_name == event_name:
            return meter
    return None


def _ensure_meter(event_name: str) -> stripe.billing.Meter:
    """Crée le meter (agrégation `sum`, mapping client par `stripe_customer_id`)
    ou réutilise l'existant — Stripe refuse deux meters actifs de même nom."""
    existing = _find_active_meter(event_name)
    if existing is not None:
        print(f"meter réutilisé : {existing.id} (event_name={event_name})")
        return existing
    meter = stripe.billing.Meter.create(
        display_name="Assistant RAG — tokens",
        event_name=event_name,
        default_aggregation={"formula": "sum"},
        value_settings={"event_payload_key": "value"},
        customer_mapping={"type": "by_id", "event_payload_key": "stripe_customer_id"},
    )
    print(f"meter créé : {meter.id} (event_name={event_name})")
    return meter


def _create_price(meter_id: str, currency: str, price_cents: int) -> stripe.Price:
    """Crée le Product + Price metered, facturé par tranche de 1000 tokens."""
    product = stripe.Product.create(name="Assistant RAG — paiement à l'usage")
    price = stripe.Price.create(
        product=product.id,
        currency=currency,
        unit_amount=price_cents,
        billing_scheme="per_unit",
        # divise le total agrégé de tokens par 1000 et arrondit au plafond :
        # `unit_amount` est donc le prix d'une tranche de 1000 tokens.
        transform_quantity={"divide_by": 1000, "round": "up"},
        recurring={"interval": "month", "usage_type": "metered", "meter": meter_id},
    )
    print(f"product créé : {product.id}")
    print(f"price metered créé : {price.id}")
    return price


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--price-cents", type=int, required=True,
        help="prix HT en centimes pour 1000 tokens facturables",
    )
    parser.add_argument("--currency", default="eur")
    parser.add_argument(
        "--event-name", default=os.environ.get("STRIPE_METER_EVENT_NAME", "rag_tokens"),
    )
    args = parser.parse_args()

    secret = os.environ.get("STRIPE_SECRET_KEY")
    if not secret:
        print("STRIPE_SECRET_KEY manquant dans l'environnement", file=sys.stderr)
        return 1
    if args.price_cents <= 0:
        print("--price-cents doit être strictement positif", file=sys.stderr)
        return 1
    stripe.api_key = secret

    meter = _ensure_meter(args.event_name)
    price = _create_price(meter.id, args.currency, args.price_cents)

    print("\n→ à reporter dans .env :")
    print(f"STRIPE_PRICE_PAYG={price.id}")
    print(f"STRIPE_METER_EVENT_NAME={args.event_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
