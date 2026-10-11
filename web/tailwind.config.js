/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#615ced',
          dark: '#4f46e5',
          light: '#8b85f0',
        },
      },
    },
  },
  plugins: [],
}
