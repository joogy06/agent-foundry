"""The AI surface registry: complete rows, a 90-day age WARN, and no availability claims
restated in skill prose (best-effort grep)."""
from __future__ import annotations

import copy
import re
import subprocess
import sys
import unittest
import warnings
from datetime import date, timedelta
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SKILLS = SKILL.parent
sys.path.insert(0, str(SKILL / "scripts"))

import surfaces  # noqa: E402

DOC = surfaces.load()

#: The search and AI-visibility family whose prose must link the registry, not restate it.
FAMILY = [
    "ai-search-optimizer", "agentic-commerce-readiness", "markdown-for-agents", "ai-assistant-referrals",
    "seo-authority-builder", "seo-content-strategist", "seo-data-analyst", "seo-keyword-strategist",
    "seo-meta-optimizer", "seo-serp-optimizer", "seo-structure-architect", "ecommerce-growth",
]
#: A place, case-sensitive so the pronoun "us" never counts.
GEO = (r"(?:\bGB\b|\bUK\b|\bU\.K\.|United Kingdom|Great Britain|\bBritain\b|\bBritish\b|"
       r"\bUS\b|\bU\.S\.|\bUSA\b|United States)")
#: An availability state, either direction ("available in the UK", "UK: live", "not live in GB",
#: "US-first", "US beta", "supported in the UK", "not listed for GB", "open in GB", "reached the
#: UK", "UK merchants can use"; post-convergence: "rolling out in the UK", "coming to Britain",
#: "enabled for GB", "disabled in the UK", "excluded from the UK", "the page lists GB", "not yet
#: in the UK").
STATE = (r"(?i:\b(?:available|availability|unavailable|live|only|eligible|ineligible|exclusive|"
         r"launched|rolled out|rolling out|first|beta|supported|supports?|listed|unlisted|lists|"
         r"open|opened|reached|arrived|expanded|coming|enabled|disabled|excluded|"
         r"not (?:yet )?in|can use|cannot use|can't use)\b)")
CLAIM = re.compile(rf"{GEO}[^|]{{0,60}}?{STATE}|{STATE}[^|]{{0,60}}?{GEO}")
#: A parenthesised market marker ("Instant Buy (US)") is a claim on its face.
PAREN_MARKER = re.compile(r"\((?:US|UK|GB|USA|U\.S\.|U\.K\.)(?:\s+only)?\)")
#: A comma-separated market list ("US, CA, AU"), counted in a cell under a "Markets" header.
MARKET = r"(?:\b[A-Z]{2}\b|United Kingdom|United States|Great Britain|Britain)"
COMMA_MARKETS = re.compile(rf"{MARKET}(?:\s*,\s*(?:and\s+)?{MARKET})+")
MARKETS_HEAD = re.compile(r"(?i)\bmarkets?\b")
#: A market list ("US/CA/AU", "UK/IE") is an availability claim on its face.
MARKET_LIST = re.compile(r"\b(?:US|UK|GB|CA|AU|NZ|IE|IN|DE|FR)(?:\s?/\s?(?:US|UK|GB|CA|AU|NZ|IE|IN|DE|FR)\b)+")
GEO_RE = re.compile(GEO)
STATE_RE = re.compile(STATE)
POINTER = re.compile(r"registry|surfaces\.v1\.json|surfaces\.py", re.IGNORECASE)
#: The allow-list, kept small on purpose: only the registry's owner may state the rule itself
#: (how to phrase a GB status the primary page does not list), and PSP market facts, which are
#: not registry surfaces, may stay in their own dated, sourced table rows (each is a FRESHNESS
#: anchor with its own source_url). Exact phrases, per file, so nothing else rides on them. The
#: registry data file is JSON and is never scanned.
RULE_DOCS: dict[str, tuple[str, ...]] = {
    "ai-search-optimizer/SKILL.md": ('say "not listed for GB"',),
    "agentic-commerce-readiness/references/standards.md": (
        "Lists **GB** as a seller country, as of 2026-09-27",          # Stripe ACS
        "limited to **US enterprise merchants** as of 2026-09-27",     # Adyen Agentic
    ),
}


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_claim(text: str, allow: tuple[str, ...] = ()) -> bool:
    for rule in allow:
        text = text.replace(rule, "")
    if POINTER.search(text) and not STATE_RE.search(text):
        return False
    return bool(CLAIM.search(text) or MARKET_LIST.search(text) or PAREN_MARKER.search(text))


def availability_claims(text: str, allow: tuple[str, ...] = ()):
    """Yield (lineno, text) for prose that states a surface's availability in a place.

    Both directions; a claim wrapped across lines (a paragraph or list item is joined before it
    is scanned); a market list ("US/CA/AU"); and in tables, a claim inside one cell or ANY
    non-empty cell under a header cell that names a place (a "UK" column). Only a pure pointer
    (it names the registry and carries no state word) is exempt; pointing at the registry does
    not license restating it. Frontmatter, code fences and HTML comments are skipped.
    """
    header: list[str] | None = None
    in_code = in_comment = False
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":            # frontmatter is routing, not a claim
        start = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0) + 1
    para: list[str] = []
    para_start = 0

    def flush():
        nonlocal para
        joined = " ".join(para)
        para = []
        if joined and _is_claim(joined, allow):
            yield para_start, joined

    for n, line in enumerate(lines, 1):
        if n <= start:
            continue
        s = line.strip()
        if s.startswith("```"):
            yield from flush()
            in_code = not in_code
            continue
        if in_comment:
            in_comment = "-->" not in s
            continue
        if s.startswith("<!--"):
            yield from flush()
            in_comment = "-->" not in s
            continue
        if in_code:
            continue
        if s.startswith("|"):
            yield from flush()
            if header is None:
                header = _cells(s)
                if _is_claim(s, allow):
                    yield n, s
                continue
            if set(s.replace("|", "").strip()) <= set("-: "):
                continue
            hit = _is_claim(s, allow)
            if not hit:
                for head, cell in zip(header, _cells(s)):
                    if GEO_RE.search(head) and cell and cell not in ("-", chr(0x2014)):
                        hit = True
                    if MARKETS_HEAD.search(head) and COMMA_MARKETS.search(cell):
                        hit = True
            if hit:
                yield n, s
            continue
        header = None
        body = s.lstrip(">").strip()          # a blockquote line reads as its text
        if not body or body.startswith("#") or re.match(r"(?:[-*+]|\d+[.)])\s", body):
            yield from flush()
        if body:
            if not para:
                para_start = n
            para.append(body)
            if body.startswith("#"):
                yield from flush()
    yield from flush()


class RegistryRows(unittest.TestCase):
    def test_registry_is_valid_today(self):
        errors, warns = surfaces.validate(DOC)
        self.assertEqual(errors, [])
        for w in warns:   # age is a WARN: surfaced, never failing
            warnings.warn(f"surface registry: {w}", stacklevel=1)

    def test_every_row_carries_every_required_field(self):
        required = set(DOC["required_fields"])
        self.assertTrue({"vendor", "surface_type", "gb_availability", "gb_evidence_url",
                         "feed_or_protocol", "crawler_ua", "measurement", "as_of",
                         "review_after", "source_url"} <= required)
        for row in DOC["surfaces"]:
            self.assertEqual(required - set(row), set(), row.get("id"))

    def test_brief_surfaces_are_present(self):
        ids = {r["id"] for r in DOC["surfaces"]}
        for needed in ("google-search", "google-ai-overviews", "google-ai-mode", "gemini", "chatgpt-search",
                       "chatgpt-shopping", "chatgpt-apps", "copilot", "bing", "perplexity", "duckduckgo",
                       "duckduckgo-search-assist", "apple-siri-ai", "apple-safari-spotlight", "meta-ai",
                       "grok", "amazon-rufus-alexa"):
            self.assertIn(needed, ids)

    def test_missing_gb_field_is_an_error(self):
        doc = copy.deepcopy(DOC)
        del doc["surfaces"][0]["gb_availability"]
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("gb_availability" in e for e in errors), errors)

    def test_confident_gb_claim_needs_evidence(self):
        doc = copy.deepcopy(DOC)
        row = next(r for r in doc["surfaces"] if r["evidence"] == "V")
        row["gb_evidence_url"] = None
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("gb_evidence_url" in e for e in errors), errors)

    def test_measurement_points_at_ai_assistant_referrals(self):
        doc = copy.deepcopy(DOC)
        doc["surfaces"][0]["measurement"] = "GA4"
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("measurement" in e for e in errors), errors)

    def test_old_row_warns_but_does_not_error(self):
        later = date.fromisoformat(DOC["as_of"]) + timedelta(days=DOC["max_age_days"] + 1)
        errors, warns = surfaces.validate(DOC, today=later)
        self.assertEqual(errors, [])
        self.assertTrue(any("days old" in w for w in warns))

    # --- fix round 1 (C1, C8, C10, S10d) ---------------------------------------------
    def _row(self, doc, rid):
        return next(r for r in doc["surfaces"] if r["id"] == rid)

    def test_null_gb_evidence_only_when_unknown(self):
        doc = copy.deepcopy(DOC)
        row = self._row(doc, "copilot-checkout")          # us_only
        row["gb_evidence_url"] = None
        row["evidence"] = "I"                              # an I label does not excuse it
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("copilot-checkout" in e and "gb_evidence_url" in e for e in errors), errors)

    def test_live_claim_on_inferred_evidence_warns_and_shows_inferred(self):
        doc = copy.deepcopy(DOC)
        row = self._row(doc, "copilot")
        row["evidence"] = "I"
        _, warns = surfaces.validate(doc)
        self.assertTrue(any("copilot:" in w and "inferred" in w for w in warns), warns)
        self.assertEqual(surfaces.gb_label(row), "live (inferred)")
        self.assertEqual(surfaces.gb_label(self._row(DOC, "bing")), "live")

    def test_forecast_rows_need_forecast_due_and_warn_when_passed(self):
        doc = copy.deepcopy(DOC)
        row = self._row(doc, "bing")
        row["status"] = "FORECAST"
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("forecast_due" in e for e in errors), errors)
        row["forecast_due"] = "2026-01-01"
        errors, warns = surfaces.validate(doc)
        self.assertFalse(any("forecast_due" in e for e in errors), errors)
        self.assertTrue(any("forecast_due" in w for w in warns), warns)

    def test_malformed_rows_are_errors_not_crashes(self):
        doc = copy.deepcopy(DOC)
        doc["surfaces"].append("not a row")
        self._row(doc, "bing")["gb_share"] = "5%"
        self._row(doc, "perplexity")["crawler_ua"] = "PerplexityBot"
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("not an object" in e for e in errors), errors)
        self.assertTrue(any("bing" in e and "gb_share" in e for e in errors), errors)
        self.assertTrue(any("perplexity:" in e and "crawler_ua" in e for e in errors), errors)

    def test_max_age_is_capped_at_90_days(self):
        doc = copy.deepcopy(DOC)
        doc["max_age_days"] = 400
        later = date.fromisoformat(DOC["as_of"]) + timedelta(days=91)
        errors, warns = surfaces.validate(doc, today=later)
        self.assertTrue(any("max_age_days" in w for w in warns), warns)
        self.assertTrue(any("days old" in w for w in warns), warns)

    def test_review_after_window(self):
        doc = copy.deepcopy(DOC)
        row = self._row(doc, "bing")
        row["review_after"] = "2027-06-01"                 # beyond as_of + 90
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("bing" in e and "review_after" in e for e in errors), errors)
        row["review_after"] = "2026-01-01"                 # before as_of
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("bing" in e and "review_after" in e for e in errors), errors)

    def test_null_source_url_only_for_unverifiable_inferred_rows(self):
        doc = copy.deepcopy(DOC)
        self.assertIsNone(self._row(doc, "grok")["source_url"])
        self.assertEqual(surfaces.validate(doc)[0], [])
        row = self._row(doc, "bing")
        row["source_url"] = None
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("bing" in e and "source_url" in e for e in errors), errors)

    def test_gemini_answers_and_shopping_are_separate_rows(self):
        self.assertEqual(self._row(DOC, "gemini")["gb_availability"], "live")
        self.assertEqual(self._row(DOC, "gemini")["surface_type"], "answer")
        shop = self._row(DOC, "gemini-shopping")
        self.assertEqual(shop["gb_availability"], "unknown")
        self.assertIn("could not verify", shop["notes"].lower())

    def test_bad_today_is_rejected_by_argparse(self):
        script = SKILL / "scripts" / "surfaces.py"
        r = subprocess.run([sys.executable, str(script), "check", "--today", "yesterday"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--today", r.stderr)

    def test_cli_check_and_show(self):
        script = SKILL / "scripts" / "surfaces.py"
        r = subprocess.run([sys.executable, str(script), "check"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout)
        r = subprocess.run([sys.executable, str(script), "show", "--type", "checkout"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertIn("Copilot Checkout", r.stdout)
        self.assertNotIn("Google Search (web", r.stdout)


class TrustedSchema(unittest.TestCase):
    """Finding 5 (fix round 2): the validator does not trust the schema inside the file it
    validates. Deleting or corrupting `enums` / `required_fields` is itself an error, and a row
    carrying a bad value still fails against the hard-coded copy."""

    def _bad_row(self, doc, value):
        doc["surfaces"][0]["gb_availability"] = value
        return doc

    def test_deleted_enums_or_required_fields_are_errors(self):
        for key in ("enums", "required_fields"):
            for value in ("yes",):
                doc = self._bad_row(copy.deepcopy(DOC), value)
                del doc[key]
                errors, _ = surfaces.validate(doc)
                self.assertTrue(any(key in e for e in errors), (key, errors))
                self.assertTrue(any("gb_availability" in e for e in errors), (key, errors))

    def test_wrong_typed_enums_or_required_fields_are_errors(self):
        for key, bad in (("enums", []), ("enums", "x"), ("enums", {"gb_availability": "live"}),
                         ("required_fields", {}), ("required_fields", "id"),
                         ("required_fields", [1, 2])):
            doc = self._bad_row(copy.deepcopy(DOC), "yes")
            doc[key] = bad
            errors, _ = surfaces.validate(doc)
            self.assertTrue(any(key in e for e in errors), (key, bad, errors))
            self.assertTrue(any("'yes'" in e and "gb_availability" in e for e in errors), errors)

    def test_widened_enum_does_not_license_a_bad_value(self):
        doc = self._bad_row(copy.deepcopy(DOC), "yes")
        doc["enums"]["gb_availability"].append("yes")
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("enums" in e for e in errors), errors)
        self.assertTrue(any("'yes'" in e for e in errors), errors)

    def test_dropped_required_field_still_required(self):
        doc = copy.deepcopy(DOC)
        doc["required_fields"].remove("gb_availability")
        del doc["surfaces"][0]["gb_availability"]
        errors, _ = surfaces.validate(doc)
        self.assertTrue(any("required_fields" in e for e in errors), errors)
        self.assertTrue(any("missing required field 'gb_availability'" in e for e in errors), errors)

    def test_live_registry_matches_the_trusted_copy(self):
        self.assertEqual(DOC["enums"], surfaces.TRUSTED_ENUMS)
        self.assertEqual(DOC["required_fields"], surfaces.TRUSTED_REQUIRED)


def prose_lines(path: Path):
    in_code = in_comment = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_comment:
            in_comment = "-->" not in s
            continue
        if s.startswith("<!--"):
            in_comment = "-->" not in s
            continue
        if not in_code:
            yield n, line


class NoDuplicatedAvailability(unittest.TestCase):
    def test_catches_optimistic_and_pessimistic_claims(self):
        for text in ("Copilot Checkout is available in the UK.\n",
                     "Instant Buy is not live in the UK.\n",
                     "Siri AI: UK live, EU later\n",
                     "| Surface | Notes |\n|---|---|\n| Copilot | available in the United States only |\n",
                     "| Surface | UK |\n|---|---|\n| Copilot Checkout | live |\n",
                     "Per the registry, Copilot Checkout is US only.\n"):
            self.assertTrue(list(availability_claims(text)), text)

    def test_fix_round_2_recall(self):
        """Finding 4: phrasings the first guard missed, including wrapped claims and cells."""
        for text in ("Every checkout surface is US-first today.\n",
                     "Instant Buy is a US beta.\n",
                     "Checkout is open in the US/CA/AU.\n",
                     "Copilot Checkout is supported in the UK.\n",
                     "Copilot Checkout is now supported in the UK.\n",
                     "Rufus is not listed for GB.\n",
                     "Instant Checkout is open in GB.\n",
                     "Universal Cart reached the UK in May.\n",
                     "UK merchants can use Copilot Checkout.\n",
                     "Copilot Checkout is, after a long\nwait, now supported for sellers based in the\nUnited Kingdom.\n",
                     "| Surface | GB |\n|---|---|\n| Copilot Checkout | yes |\n",
                     "| Surface | US status |\n|---|---|\n| Instant Buy | since May |\n"):
            self.assertTrue(list(availability_claims(text)), text)

    def test_post_convergence_recall(self):
        """Post-convergence minor 3: state words, Britain/British, Markets lists, (US) markers."""
        for text in ("Copilot Checkout is rolling out in the UK.\n",
                     "Instant Buy is coming to Britain next year.\n",
                     "Agent checkout is enabled for GB merchants.\n",
                     "The feature is disabled in the UK.\n",
                     "British sellers are excluded from the beta programme.\n",
                     "The Stripe page lists GB as a seller country.\n",
                     "Instant Buy is not in the UK.\n",
                     "Instant Buy is not yet in the UK.\n",
                     "Buy for Me (US) lets an agent check out.\n",
                     "| Surface | Markets |\n|---|---|\n| Instant Buy | US, CA, AU |\n",
                     "| Surface | Markets |\n|---|---|\n| Checkout | United States, United Kingdom |\n"):
            self.assertTrue(list(availability_claims(text)), text)
        for text in ("| Surface | Markets |\n|---|---|\n| Checkout | see the registry |\n",
                     "| Tool | Notes |\n|---|---|\n| GA4 | UTM, API, SQL |\n",
                     "The page is coming along.\n"):
            self.assertEqual(list(availability_claims(text)), [], text)

    def test_allow_list_is_small_and_file_scoped(self):
        self.assertEqual(set(RULE_DOCS), {"ai-search-optimizer/SKILL.md",
                                          "agentic-commerce-readiness/references/standards.md"})
        text = 'If the page does not list it, say "not listed for GB".\n'
        self.assertTrue(list(availability_claims(text)))
        self.assertEqual(list(availability_claims(text, RULE_DOCS["ai-search-optimizer/SKILL.md"])), [])

    def test_psp_market_facts_are_restored_dated_and_allowed_one_entry_each(self):
        """Post-convergence minor 2: the Stripe and Adyen market facts are back, each dated, each
        its own allow-list entry and its own FRESHNESS anchor with a source_url."""
        rel = "agentic-commerce-readiness/references/standards.md"
        allow = RULE_DOCS[rel]
        self.assertEqual(len(allow), 2)
        text = (SKILLS / rel).read_text(encoding="utf-8")
        stripe = next(l for l in text.splitlines() if l.startswith("| Stripe Agentic Commerce Suite"))
        adyen = next(l for l in text.splitlines() if l.startswith("| Adyen Agentic"))
        self.assertIn(allow[0], stripe)
        self.assertIn(allow[1], adyen)
        for row, url in ((stripe, "https://docs.stripe.com/agentic-commerce/for-sellers"),
                         (adyen, "https://www.adyen.com/press-and-media/adyen-agentic")):
            self.assertIn(url, row)
            self.assertTrue(list(availability_claims(row + "\n")), row)          # a claim without it
            self.assertEqual(list(availability_claims(row + "\n", allow)), [], row)
        other = text.replace(allow[0], "").replace(allow[1], "")
        self.assertNotIn("**GB**", other.split("## PSP and platform support", 1)[1].split("##", 1)[0])
        head = text.split("-->", 1)[0]
        for subject, url in (("stripe-acs-seller-countries", "https://docs.stripe.com/agentic-commerce/for-sellers"),
                             ("adyen-agentic-eligibility", "https://www.adyen.com/press-and-media/adyen-agentic")):
            anchor = head.split(f"subject: {subject}", 1)[1].split("- kind:", 1)[0]
            self.assertIn(f"source_url: {url}", anchor)
        self.assertEqual(head.count("source_url:"), head.count("- kind: external_fact"))

    def test_leaves_pointers_and_unrelated_prose_alone(self):
        for text in ("GB status: registry row `apple-siri-ai`.\n",
                     "Run `scripts/surfaces.py show --type checkout`.\n",
                     "Let us know if the page is live.\n",
                     "UK VAT is 20 percent on the displayed price.\n",
                     "```\nUK live\n```\n",
                     "<!-- FRESHNESS:v1\n  claim: UK live\n-->\n",
                     "---\nname: x\ndescription: surfaces with UK availability\n---\nbody\n"):
            self.assertEqual(list(availability_claims(text)), [], text)

    def test_skill_prose_links_the_registry_instead_of_restating_availability(self):
        offenders = []
        scanned = 0
        for name in FAMILY:
            sdir = SKILLS / name
            for f in [sdir / "SKILL.md", *sorted((sdir / "references").glob("*.md"))]:
                if not f.exists():
                    continue
                scanned += 1
                rel = f.relative_to(SKILLS).as_posix()
                for n, line in availability_claims(f.read_text(encoding="utf-8"), RULE_DOCS.get(rel, ())):
                    offenders.append(f"{f.relative_to(SKILLS)}:{n}: {line[:110]}")
        self.assertGreaterEqual(scanned, len(FAMILY))
        self.assertEqual(offenders, [], "restate availability via the registry:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
