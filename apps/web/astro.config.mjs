// SPDX-License-Identifier: AGPL-3.0-or-later
import { defineConfig } from "astro/config";
import tailwind from "@astrojs/tailwind";

export default defineConfig({
  site: process.env.SITE_URL ?? "http://localhost:3000",
  server: { host: true, port: 3000 },
  integrations: [tailwind({ applyBaseStyles: false })],
  redirects: {
    "/fr": "/",
    "/fr/[...path]": "/[...path]",
  },
});
