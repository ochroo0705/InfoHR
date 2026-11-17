import type { Preview } from "@storybook/react";
import "../src/styles/app.css";

// The theme global sets the same data-theme attribute the app uses, so dark: utilities and tokens follow it.
// A story can pin its own theme with parameters.theme, which wins over the toolbar.
const preview: Preview = {
  globalTypes: {
    theme: {
      description: "Colour theme",
      defaultValue: "light",
      toolbar: {
        title: "Theme",
        icon: "mirror",
        items: [
          { value: "light", title: "Цайвар" },
          { value: "dark", title: "Бараан" },
        ],
        dynamicTitle: true,
      },
    },
  },
  decorators: [
    (Story, context) => {
      const theme = (context.parameters.theme as string | undefined) ?? context.globals.theme;
      document.documentElement.dataset.theme = theme;
      return <Story />;
    },
  ],
};

export default preview;
