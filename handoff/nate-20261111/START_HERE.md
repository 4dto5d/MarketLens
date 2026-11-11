# MarketLens complete application for Nate

This branch contains the full MarketLens Local Python/Windows application and the November 11 response-version correction. The 314 application-source files exactly match CANDIDATE_MANIFEST.json. This handoff folder contains additional setup and verification metadata.

## Run on your own Windows computer

Install Python 3.11 with the Windows Python launcher. Clone this branch:

    git clone --branch codex/marketlens-complete-nate-20261111 --single-branch https://github.com/4dto5d/MarketLens.git
    cd MarketLens
    powershell -ExecutionPolicy Bypass -File .\run_windows.ps1

The launcher creates a project virtual environment, installs the application dependencies, and launches app.py. Your Windows user profile gets its own local database under %LOCALAPPDATA%\LocalPresenceMiner. Credentials and databases are created on your computer.

For the optional model layer, open a prospect's Guided Opportunity workflow, enable the AI panel and choose Continue with ChatGPT. Complete sign-in using your own account. Model availability and usage follow the connected account. Review each request and choose Send once deliberately. If account access or quota is unavailable, the existing offline workflows remain available. Fresh discovery needs your own provider configuration; see .env.example. Demo/synthetic inputs can be used for initial evaluation.

## Code review or Codex Cloud

Use this exact branch. Read CLOUD_HANDOFF.md and the correction IMPLEMENTATION_HANDOFF.md in this folder. Linux/Cloud can execute portable tests; native Windows account storage and GUI require Windows.

To install development dependencies on Windows:

    .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    $env:QT_QPA_PLATFORM = "offscreen"
    .\.venv\Scripts\python.exe -m pytest -q tests/test_intelligence_response_versions.py

Ordinary pytest runs serially. The supplied 161-test receipt used pytest-xdist, an optional runner installed in the implementation environment.

## Checkpoint and review status

Source SHA-256 c4f92cb7f893cb764d07c22949de95f8bb48798bb57c67bf1fe25747d6dbd9a3. The canonical algorithm hashes UTF-8 sorted-key JSON, compact separators, of relative path to {bytes,sha256} entries.

The version correction has 161 affected tests passing, Ruff/compileall passing and 91 historical mypy diagnostics with zero additions. The six new tests reproduce the old response-version defect and validate failed raw receipt retention, cache rejection and historical compatibility. Full-suite 1,466-pass evidence belongs to the parent candidate. Independent acceptance and live-model intelligence quality remain open gates. This is a development review checkpoint.

The previous cloud branch and main contain older application snapshots. Select this branch explicitly.
