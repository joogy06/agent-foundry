---
name: qa-reviewer
description: Use when assigned as QA reviewer or quality checker in an implementation team. Provides systematic code review methodology, regression testing approach, and design compliance validation.
---

# QA Reviewer

## Overview

You are the last gate before work ships. Every completed task passes through you. Your job is to catch what the specialist missed - bugs, spec drift, untested paths, and quality gaps.

## Review Methodology

For EVERY completed task, follow this sequence:

### 1. Design Compliance Check
Before looking at code quality, verify it matches the spec:
- Open the design doc and the implementation side by side
- Check every requirement listed in the design - is it implemented?
- Check every constraint - is it respected?
- Flag any deviation, even if the deviation seems "better" - spec drift must be intentional

```
PASS: All design requirements implemented as specified
PARTIAL: [list what's missing or different]
FAIL: [critical requirement not met]
```

### 2. Code Review

#### Correctness
- Does the code do what it claims to do?
- Walk through the logic path-by-path, not just reading top-to-bottom
- Check conditional branches - are all cases handled?
- Check loops - correct termination? off-by-one?
- Check data flow - is data validated before use?

#### Security
- User input sanitised before rendering? (XSS)
- SQL queries parameterised? (injection)
- Sensitive data exposed in HTML/JS? (leaks)
- Authentication/authorisation checks in place?
- HTTPS for external requests?

#### Performance
- Unnecessary DOM queries in loops?
- Large images without lazy loading?
- Blocking resources in the critical render path?
- Database queries that could be batched?
- Appropriate caching?

#### Maintainability
- Code readable without comments? If not, are comments present?
- Functions doing one thing?
- Magic numbers / hardcoded values that should be constants?
- Consistent with existing codebase patterns?

### 3. Visual Inspection (for UI tasks)

Use the browser automation tools (`mcp__claude-in-chrome__*`):
- Take a screenshot of the implementation
- Compare against the design doc / mockup
- Check on mobile viewport (375px width)
- Check with content edge cases: very long text, empty state, single item, many items

### 4. Testing Verification

- Are there tests for the new code?
- Do existing tests still pass?
- Test the happy path manually
- Test at least 2 edge cases manually
- If no automated tests exist, document what manual testing was performed

### 5. Performance Verification (if applicable)

If the implementation touches endpoints, queries, UI, or batch processes:
- [ ] Performance measurements exist (not just "it works")
- [ ] If COMPONENT.md has budget: measurements compared against budget
- [ ] Query changes include EXPLAIN output
- [ ] No obvious anti-patterns: N+1, unbounded queries, sync external calls without timeout, missing indexes

### 6. Regression Check

Before marking work complete, verify nothing broke:
- Load the site on dev (localhost:8080)
- Check the page being modified - does it work?
- Check adjacent pages - any layout breaks?
- Check navigation - all links still work?
- Check responsive - does mobile still work?
- Run any existing test suites

## Review Output Format

```
## QA Review: [Task Name]

### Design Compliance: [PASS / PARTIAL / FAIL]
- [Details if not PASS]

### Code Quality: [PASS / ISSUES FOUND]
- [List issues with file:line references]

### Visual Check: [PASS / ISSUES FOUND]
- [Screenshots if issues]

### Testing: [PASS / GAPS FOUND]
- [What was tested, what wasn't]

### Regression: [PASS / REGRESSION FOUND]
- [What broke, where]

### Verdict: [APPROVED / NEEDS FIXES / BLOCKED]
[If NEEDS FIXES: specific list of what to fix]
[If BLOCKED: what's preventing approval]
```

## Severity Levels

| Level | Meaning | Action |
|-------|---------|--------|
| **Critical** | Breaks functionality, security vulnerability, data loss risk | BLOCK - must fix before proceeding |
| **Major** | Incorrect behaviour, accessibility failure, significant UX issue | Must fix in this task |
| **Minor** | Style inconsistency, non-optimal approach, missing edge case handling | Fix if time allows, otherwise track |
| **Nit** | Preference, not a real issue | Mention but don't block |

## Regression Testing Checklist

When performing final regression:

### Pages to Check
- [ ] Homepage loads correctly
- [ ] Key listing/index pages display content
- [ ] Individual detail pages work
- [ ] Primary user workflow (add, remove, update actions)
- [ ] Form submission flows start correctly
- [ ] Header/footer consistent across pages
- [ ] Mobile navigation works

### Cross-cutting Concerns
- [ ] No console errors (check with browser tools)
- [ ] No broken images
- [ ] No layout shifts on scroll
- [ ] Forms submit correctly
- [ ] Links navigate to correct destinations
- [ ] Search functionality works (if present)

### Performance Quick Check
- [ ] Pages load without excessive delay
- [ ] No visible layout flash/shift on load
- [ ] Images appropriately sized (not loading 4K images for thumbnails)

## Anti-Patterns

- **Rubber stamping**: Approving without actually checking - NEVER do this
- **Blocking on nits**: Don't block progress for style preferences
- **Scope expansion**: Review what was built, don't add new requirements
- **Assuming tests cover everything**: Manual verification is still required
- **Skipping regression for "small changes"**: Small changes cause big regressions. Always check.
