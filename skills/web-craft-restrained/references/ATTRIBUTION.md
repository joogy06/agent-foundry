# Attribution: where the restrained house comes from

`web-craft-restrained` is ADAPTED guidance. The ideas listed below were taken from one open-source project and
written again in this library's own words. No file, passage, markup, style or program of that project is in
this library, and nothing of it is installed or run.

**Contents:** The source · Intake verdict · What was adapted, and how it was changed · Primary sources for facts · Licence of the source (full text)

<!-- FRESHNESS:v1
anchors:
  - kind: date_review
    subject: adapted-source-commit-and-primary-source-addresses
    review_by: "2027-04-12"
-->

## The source

| | |
|---|---|
| Project | Impeccable |
| Repository | <https://github.com/pbakaus/impeccable> |
| Commit read | `c63b8dd7dd5a5f3c32eaabe1af76d0694f863ed2` (committed 2026-10-11) |
| Licence | Apache License, Version 2.0 (full text below) |
| Copyright notice of the source | Copyright 2025 Paul Bakaus |
| Read on | 2026-10-12 |

## Intake verdict

| | |
|---|---|
| Scanner | `skills/intake-scan` (`intake.py scan <clone> --kind repo --offline`) |
| Intake verdict id | `q20261012T121219Z-66b4947d` |
| Verdict | **block** |
| Scanned on | 2026-10-12 |

Why it was not installed: the scan returned the verdict block with 59 block-rule hits and no exception. The
block rules that fired were: harness configuration shipped inside the repository (settings, hooks and harness
dot-directories), a shell block that runs when a skill file is loaded, opaque binary files, hidden or
zero-width characters in text files, and lines too long to be pattern-checked in executable and markdown
files. A unit with a block verdict is not adopted into this library. Its text was therefore read as data only
and the design guidance in it was re-expressed. Nothing was run from the clone.

An earlier scan of the same commit, made when the design was written, also returned block; the id above is
the scan made when this skill was written. In it one optional scanner did not finish inside its time limit;
that is a coverage gap of the scan and does not change the verdict, which rests on the block rules above.

## What was adapted, and how it was changed

All of it was changed. The table names each idea, where in the source it was read, and what this library did
with it.

| Idea | Read in the source at | What changed here |
|---|---|---|
| A list of visual habits that make a page look machine-assembled, to be refused unless the brief asks for them | `skill/reference/craft-floor.md` | Re-written as this house's refuse list in `doctrine.md`: our own wording, a reason and an alternative per row, rows added from our own observation (the default purple to blue backdrop, over-rounded corners), rows left out where they concern platforms or tools this library does not cover. Rows the source applies to every kind of work are here the taste of ONE house, with a rival house that refuses different things |
| Checks on a built page: spacing rhythm, heading spacing, type measure and scale, one elevation method | `skill/reference/craft-floor.md`, `skill/reference/typeset.md`, `skill/reference/layout.md` | Turned into a table of working numbers. The numbers are this house's own and mostly tighter (a smaller largest heading, fewer sizes, one radius); they are stated as choices of taste, not as rules for all work |
| Colour by role: neutrals, one accent kept rare, secondary text tinted from its surface, even lightness steps | `skill/reference/colorize.md`, `skill/reference/quieter.md` | Reduced to the `neutral-accent` and `tonal` values of the colour axis and three sentences of practice |
| Motion that explains a change of state, with short durations | `skill/reference/animate.md` | Kept only the feedback part as this house's `motion` value, with our own duration bands. The source's authored focal sequence was NOT taken into this house; an authored sequence is the rival house's value |
| Removing whatever does not earn its place; grouping by space before boxes | `skill/reference/distill.md`, `skill/reference/layout.md` | Became the "Subtract" step of the process and the `structural` ornament value |
| Deciding the direction before building | `skill/SKILL.src.md`, `skill/reference/shape.md` | Replaced by this library's direction contract: a maker fills the shared axis table before any markup. The source's commands, launcher, project files and review loop were not taken |

Not adapted at all: the source's commands and routing, its launcher and scripts, its agent definitions, its
hooks and detector, its live browser mode, its platform references for phones (which its own notice file says
are derived from a third project under the MIT licence), and its overall stance. The source asks for bold,
award-seeking work on every task; this house is deliberately the quiet one of two, and the bold position
belongs to `web-craft-expressive`, which is this library's own and takes nothing from the source.

The axis table, the axis vocabulary, the rivalry between two houses, the direction contract and the rule that
usability and accessibility are shared by both houses are this library's own design.

## Primary sources for facts

Where `doctrine.md` or the neutral floor states a fact, the fact rests on the primary source below and not on
the adapted project.

| Fact | Primary source |
|---|---|
| Text contrast of at least 4.5 to 1, and 3 to 1 for large text | WCAG 2.2, Success Criterion 1.4.3 Contrast (Minimum): <https://www.w3.org/TR/WCAG22/#contrast-minimum> |
| Contrast of at least 3 to 1 for interface components and graphics | WCAG 2.2, Success Criterion 1.4.11 Non-text Contrast: <https://www.w3.org/TR/WCAG22/#non-text-contrast> |
| A line width of no more than 80 characters as an enhanced-level requirement | WCAG 2.2, Success Criterion 1.4.8 Visual Presentation: <https://www.w3.org/TR/WCAG22/#visual-presentation> |
| The `ch` unit is the advance width of the "0" glyph of the font in use | CSS Values and Units Module Level 4: <https://www.w3.org/TR/css-values-4/#font-relative-lengths> |
| `oklch()` and why its lightness steps are even to the eye | CSS Color Module Level 4: <https://www.w3.org/TR/css-color-4/#ok-lab> |
| The reduced-motion preference a page can read | Media Queries Level 5: <https://www.w3.org/TR/mediaqueries-5/#prefers-reduced-motion> |
| 45 to 75 characters as a satisfactory line length for a single column of prose | Robert Bringhurst, *The Elements of Typographic Style*, section 2.1.2 |

**Freshness anchor.** Checked 2026-10-12: the source commit above, the intake verdict, and the WCAG 2.2
Recommendation of 12 December 2024. Re-check by 2027-04-12, or when the doctrine is revised: whether the
source has moved in a way that matters to the adapted ideas (a later commit is a new read and a new scan, never
a silent update), and whether the section numbers and addresses of the primary sources still resolve.

## Licence of the source

The adapted ideas come from a work under the Apache License, Version 2.0. The licence text is kept here in
full, as that licence asks. This file is the notice that the material was changed.

```text

                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright [yyyy] [name of copyright owner]

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```
