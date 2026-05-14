// SPDX-License-Identifier: AGPL-3.0-or-later
import { test as base, expect } from "@playwright/test";

const API_BASE = process.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const test = base.extend<{ seededCorpus: void }>({
  seededCorpus: [
    async ({}, use) => {
      const res = await fetch(`${API_BASE}/__debug/seed`, { method: "POST" });
      if (!res.ok) {
        throw new Error(`seed failed: HTTP ${res.status}`);
      }
      await use();
    },
    { auto: false },
  ],
});

export { expect };
