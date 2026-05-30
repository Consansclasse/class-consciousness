// SPDX-License-Identifier: AGPL-3.0-or-later
// E2E accueil — parcours d'un visiteur qui découvre le site : héro, CTA vers
// l'assistant, exemples pré-remplis, ancre vers le projet, accordéon FAQ.

import { expect, test } from "@playwright/test";

test.describe("accueil — héro et appels à l'action", () => {
  test("un seul h1, titre de page correct", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/Conscience de classe/);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(
      page.getByRole("heading", { level: 1, name: "Outil pour la révolution communiste." }),
    ).toBeVisible();
  });

  test("le CTA principal mène à l'assistant (ou à la porte de connexion)", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "POSEZ VOTRE QUESTION" }).click();
    // L'assistant exige une session : un visiteur anonyme atterrit sur /chat
    // puis est redirigé vers /login. Les deux sont des destinations « assistant ».
    await expect(page).toHaveURL(/\/(chat|login)/);
  });

  test("UX : cliquer un exemple ne doit pas perdre la question posée", async ({ page }) => {
    await page.goto("/");
    const example = page.getByRole("button", { name: /^Bilan/ }).first();
    await example.click();
    // L'anonyme est renvoyé vers /login, mais la question doit survivre :
    // soit directement en ?q= (si sur /chat), soit conservée dans ?next=… pour
    // y revenir après connexion.
    const url = new URL(page.url());
    const directQ = url.searchParams.get("q");
    const next = url.searchParams.get("next") ?? "";
    expect(
      directQ !== null || /[?&]q=/.test(decodeURIComponent(next)),
      "la question doit survivre à la navigation (q= direct ou via next=)",
    ).toBe(true);
  });

  test("le lien « Explorer le projet » défile vers la section projet", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Explorer le projet" }).click();
    await expect(page).toHaveURL(/#projet$/);
    await expect(page.getByRole("heading", { name: "Le projet, ouvertement." })).toBeInViewport();
  });
});

test.describe("accueil — accordéon FAQ projet", () => {
  test("une question s'ouvre au clic et révèle sa réponse", async ({ page }) => {
    await page.goto("/");
    const details = page.locator("details").filter({ hasText: "Pourquoi ce projet existe" });
    await expect(details).not.toHaveAttribute("open", /.*/);
    await details.locator("summary").click();
    await expect(details).toHaveAttribute("open", "");
  });

  test("UX/a11y : le résumé d'accordéon annonce son état via aria-expanded", async ({ page }) => {
    await page.goto("/");
    // Les <details> natifs n'exposent pas aria-expanded ; un summary accessible
    // devrait le porter pour les lecteurs d'écran.
    const firstSummary = page.locator("details summary").first();
    await expect(firstSummary).toHaveAttribute("aria-expanded", /true|false/);
  });
});

test.describe("accueil — section manifeste", () => {
  // Tâche de contenu en attente (le manifeste reste à rédiger) — ce n'est pas un
  // bug de code mais un placeholder. On garde le test visible via fixme.
  test.fixme("la section manifeste ne doit pas être un placeholder « ( à faire ) »", async ({ page }) => {
    await page.goto("/");
    const manifesto = page
      .getByRole("heading", { name: "Manifeste" })
      .locator("xpath=ancestor::section[1]");
    // Régression contenu : un visiteur ne doit jamais voir un placeholder de chantier.
    await expect(manifesto).not.toContainText("( à faire )");
  });
});

test.describe("règles UI dures — palette stricte (toutes pages clés)", () => {
  for (const path of ["/", "/corpus", "/help", "/contact", "/join", "/login", "/register"]) {
    test(`aucun gris ni gras sur ${path}`, async ({ page }) => {
      await page.goto(path);
      const grays = await page
        .locator('[class*="text-gray"], [class*="bg-gray"], [class*="text-slate"], [class*="bg-slate"]')
        .count();
      expect(grays, "classes grises interdites par la palette stricte").toBe(0);
      const bold = await page.locator('strong, [class*="font-bold"], [class*="font-semibold"]').count();
      expect(bold, "<strong>/font-bold interdits par la règle typographique").toBe(0);
    });
  }
});
