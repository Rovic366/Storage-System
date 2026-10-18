/**
 * Legacy Tailwind config kept for tooling/IDE support and spec conformance.
 *
 * django-tailwind 4.5 + Tailwind CSS v4 is CSS-first: the authoritative token
 * source is theme/static_src/src/styles.css (@theme) and components.css (@apply).
 * This file mirrors those tokens (loaded via @config in styles.css) so editor
 * plugins and external tooling get the same type scale, colors and dark mode.
 *
 * Build: python manage.py tailwind build   (watch: tailwind start)
 */
module.exports = {
  darkMode: "class",
  content: [
    "./templates/**/*.html",
    "./**/templates/**/*.html",
    "./static/**/*.js",
    "./theme/static_src/src/**/*.{css,js}",
  ],
  theme: {
    extend: {
      colors: {
        surface: "#05070b",
        panel: "#0c1118",
        "panel-2": "#10161f",
        hairline: "#1c2530",
        "row-alt": "#0a0f16",
        ink: { DEFAULT: "#e2e8f0", "2": "#94a3b8", "3": "#64748b" },
        accent: "#22d3ee",
        healthy: "#34d399",
        warning: "#fbbf24",
        critical: "#fb7185",
        info: "#38bdf8",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
      },
    },
  },
  plugins: [],
};
