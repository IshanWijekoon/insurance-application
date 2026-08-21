import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          950: "#07111f",
          900: "#0c1a2e",
          800: "#13263f",
          700: "#1b3554",
        },
        accent: {
          400: "#3ee0c2",
          500: "#1ec9ab",
          600: "#12a78e",
        },
        gold: {
          400: "#e4c06a",
          500: "#d4a84b",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(12,26,46,0.06), 0 12px 32px rgba(12,26,46,0.06)",
      },
    },
  },
  plugins: [],
};

export default config;
