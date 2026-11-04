from django.contrib.staticfiles.apps import StaticFilesConfig
from infohr_firebird.prefix import connect_prefix_receiver

# Connected here, not in a models module: app configs are imported before any models.py runs,
# so the receiver sees every model (auth, admin, sessions, migrations' rendered models too).
connect_prefix_receiver()


class HRStaticFilesConfig(StaticFilesConfig):
    # css/input.css is the Tailwind source (`@import "tailwindcss"`), not a served file;
    # collecting it makes the manifest storage fail on the unresolvable import.
    ignore_patterns = [*StaticFilesConfig.ignore_patterns, "input.css"]
