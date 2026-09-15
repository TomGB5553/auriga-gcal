"""Get an authenticated Auriga browser context.

Strategy:
  1. Open the SPA with whatever session we have saved (storage_state.json).
  2. If Keycloak bounces us to its login form, fill it from the Keychain
     credentials and submit.
  3. Save the refreshed session back to storage_state.json.

The caller gets a live Playwright `page` sitting on the planning view, plus
the `browser` handle so it can close it.
"""
from __future__ import annotations

import sys
import time

import keyring
from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

import config

SERVICE = "auriga-gcal"
# The SPA planning route (hash-router). Landing here triggers the planning API.
PLANNING_PAGE = config.AURIGA_BASE + "/#/mainContent/menuEntry/227/planning"

# Chromium network-layer errors that just mean "no connectivity right now"
# (laptop asleep, Wi-Fi reconnecting after wake, captive portal, DNS not up yet).
_OFFLINE_MARKERS = (
    "ERR_INTERNET_DISCONNECTED", "ERR_NAME_NOT_RESOLVED", "ERR_NETWORK_CHANGED",
    "ERR_CONNECTION_RESET", "ERR_CONNECTION_CLOSED", "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT", "ERR_ADDRESS_UNREACHABLE", "ERR_PROXY_CONNECTION_FAILED",
    "ERR_TIMED_OUT",
)


class OfflineError(RuntimeError):
    """Raised when the machine has no working internet connection."""


def _is_offline(exc: BaseException) -> bool:
    return any(m in str(exc) for m in _OFFLINE_MARKERS)


IDP_HOST = "eliot.isae.fr"          # ISAE Shibboleth identity provider
USER_FIELD = "input#username, input[name='j_username'], input[name='username']"
PASS_FIELD = "input#password, input[name='j_password'], input[name='password']"
SUBMIT_BTN = (
    "button[name='_eventId_proceed'], button#login, "
    "button[type='submit'], input[type='submit'], input[name='_eventId_proceed']"
)


def _dump(page: Page, tag: str) -> None:
    """Save a screenshot + URL on failure, for debugging headless login."""
    try:
        shot = config.HERE / f"login-fail-{tag}.png"
        page.screenshot(path=str(shot), full_page=True)
        print(f"  [debug] stuck at {page.url}")
        print(f"  [debug] screenshot: {shot}")
    except Exception:
        pass


def _looks_like_login(page: Page) -> bool:
    if any(s in page.url for s in ("/auth/realms/", "/protocol/openid-connect/", IDP_HOST)):
        return True
    return page.locator(USER_FIELD).count() > 0


def _back_on_auriga(u: str) -> bool:
    return "auriga.isae-supaero.fr" in u and "/auth/" not in u and "/login" not in u


def _do_keycloak_login(page: Page) -> None:
    user = keyring.get_password(SERVICE, "username")
    pw = keyring.get_password(SERVICE, "password")
    if not user or not pw:
        sys.exit("No credentials in Keychain. Run:  python setup_login.py")

    # Keycloak page: choose the ISAE-SUPAERO identity provider rather than the
    # local email/password form. (Skip if we're already on the CAS page.)
    if "auth/realms/" in page.url or "/protocol/openid-connect/" in page.url:
        sso = page.locator(
            "#social-isae-supaero, a[href*='broker'], "
            "a:has-text('SSO ISAE-SUPAERO'), button:has-text('SSO ISAE-SUPAERO')"
        ).first
        try:
            sso.wait_for(timeout=8_000)
            sso.click()
            page.wait_for_url(lambda u: IDP_HOST in u, timeout=20_000)
        except PWTimeout:
            _dump(page, "no-idp-redirect")
            sys.exit(
                "Clicking 'SSO ISAE-SUPAERO' did not reach the ISAE login page -- "
                "layout changed. Run `python fetch_timetable.py --login` to log in by hand."
            )

    # Shibboleth IdP (eliot.isae.fr): username/password form.
    try:
        page.wait_for_selector(USER_FIELD, timeout=20_000)
        page.fill(USER_FIELD, user)
        page.fill(PASS_FIELD, pw)
        page.click(SUBMIT_BTN)
    except PWTimeout:
        _dump(page, "no-login-fields")
        sys.exit(
            "Could not find the ISAE login fields -- layout changed. "
            "Run `python fetch_timetable.py --login` to log in by hand."
        )

    # Possible one-off attribute-release consent page -- click through it.
    for _ in range(3):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except PWTimeout:
            break
        if _back_on_auriga(page.url):
            break
        if IDP_HOST in page.url and page.locator(SUBMIT_BTN).count():
            page.click(SUBMIT_BTN)
            continue
        break

    try:
        page.wait_for_url(_back_on_auriga, timeout=45_000)
    except PWTimeout:
        errs = page.locator(
            ".form-error, .form-element-error, p.form-error, .alert-error, "
            "#error, .errors, #msg.errors, .kc-feedback-text"
        ).all_inner_texts()
        _dump(page, "no-return-to-auriga")
        hint = f" Server said: {errs}" if errs else ""
        sys.exit(
            "Login did not complete -- wrong password, an MFA prompt, or the SSO "
            f"changed again.{hint} Try `python fetch_timetable.py --login` by hand."
        )


def open_authenticated(headless: bool = True):
    """Returns (playwright, browser, page). Caller must call browser.close()
    and playwright.stop() -- or use the `authenticated_page` context manager."""
    pw = sync_playwright().start()
    browser = None
    launch_err: BaseException | None = None
    for attempt in range(3):
        try:
            browser = pw.chromium.launch(headless=headless)
            launch_err = None
            break
        except PWTimeout as e:
            # right after waking from sleep, Chromium can be slow to spawn
            launch_err = e
            if attempt < 2:
                time.sleep(20)
    if launch_err is not None:
        pw.stop()
        # Unlike a network drop, a browser that still won't start after 3 tries
        # is worth surfacing (disk full, corrupted install, ...) rather than
        # silently skipping -- so this is NOT an OfflineError.
        raise RuntimeError(f"Chromium failed to launch after 3 attempts: {launch_err}")

    ctx_kwargs = {}
    if config.STORAGE_STATE.exists():
        ctx_kwargs["storage_state"] = str(config.STORAGE_STATE)
    context = browser.new_context(**ctx_kwargs)
    page = context.new_page()

    # Retry the first navigation a few times -- covers Wi-Fi still coming back
    # after the Mac wakes for a scheduled run.
    last_err: BaseException | None = None
    for attempt in range(4):
        try:
            page.goto(PLANNING_PAGE, wait_until="domcontentloaded")
            last_err = None
            break
        except Exception as e:  # noqa: BLE001 -- inspect then re-raise/translate
            last_err = e
            if not _is_offline(e) or attempt == 3:
                break
            time.sleep(15)
    if last_err is not None:
        browser.close()
        pw.stop()
        if _is_offline(last_err):
            raise OfflineError(str(last_err))
        raise last_err
    page.wait_for_timeout(2500)  # let Keycloak-js decide whether to redirect

    if _looks_like_login(page):
        _do_keycloak_login(page)
        page.wait_for_timeout(2500)

    context.storage_state(path=str(config.STORAGE_STATE))
    return pw, browser, page


class authenticated_page:
    def __init__(self, headless: bool = True):
        self.headless = headless

    def __enter__(self) -> Page:
        self._pw, self._browser, page = open_authenticated(self.headless)
        return page

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._pw.stop()
