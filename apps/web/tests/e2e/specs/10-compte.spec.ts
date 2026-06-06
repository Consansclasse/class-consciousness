// SPDX-License-Identifier: AGPL-3.0-or-later
// E2E « Mon compte » : crée une vraie session (register → verify via l'API, le
// lien étant renvoyé dans devLink en local), puis depuis /chat ouvre le menu
// compte → /compte, édite le nom (persistant après reload) et se déconnecte.
// Locators sémantiques uniquement (getByRole / getByLabel).

import { type APIRequestContext, request as apiRequest, expect, test } from "@playwright/test";

const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:8000";
const PASSWORD = "MotDePasse-E2E-12";

// Compte créé par le test : supprimé après chaque cas pour ne laisser AUCUN
// résidu en base (hygiène — la suite tourne contre une vraie base partagée).
let createdEmail: string | null = null;

test.afterEach(async () => {
  if (!createdEmail) return;
  const email = createdEmail;
  createdEmail = null;
  const ctx = await apiRequest.newContext();
  try {
    const login = await ctx.post(`${API_BASE}/auth/login`, {
      data: { email, password: PASSWORD },
    });
    if (login.ok()) {
      await ctx.post(`${API_BASE}/auth/delete-account`, { data: {} });
    }
  } finally {
    await ctx.dispose();
  }
});

async function createVerifiedSession(request: APIRequestContext, email: string, password = PASSWORD): Promise<void> {
  const reg = await request.post(`${API_BASE}/auth/register`, {
    data: { email, password, consent_data: true },
  });
  expect(reg.ok(), await reg.text()).toBeTruthy();
  const devLink = (await reg.json()).devLink as string | undefined;
  expect(devLink, "devLink attendu (SMTP non configuré en local)").toBeTruthy();
  const token = new URL(devLink as string).searchParams.get("token");
  expect(token).toBeTruthy();
  const verify = await request.post(`${API_BASE}/auth/verify-email`, {
    data: { token },
  });
  expect(verify.ok(), await verify.text()).toBeTruthy();
}

test.describe("Mon compte — parcours connecté", () => {
  test("menu compte depuis /chat → /compte → éditer le nom → déconnexion", async ({ page, context }) => {
    const email = `compte-e2e-${Date.now()}@example.org`;
    createdEmail = email;
    // Hygiène : aucune exception JS ne doit survenir sur tout le parcours.
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
    await createVerifiedSession(context.request, email);

    // 1. /chat authentifié : le shell se révèle, le bouton compte est visible.
    await page.goto("/chat");
    const trigger = page.getByRole("button", { name: "Mon compte" });
    await expect(trigger).toBeVisible({ timeout: 7000 });

    // 2. Ouvrir le menu compte → aller sur /compte.
    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await page.getByRole("menuitem", { name: "Mon compte" }).click();
    await expect(page).toHaveURL(/\/compte$/);
    await expect(page.getByRole("heading", { level: 1, name: "Mon compte" })).toBeVisible();
    // 2 bis. Hygiène /compte : un seul <h1> et l'accès au chat dans la barre.
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(page.getByRole("link", { name: "Le chat" })).toBeVisible();

    // 3. Éditer le nom affiché.
    await page.getByLabel("Nom affiché").fill("Camarade E2E");
    await page.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByText("Nom enregistré.")).toBeVisible({ timeout: 7000 });

    // 4. Persistance après rechargement (la garde re-fetch /auth/me et pré-remplit).
    await page.reload();
    await expect(page.getByLabel("Nom affiché")).toHaveValue("Camarade E2E", {
      timeout: 7000,
    });

    // 5. Déconnexion (bouton de la section compte, distinct du header global)
    //    → retour à /login.
    await page.getByRole("main").getByRole("button", { name: "Se déconnecter" }).click();
    await expect(page).toHaveURL(/\/login/, { timeout: 7000 });

    // Aucune exception JS sur tout le parcours (chat → compte → login).
    expect(pageErrors, pageErrors.join("; ")).toEqual([]);
  });

  test("header global : menu compte discret (icône) + déconnexion sur l'accueil", async ({ page, context }) => {
    const email = `compte-e2e-h-${Date.now()}@example.org`;
    createdEmail = email;
    await createVerifiedSession(context.request, email);

    // La barre du header n'expose plus « Déconnexion » en clair : un bouton compte
    // discret (icône) ouvre un petit menu Mon compte / Déconnexion.
    await page.goto("/");
    const account = page.getByRole("button", { name: "Mon compte" });
    await expect(account).toBeVisible({ timeout: 7000 });
    await account.click();
    await expect(account).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("menuitem", { name: "Mon compte" })).toBeVisible();

    // Déconnexion depuis le menu → session fermée → /compte redemande la connexion.
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/auth/logout")),
      page.getByRole("menuitem", { name: "Déconnexion" }).click(),
    ]);
    await page.goto("/compte");
    await expect(page).toHaveURL(/\/login/, { timeout: 7000 });
  });
});
