// SPDX-License-Identifier: AGPL-3.0-or-later
import { defineConfig } from "astro/config";

export default defineConfig({
  site: process.env.SITE_URL ?? "http://localhost:3000",
  server: { host: true, port: 3000 },
});
