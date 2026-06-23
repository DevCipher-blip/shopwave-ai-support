/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: "#F6F1E7",
        card: "#FFFDF8",
        ink: "#1F2A2E",
        muted: "#5B6670",
        line: "#E2D9C8",
        tide: {
          50: "#E6F2EF",
          100: "#CBE5DF",
          600: "#13716B",
          700: "#0F5E5A",
          800: "#0B4A47",
        },
        approve: { DEFAULT: "#2F6B3A", soft: "#E5F0E3" },
        deny: { DEFAULT: "#A8372A", soft: "#F8E5E1" },
        escalate: { DEFAULT: "#8A5300", soft: "#F7EBD3" },
      },
      fontFamily: {
        display: ['"Fraunces Variable"', "Georgia", "serif"],
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      animation: {
        "fade-in": "fadeIn 0.15s ease-out",
        "slide-up": "slideUp 0.2s ease-out",
      },
      keyframes: {
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
      },
    },
  },
  plugins: [],
};
