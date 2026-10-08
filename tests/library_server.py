"""Isolated shared-library browser test server, without paid APIs or personal data."""
import os
import tempfile

os.environ['LIBRARY_COOKIE_SECURE'] = 'false'
os.environ['LIBRARY_DATA_DIR'] = tempfile.mkdtemp(prefix='zhixi-library-e2e-')
os.environ.pop('LIBRARY_PUBLIC_ORIGIN', None)
os.environ.pop('LIBRARY_REGISTRATION_CODE', None)
from backend.library.main import app  # noqa: E402,F401
