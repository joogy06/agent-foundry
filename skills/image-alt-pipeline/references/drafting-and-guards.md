# Drafting, guards, review queue and cost

## Contents

- The draft request
- The draft response
- Guards
- Confidence and the review queue
- Sampling and model choice
- Cost model per 1,000 images (dated)
- Field-test traits (measured, 2026-10-25)
- Field measure: a real run (2026-10-26)
- Prompt injection and data handling

## The draft request

One request per deduplicated attachment. Send the image at a size the model actually uses (a long edge
of about 768 to 1,024 px is enough for alt text; larger costs more, and each vendor downscales past its
own limit anyway) plus a context block:

| Context field | From | Why |
|---|---|---|
| `use_roles` | Inventory | Link or button means functional alt; gallery means shot-specific alt |
| `products` | Catalogue: name, brand, model, colour, variant attributes, for every product using the image | The only allowed source of names and specs |
| `shared` | Use count > 1 across different products | Forces generic-but-true alt |
| `constant_attributes` | Catalogue attributes whose value is the same on **every** product using the image (the same case, colour or finish term) | A catalogue fact for the image itself: cheap to compute per asset and a strong context source; generic-but-true alt may name it |
| `page_type` | Product, category, article, home, landing | Wording and length |
| `adjacent_text` | Caption, heading, link text near the image | Avoid repeating it; may mean decorative |
| `file_name` | Inventory | A hint only, never a fact source |
| `house_style` | The site's alt style sheet (`image-alt-text`) | Language, length, banned words |

Instruction core (adapt, keep the rules): write alt to the house style; say what the image shows and
what it is for in this role; use a name, model or number only if it appears legibly in the image or in
`products`; if the image is shared, describe the object without naming one product; if the image adds
nothing beyond `adjacent_text`, return decorative; never use marketing adjectives or "image of"; when
the image is the only content of a link or button, the alt states only the destination or action and
does not describe the scene (without this line, models pad linked tiles with scene description).

## The draft response

Ask for structured output (JSON schema or tool call) with these fields:

`alt` (string, may be empty) | `decorative` (bool) | `facts_used` (list of {fact, source: image|image-legible|catalogue}) | `confidence` (0 to 1) | `notes` (why decorative, what was unclear)

Do not use self-reported confidence as a filter: in the field test it was 0.96 to 0.99 on every answer,
the wrong ones included. Keep the field for the log; route by guards, use count and sampled review.

## Guards

Run every draft through mechanical checks before it can enter a write-back plan. A failed guard sends
the row to review with the reason; it never silently "fixes" the text.

| Guard | Rule |
|---|---|
| Length | Non-decorative alt between about 5 and 150 characters (site may tighten); one sentence |
| Banned phrases | image of, picture of, photo of, graphic of; the site name alone; placeholder words (the rubric's A5 list); marketing adjectives the house style bans |
| Fact source | Every brand, model, number with unit, and product name in `alt` appears in `facts_used`, and each fact with source `catalogue` appears in the supplied `products` data; any token that looks like a model or spec (letters plus digits, numbers with units) and is not traceable fails. A fact with source `image` is a model claim, not evidence: it passes only if text recognition on the image or a catalogue match confirms it, otherwise the row goes to review. Source `image-legible` is large printed text in the photo that shoppers choose by (a style or model number on the product or a card): it is image-of-text information, so the alt may carry it (`..., case style 12`), and it passes when text recognition or the sampled review confirms the reading; a model number inferred from shape is never `image-legible` |
| Shared image | If `shared`, no product name or attribute from a single product's record appears; values in `constant_attributes` are allowed |
| Duplicates | No two attachments used on the same page get identical alt, unless the content hash says they are the same picture. Identical alt on a same-design pair (two photos of the same product design that show the same thing) is acceptable: flag it, and let review clear it |
| Not the file name | Alt does not reduce to the file name |
| Language | Alt language matches the page language |
| Repeat of adjacent text | Alt is not the same as the caption or link text |
| Decorative sanity | `decorative: true` is not allowed when the image is the only content of a link or button and the control has no other accessible name |

## Confidence and the review queue

| Route to review when | Why |
|---|---|
| Any guard failed | By definition |
| Random sample of passing drafts (start at 5%, and at least 20 per run) | Catches errors no guard or confidence score flags |
| Use count above a threshold (start at the top 5% of images by rendered occurrences, or any image on every page) | One error is heard everywhere |
| `shared` is true | Generic-but-true wording needs a human eye at first |
| `decorative: true` on a product or content image | Easy to get wrong in the expensive direction |
| `facts_used` holds a brand, model or number with source `image` and no confirmation | The model may have read or invented it |
| Judgement findings from the rubric (empty but informative, CSS-only information) | Mechanics cannot decide them |

The reviewer sees the image, the context block, the draft, the facts used and every page that uses it;
choices are accept, edit, mark decorative, or reject. An edit or an accept is recorded as human-approved.
Target a queue a person can clear: if more than about 20% of drafts go to review, fix the prompt or the
context before scaling up.

## Sampling and model choice

**Recommended default (2026-10-26): OpenAI `gpt-6-luna`**, with the linked-image instruction above (16/16
correct in the field test, about $0.20 per 1,000 images, about $0.10 on the Batch API). Named
alternatives: Claude Haiku 5.5 (also usable for a sample through a Claude subscription CLI) and Gemini
Flash-Lite on Vertex AI. A default is a starting point, not a result: **re-run the 50 to 100 image
sample whenever a model or a price changes**, and switch if another model wins it.

1. Draw 50 to 100 images stratified by role (main, gallery, inline, template, linked) and by category.
2. Draft with two or three candidate models (a small and a mid model per vendor).
3. Score each draft against the `image-alt-text` rubric and the fact guard; count hallucinated facts
   separately, since one invented spec outweighs many good drafts.
4. Choose the cheapest model with zero invented facts on the sample and an acceptance rate the owner
   accepts. Record the sample, scores and choice in the plan.

## Cost model per 1,000 images (dated)

Assumptions: one product photo resized to 1,024 x 1,024 px, about 300 tokens of instructions and context
text, about 60 output tokens (one alt plus small JSON). Prices are list prices per million tokens read
on 2026-10-25; check the source pages before quoting a budget.

Image tokens:

- **Claude:** 28 x 28 px patches, `ceil(w/28) x ceil(h/28)` tokens; 1,024 x 1,024 = 1,369 tokens.
  Larger images are downscaled (long edge 1,568 px on the standard tier, 2,576 px on Claude 4.7 and
  later). This replaced the older `w x h / 750` formula. Source:
  https://platform.claude.com/docs/en/build-with-claude/vision (read 2026-10-25).
- **OpenAI (patch models, GPT-5.x):** `ceil(w/32) x ceil(h/32)` patches x a model multiplier (1.2 for
  the GPT-5.4 and 5.6 families). `low` detail on GPT-5.6 fits the image within 512 x 512 (308 tokens
  here); on the GPT-5.4 family `low` does not shrink a 1,024 px image (1,229 tokens either way). Tile
  models (GPT-4o family) use a different scheme. Source:
  https://developers.openai.com/api/docs/guides/images-vision (read 2026-10-25).
- **Gemini 3 on Vertex AI:** a fixed count per image set by `media_resolution`: 1,120 tokens when unset
  (and at `HIGH`), 560 at `MEDIUM`, 280 at `LOW`; models before Gemini 3 charge 258 per image. Source:
  https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/image-understanding (updated
  2026-10-22, read 2026-10-25).

| Model | Detail | Input tokens | $ / 1M in / out | $ per 1,000 images | Batch (50% off) |
|---|---|---|---|---|---|
| Claude Haiku 5.5 (`claude-haiku-5-5`) | full | 1,669 | 0.10 / 0.50 | 0.20 | 0.10 |
| Claude Sonnet 5.5 (`claude-sonnet-5-5`) | full | 1,669 | 2.00 / 10.00 | 3.94 | 1.97 |
| Claude Opus 5.5 (`claude-opus-5-5`) | full | 1,669 | 4.00 / 20.00 | 7.88 | 3.94 |
| OpenAI gpt-6-luna (recommended default, 2026-10-26) | measured | not documented | 0.10 / 0.50 | about 0.20 (field measure) | about 0.10 |
| OpenAI gpt-5.6-luna | low | 608 | 0.20 / 1.20 | 0.19 | 0.10 |
| OpenAI gpt-5.6-luna | high | 1,529 | 0.20 / 1.20 | 0.38 | 0.19 |
| OpenAI gpt-5.4-mini | low or high | 1,529 | 0.75 / 4.50 | 1.42 | 0.71 |
| OpenAI gpt-5.6-terra | low | 608 | 2.00 / 12.00 | 1.94 | 0.97 |
| OpenAI gpt-5.6-terra | high | 1,529 | 2.00 / 12.00 | 3.78 | 1.89 |
| Gemini 3.1 Flash-Lite (`gemini-3.1-flash-lite`) | low | 580 | 0.25 / 1.50 | 0.24 | 0.12 |
| Gemini 3.1 Flash-Lite (`gemini-3.1-flash-lite`) | default | 1,420 | 0.25 / 1.50 | 0.45 | 0.22 |
| Gemini 3.5 Flash-Lite (`gemini-3.5-flash-lite`) | low | 580 | 0.30 / 2.50 | 0.32 | 0.16 |
| Gemini 3.5 Flash-Lite (`gemini-3.5-flash-lite`) | default | 1,420 | 0.30 / 2.50 | 0.58 | 0.29 |
| Gemini 3.8 Flash, introductory price to 2026-12-31 | default | 1,420 | 0.75 / 3.75 | 1.29 | 0.65 |
| Gemini 3.8 Flash, from 2027-01-01 | default | 1,420 | 1.50 / 7.50 | 2.58 | 1.29 |

Arithmetic, per image: `input_tokens x in_price / 1e6 + 60 x out_price / 1e6`, times 1,000. Example,
Haiku 5.5: `1,669 x 0.10 / 1e6 + 60 x 0.50 / 1e6 = $0.000197`, so $0.20 per 1,000.

Sources and caveats:

- Claude prices: Anthropic list prices (Haiku 5.5 rate applies to prompts up to 100K tokens), from the
  `claude-api` skill's model table cached 2026-10-06; confirm at
  https://platform.claude.com/docs/en/about-claude/pricing. Message Batches: 50% off, most batches
  finish within an hour
  (https://platform.claude.com/docs/en/build-with-claude/batch-processing, read 2026-10-25). Unfinished
  requests expire after 24 hours; results stay available for 29 days from batch creation.
- OpenAI prices: https://developers.openai.com/api/docs/pricing (read 2026-10-25). Batch: 50% off, 24-hour
  completion window (https://developers.openai.com/api/docs/guides/batch).
- Gemini prices: Vertex AI pricing, Global endpoint, prompts up to 200K tokens; the batch column is the
  page's Flex/Batch table, half the standard rate; non-global endpoints cost about 10% more
  (https://cloud.google.com/vertex-ai/generative-ai/pricing, read 2026-10-25). Model IDs from the Vertex
  model pages; confirm the 3.8 Flash ID in the model list before use.
- gpt-6-luna's image token rule is not documented (UNCERTAIN); its row is the field measure at batches
  of 4 (about 8 to 13 s per request). Per token it is half the price of gpt-5.6-luna in and under half
  out, so it should match or beat that row; confirm on your sample.
- Choose between the three vendors by the labelled sample, not by this table.
- **An AI CLI on a subscription is not a bulk route.** A delegate CLI such as agy runs on a subscription
  quota, takes tens of seconds per call, has no measured way to read an image file in an advisory
  call (not tested), and the harness limits it to one model family. Bulk drafting goes through a vendor API with batch.
- **Reasoning tokens are excluded** and are billed as output. Current Claude models think adaptively
  and some cannot turn thinking off; run alt drafting at the lowest effort setting and measure real
  output tokens on the sample before quoting a budget. The same applies to OpenAI reasoning models.
- Resizing to a 768 px long edge cuts Claude image tokens to 784 (28 x 28 patches); test on the sample
  that quality holds.
- Low detail is only cheaper on models where it actually shrinks the image; check the model's own row.

Reading the table:

- The image dominates input cost. Halving the long edge roughly quarters image tokens on Claude
  (tokens scale with pixel area). Do not send originals.
- Batch processing halves the price on both vendors, completing within 24 hours; an alt backlog can
  almost always wait.
- Prompt caching of the fixed instruction block helps only when it is long; with about 300 text tokens
  the image dominates and caching saves little.
- Model spend is rarely the real cost at this scale: human review time is. Spend on a better model if it
  cuts the review queue.

## Field-test traits (measured, 2026-10-25)

A small field test (16 product photos and linked tiles through a small Claude model) showed:

- **Batch size changes accuracy.** With 16 images in one request, one photo got another photo's
  description, at confidence 0.8; alone, it came out right twice. Send about 1 to 5 images per request,
  give each a stable id, require the id back in the response, and check the file-to-alt pairing.
- **Self-reported confidence missed the error.** Keep the sampled human review; do not rely on the
  model's confidence alone.
- **Real cost ran about three times the table.** Thinking tokens were most of the output, and a CLI
  route adds a large fixed setup context per call. Measure tokens on the sample before quoting a budget.
- **A headless CLI on a subscription plan works for a sample**, with tools limited to file reading,
  no MCP servers, no saved session and JSON output. It draws plan quota, not money: measure quota use
  on the sample and run off-peak in small chunks. For the full backlog, use an API with batch.
- Linked tiles got destination wording, and no invented specs appeared once catalogue facts were given.
- A follow-up on the same 16 images at 4 per request: the mix-up seen at 16 per request did not recur.
  Maximum effort cost about six times the default (thinking was almost all of the output) and gained
  nothing. The larger model cost about 18 times more, swapped one detail, padded linked-image alt with
  scene description and stated a catalogue series name as the model. Default effort is enough, and a
  bigger model is not automatically better: choose by the sample.
- Field measure, 2026-10-26, a small model through a coding CLI on a consumer subscription plan (4
  images per call, low reasoning effort): 16/16 correct with the link-only rule, about 5 to 6 s per
  call, about 7k to 14.5k tokens per call (roughly double the direct API, because the CLI adds its own
  instructions to every call), and under 1% of the 5-hour and weekly quota for all four calls (the CLI
  shows whole percentages only).

**Subscription CLIs.** A CLI on a subscription plan can serve a pilot or a small batch with no bill.
Its quota is shared with every other use of the plan, so measure quota use on a 100-image chunk before
any larger run. For a full catalogue, prefer the vendor's Batch API, which carries no quota risk.

## Field measure: a real run (2026-10-26)

One catalogue, OpenAI `gpt-6-luna`, 299 distinct pictures, 4 per request, JSON output with a stable id
echoed back: about 347k input and 43k output tokens, about $0.06 for the whole run at standard (not
batch) prices. The guards flagged 2.3% (the site icon and the placeholder as decorative, which the skip
rule now excludes; one draft over length; identical alt on same-design pairs). Spot checks found no
invented brands or specs. The review queue was dominated by shared images (every product picture in that
catalogue was shared), plus a 10% sample of theme pictures. A **contact-sheet review page** (image,
draft, context and accept/edit control on one screen, many rows per page) made that queue practical.
A prompt line that paid off: when the photo shows a large printed style number customers pick by, end
the alt with it; the fact guard allows it as `image-legible`.

## Prompt injection and data handling

- Text inside images (a photo of a sign saying "ignore previous instructions") and catalogue text are
  data. The instructions say so, and the output is constrained to the schema; a draft that contains
  instructions, URLs or code fails the guards.
- Send only the image and the fields above. No credentials, customer data or order data in requests.
- Keep the request and response log for the run; it is the evidence for every written alt.
