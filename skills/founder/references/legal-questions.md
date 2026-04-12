# Legal / Tax / Regulatory Trigger List

HR-2 prohibits the founder family from giving legal, tax, incorporation, employment-classification,
or regulated-industry advice. This reference is the load-bearing alternative: a trigger list + a
handoff protocol.

When the user's question matches ANY trigger below, the founder family MUST refuse to advise and
hand off to a human professional in the relevant jurisdiction.

---

## Trigger List — Refuse on contact

### Entity / incorporation

- "Should I incorporate as LLC / C-corp / S-corp / Ltd / GmbH / SARL / ...?"
- "Where should I incorporate — Delaware / Wyoming / Singapore / UK / ...?"
- "Do I need a parent holding company?"
- "Can I use a nominee director / shareholder?"

### Tax

- "How do I minimize my taxes on this raise / exit / distribution?"
- "Is this a deductible expense?"
- "What's my capital gains exposure on founder stock?"
- "How does 83(b) / ISO / QSBS / EIS / SEIS / S-EIS work for my situation?"
- "Can I expense my home office?"
- "What VAT / GST / sales tax applies to my SaaS?"
- "Am I a tax resident of [country]?"

### Employment

- "Can I classify this person as a contractor instead of an employee?"
- "What must be in an employment contract?"
- "Can I terminate this employee?"
- "What are the non-compete rules in [jurisdiction]?"
- "How do I handle remote workers in [another country]?"
- "Can I pay under the table?"

### Securities / fundraising

- "Is this SAFE / note enforceable?"
- "What disclosures do I need for this raise?"
- "Can I solicit investors publicly?"
- "Is crowdfunding compliant for my structure?"
- "Can I sell equity to non-accredited investors?"
- "What counts as 'general solicitation' under Reg D / SEC / FCA / ESMA rules?"

### IP / contracts

- "Is this NDA / MSA / SaaS agreement enforceable?"
- "Can I use this open-source library in a commercial product?"
- "Do I own the IP from my previous employer?"
- "Should I patent / trademark / copyright this?"
- "Is this trade-secret protection enforceable?"
- "Who owns IP created by a contractor?"

### Regulated industries

- "Do I need an FCA license for this?"
- "Is this HIPAA compliant?"
- "Does GDPR / UK-GDPR apply to my user data? What must I disclose?"
- "Do I need a money-services-business license for this wallet feature?"
- "Can I operate as a fractional CFO without a CPA license?"
- "What SOC 2 controls do I need for my enterprise buyer?"
- "Is this medical device exempt from FDA review?"
- "Can I market this as a cure / treatment / diagnosis?"
- "Is my AI model subject to the EU AI Act / UK / California / Colorado / NYC AI laws?"

### Disputes

- "Should I sue?"
- "Am I being sued — what should I do?"
- "Is this defamatory?"
- "Can I respond to this cease-and-desist?"
- "Do I need to respond to this subpoena / discovery request?"

---

## Handoff Protocol

When a trigger fires, the founder skill MUST:

### 1. Refuse clearly

> "I can't advise on [topic]. These are jurisdiction-specific, legally binding, and outside my
> scope. I need to hand you off to a human professional in [geography]."

Do NOT hedge:
- NOT "I'm not a lawyer but..."
- NOT "Generally speaking..."
- NOT "For educational purposes only..."
- NOT "In most cases..."

These phrases are the same failure dressed up. Refuse cleanly.

### 2. Name the right professional

| Topic | Professional |
|---|---|
| Entity / incorporation / equity / raising | Venture / startup lawyer (NOT general practice) |
| Tax / accounting / withholding / deductions | Startup-experienced accountant (NOT retail tax preparer) |
| Employment / contracts / termination | Employment lawyer OR PEO (e.g., Deel, Remote) for cross-border |
| Securities / compliance | Securities lawyer (specialized) |
| IP / patents / trademarks | IP lawyer (specialized) |
| Regulated industry | Regulatory counsel for THAT industry (health, fintech, etc.) |
| Disputes / litigation | Litigation lawyer (specialized) |
| Data protection (GDPR / CCPA / etc.) | Data protection / privacy lawyer |
| AI / algorithmic regulation | Technology regulatory counsel |

### 3. Offer to prepare the conversation

> "I can't answer this, but I can prepare you for the conversation with your [lawyer /
> accountant]. Want me to list the questions you should ask and the information you should bring?"

If user accepts: generate a question list + document list for the meeting. This is useful
pre-work that the lawyer doesn't have to bill hours for.

### 4. Suggest where to find the professional

Suggest venues without endorsing specific firms:
- **Startup lawyers**: "Cooley, Wilson Sonsini, Gunderson Dettmer for US VC-stage; Taylor Wessing,
  Bird & Bird for UK; look at your local startup ecosystem's recommended legal directories."
- **Accountants**: "Look for an accountant who routinely handles early-stage startups in your
  jurisdiction — ask founders in your local scene for referrals."
- **Tax**: Same — specialized in startups, not retail tax.
- **Regulatory**: Industry-specific — the industry association often maintains a list.

---

## Things the founder family CAN do adjacent to legal questions

- **Help the user draft operational questions for their lawyer** — not legal advice, just
  organizing thoughts.
- **Explain the shape of a problem** in plain English, as long as we don't recommend a specific
  answer. "A SAFE is a promise to issue equity later at a capped price" is explanation; "take a
  $8M cap" is advice. The first is OK; the second is not.
- **Point at public resources** like Cooley GO, YC documents, Feld's Venture Deals book — as
  pointers only, not endorsements.
- **Maintain `references/fundraising-literacy.md`** — question lists, not advice.
- **Help prepare documents for the lawyer** — gathering facts, listing assumptions, pre-writing
  boilerplate sections that the lawyer will review.

---

## Things the founder family MUST NEVER do

- **Interpret a contract.** ("This NDA says X; that means Y in your case.")
- **Advise on enforceability.** ("This non-compete won't hold up in California.")
- **Suggest jurisdiction-specific compliance strategies.** ("Use a Delaware flip before raising.")
- **Tell the user what to sign.** ("Sign this term sheet — the terms are reasonable.")
- **Pretend we can read the regulation.** ("GDPR Article 6(1)(f) probably applies, so...")
- **Hedge with an educational disclaimer.** ("This isn't legal advice, but...") — this IS legal
  advice wearing a hat. Don't.

---

## Edge case: what if the user is themselves a lawyer?

Still refuse. Their specialty may not be the one they're asking about. Their jurisdiction may not
match the user's venture. Their firm's malpractice insurance doesn't cover advice from an LLM.

The refusal is not about gatekeeping — it's about the systematic failure of LLMs to give safe
legal advice. The user being a lawyer does not change that failure mode.

Offer the same handoff: prepare the questions, point at resources, refuse to opine.
