// SPDX-License-Identifier: AGPL-3.0-or-later
// E2E lecture — parcours d'un lecteur : il ouvre le corpus, déplie un numéro,
// clique un article, lit, lance la lecture audio (TTS). On teste aussi la
// robustesse des URLs d'article inexistantes.
//
// Dépend du seed démo (issue "bilan-demo" / article "note-de-demonstration"),
// inséré via seed_demo_lecture.py et présent en base de dev.

import { expect, test } from "@playwright/test";

const DEMO_ISSUE = "bilan-demo";
const DEMO_ARTICLE = "note-de-demonstration";

test.describe("corpus — liste et navigation vers un article", () => {
  test("la page corpus affiche un compteur et le numéro de démonstration", async ({ page }) => {
    await page.goto("/corpus");
    await expect(page.getByRole("heading", { level: 1, name: "Le corpus" })).toBeVisible();
    await expect(page.getByText(/\d+ numéros? indexés?/)).toBeVisible();
  });

  test("déplier un numéro révèle ses articles, et le lien mène à la lecture", async ({ page }) => {
    await page.goto("/corpus");
    // Déplier le numéro de démonstration.
    const issue = page.locator("details").filter({ hasText: /démonstration/i }).first();
    await issue.locator("summary").click();
    const articleLink = page.getByRole("link", { name: /Note de démonstration/ });
    await expect(articleLink).toBeVisible();
    await expect(articleLink).toHaveAttribute("href", `/corpus/${DEMO_ISSUE}/${DEMO_ARTICLE}`);
    await articleLink.click();
    await expect(page).toHaveURL(new RegExp(`/corpus/${DEMO_ISSUE}/${DEMO_ARTICLE}$`));
  });
});

test.describe("page article — lecture et audio", () => {
  test("affiche titre (h1), auteur et corps de l'article", async ({ page }) => {
    await page.goto(`/corpus/${DEMO_ISSUE}/${DEMO_ARTICLE}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText(/Rédaction/)).toBeVisible();
    const paragraphs = page.locator("[data-article-body] > p");
    expect(await paragraphs.count()).toBeGreaterThan(0);
  });

  test("le lecteur audio démarre et expose son état via aria-pressed", async ({ page }) => {
    await page.goto(`/corpus/${DEMO_ISSUE}/${DEMO_ARTICLE}`);
    const play = page.getByRole("button", { name: /Écouter/ });
    await expect(play).toBeVisible();
    await expect(play).toHaveAttribute("aria-pressed", "false");

    await play.click();
    // Après lecture : bouton Stop visible + état pressé.
    await expect(page.getByRole("button", { name: /Arrêter la lecture/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Pause|Mettre la lecture en pause/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  test("article inexistant : le statut HTTP devrait être 404, pas 200", async ({ page }) => {
    const res = await page.goto(`/corpus/${DEMO_ISSUE}/article-qui-nexiste-pas`);
    // L'utilisateur voit « Article introuvable » mais le statut doit être 404
    // (SEO, cache, robustesse). Régression connue à vérifier.
    expect(res?.status()).toBe(404);
  });

  test("article inexistant : page d'erreur exploitable (pas un 404 brut Astro)", async ({ page }) => {
    // En mode statique (getStaticPaths), une URL d'article inconnue tombe sur le
    // 404 générique d'Astro — l'écran soigné « Article introuvable » + « Retour
    // au corpus » de la page n'est jamais atteint. On attend un chemin de retour.
    await page.goto(`/corpus/${DEMO_ISSUE}/article-qui-nexiste-pas`);
    await expect(
      page.getByRole("main").getByRole("link", { name: /corpus|accueil/i }).first(),
    ).toBeVisible();
  });
});
