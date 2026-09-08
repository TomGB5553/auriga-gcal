"""Store your Auriga SSO username + password in the macOS Keychain.

Run once:   python setup_login.py

Nothing is written to disk in plain text -- the values live in the login
Keychain under the service name "auriga-gcal". Delete them anytime with:
    python -m keyring del auriga-gcal username
    python -m keyring del auriga-gcal password
"""
import getpass

import keyring

SERVICE = "auriga-gcal"


def main() -> None:
    user = input("Auriga SSO username (the e-mail you log in with): ").strip()
    pw = getpass.getpass("Auriga SSO password (hidden): ")
    keyring.set_password(SERVICE, "username", user)
    keyring.set_password(SERVICE, "password", pw)
    print("Saved to Keychain under service 'auriga-gcal'.")


if __name__ == "__main__":
    main()
