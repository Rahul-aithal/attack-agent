/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0b1220",
        panel: "#121a2b",
        panel2: "#1a2540",
        line: "#243149",
        accent: "#5b8cff",
      },
    },
  },
  plugins: [],
};
