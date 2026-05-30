// SPDX-License-Identifier: AGPL-3.0-or-later
// E2E navigation — header overlay (menu plein écran à onglets), thème, footer.
// On teste comme un vrai utilisateur : ouvrir le menu, changer d'onglet, fermer
// au clavier, basculer le thème et vérifier la persistance.

import { expect, test } from "@playwright/test";

test.describe("navigation — header overlay plein écran", () => {
  test("le menu s'ouvre via le hamburger et se ferme avec Échap", async ({ page }) => {
    await page.goto("/");

    const overlay = page.getByRole("dialog", { name: "Navigation principale" });
    // Le dialog existe dans le DOM mais ne doit pas être actif au repos.
    await expect(overlay).toHaveAttribute("data-open", "false");

    await page.getByRole("button", { name: "Ouvrir le menu de navigation" }).first().click();
    await expect(overlay).toHaveAttribute("data-open", "true");
    // aria-expanded du bouton doit suivre l'état.
    await expect(
      page.getByRole("button", { name: "Ouvrir le menu de navigation" }).first(),
    ).toHaveAttribute("aria-expanded", "true");

    await page.keyboard.press("Escape");
    await expect(overlay).toHaveAttribute("data-open", "false");
  });

  test("les onglets LE PROJET / INFO révèlent leurs liens", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Ouvrir le menu de navigation" }).first().click();

    // On scope au dialog de navigation (le footer de l'accueil contient aussi
    // un lien « Contact » → on évite la collision de noms).
    const menu = page.getByRole("dialog", { name: "Navigation principale" });

    // Onglet LE PROJET → liens "L'assistant" et "Adhérer".
    await menu.getByRole("button", { name: "LE PROJET" }).first().click();
    await expect(menu.getByRole("link", { name: "L'assistant" })).toBeVisible();
    await expect(menu.getByRole("link", { name: "Adhérer" })).toBeVisible();

    // Onglet INFO → Contact / Aide / Confidentialité.
    await menu.getByRole("button", { name: "INFO" }).first().click();
    await expect(menu.getByRole("link", { name: "Contact", exact: true })).toBeVisible();
    await expect(menu.getByRole("link", { name: "Aide" })).toBeVisible();
    await expect(menu.getByRole("link", { name: "Confidentialité" })).toBeVisible();
  });

  test("cliquer un lien du menu navigue et ferme l'overlay", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Ouvrir le menu de navigation" }).first().click();
    await page.getByRole("button", { name: "INFO" }).first().click();
    await page.getByRole("link", { name: "Aide" }).click();
    await expect(page).toHaveURL(/\/help$/);
    await expect(page.getByRole("heading", { level: 1, name: "Aide" })).toBeVisible();
  });

  test("le verrou de défilement du body est libéré après fermeture du menu", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Ouvrir le menu de navigation" }).first().click();
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe("hidden");
    await page.keyboard.press("Escape");
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe("");
  });
});

test.describe("thème clair / sombre", () => {
  test("le bouton bascule la classe .dark et persiste le choix", async ({ page }) => {
    await page.goto("/");
    const toggle = page.getByRole("button", { name: /Basculer le thème/ });

    const wasDark = await page.evaluate(() =>
      document.documentElement.classList.contains("dark"),
    );
    await toggle.click();
    const nowDark = await page.evaluate(() =>
      document.documentElement.classList.contains("dark"),
    );
    expect(nowDark).toBe(!wasDark);

    // localStorage doit refléter le nouvel état.
    const stored = await page.evaluate(() => localStorage.getItem("theme"));
    expect(stored).toBe(nowDark ? "dark" : "light");

    // Le choix persiste après rechargement (pas de flash + pas de retour au défaut).
    await page.reload();
    const afterReload = await page.evaluate(() =>
      document.documentElement.classList.contains("dark"),
    );
    expect(afterReload).toBe(nowDark);
  });

  test("UX/a11y : le bouton de thème expose son état via aria-pressed", async ({ page }) => {
    await page.goto("/");
    const toggle = page.getByRole("button", { name: /Basculer le thème/ });
    // Un bouton bascule binaire doit annoncer son état aux lecteurs d'écran.
    await expect(toggle).toHaveAttribute("aria-pressed", /true|false/);
  });
});

test.describe("footer", () => {
  test("expose une navigation réseaux sociaux nommée avec 4 liens externes sûrs", async ({
    page,
  }) => {
    await page.goto("/");
    const social = page.getByRole("navigation", { name: "Réseaux sociaux" });
    await expect(social).toBeVisible();
    for (const name of ["Facebook", "Instagram", "GitHub", "TikTok"]) {
      const link = social.getByRole("link", { name });
      await expect(link).toHaveAttribute("target", "_blank");
      await expect(link).toHaveAttribute("rel", /noopener/);
    }
  });

  test("le lien de marque du footer (accueil) ramène à l'accueil", async ({ page }) => {
    // NB : le footer n'existe que sur l'accueil (cf. 08 — footer absent ailleurs).
    await page.goto("/corpus");
    await page.goto("/");
    await page.locator("footer").getByRole("link", { name: "Conscience de classe" }).first().click();
    await expect(page).toHaveURL(/\/$/);
  });
});
