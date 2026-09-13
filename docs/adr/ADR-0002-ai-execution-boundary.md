# ADR-0002: AI Execution Boundary

- Status: Accepted
- Date: 2026-09-13

## Decision
AI-generated actions are represented as structured tool requests, validated against registered schemas, checked against permissions, and executed by deterministic plugin tools. Arbitrary code execution is not the default path.

## Consequences
- Tool schemas become stable public contracts inside the plugin.
- Destructive actions can require confirmation.
- GIS correctness remains testable without an LLM.
