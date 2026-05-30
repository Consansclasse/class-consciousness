// SPDX-License-Identifier: AGPL-3.0-or-later
// E2E adhésion — un visiteur qui veut soutenir le projet. On teste la
// découvrabilité des paliers, le formulaire de tier, et la robustesse des URLs.

import { expect, test } from "@playwright/test";

test.describe("page /join", () => {
  test("h1 « Adhérer » et titre de page", async ({ page }) => {
    await page.goto("/join");
    await expect(page).toHaveTitle(/Adhérer/);
    await expect(page.getByRole("heading", { level: 1, name: "Adhérer" })).toBeVisible();
  });

  test("explique pourquoi aucun palier n'est encore affiché (état assumé)", async ({ page }) => {
    // Choix de conception assumé : tant que l'association n'est pas déclarée,
    // aucun palier n'est proposé. On vérifie que ce message est bien présent
    // (et non une page vide qui désoriente le visiteur).
    await page.goto("/join");
    await expect(
      page.getByText(/dispositif d'adhésion sera ouvert une fois l'association déclarée/),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: /Explorer le corpus/ })).toHaveAttribute(
      "href",
      "/corpus",
    );
  });
});

test.describe("formulaire de palier /join/[tier]", () => {
  test("le palier individuel propose email, consentement et bouton de paiement", async ({
    page,
  }) => {
    await page.goto("/join/individual");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByLabel(/Email/)).toBeVisible();
    // Le consentement données est obligatoire (case à cocher).
    await expect(page.getByRole("checkbox").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Payer par carte/ })).toBeVisible();
  });

  test("sans consentement : un message d'erreur (role=alert) apparaît", async ({ page }) => {
    await page.goto("/join/individual");
    await page.getByLabel(/Email/).fill("soutien@example.org");
    await page.getByRole("button", { name: /Payer par carte/ }).click();
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole("alert")).toContainText(/consentement/i);
  });

  test("palier inexistant : ne doit pas renvoyer une page applicative 200 vide", async ({ page }) => {
    const res = await page.goto("/join/palier-bidon");
    // Une route SSG non générée devrait répondre 404 (et non une page molle 200).
    expect(res?.status()).toBe(404);
  });
});

test.describe("pages de retour Stripe", () => {
  test("/join/thanks sans intent : message d'attente explicite, pas d'écran cassé", async ({
    page,
  }) => {
    await page.goto("/join/thanks");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText(/identifiant d'adhésion|Confirmation/i)).toBeVisible();
  });

  test("/join/error : aucun débit + chemin de reprise vers /join", async ({ page }) => {
    await page.goto("/join/error");
    await expect(page.getByRole("heading", { level: 1, name: /Aucun montant/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Revenir aux paliers/ })).toHaveAttribute(
      "href",
      "/join",
    );
  });
});
