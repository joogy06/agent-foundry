# Format: the words of a website page

The format of the words a page maker sets: the hero, the section copy, the labels of the actions. It says
where things go. It says nothing about how the page sounds: that is the school's. Both schools of a studio
run read this same file.

## The file

One Markdown file, `copy.md`. A page maker of the same run builds the page around it and sets every part of
it, so write nothing that is not meant to appear on the page.

1. **The front block**: two lines between a pair of `---` lines.

   ```
   ---
   title: the page title
   description: the meta description
   ---
   ```

   Both keep to the lengths `constraints.md` gives.
2. **`# Hero`**: the headline (one line), the supporting line (one or two sentences) and the label of the
   primary action (two to four words, starting with a verb).
3. **One `##` section per heading** `constraints.md` asks the page to carry, in its order. Under each: the
   section heading as it will appear, then the body, then, where the section has one, the label of its action.
4. **`## States`**: one line per key state `constraints.md` names (empty, loading, error, success and so on):
   what the page says in that state.
5. **`## Small print`**: the labels of the navigation, the footer lines and any required notice.

## Length

- A headline fits on two lines at phone width: about eight words.
- A section body is at most three short paragraphs or one list. The page is scanned before it is read.
- An action label never wraps.

## Facts

- This format takes no truth pack. A fact you do not have (a price, a figure, a delivery time, a name) is a
  labelled placeholder: `[FACT NEEDED: what is missing]`. Never invent one.
- Square brackets are kept for placeholders. Do not use them for anything else.

## What you do not decide

Typeface, colour, layout, imagery and motion belong to the page maker. Do not describe how a section should
look; say what it has to tell the visitor.
