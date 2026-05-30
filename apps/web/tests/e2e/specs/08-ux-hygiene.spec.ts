// SPDX-License-Identifier: AGPL-3.0-or-later
// E2E hygiène UX transverse — ce qu'un vrai utilisateur ressent sur chaque page :
// un titre d'onglet distinct, un seul h1, aucune erreur console rouge, et des
// pages d'info qui rendent leur contenu essentiel.

import { expect, test } from "@playwright/test";

const PAGES = [
  { path: "/", title: /Conscience de classe/ },
  { path: "/corpus", title: /Corpus/ },
  { path: "/contact", title: /Contact|Conscience de classe/ },
  { path: "/help", title: /Aide|Conscience de classe/ },
  { path: "/join", title: /Adhérer/ },
  { path: "/login", title: /Connexion/ },
  { path: "/register", title: /Inscription/ },
  { path: "/forgot-password", title: /Mot de passe oublié/ },
  { path: "/legal/privacy", title: /Confidentialité/ },
];

for (const { path, title } of PAGES) {
  test.describe(`hygiène — ${path}`, () => {
    test("titre d'onglet présent et non vide", async ({ page }) => {
      await page.goto(path);
      await expect(page).toHaveTitle(title);
    });

    test("exactement un h1", async ({ page }) => {
      await page.goto(path);
      // getByRole(heading) ignore les h1 cachés de la barre d'outils dev Astro.
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    });

    test("aucune erreur console (hors CORS dev — voir test dédié)", async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") errors.push(msg.text());
      });
      page.on("pageerror", (err) => errors.push(err.message));
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      // On filtre deux bruits attendus, non bloquants :
      //  - l'erreur CORS (cf. test dédié « CORS configuré ») ;
      //  - le 401 de la sonde d'auth /auth/me du header (normal pour un visiteur
      //    anonyme ; le navigateur loggue tout 4xx en console, on ne peut pas le
      //    supprimer côté fetch). Toute AUTRE erreur console reste un échec.
      const others = errors.filter(
        (e) =>
          !/CORS|auth\/me|ERR_FAILED|Access-Control/i.test(e) &&
          !/Failed to load resource.*(401|403)|Unauthorized/i.test(e),
      );
      expect(others, `erreurs console sur ${path}: ${others.join(" | ")}`).toHaveLength(0);
    });
  });
}

test.describe("intégration navigateur ↔ API (CORS)", () => {
  test("le navigateur peut joindre l'API en cross-origin (CORS configuré)", async ({ page }) => {
    const apiBase = process.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    await page.goto("/");
    // Reproduit l'appel d'auth du header : doit aboutir (200/401), pas être bloqué CORS.
    const reachable = await page.evaluate(async (base) => {
      try {
        const r = await fetch(`${base}/auth/me`, { credentials: "include" });
        return r.status; // 200 ou 401 = joignable
      } catch {
        return -1; // bloqué (CORS / réseau)
      }
    }, apiBase);
    expect(
      reachable,
      `appel cross-origin bloqué (CORS off ?). Erreurs: ${errors.join(" | ")}`,
    ).toBeGreaterThan(0);
  });
});

test.describe("pages d'information — contenu essentiel", () => {
  test("contact expose une adresse email cliquable", async ({ page }) => {
    await page.goto("/contact");
    // .first() : le footer global expose aussi l'email → on vise celui du corps.
    await expect(
      page.getByRole("main").getByRole("link", { name: /contact@consciencedeclasse\.com/ }),
    ).toHaveAttribute("href", /^mailto:/);
  });

  test("aide : déplier une question révèle sa réponse", async ({ page }) => {
    await page.goto("/help");
    const details = page.locator("details").filter({ hasText: /Faut-il un compte/ }).first();
    await details.locator("summary").click();
    await expect(details).toHaveAttribute("open", "");
    await expect(details).toContainText(/Non|compte|lire/i);
  });

  test("confidentialité : sections clés présentes", async ({ page }) => {
    await page.goto("/legal/privacy");
    await expect(page.getByRole("heading", { level: 1, name: /Confidentialité/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Mesure d'audience/ })).toBeVisible();
  });
});

test.describe("footer — présence et liens", () => {
  test("la page d'accueil a un footer dont les liens internes répondent < 400", async ({
    page,
    request,
  }) => {
    await page.goto("/");
    const footer = page.locator("footer");
    await expect(footer).toBeVisible();
    const hrefs = await footer.locator('a[href^="/"]').evaluateAll((els) =>
      Array.from(new Set(els.map((e) => (e as HTMLAnchorElement).getAttribute("href")))).filter(
        (h): h is string => !!h,
      ),
    );
    expect(hrefs.length).toBeGreaterThan(0);
    for (const href of hrefs) {
      const res = await request.get(href);
      expect(res.status(), `lien footer ${href}`).toBeLessThan(400);
    }
  });

  test("UX : le footer devrait être présent aussi sur les pages internes", async ({ page }) => {
    // Constat : SiteFooter n'est inclus que dans index.astro → pas de contact /
    // réseaux / mentions légales sur corpus, aide, connexion, etc.
    for (const path of ["/corpus", "/help", "/login"]) {
      await page.goto(path);
      await expect(page.locator("footer"), `footer manquant sur ${path}`).toBeVisible();
    }
  });

  test("UX/a11y : le footer devrait exposer le repère contentinfo", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("contentinfo")).toBeVisible();
  });
});
