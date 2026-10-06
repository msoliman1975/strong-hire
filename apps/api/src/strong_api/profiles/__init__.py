"""Company profiles (AD-1), write side: file validation, versioned import, diff and publish.
The strongctl command line is in cli.py.

The read side (get_published_profile, resolve_profile with the generic default profile,
use_profile_for_session, profile_for_session) is in strong_core.profiles. The voice agent and
the worker import it from there.
"""

from strong_api.profiles.repository import import_profile, publish_profile
from strong_api.profiles.validation import ProfileFileError, load_profile_file

__all__ = [
    "ProfileFileError",
    "import_profile",
    "load_profile_file",
    "publish_profile",
]
