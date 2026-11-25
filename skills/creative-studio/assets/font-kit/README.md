# Font kit

A variant page is captured offline. It can use the fonts the host already has, and font files its maker
placed inside the variant directory. Nothing else: a page that asks for a font at any address outside its own
directory fails the capture, and the address is listed.

This kit holds no font files. It is a set of stacks and the rule for using them.

## The rule for makers

| Allowed | Not allowed |
|---|---|
| A stack of local family names, ending in a generic family | A stylesheet or font file at an `http:` or `https:` address |
| `@font-face` with `src: url(...)` pointing at a file inside the variant directory | A path that leaves the directory through `..`, an absolute path or a symlink |
| `@font-face` with `src: local("Family Name")` | A font loaded by script from anywhere else |

A font file a maker adds must be one they may redistribute; its licence file goes beside it in the variant
directory. The file counts toward the `page-weight` floor row.

## Which families a host has

Where fontconfig is present, the host lists them:

```bash
fc-list : family | sort -u          # every installed family
fc-match "Georgia"                  # what a name actually resolves to here
fc-match -s serif | head -5         # the order the generic serif falls back through
```

A name the host does not have is not an error: the browser moves down the stack. That is why the first name of
a stack is a wish and the last one is a guarantee. Check with `fc-match` before leaning on a face for the
character of a page.

On a host without fontconfig, write the stack anyway and read what the capture reports.

## Stacks

Each stack names faces common to the three desktop systems and ends in a generic family. Pick by role, then
check what rendered.

| Role | Stack |
|---|---|
| Interface sans | `system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", "Liberation Sans", Arial, sans-serif` |
| Humanist sans | `"Gill Sans", "Gill Sans MT", Calibri, "Trebuchet MS", "DejaVu Sans", "Noto Sans", sans-serif` |
| Geometric sans | `Futura, "Century Gothic", "URW Gothic", "Avenir Next", "Noto Sans", sans-serif` |
| Book serif | `"Iowan Old Style", "Palatino Linotype", Palatino, "URW Palladio L", "Book Antiqua", Georgia, serif` |
| Transitional serif | `Charter, "Bitstream Charter", "Sitka Text", Cambria, "Liberation Serif", "DejaVu Serif", serif` |
| Display serif | `Didot, "Bodoni MT", "Playfair Display", "Noto Serif Display", "DejaVu Serif", serif` |
| Slab | `Rockwell, "Rockwell Nova", "Roboto Slab", "DejaVu Serif", serif` |
| Monospace | `ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", "DejaVu Sans Mono", monospace` |

The same stack renders as different faces on different hosts. A direction that depends on one exact face
carries that face as a file inside the variant directory.

## What the capture records

| Field of the evidence set | Holds |
|---|---|
| `fonts_rendered` | The host families that actually drew text on the page, with glyph counts, most used first |
| `variant_fonts` | How many families came from files inside the variant directory, and their glyph count |
| `requests.inside` | The files the page loaded from its own directory, font files included |
| `requests.outside` | Every address the page asked for outside its directory. Any entry here fails the capture |

A family that came from a file in the variant directory is counted and not named: the name inside a font file
is chosen by whoever made the file, and the evidence set carries no text a page supplied.

If `fonts_rendered` shows the last, generic entry of a stack where a named face was expected, the host does not
have that face. Choose another stack, or bring the face as a file.

## Limits of a page opened from a file

The capture opens `index.html` from disk, not from a server. Styles, images, classic scripts and font files
load from the variant directory by relative path. `fetch()` of a local file and `<script type="module">` with
an import do not work from a file address in Chrome; keep scripts classic and data inline.
