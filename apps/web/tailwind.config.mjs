// SPDX-License-Identifier: AGPL-3.0-or-later
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "selector",
  content: ["./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}"],
  theme: {
    container: { center: true },
    screens: {
      sm: "640px",
      md: "768px",
      lg: "1024px",
      xl: "1280px",
      "2xl": "1536px",
      "3xl": "1920px",
    },
    extend: {
      fontFamily: {
        Scheherazade: ['"Scheherazade New"', "serif"],
        PlayfairDisplay: ['"Playfair Display"', "Georgia", "serif"],
      },
      colors: {
        // STRICT : noir, blanc, rose. Rien d'autre.
        darkpink: "#E27ECC",
      },
    },
  },
  plugins: [],
};
