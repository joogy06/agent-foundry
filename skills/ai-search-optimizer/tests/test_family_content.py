"""Content guards for the search and AI-visibility family (D21 fix round 1, 2026-09-27).

Each test pins a defect a reviewer found in the skill TEXT, so a later edit cannot quietly
reintroduce it: a robots template that opens crawl traps, measurement that folds paid into
organic, an incentivised review, a training policy stated two ways, a rubric that lets a
market with no surface score its way to "build".
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (SKILLS / rel).read_text(encoding="utf-8")


def robots_groups(block: str) -> list[tuple[list[str], list[str]]]:
    """Parse a robots.txt text into (user-agents, rules) groups (RFC 9309).

    Only an Allow or Disallow rule closes a group (RFC 9309 section 2.2.4): a user-agent line
    that follows only extension records (Content-Signal, Sitemap, Crawl-delay, ...) joins the
    same group, so those lines never split one group into two."""
    groups: list[tuple[list[str], list[str]]] = []
    agents: list[str] = []
    rules: list[str] = []
    for raw in block.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if any(r.startswith(("allow:", "disallow:")) for r in rules):
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value)
        else:
            rules.append(f"{key}: {value}")
    if agents:
        groups.append((agents, rules))
    return groups


#: The two variants of the one template, by the owner's answer to the training question.
VARIANTS = {"yes": '### Variant: training allowed (answer "yes")',
            "no": '### Variant: training refused (answer "no")'}


def template_head(text: str) -> str:
    """The template section's prose before its first code block."""
    return text.split("## robots.txt template", 1)[1].split("```", 1)[0]


def robots_block(text: str, answer: str) -> str:
    """The robots.txt code block of one variant (`answer` is the owner's "yes" or "no")."""
    return text.split(VARIANTS[answer], 1)[1].split("```", 2)[1]


WOO_TRAPS = ("/wp-admin/", "/cart/", "/checkout/", "/my-account/", "/*?add-to-cart=",
             "/*&add-to-cart=", "/*?*filter_", "/*?*orderby=")


def signal(answer: str) -> str:
    return f"content-signal: search=yes, ai-input=yes, ai-train={answer}"


class RobotsTemplate(unittest.TestCase):
    """S1: a named group REPLACES `*` (RFC 9309), so every allowing group repeats the traps."""

    def setUp(self):
        self.text = read("ai-search-optimizer/references/crawlers.md")
        self.variants = {a: robots_groups(robots_block(self.text, a)) for a in VARIANTS}

    def test_every_allowing_group_carries_the_woocommerce_disallows(self):
        for answer, groups in self.variants.items():
            allowing = [g for g in groups if "allow: /" in g[1]]
            self.assertTrue(allowing, answer)
            for agents, rules in allowing:
                for trap in WOO_TRAPS:
                    self.assertIn(f"disallow: {trap}", rules, (answer, agents))

    def test_star_group_exists_with_traps_and_the_answers_signal(self):
        for answer, groups in self.variants.items():
            star = [rules for agents, rules in groups if "*" in agents]
            self.assertEqual(len(star), 1, answer)
            self.assertIn(signal(answer), star[0])
            for trap in WOO_TRAPS:
                self.assertIn(f"disallow: {trap}", star[0], answer)

    def test_template_warns_that_named_groups_replace_star(self):
        head = template_head(self.text)
        self.assertIn("RFC 9309", head)
        self.assertRegex(head, r"(?i)replace")


# --- fix round 2: evaluate URL decisions, not string presence ---------------------------

def _rule_regex(path: str) -> re.Pattern:
    """RFC 9309 path pattern: `*` is any run of characters, a trailing `$` anchors the end."""
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    return re.compile("".join(".*" if c == "*" else re.escape(c) for c in body) + ("$" if anchored else ""))


def rfc9309_allowed(block: str, user_agent: str, url_path: str) -> bool:
    """Is `url_path` allowed for `user_agent`? A small RFC 9309 matcher: the groups naming the
    agent (case-insensitive product token; merged when several do) else `*`; the longest
    matching rule wins; Allow wins a tie; no matching rule means allowed."""
    groups = robots_groups(block)
    ua = user_agent.lower()
    named = [rules for agents, rules in groups if ua in {a.lower() for a in agents}]
    rules = [r for g in (named or [rules for agents, rules in groups if "*" in agents]) for r in g]
    best_len, best_allow = -1, True
    for rule in rules:
        kind, _, pattern = rule.partition(": ")
        if kind not in ("allow", "disallow") or not pattern:
            continue
        if _rule_regex(pattern).match(url_path):
            length = len(pattern)
            if length > best_len or (length == best_len and kind == "allow"):
                best_len, best_allow = length, kind == "allow"
    return best_allow


#: The training class, from crawlers.md's table and the store owner's list (cpmail
#: 01M3HN1SMG86E247E9T6S4ZXM0); Bytespider is labelled [I] in crawlers.md.
TRAINING_TOKENS = ("GPTBot", "ClaudeBot", "CCBot", "meta-externalagent", "Amazonbot",
                   "Applebot-Extended", "Bytespider", "Google-Extended")
EXCEPTION_RE = re.compile(r"#\s*training-exception:\s*(\S+)", re.IGNORECASE)
AI_TRAIN_RE = re.compile(r"(?im)^\s*content-signal:.*?\bai-train\s*=\s*(\w+)")
PRODUCT = "/product/x/"


def training_policy_conflicts(block: str) -> list[str]:
    """The consistency guard: the robots groups must match the file's `ai-train` answer.

    `ai-train=yes` requires every training token to be allowed on a product page, and takes no
    exception. `ai-train=no` requires every training token to be refused there, except
    `Google-Extended` when the file declares `# training-exception: Google-Extended` (its allow
    keeps Gemini grounding). Any other declared exception, or mixed `ai-train` values, is itself
    a conflict. A file with no `ai-train` signal is not checked."""
    answers = {m.group(1).lower() for m in AI_TRAIN_RE.finditer(block)}
    if not answers:
        return []
    if len(answers) > 1:
        return [f"mixed ai-train values: {', '.join(sorted(answers))}"]
    answer = answers.pop()
    declared = [m.group(1) for m in EXCEPTION_RE.finditer(block)]
    conflicts = [f"training-exception: {tok}" for tok in declared
                 if answer != "no" or tok.lower() != "google-extended"]
    excused = {tok.lower() for tok in declared} if answer == "no" else set()
    for token in TRAINING_TOKENS:
        allowed = rfc9309_allowed(block, token, PRODUCT)
        if answer == "yes" and not allowed:
            conflicts.append(token)
        elif answer == "no" and allowed and not (token == "Google-Extended" and "google-extended" in excused):
            conflicts.append(token)
    return conflicts


DENIED = ("/cart/", "/checkout/", "/checkout/order-received/1/", "/my-account/",
          "/wp-admin/", "/product/x/?add-to-cart=123",
          "/product/x/?utm_source=chatgpt.com&add-to-cart=123",
          "/shop/?filter_colour=red", "/shop/?utm_source=x&filter_colour=red",
          "/shop/?orderby=price", "/shop/?page=2&orderby=price")
ALLOWED = ("/", "/product/x/", "/product/x/?utm_source=chatgpt.com", "/product-category/gpus/",
           "/wp-admin/admin-ajax.php", "/sitemap_index.xml")
SEARCH_BOTS = ("Googlebot", "bingbot", "OAI-SearchBot", "Claude-SearchBot", "PerplexityBot",
               "meta-webindexer", "Amzn-SearchBot", "DuckAssistBot")


def _stripped(block: str, answer: str) -> str:
    """The variant with its training group and ai-train value removed, to compare the rest."""
    lines = [l for l in block.splitlines() if "ai-train=" not in l]
    kept, skip = [], False
    for l in lines:
        if l.startswith("# Training"):
            skip = True
        elif skip and l.startswith("Sitemap:"):
            skip = False
        if not skip:
            kept.append(l)
    return "\n".join(kept)


class RobotsDecisions(unittest.TestCase):
    """Findings 1, 2 and 7: URL decisions per group, the training answer, group parity. The
    store-owner correction (cpmail 01M3HN1SMG86E247E9T6S4ZXM0): training is asked, never assumed."""

    def setUp(self):
        self.text = read("ai-search-optimizer/references/crawlers.md")
        self.blocks = {a: robots_block(self.text, a) for a in VARIANTS}

    def test_matcher_follows_rfc9309(self):
        b = "User-agent: *\nAllow: /\nDisallow: /a/\nAllow: /a/b\nDisallow: /*.pdf$\n"
        self.assertFalse(rfc9309_allowed(b, "x", "/a/c"))
        self.assertTrue(rfc9309_allowed(b, "x", "/a/b"))
        self.assertFalse(rfc9309_allowed(b, "x", "/f.pdf"))
        self.assertTrue(rfc9309_allowed(b, "x", "/f.pdf?x=1"))
        self.assertTrue(rfc9309_allowed("User-agent: *\nDisallow: /a\nAllow: /a\n", "x", "/a"))

    def test_extension_records_do_not_split_a_group(self):
        """Post-convergence minor 5: RFC 9309 section 2.2.4, only Allow/Disallow close a group."""
        b = ("User-agent: *\nAllow: /\n"
             "User-agent: Googlebot\nContent-Signal: search=yes, ai-input=yes, ai-train=no\n"
             "User-agent: Google-Extended\nDisallow: /\n")
        self.assertFalse(rfc9309_allowed(b, "Googlebot", PRODUCT))
        self.assertFalse(rfc9309_allowed(b, "Google-Extended", PRODUCT))
        self.assertTrue(rfc9309_allowed(b, "bingbot", PRODUCT))
        self.assertEqual([g[0] for g in robots_groups(b)], [["*"], ["Googlebot", "Google-Extended"]])
        with_sitemap = b.replace("Content-Signal", "Sitemap: https://example.com/s.xml\nContent-Signal")
        self.assertFalse(rfc9309_allowed(with_sitemap, "Googlebot", PRODUCT))

    def test_later_parameter_add_to_cart_was_the_hole(self):
        old = "User-agent: *\nDisallow: /*?add-to-cart=\n"
        self.assertTrue(rfc9309_allowed(old, "x", "/product/x/?utm_source=chatgpt.com&add-to-cart=123"))

    def test_every_group_decides_every_url_in_both_variants(self):
        training = {t.lower() for t in TRAINING_TOKENS}
        for answer, block in self.blocks.items():
            agents = {a for ags, _ in robots_groups(block) for a in ags} | set(SEARCH_BOTS)
            self.assertTrue(training <= {a.lower() for a in agents}, answer)
            for ua in sorted(agents):
                for path in DENIED:
                    self.assertFalse(rfc9309_allowed(block, ua, path), (answer, ua, path))
                for path in ALLOWED:
                    expect = answer == "yes" or ua.lower() not in training
                    self.assertEqual(rfc9309_allowed(block, ua, path), expect, (answer, ua, path))

    def test_search_bots_read_product_pages_in_both_variants(self):
        for answer, block in self.blocks.items():
            for ua in SEARCH_BOTS:
                self.assertTrue(rfc9309_allowed(block, ua, PRODUCT), (answer, ua))

    def test_allow_variant_lets_every_training_bot_read_product_pages(self):
        for ua in TRAINING_TOKENS:
            self.assertTrue(rfc9309_allowed(self.blocks["yes"], ua, PRODUCT), ua)
            self.assertFalse(rfc9309_allowed(self.blocks["no"], ua, PRODUCT), ua)

    def test_both_variants_are_consistent(self):
        for answer, block in self.blocks.items():
            self.assertEqual(training_policy_conflicts(block), [], answer)
            self.assertEqual({m.group(1) for m in AI_TRAIN_RE.finditer(block)}, {answer})

    def test_variants_differ_only_in_the_training_answer(self):
        """Traps, the admin-ajax allow and the Sitemap line are identical in both."""
        self.assertEqual(_stripped(self.blocks["yes"], "yes"), _stripped(self.blocks["no"], "no"))
        for block in self.blocks.values():
            self.assertRegex(block, r"(?m)^Sitemap: https://")

    def test_consistency_guard(self):
        """Replaces minor 6's exception-only guard: ai-train=yes needs every training token
        allowed, ai-train=no needs every one refused; the one exception is Google-Extended under
        ai-train=no; mixed files fail."""
        star = "User-agent: *\nContent-Signal: search=yes, ai-input=yes, ai-train={}\nDisallow: /cart/\n"
        refuse = "".join(f"User-agent: {t}\n" for t in TRAINING_TOKENS) + "Disallow: /\n"
        # ai-train=no, everything refused: consistent.
        self.assertEqual(training_policy_conflicts(star.format("no") + refuse), [])
        # ai-train=yes with the refusal group: every token conflicts.
        self.assertEqual(training_policy_conflicts(star.format("yes") + refuse), list(TRAINING_TOKENS))
        # ai-train=yes, all falling through to *: consistent.
        self.assertEqual(training_policy_conflicts(star.format("yes")), [])
        # ai-train=no, Google-Extended allowed: a conflict unless declared.
        mixed = (star.format("no") + "".join(f"User-agent: {t}\n" for t in TRAINING_TOKENS[:-1])
                 + "Disallow: /\nUser-agent: Google-Extended\nAllow: /\nDisallow: /cart/\n")
        self.assertEqual(training_policy_conflicts(mixed), ["Google-Extended"])
        self.assertEqual(training_policy_conflicts("# training-exception: Google-Extended\n" + mixed), [])
        # Any other exception token fails, and excuses nothing.
        gpt = star.format("no") + "User-agent: GPTBot\nAllow: /\n" + refuse.replace("User-agent: GPTBot\n", "")
        self.assertEqual(training_policy_conflicts("# training-exception: GPTBot\n" + gpt),
                         ["training-exception: GPTBot", "GPTBot"])
        # Under ai-train=yes no exception is valid, Google-Extended included.
        self.assertEqual(training_policy_conflicts("# training-exception: Google-Extended\n" + star.format("yes")),
                         ["training-exception: Google-Extended"])
        # ai-train=yes with one training token refused: mixed, fails.
        self.assertEqual(training_policy_conflicts(star.format("yes") + "User-agent: CCBot\nDisallow: /\n"),
                         ["CCBot"])
        # Two different ai-train values in one file fail.
        two = star.format("no") + "User-agent: OAI-SearchBot\nContent-Signal: ai-train=yes\nAllow: /\n"
        self.assertEqual(training_policy_conflicts(two), ["mixed ai-train values: no, yes"])

    def test_template_asks_the_training_question_and_recommends_yes(self):
        head = re.sub(r"\s+", " ", template_head(self.text))
        self.assertIn('"Do you want your content used for AI model training? yes / no"', head)
        self.assertRegex(head, r"(?i)recommended answer is \*\*\"yes\"\*\*")
        self.assertRegex(head, r"(?i)still the owner's call")
        self.assertNotRegex(self.text, r"(?i)allow search, block training")
        skill = re.sub(r"\s+", " ", read("ai-search-optimizer/SKILL.md"))
        self.assertIn("Do you want your content used for AI model training? yes / no", skill)
        self.assertNotRegex(skill, r"(?i)block training crawlers")

    def test_training_class_is_not_described_as_costless(self):
        """Post-convergence minor 1: refusing training bots costs Gemini-app/Vertex grounding."""
        row = next(l for l in self.text.splitlines() if l.startswith("| **Training**"))
        self.assertIn("Nothing in search; refusing Google-Extended also drops Gemini-app/Vertex grounding", row)
        self.assertNotRegex(row, r"(?i)or answers")
        for block in self.blocks.values():
            self.assertNotRegex(block, r"(?i)no search or answer benefit")

    def test_google_extended_refusal_states_the_grounding_cost_and_the_exception(self):
        after = self.text.split("## robots.txt template", 1)[1].split("## One training policy", 1)[0]
        self.assertRegex(after, r"(?is)Google-Extended.{0,400}grounding")
        self.assertIn("training-exception: Google-Extended", after)
        controls = read("ai-search-optimizer/references/controls.md")
        row = next(l for l in controls.splitlines() if l.startswith("| `Google-Extended`"))
        self.assertIn("grounding", row)
        self.assertNotIn("training only", row)
        self.assertNotRegex(row, r"(?i)refused by the family")
        skill = read("ai-search-optimizer/SKILL.md")
        self.assertNotRegex(skill, r"allow `Google-Extended` unless")

    def test_groups_that_block_wp_admin_reopen_admin_ajax(self):
        for block in self.blocks.values():
            for agents, rules in robots_groups(block):
                if "disallow: /wp-admin/" in rules:
                    self.assertIn("allow: /wp-admin/admin-ajax.php", rules, agents)

    def test_allowing_named_groups_carry_the_content_signal(self):
        for answer, block in self.blocks.items():
            for agents, rules in robots_groups(block):
                if "allow: /" in rules or "*" in agents:
                    self.assertIn(signal(answer), rules, (answer, agents))

    def test_sitemap_line_and_facet_warning(self):
        for block in self.blocks.values():
            self.assertRegex(block, r"(?m)^Sitemap: https://")
        head = self.text.split("## robots.txt template", 1)[1].split("## One training policy", 1)[0]
        self.assertRegex(head, r"(?is)filter_.{0,300}Googlebot|Googlebot.{0,300}filter_")
        self.assertIn("woocommerce-faceted-navigation", head)


class OneTrainingPolicy(unittest.TestCase):
    """S4: the family states one training policy, with exact syntax, in one place."""

    def test_markdown_for_agents_gives_exact_signal_syntax(self):
        text = read("markdown-for-agents/SKILL.md") + read("markdown-for-agents/references/implementation.md")
        self.assertIn("Content-Signal: search=yes, ai-input=yes, ai-train=no", text)
        self.assertIn("header('Content-Signal: search=yes, ai-input=yes, ai-train=no')", text)
        self.assertIn("send_headers", text)
        self.assertRegex(text, r"(?i)origin.{0,80}precedence|precedence.{0,80}origin")

    def test_crawlers_reference_links_the_policy(self):
        self.assertIn("One training policy", read("ai-search-optimizer/references/crawlers.md"))
        self.assertIn("ai-search-optimizer/references/crawlers.md", read("markdown-for-agents/SKILL.md"))


class ReferralMeasurement(unittest.TestCase):
    """S2: gateway self-referrals, and paid vs organic ChatGPT, before any consent diagnosis."""

    def setUp(self):
        self.skill = read("ai-assistant-referrals/SKILL.md")
        self.orders = read("ai-assistant-referrals/references/orders-and-privacy.md")

    def test_gateway_referral_exclusion_comes_before_consent(self):
        self.assertIn("unwanted referrals", self.skill)
        self.assertLess(self.skill.index("unwanted referrals"), self.skill.index("consent loss"))
        self.assertRegex(self.skill, r"(?i)paypal\.com")
        self.assertRegex(self.skill, r"(?i)worldpay")

    def test_floor_query_splits_on_utm_medium(self):
        self.assertIn("_wc_order_attribution_utm_medium", self.orders)
        self.assertIn("utm_medium=paid", self.orders + self.skill)
        self.assertRegex(self.skill, r"(?i)ChatGPT Ads.{0,80}separate|separate.{0,80}ChatGPT Ads")


class PaidMediums(unittest.TestCase):
    """Finding 3 (fix round 2): the documented floor query, run on fixture orders, keeps every
    paid medium out of organic and keeps an unknown medium on its own line."""

    def run_floor_query(self, orders):
        import sqlite3
        doc = read("ai-assistant-referrals/references/orders-and-privacy.md")
        sql = doc.split("**Counting a month (read-only).**", 1)[1].split("```sql", 1)[1].split("```", 1)[0]
        db = sqlite3.connect(":memory:")
        db.executescript(
            "CREATE TABLE wp_wc_orders (id INTEGER, status TEXT, total_amount REAL, date_created_gmt TEXT);"
            "CREATE TABLE wp_wc_orders_meta (order_id INTEGER, meta_key TEXT, meta_value TEXT);")
        for i, (medium, total) in enumerate(orders, 1):
            db.execute("INSERT INTO wp_wc_orders VALUES (?, 'wc-completed', ?, '2026-09-10 12:00:00')", (i, total))
            db.execute("INSERT INTO wp_wc_orders_meta VALUES (?, '_wc_order_attribution_utm_source', 'chatgpt.com')", (i,))
            if medium is not None:
                db.execute("INSERT INTO wp_wc_orders_meta VALUES (?, '_wc_order_attribution_utm_medium', ?)",
                           (i, medium))
        cur = db.execute(sql)
        cols = [c[0] for c in cur.description]
        totals: dict[str, float] = {}
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            totals[r["channel"]] = totals.get(r["channel"], 0) + r["revenue"]
        return totals

    def test_cpc_is_paid_not_organic(self):
        self.assertEqual(self.run_floor_query([("organic", 100), ("paid", 200), ("cpc", 300)]),
                         {"organic": 100, "paid": 500})

    def test_paid_medium_family_and_unknowns(self):
        paid = ["CPC", "ppc", "paidsearch", "cpm", "display", "paid_social", "Paid", "retargeting", "cpv"]
        totals = self.run_floor_query([(m, 1) for m in paid] + [(None, 10), ("referral", 20), ("email", 40)])
        self.assertEqual(totals, {"paid": len(paid), "organic": 30, "unclassified": 40})

    def test_prose_names_the_rule_and_the_ads_tag(self):
        doc = read("ai-assistant-referrals/references/orders-and-privacy.md")
        skill = read("ai-assistant-referrals/SKILL.md")
        self.assertIn("^(.*cp.*|ppc|retargeting|paid.*)$", doc)
        self.assertIn("utm_source=chatgpt.com&utm_medium=paid", doc + skill)
        self.assertRegex(skill, r"(?i)unclassified")
        self.assertNotIn("every other `chatgpt.com` medium as organic", doc)


class Reviews(unittest.TestCase):
    """S3: no skill tells a UK store to pay for reviews."""

    def test_no_incentivised_review_copy(self):
        eg = read("ecommerce-growth/SKILL.md")
        self.assertNotRegex(eg, r"(?i)% off [^|\n]{0,30}for a review")
        self.assertIn("seo-authority-builder", eg)
        self.assertRegex(eg, r"(?i)unconditional on sentiment")


class ReadinessRubric(unittest.TestCase):
    """S5: no surface in your market is a gate, not a score."""

    def setUp(self):
        self.text = read("agentic-commerce-readiness/SKILL.md")

    def test_market_is_a_hard_gate(self):
        self.assertRegex(self.text, r"(?i)hard gate")
        self.assertNotIn("**\u22123 if none**", self.text)

    def test_gate_wording_does_not_overstate(self):
        """Finding 9 (fix round 2): unknown or unlisted evidence proves no route, not no agent."""
        self.assertNotRegex(self.text, r"(?i)no agent can transact")
        gate = self.text.split("**Step 1: the market gate", 1)[1].split("**Step 2", 1)[0]
        self.assertIn("no verified eligible route established", re.sub(r"\s+", " ", gate).replace("**", ""))
        example = self.text.split("> **Worked example", 1)[1].split("## 4.", 1)[0]
        flat = re.sub(r"\s*\n>?\s*", " ", example).replace("**", "")
        self.assertIn("no verified eligible route established", flat)

    def test_rubric_is_scored_per_product_line_and_uses_the_registry_command(self):
        self.assertRegex(self.text, r"(?i)per product line")
        self.assertIn("surfaces.py show --type checkout --gb live,beta", self.text)
        self.assertRegex(self.text, r"(?i)skip for now")


class SingleOwnership(unittest.TestCase):
    """S6/S7/S8/S10: one owner per fact, and the family's shared safeguards."""

    def test_one_google_ai_controls_table(self):
        owner = read("ai-search-optimizer/references/controls.md")
        self.assertIn("Search generative AI", owner)
        for rel in ("ai-search-optimizer/SKILL.md", "seo-meta-optimizer/SKILL.md"):
            text = read(rel)
            self.assertIn("references/controls.md", text, rel)
            self.assertNotRegex(text, r"\|\s*`?nosnippet", rel)   # no second controls table

    def test_serp_does_not_claim_preferred_sources(self):
        head = read("seo-serp-optimizer/SKILL.md").split("---", 2)[1]
        self.assertNotIn("preferred sources", head)

    def test_structure_architect_has_the_verify_block_and_others_point_at_it(self):
        self.assertIn("## Verify before you assert", read("seo-structure-architect/SKILL.md"))
        for name in ("seo-authority-builder", "seo-content-strategist", "seo-data-analyst",
                     "seo-keyword-strategist", "seo-meta-optimizer", "seo-serp-optimizer",
                     "ecommerce-growth"):
            self.assertIn("Verify before you assert", read(f"{name}/SKILL.md"), name)

    def test_identifier_exists_is_a_feed_attribute(self):
        for rel in ("ai-search-optimizer/SKILL.md", "seo-structure-architect/SKILL.md"):
            for line in read(rel).splitlines():
                if "identifier_exists" in line:
                    self.assertRegex(line, r"(?i)feed|merchant center", rel)

    def test_precedence_names_merchant_center_settings_not_the_content_api(self):
        text = read("seo-structure-architect/SKILL.md")
        self.assertNotIn("Content API settings >", text)
        self.assertIn("Merchant Center settings (UI or Merchant API)", text)

    def test_surfaces_commands_use_absolute_paths(self):
        for rel in ("ai-search-optimizer/SKILL.md", "agentic-commerce-readiness/SKILL.md"):
            for m in re.finditer(r"python3 (\S*surfaces\.py)", read(rel)):
                self.assertTrue(m.group(1).startswith("~/.claude/skills/"), (rel, m.group(1)))

