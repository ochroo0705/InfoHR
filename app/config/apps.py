from django.contrib.staticfiles.apps import StaticFilesConfig


class HRStaticFilesConfig(StaticFilesConfig):
    # css/input.css is the Tailwind source (`@import "tailwindcss"`), not a served file;
    # collecting it makes the manifest storage fail on the unresolvable import.
    ignore_patterns = [*StaticFilesConfig.ignore_patterns, "input.css"]
