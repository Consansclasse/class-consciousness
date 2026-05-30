// SPDX-License-Identifier: AGPL-3.0-or-later
import { expect, test } from "@playwright/test";

test.describe("smoke — golden path", () => {
  test("home page loads under 2s with no console errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    const t0 = Date.now();
    const response = await page.goto("/");
    const elapsed = Date.now() - t0;

    expect(response?.status()).toBeLessThan(400);
    expect(elapsed).toBeLessThan(2000);
    // Le header sonde l'auth via GET /auth/me : un visiteur anonyme reçoit 401,
    // que le navigateur loggue en console (4xx non supprimable côté fetch). Ce
    // bruit est attendu ; toute AUTRE erreur console reste un échec.
    const real = errors.filter((e) => !/Failed to load resource.*401|Unauthorized/i.test(e));
    expect(real, `console errors: ${real.join(" | ")}`).toHaveLength(0);
  });

  test("API health is reachable from the browser context", async ({ page }) => {
    const apiBase = process.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";
    const res = await page.request.get(`${apiBase}/health`);
    expect(res.status()).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
  });
});
