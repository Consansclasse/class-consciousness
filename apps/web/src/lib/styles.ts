// SPDX-License-Identifier: AGPL-3.0-or-later
// Classes Tailwind partagées (palette stricte noir/blanc/darkpink, sans gris).
// Importées dans le frontmatter Astro des pages pour éviter la duplication.

/** Champ de saisie « barre du bas » : soulignement seul, placeholder en MAJUSCULES. */
export const INPUT_CLASS =
  "w-full border-0 border-b border-black dark:border-white bg-transparent px-0 py-3 font-Scheherazade text-base text-black dark:text-white outline-none placeholder:uppercase placeholder:tracking-[0.15em] focus-visible:border-darkpink";

/** Bouton d'action principal (darkpink) avec padding latéral — usage en ligne. */
export const BTN_CLASS =
  "bg-darkpink text-white font-Scheherazade text-sm uppercase tracking-[0.2em] px-6 py-3 transition-opacity hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed";

/** Bouton d'action principal pleine largeur (boutons de soumission des formulaires). */
export const BTN_FULL_CLASS =
  "w-full bg-darkpink text-white font-Scheherazade text-sm uppercase tracking-[0.2em] py-3 transition-opacity hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed";

/** Titre de section (h2) en MAJUSCULES. */
export const H2_CLASS = "font-Scheherazade text-sm uppercase tracking-[0.25em] text-black dark:text-white mb-4";
