// SPDX-License-Identifier: AGPL-3.0-or-later
// Helpers client partagés (utilisés dans les `<script>` Astro des pages auth).
// Vite résout `import.meta.env` dans les scripts module — pas dans les inline.

/** Base de l'API, sans slash final. */
export const API_BASE = (import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Échappe le HTML avant injection via innerHTML (anti-XSS). */
export const escapeHtml = (s: string): string =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
