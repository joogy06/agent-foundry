# Format: an article

The format of a long-form piece for a website: a technical article, a guide, the body text of a product or
category page. It says where things go. It says nothing about how the piece sounds: that is the school's.
Both schools of a studio run read this same file.

## The file

One Markdown file, `article.md`, in this order.

1. **The front block**: three lines between a pair of `---` lines.

   ```
   ---
   title: the page title
   description: the meta description
   structured-data: the schema.org type suggested for the page
   ---
   ```

   - `title` and `description` keep to the lengths `constraints.md` gives.
   - `structured-data` is one schema.org type name, for example `TechArticle`, `Article`, `HowTo` or
     `FAQPage`. Name the type only; the markup is written by whoever publishes the page.
2. **One `#` heading**: the headline of the piece.
3. **The first screen**: the text before the first `##` heading. It answers the search question
   `constraints.md` names, whatever else it does.
4. **The sections**: one `##` heading per entry of the heading outline in `constraints.md`, in the outline's
   order and in its exact words. Add `###` headings under them where a section needs them. Do not add, drop,
   reorder or reword a `##` heading: the outline is checked by the runner.

## Length

The body (everything after the front block) falls inside the length band of the brief, counted in words.

## Facts

- State a fact only when the truth pack of the brief holds it. Write a figure the way the pack writes it: the
  same number, the same unit.
- A fact you need and the pack lacks is a labelled placeholder: `[FACT NEEDED: what is missing]`. The words
  after the colon say what to look up. A placeholder is not a failure; an invented fact is.
- Square brackets are kept for placeholders and link slots. Anything else in square brackets is read as an
  unfinished gap and fails the piece.
- Every sentence with a number, a unit, a model name, a comparison or a date is listed by the runner and
  matched to the truth pack. A sentence it cannot match makes the draft ineligible until the sentence is
  removed, corrected or turned into a placeholder.
- State each figure once in full, where the reader first needs it: the product by a name the truth pack uses,
  the number and the unit. A table row may hold the figure as well. Every later mention refers back to it and
  does not write the number again. After `The Example Lamp 200 draws 9 W`, a later sentence reads `That draw is
  why the lamp can stay on all evening` or `On power the Example Lamp 200 is still the one to pick`.
- A back-reference costs nothing at the check. A sentence with no number, unit, model name, comparison or date
  in it is not listed, and neither is one that only names a product by a name the truth pack uses. Refer to the
  product by such a name or by an ordinary noun (`the lamp`): a shortened model name the pack does not list is
  read as an unknown model and listed. Keep comparison words out of it (`cheaper than`, `the cheapest`): they
  are listed and wait for a ruling.
- The same figure for the same product, stated in three or more sentences of the body, is reported as repetition
  and counts against the draft when it is judged. Table rows and headings are not counted.

## Internal links

`constraints.md` lists the internal-link slots. Place each one where it helps the reader, written
`[LINK: anchor text -> slot name]`. Do not write a URL.

## Tables, lists, code

- A table for anything compared on more than two points; every figure in it follows the rule under Facts.
- A numbered list only for steps done in order.
- Code and commands in fenced blocks.

## What is handed over

The hand-over lists the article, its title and description, the structured-data type, the link slots, the
placeholders, and every listed sentence with the truth-pack entry and source it rests on.
