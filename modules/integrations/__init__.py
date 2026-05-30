"""Third-party integrations for the 6DE Company Platform.

Each integration is opt-in via a feature flag in ``config.py`` and is written
so the core data-transform logic is credential-free and unit-testable. Live
API wiring (QBO OAuth, SMTP, Slack webhooks) is layered on top in a later
session — see ``docs/roadmap/integrations.md``.
"""
