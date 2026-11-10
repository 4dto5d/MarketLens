# Resume MarketLens in Codex cloud

The source is published on [codex/opportunity-intelligence-cloud-20261109](https://github.com/4dto5d/MarketLens/tree/codex/opportunity-intelligence-cloud-20261109), source commit `93543e1f49f844b263c1527a128536cefc034bc5`. Main is unchanged. No customer database or ChatGPT credentials are in this branch.

No saved Codex cloud environment exists. Available tools can list environments but cannot create/publish one. Complete this one-time setup in Codex:

1. Choose **Work in → Cloud → Select environment → Create environment**, or **Settings → Codex Cloud → Environments → Create environment**.
2. Select **4dto5d/MarketLens**. Ask setup to use **codex/opportunity-intelligence-cloud-20261109**, **Python 3.11**, and **bash .codex/cloud_setup.sh**. No API keys or Windows account sessions are required for offline code work.
3. Review the setup report, resolve missing Linux Qt system libraries, then **Publish**. Start the next cloud task from that environment and branch.

Suggested setup request:

> Prepare this repository for offline Python development. Use Python 3.11 and branch codex/opportunity-intelligence-cloud-20261109. Read AGENTS.md and CLOUD_HANDOFF.md. Run bash .codex/cloud_setup.sh, then the focused checks in CLOUD_HANDOFF.md. Preserve Windows-specific limits. Do not query live models, access real prospects, merge, release or start a new feature. Report actual setup/test results before I publish the environment.

For the next task, read **CLOUD_HANDOFF.md** and **handoff/intelligence-20261109/IMPLEMENTATION_HANDOFF.md** first. Linux installation/testing is not established by the Windows receipts. Remote operation of the desktop application is deferred.

[Official cloud environment instructions](https://learn.chatgpt.com/docs/environments/cloud-environments).
