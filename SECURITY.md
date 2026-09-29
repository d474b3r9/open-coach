# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them
privately through GitHub: **Security → Report a vulnerability** on this
repository (a private security advisory visible only to the maintainer).

Useful details: affected version or commit, steps to reproduce, impact, and
whether credentials or personal data could be exposed.

You can expect an acknowledgement within a week. Fixes are released as soon
as practical, and the advisory is published once users can upgrade.

## Scope worth special care

- **Credentials**: Garmin / Strava credentials and token caches
  (`~/.garth/`, `~/.open-coach/strava_tokens.json`) must never be logged,
  committed or sent anywhere but to the platform they belong to.
- **Personal health data**: activities, heart rate, sleep and injuries stay on
  the athlete's machine (`~/.open-coach/`, gitignored `plans/`). A change that
  sends them to a third party is a security issue.
- **Watch platforms**: repeated failed logins can lock an account for 48 h+
  (Garmin SSO). Anything that retries logins in a loop counts as a bug here.
