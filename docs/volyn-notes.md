# Volynoblenergo: research notes

Status: **postponed** (2026-10-18). Not built. Reopen when the owner asks.

## What the source looks like

- Site: `https://energy.volyn.ua/spozhyvacham/perervy-u-elektropostachanni/hrafik-vidkliuchen/`.
  The page says the data refreshes every 60 minutes and shows an "Оновлено: DD-MM-YYYY HH:MM" stamp.
- No JSON API, unlike Ternopiloblenergo. The schedule is a server-rendered PHP form:
  - `POST /spozhyvacham/perervy-u-elektropostachanni/hrafik-vidkliuchen/pagephp.php`
  - fields:
    - `searchForm=searchFromForm`;
    - `formCity` (required, free text);
    - `formStreet` (optional, free text);
    - `formGpvDate` (`YYYY-MM-DD`, the `<select>` offers today and tomorrow).
  - The response is a full HTML page.
- There is no city/street catalogue: the site matches free text and asks for names without "м.", "с.", "вул.".
- Cloudflare is in front of the site.
- Other channels don't fit an address-based bot, because they need a personal account number:
  - Viber bot `viber://pa?chatURI=botvoe`;
  - personal cabinets at `ok.prosvitlo.com` and `kabinet.prosvitlo.com`.

## What is still unknown

- The result format. A single test search (`Луцьк` / `Лесі Українки` / 2026-10-19) returned the search page with no results and no tables. Most likely no outages were scheduled, but a cookie or session requirement is not ruled out.
- Queue naming: whether it uses `1.1`-style subqueues like Ternopil, or something else.
- Whether a building can sit in several queues.
- How "no schedule", "switching" and partial hours are shown.
- Whether the archive (`.../hrafik-vidkliuchen-arc/`) has a parseable format.

These need a Phase 0-style probe while outages are actually scheduled in Volyn. Record real responses as fixtures without personal addresses. Live calls only from `scripts/probe.py`, at most 1 request/second.

## Impact on the code if we build it

- A second source adapter that scrapes HTML. It is more fragile than JSON, so it needs strict validation and an `ApiSchemaError` on any layout change.
- Subqueues must be scoped by provider: Ternopil "1.1" and Volyn "1.1" are different schedules. This needs a migration of `subscriptions`, `subscription_subqueues` and `schedule_versions`, plus a provider key in `core`.
- `/add` for Volyn is text input only. There are no buttons, because there is no catalogue to page through.
- Building this generically opens the way for other oblenergos.
