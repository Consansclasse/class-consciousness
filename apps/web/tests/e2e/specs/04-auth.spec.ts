// SPDX-License-Identifier: AGPL-3.0-or-later
// E2E authentification — parcours réels : connexion ratée, inscription avec
// validations, mot de passe oublié (anti-énumération), liens cassés/incomplets.
// On ne crée pas de vrai compte ici (pas d'email réel) : on teste le comportement
// UI/UX des formulaires et la robustesse des messages.

import { expect, test } from "@playwright/test";

test.describe("login", () => {
  test("structure : un h1, champs étiquetés, liens secondaires", async ({ page }) => {
    await page.goto("/login");
    await expect(page).toHaveTitle(/Connexion/);
    await expect(page.getByRole("heading", { level: 1, name: "SE CONNECTER" })).toBeVisible();
    await expect(page.getByLabel("Adresse électronique")).toBeVisible();
    await expect(page.getByLabel("Mot de passe")).toBeVisible();
    await expect(page.getByRole("button", { name: "SE CONNECTER" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Créer un compte" })).toHaveAttribute("href", "/register");
    await expect(page.getByRole("link", { name: "Mot de passe oublié ?" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  test("autocomplete correct pour gestionnaires de mots de passe", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel("Adresse électronique")).toHaveAttribute("autocomplete", "email");
    await expect(page.getByLabel("Mot de passe")).toHaveAttribute("autocomplete", "current-password");
  });

  test("identifiants invalides : message d'erreur visible, on reste sur /login", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Adresse électronique").fill("inconnu@example.org");
    await page.getByLabel("Mot de passe").fill("mauvais-mot-de-passe");
    await page.getByRole("button", { name: "SE CONNECTER" }).click();

    // Un message d'échec doit apparaître et l'utilisateur ne doit pas être redirigé.
    await expect(page.locator("#result")).not.toBeEmpty({ timeout: 7000 });
    await expect(page).toHaveURL(/\/login$/);
    // Le bouton doit redevenir actionnable pour réessayer (pas bloqué disabled).
    await expect(page.getByRole("button", { name: "SE CONNECTER" })).toBeEnabled();
  });

  test("UX/a11y : l'erreur de connexion devrait avoir role=alert", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Adresse électronique").fill("inconnu@example.org");
    await page.getByLabel("Mot de passe").fill("mauvais-mot-de-passe");
    await page.getByRole("button", { name: "SE CONNECTER" }).click();
    await expect(page.locator("#result")).not.toBeEmpty({ timeout: 7000 });
    // Une erreur d'action devrait être annoncée fermement (role=alert / aria-live=assertive).
    await expect(page.getByRole("alert")).toBeVisible();
  });
});

test.describe("register", () => {
  test("structure et contraintes de mot de passe", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByRole("heading", { level: 1, name: "CRÉER UN COMPTE" })).toBeVisible();
    await expect(page.getByLabel("Mot de passe")).toHaveAttribute("minlength", "10");
    await expect(page.getByLabel("Mot de passe")).toHaveAttribute("autocomplete", "new-password");
    await expect(page.getByRole("checkbox")).toBeVisible();
  });

  test("sans cocher le consentement, aucune requête réseau n'est émise", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Adresse électronique").fill("nouveau@example.org");
    await page.getByLabel("Mot de passe").fill("motdepasse-long");

    let registerCalled = false;
    page.on("request", (req) => {
      if (req.url().includes("/auth/register")) registerCalled = true;
    });
    await page.getByRole("button", { name: "CRÉER LE COMPTE" }).click();
    await page.waitForTimeout(800);
    expect(registerCalled, "le consentement non coché doit bloquer la soumission").toBe(false);
  });

  test("le mot de passe trop court est refusé par la validation native", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Adresse électronique").fill("nouveau@example.org");
    await page.getByLabel("Mot de passe").fill("court");
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "CRÉER LE COMPTE" }).click();
    // minlength=10 → le champ doit être invalide côté navigateur, pas de succès.
    const valid = await page.getByLabel("Mot de passe").evaluate(
      (el: HTMLInputElement) => el.validity.valid,
    );
    expect(valid).toBe(false);
  });
});

test.describe("mot de passe oublié — anti-énumération", () => {
  test("réponse générique quelle que soit l'adresse", async ({ page }) => {
    await page.goto("/forgot-password");
    await page.getByLabel("Adresse électronique").fill("peut-etre-inexistant@example.org");
    await page.getByRole("button", { name: "ENVOYER LE LIEN" }).click();
    await expect(page.getByText(/Si un compte correspond à cette adresse/)).toBeVisible({
      timeout: 7000,
    });
  });
});

test.describe("liens d'action incomplets (robustesse UX)", () => {
  test("reset-password sans token : message clair + lien de secours", async ({ page }) => {
    await page.goto("/reset-password");
    await expect(page.getByText(/lien de réinitialisation est incomplet/)).toBeVisible();
    await expect(page.getByRole("link", { name: /Demander un nouveau lien/ })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  test("verify-email sans token : message clair + chemin de reprise", async ({ page }) => {
    await page.goto("/verify-email");
    await expect(page.getByText(/lien de vérification est incomplet/)).toBeVisible();
    await expect(page.getByRole("link", { name: /Créer un compte/ })).toBeVisible();
  });

  test("verify-email avec token invalide : message d'expiration + reprise", async ({ page }) => {
    await page.goto("/verify-email?token=token-bidon-invalide");
    await expect(page.getByText(/invalide ou expiré/)).toBeVisible({ timeout: 7000 });
    await expect(page.getByRole("link", { name: /Recommencer l'inscription/ })).toBeVisible();
  });
});
