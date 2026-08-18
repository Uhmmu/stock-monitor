import os

# Fail-closed auth code must stay usable in tests without production secrets.
# Set before any `app.*` import happens inside test modules.
os.environ.setdefault("APP_ENV", "test")
