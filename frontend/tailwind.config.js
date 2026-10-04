/** Design tokens. Status colours are semantic: each lifecycle state owns one hue everywhere it appears. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        canvas: "#EDF0EE",
        surface: "#FFFFFF",
        sunken: "#F5F7F6",
        line: { DEFAULT: "#D9DFDC", strong: "#C2CAC6" },
        ink: { DEFAULT: "#15202B", soft: "#46535F", mute: "#74818C" },
        brand: { DEFAULT: "#0B7A66", dark: "#085C4D", tint: "#E1F0EC" },
        st: {
          submitted: { DEFAULT: "#566673", tint: "#E9EDF0" },
          progress: { DEFAULT: "#92610A", tint: "#FBF0D6" },
          delivered: { DEFAULT: "#2457A6", tint: "#E3ECF9" },
          accepted: { DEFAULT: "#1B7439", tint: "#DFF2E6" },
          rejected: { DEFAULT: "#B02A22", tint: "#FBE5E3" },
        },
      },
      boxShadow: {
        card: "0 1px 0 rgba(21,32,43,.04), 0 1px 3px rgba(21,32,43,.06)",
        pop: "0 10px 30px -8px rgba(21,32,43,.28), 0 2px 6px rgba(21,32,43,.08)",
      },
      keyframes: {
        "toast-in": { from: { opacity: 0, transform: "translateY(10px) scale(.98)" }, to: { opacity: 1, transform: "none" } },
        "toast-out": { from: { opacity: 1, transform: "none" }, to: { opacity: 0, transform: "translateX(16px)" } },
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "dialog-in": { from: { opacity: 0, transform: "translateY(8px) scale(.985)" }, to: { opacity: 1, transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "tape-fill": { from: { transform: "scaleY(.2)", opacity: 0.3 }, to: { transform: "scaleY(1)", opacity: 1 } },
      },
      animation: {
        "toast-in": "toast-in .28s cubic-bezier(.2,.8,.2,1) both",
        "toast-out": "toast-out .2s ease-in both",
        "fade-in": "fade-in .18s ease-out both",
        "dialog-in": "dialog-in .22s cubic-bezier(.2,.8,.2,1) both",
        "tape-fill": "tape-fill .35s cubic-bezier(.2,.8,.2,1) both",
      },
    },
  },
  plugins: [],
};
