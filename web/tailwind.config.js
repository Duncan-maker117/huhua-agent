// Build (needs tailwindcss@3.4.17 + @tailwindcss/forms on NODE_PATH): tailwindcss -c web/tailwind.config.js -i web/tailwind.input.css -o web/tailwind.css --minify
module.exports = Object.assign({ content: ['./web/index.html', './web/*.js'], plugins: [require('@tailwindcss/forms')] }, {
    darkMode: "class",
    theme: {
      extend: {
        colors: {
          "background": "#faf8fe", "on-primary-fixed": "#1b0062", "surface-variant": "#e3e2e7",
          "tertiary-fixed": "#ffdea3", "error-container": "#ffdad6", "surface-bright": "#faf8fe",
          "on-primary-container": "#ccc1ff", "primary-fixed": "#e6deff",
          "on-surface-variant": "#484456", "on-secondary-fixed-variant": "#461cc6",
          "on-background": "#1a1b1f", "on-tertiary-fixed": "#261900",
          "primary-container": "#5423e7", "surface-tint": "#5f34f1",
          "secondary-container": "#7659f6", "secondary-fixed": "#e6deff", "outline": "#797488",
          "on-tertiary-fixed-variant": "#594316", "on-tertiary-container": "#e4c58b",
          "surface-container-low": "#f4f3f8", "surface-container": "#efedf3",
          "on-error-container": "#93000a", "primary": "#3c00bd", "error": "#ba1a1a",
          "on-secondary": "#ffffff", "tertiary-fixed-dim": "#e2c289", "surface": "#faf8fe",
          "on-primary": "#ffffff", "surface-dim": "#dad9df", "on-secondary-container": "#fffbff",
          "on-surface": "#1a1b1f", "on-secondary-fixed": "#1b0063", "inverse-surface": "#2f3034",
          "secondary-fixed-dim": "#c9beff", "on-error": "#ffffff",
          "primary-fixed-dim": "#c9beff", "tertiary-container": "#675122",
          "surface-container-highest": "#e3e2e7", "inverse-primary": "#c9beff",
          "tertiary": "#4e3a0c", "secondary": "#5c3cdb", "outline-variant": "#c9c3d9",
          "surface-container-high": "#e9e7ed", "on-primary-fixed-variant": "#4600d7",
          "on-tertiary": "#ffffff", "surface-container-lowest": "#ffffff",
          "inverse-on-surface": "#f1f0f5"
        },
        borderRadius: { DEFAULT: "0.25rem", lg: "0.5rem", xl: "0.75rem", full: "9999px" },
        fontFamily: {
          headline: ["Plus Jakarta Sans"], body: ["Inter"], label: ["Inter"]
        }
      }
    }
  });
