"""Outreach signals: fresh "we're hiring" posts, newly funded startups and their founders.

Runs after each sweep (`gradient.cli signals`). Public, no-login sources only: Bluesky and
Mastodon search APIs, news RSS (Google News, TechCrunch, Crunchbase News, Inc42), YC batch data
and YC company pages (founders are listed there publicly). LinkedIn and X posts need a login,
so the site links out to their searches instead of scraping them.
"""
