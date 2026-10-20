/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["../web/**/*.{html,js}"],
  darkMode: "media",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Rubik", "Assistant", "Segoe UI", "Arial Hebrew", "Arial", "sans-serif"],
      },
    },
  },
};
