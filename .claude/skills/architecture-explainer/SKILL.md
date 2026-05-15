---
name: architecture-explainer
description: Keep the system explainable. Use when answering "how does X work", designing new features, onboarding to the codebase, or before any significant change. Forces clear mental models and prevents cargo-cult architecture.
---

# Architecture Explainer

Forces the system to remain explainable. Every module, layer, and dependency must have a clear WHY that can be stated in one sentence.

## When to Apply

Activate this explainer when:

- Someone asks "how does X work?" or "why is Y structured this way?"
- Designing a new feature that touches multiple modules
- Reviewing a PR that changes architectural boundaries
- Adding a new layer, adapter, or abstraction
- Onboarding — explaining the codebase to someone new
- Before deleting or significantly changing a module

## Mental Model First

Before explaining code, state the mental model:

1. **One-sentence purpose**: What problem does this solve?
2. **Data flow**: What goes in, what comes out, which path does it take?
3. **Layer placement**: Where does this sit in the stack, and why?
4. **Dependencies**: What does it depend on, and what depends on it?
5. **Non-obvious constraints**: What would break if someone changed this naively?

## Architecture Decision Records

When a significant architectural choice is made, document:

- **Context**: What was the situation? (constraints, deadlines, unknowns)
- **Decision**: What did we choose?
- **Alternatives**: What else was considered and why rejected?
- **Consequences**: What's easier now? What's harder? What must future changes respect?

Keep ADRs in `docs/adr/` or inline near the affected code as a short comment block.

## Explanation Rules

1. **Start with a diagram** (ASCII art) showing data flow between components
2. **Layer from the outside in** — network entry → routing → business logic → storage
3. **Name the format boundaries** — where does data change shape? (JSON → dict → dataclass → DB row)
4. **State the invariant** — what must always be true for this to work?
5. **Explicitly list what this does NOT do** — scope is as important as function

## Anti-Patterns to Call Out

- "Utility" or "helper" modules — these hide poor cohesion
- Circular dependencies via interfaces or events
- Layers that exist "in case we need them later"
- Config that changes behavior without changing the code path visibly
- Modules named after technologies rather than responsibilities

## Delivery

- Short answer first, then expand
- Use concrete file paths and line numbers
- Relate to things the listener already understands
- If something cannot be explained in 3 sentences, it might be too complex
