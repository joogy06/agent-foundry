# Person Schema + Canonical Bio

JSON-LD `Person` / `sameAs` worked example and the canonical-bio pattern for `career-online-presence`. This is what AI answer engines and search read to resolve a person as an entity.

---

## Why schema-mark the person

AI engines and search resolve "who is <name>" by assembling an entity from structured and corroborating signals. A `Person` block on your own site (the canonical layer) gives them an authoritative anchor; `sameAs` ties your scattered profiles into one entity instead of several ambiguous ones.

## Worked Example — JSON-LD `Person` + `sameAs`

Place in the `<head>` of your personal site's home/bio page:

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Person",
  "name": "Jordan Avery",
  "url": "https://jordanavery.dev",
  "jobTitle": "Markets Technology Engineer",
  "description": "Builds auditable trading-desk controls and surveillance automation in capital markets.",
  "knowsAbout": ["post-trade controls", "surveillance automation", "model-risk evidencing"],
  "sameAs": [
    "https://www.linkedin.com/in/jordanavery",
    "https://github.com/jordanavery",
    "https://bsky.app/profile/jordanavery.bsky.social",
    "https://jordanavery.substack.com"
  ]
}
</script>
```

- `url` is your canonical home.
- `sameAs` lists ONLY profiles you actually own and keep consistent.
- `description` / `knowsAbout` should match your canonical bio and CV — consistency is the trust signal.

## Canonical Bio Pattern

Write ONE authoritative bio. Reuse it verbatim (or lightly trimmed) everywhere: site, LinkedIn About, GitHub profile README, newsletter About, conference bio.

**Three-length kit:**
- **One-liner** (≤120 chars): "Markets-tech engineer building auditable trading controls."
- **Short** (2–3 sentences): role + the specific problem you work + one concrete proof.
- **Long** (1 paragraph): the short version + trajectory + what you want to be known for.

**Rules:**
- Same job title and focus across all surfaces (screened for consistency).
- Specific, true, and in your own voice (run it through `human-voice-writing` if it reads generic).
- No claims that don't also hold up on your CV (HARD RULE 4 / HARD RULE 3 of the parent skill).

## Maintenance

- Update `sameAs` whenever you add or retire a profile.
- Re-check the bio at each role change; propagate the change to every surface in one pass (consistency).
- The schema block is part of the freshness discipline — a current entity graph is cited more often than a stale one (see `market-snapshot-2026-06.md`).
