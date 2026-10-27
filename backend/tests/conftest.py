import os
import tempfile

# Point the app at a throwaway DB before any gradient module reads settings.
# GRADIENT_TEST_DATABASE_URL runs the same suite against Postgres (e.g. a local or Neon test DB).
if os.environ.get("GRADIENT_TEST_DATABASE_URL"):
    os.environ["GRADIENT_DATABASE_URL"] = os.environ["GRADIENT_TEST_DATABASE_URL"]
else:
    _tmp = tempfile.mkdtemp(prefix="gradient-test-")
    os.environ["GRADIENT_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
