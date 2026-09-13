# Security Model

Lunar GIS runs inside a GIS application with access to local project data and external services. Security is therefore part of the architecture.

## Rules

- API keys are never hard-coded.
- Secrets are never written to logs.
- Remote downloads go through registered providers.
- Downloaded archives are treated as untrusted input.
- No downloaded binary is executed.
- Tool requests are schema validated.
- Destructive operations require explicit confirmation.
- Arbitrary AI-generated Python is disabled by default.
- Local datasets are not automatically uploaded to remote AI services.
- AI context should contain summarized metadata unless the user explicitly authorizes transmission of content.

## Future threat-model areas

- malicious GIS archives
- path traversal
- prompt injection via layer metadata
- prompt injection via downloaded text metadata
- malicious URLs
- oversized datasets
- denial-of-service through processing
- API key leakage
- unintended file overwrite
