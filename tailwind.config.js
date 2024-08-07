/** @type {import('tailwindcss').Config} */

const defaultTheme = require("tailwindcss/defaultTheme");

module.exports = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        sans: ["Inter var", ...defaultTheme.fontFamily.sans],
      },
      colors: {
        border: "hsl(var(--border))", // --border: 214.3 31.8% 91.4%;
        input: "hsl(var(--input))", // --input: 214.3 31.8% 91.4%;
        ring: "hsl(var(--ring))", // --ring: 215 20.2% 65.1%;
        background: "hsl(var(--background))", // --background: 0 0% 100%;
        foreground: "hsl(var(--foreground))", // --foreground: 222.2 84% 4.9%;
        primary: {
          DEFAULT: "hsl(var(--primary))", // --primary: 222.2 47.4% 11.2%;
          foreground: "hsl(var(--primary-foreground))", // --primary-foreground: 210 40% 98%;
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))", // --secondary: 210 40% 96.1%;
          foreground: "hsl(var(--secondary-foreground))", // --secondary-foreground: 222.2 47.4% 11.2%;
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))", // --destructive: 0 84.2% 60.2%;
          foreground: "hsl(var(--destructive-foreground))", // --destructive-foreground: 210 40% 98%;
        },
        muted: {
          DEFAULT: "hsl(var(--muted))", // --muted: 210 40% 96.1%;
          foreground: "hsl(var(--muted-foreground))", // --muted-foreground: 215.4 16.3% 46.9%;
        },
        accent: {
          DEFAULT: "hsl(var(--accent))", // --accent: 210 40% 96.1%;
          foreground: "hsl(var(--accent-foreground))", // --accent-foreground: 222.2 47.4% 11.2%;
        },
        popover: {
          DEFAULT: "hsl(var(--popover))", // --popover: 0 0% 100%;
          foreground: "hsl(var(--popover-foreground))", // --popover-foreground: 222.2 84% 4.9%;
        },
        card: {
          DEFAULT: "hsl(var(--card))", // --card: 0 0% 100%;
          foreground: "hsl(var(--card-foreground))", // --card-foreground: 222.2 84% 4.9%;
        },
      },
      borderRadius: {
        lg: "var(--radius)", // --radius: 0.5rem;
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: 0 },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: 0 },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
      height: {
        display: "100dvh",
      },
      width: {
        display: "100dvw",
      },
    },
  },
  plugins: [require("tailwindcss-animate"), require("@tailwindcss/forms")],
};
