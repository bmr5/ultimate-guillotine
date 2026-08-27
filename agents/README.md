# Agents

This directory is reserved for league automation agents, including weekly recaps, daily research, commissioner support, and message drafting.

Each agent should have its own directory and document:

- purpose and owner;
- allowed inputs, including whether private member data is required;
- generated outputs and their retention;
- external tools and permissions;
- schedule and failure behavior;
- dry-run and human-review procedure;
- runbook for the always-on Mac mini.

Content generation and message delivery must remain separate operations. A future agent may draft a recap automatically, but it must not send external messages until its delivery policy, recipients, retry behavior, and approval mode are explicit and tested.

Secrets belong in the local environment or a secrets manager, never in agent prompts or repository files.
