// SPDX-License-Identifier: AGPL-3.0-or-later
// E2E suivi visuel de la lecture — on vérifie que pendant la lecture audio une
// PHRASE active est surlignée (.cc-reading) et que le surlignage PROGRESSE d'une
// unité à l'autre. C'est le cœur de la fonctionnalité « suivre le texte des
// yeux » : il ne dépend que des événements start/end (fiables partout), pas du
// `boundary` mot-à-mot.
//
// La synthèse vocale réelle est non déterministe (timing, voix absentes en CI) :
// on STUBBE `window.speechSynthesis` avant le chargement de la page pour piloter
// la cadence des utterances. Le stub n'altère pas la logique testée — il ne fait
// que déclencher onstart/onend, exactement comme un vrai moteur.

import { expect, test } from "@playwright/test";

const DEMO_ISSUE = "bilan-demo";
const DEMO_ARTICLE = "note-de-demonstration";

// Stub déterministe : chaque utterance reçoit onstart immédiatement puis onend
// après UTTERANCE_MS, en série. On expose le nombre d'utterances jouées.
const UTTERANCE_MS = 400;
const installSpeechStub = (utteranceMs: number) => {
  const queue: any[] = [];
  let timer: any = null;
  let cancelled = false;
  (window as any).__ttsSpoken = 0;

  const playNext = () => {
    if (cancelled) return;
    const u = queue.shift();
    if (!u) return;
    u.onstart?.({});
    timer = setTimeout(() => {
      u.onend?.({});
      (window as any).__ttsSpoken++;
      playNext();
    }, utteranceMs);
  };

  const fake = {
    speak(u: any) {
      queue.push(u);
      if (queue.length === 1 && !timer) {
        cancelled = false;
        playNext();
      }
    },
    cancel() {
      cancelled = true;
      queue.length = 0;
      if (timer) clearTimeout(timer);
      timer = null;
    },
    pause() {},
    resume() {},
    getVoices: () => [],
    addEventListener() {},
    removeEventListener() {},
  };
  Object.defineProperty(window, "speechSynthesis", { value: fake, configurable: true });
  // Utterance minimal : conserve le texte et laisse poser onstart/onboundary/onend.
  (window as any).SpeechSynthesisUtterance = class {
    text: string;
    constructor(t: string) {
      this.text = t;
    }
  };
};

test.describe("lecture audio — suivi visuel du texte", () => {
  test("une phrase est surlignée et le surlignage progresse", async ({ page }) => {
    await page.addInitScript(installSpeechStub, UTTERANCE_MS);
    await page.goto(`/corpus/${DEMO_ISSUE}/${DEMO_ARTICLE}`);

    await page.getByRole("button", { name: /Écouter/ }).click();

    // 1) Une unité devient active.
    const active = page.locator(".cc-reading");
    await expect(active).toHaveCount(1);
    const first = (await active.first().textContent())?.trim();
    expect(first && first.length > 0).toBeTruthy();

    // 2) Le surlignage se déplace vers une AUTRE unité (progression réelle).
    await expect
      .poll(async () => (await page.locator(".cc-reading").first().textContent())?.trim(), {
        timeout: 5000,
      })
      .not.toBe(first);

    // 3) À tout instant, une seule unité est active (pas de surlignage résiduel).
    expect(await page.locator(".cc-reading").count()).toBeLessThanOrEqual(1);
  });

  test("à la fin de la lecture, plus aucune unité n'est surlignée", async ({ page }) => {
    await page.addInitScript(installSpeechStub, 60);
    await page.goto(`/corpus/${DEMO_ISSUE}/${DEMO_ARTICLE}`);

    await page.getByRole("button", { name: /Écouter/ }).click();

    // Le stub enchaîne vite : on attend la fin (bouton repassé à « Écouter »).
    await expect(page.getByRole("button", { name: /Écouter l'article/ })).toHaveAttribute(
      "aria-pressed",
      "false",
      { timeout: 10000 },
    );
    await expect(page.locator(".cc-reading")).toHaveCount(0);
  });
});
