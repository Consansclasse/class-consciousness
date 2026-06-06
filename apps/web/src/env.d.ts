/// <reference path="../.astro/types.d.ts" />
/// <reference types="astro/client" />

// `process.env` est utilisé dans le frontmatter (serveur-only) des pages corpus
// pour lire API_INTERNAL_BASE_URL en SSR. Déclaration ambiante minimale pour
// satisfaire `astro check` sans tirer tout @types/node.
declare const process: { env: Record<string, string | undefined> };
