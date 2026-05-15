---
name: complexity-guard
description: Guard against unnecessary complexity and over-engineering. Use when writing or reviewing code, designing features, adding abstractions, or refactoring. This skill prevents scope creep, premature optimization, and gold-plating.
---

# Complexity Guard

Prevents infinite expansion. Every addition must justify its complexity budget.

## When to Apply

Activate this guard automatically when:

- Adding a new file, class, or abstraction
- Introducing a new dependency or pattern
- Writing a function with more than 3 parameters
- Creating a helper for a single call site
- Adding error handling for scenarios that cannot happen
- Designing for hypothetical future requirements
- Refactoring into smaller pieces (check if the pieces are truly independent)

## Complexity Budget

Every change has a complexity cost. Apply these rules:

1. **3-line rule**: If the same pattern appears 3 times, it MIGHT warrant extraction. Less than 3 — copy-paste is better than a wrong abstraction.
2. **Single-consumer rule**: A helper used by only one caller is dead weight. Delete it unless the caller is too long (>50 lines).
3. **Error handling**: Only validate at system boundaries (user input, external APIs). Trust internal code and framework guarantees.
4. **Future-proofing**: YAGNI. Don't add a parameter, config flag, or extension point until the second concrete use case exists.
5. **Dependencies**: A new import is a new liability. Prefer stdlib, then existing deps, then popular packages. Never pull a dep for a single function.
6. **Half-finished work**: A partial implementation is worse than none. If a feature isn't complete and tested, it doesn't exist.

## Questions to Ask Before Every Change

1. Can this be solved by deleting code instead of adding it?
2. Does this abstraction earn its keep (used by 2+ callers)?
3. Is there a simpler way that works now and doesn't preclude the obvious next step?
4. Am I solving the actual problem or a generalized version of it?
5. What happens if I just don't do this?

## Enforcement

When reviewing code or planning changes:

- Flag any new file with fewer than 30 lines of meaningful code (not imports/boilerplate)
- Flag any abstraction with only one caller
- Flag any error handling for errors that the framework/OS already handles
- Flag any configuration option without a concrete user story
- Flag any comment that explains WHAT the code does (naming should do that)
- Flag TODO comments without a linked issue number

## Tone

Direct and blunt. "This helper has one caller — inline it." Not "I wonder if maybe we could consider inlining this."
