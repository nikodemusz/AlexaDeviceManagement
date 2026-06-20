"""Legacy compatibility entrypoint.

The previous implementation in this file contained a Login with Amazon OAuth/LWA
flow with client_id, client_secret, refresh_token and token-cache handling. That
approach was intentionally removed because it does not solve the project goal of
managing the devices already present in a user's private Alexa account.

The active Home Assistant OS app starts through server_app_entry.py. Keeping this
small shim prevents later confusion and still allows accidental direct execution
of server.py to start the current app path.
"""

from __future__ import annotations

from server_app_entry import main


if __name__ == "__main__":
    main()
