import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        "bg-elev": "var(--bg-elev)",
        ink: "var(--ink)",
        accent: "var(--accent)",
        indigo: "var(--indigo)",
        jade: "var(--jade)",
        amber: "var(--amber)"
      },
      fontFamily: {
        sans: "var(--sans)",
        serif: "var(--serif)",
        mono: "var(--mono)"
      },
      borderRadius: {
        card: "8px"
      }
    }
  },
  plugins: []
} satisfies Config;
