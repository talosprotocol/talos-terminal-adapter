# Agent workspace: services/terminal-adapter
> **Project**: services/terminal-adapter

This folder contains agent-facing context, tasks, workflows, and planning artifacts for this submodule.

## Current State
Terminal adapter exposes controlled terminal execution and streaming session behavior to the wider Talos stack. Session isolation, bounded execution, and auditability are key concerns.

## Expected State
Least-privilege terminal mediation with strong session controls, resource limits, and deterministic audit trails for every action.

## Behavior
Bridges terminal-oriented workflows into Talos-compatible tool or service interfaces while managing session lifecycle and streamed output.

## How to work here
- Run/tests:
- Local dev:
- CI notes:

## Interfaces and dependencies
- Owned APIs/contracts:
- Depends on:
- Data stores/events (if any):

## Global context
See `.agent/context.md` for monorepo-wide invariants and architecture.
