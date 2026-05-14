// SPDX-License-Identifier: AGPL-3.0-or-later
// E2E /corpus — vérifie liste post-seed + état vide + règles UI dures
// (pas de gris, pas de <strong>/font-bold).

import { expect, test } from "../fixtures/seeded-corpus";

test.describe("corpus — page liste", () => {
  test("affiche l'état vide quand la DB est vierge", async ({ page, request }) => {
    // Reset avant le test pour avoir un état déterministe.
    await request.post(`${process.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/__debug/reset`);

    await page.goto("/corpus");
    await expect(page.getByText("( à faire )")).toBeVisible();
    await expect(page.getByText(/0 textes? indexés?/)).toBeVisible();
  });

  test("affiche au moins une entrée après seed", async ({ page, seededCorpus }) => {
    void seededCorpus;
    await page.goto("/corpus");
    // Compteur > 0 et au moins 1 item dans la liste
    await expect(page.getByText(/\d+ textes? indexés?/)).toBeVisible();
    await expect(page.getByText("Fixture de test — pipeline ingestion")).toBeVisible();
  });

  test("aucun <strong> ni font-bold dans le DOM (règle UI dure)", async ({ page }) => {
    await page.goto("/corpus");
    const strongs = await page.locator("strong").count();
    const boldClasses = await page.locator('[class*="font-bold"], [class*="font-semibold"]').count();
    expect(strongs).toBe(0);
    expect(boldClasses).toBe(0);
  });

  test("aucune classe text-gray/bg-gray dans le DOM (palette stricte)", async ({ page }) => {
    await page.goto("/corpus");
    const grays = await page.locator('[class*="text-gray"], [class*="bg-gray"]').count();
    expect(grays).toBe(0);
  });
});
