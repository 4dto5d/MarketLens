from __future__ import annotations

from verification.run_verification import manifest, manifest_digest


def test_b2_tested_tree_manifest_is_deterministic_and_excludes_generated_output(tmp_path) -> None:
    root = tmp_path / "tree"
    output = root / "verification-output"
    source = root / "local_presence_miner" / "source.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"VALUE = 1\n")
    (root / "mypy-v0115.log").write_text("generated log\n", encoding="utf-8")
    (root / "GITHUB_SOURCE_FILE_MANIFEST.json").write_text("{}\n", encoding="utf-8")
    output.mkdir()
    (output / "VERIFICATION_RESULTS.json").write_text("{}\n", encoding="utf-8")

    first = manifest(root, excluded_roots=(output,))
    first_digest = manifest_digest(first)

    assert list(first) == ["local_presence_miner/source.py"]
    assert set(first["local_presence_miner/source.py"]) == {"bytes", "sha256"}
    assert first["local_presence_miner/source.py"]["bytes"] == len(b"VALUE = 1\n")

    (root / "mypy-v0115.log").write_text("changed generated log\n", encoding="utf-8")
    (output / "VERIFICATION_RESULTS.json").write_text("changed output\n", encoding="utf-8")
    assert manifest_digest(manifest(root, excluded_roots=(output,))) == first_digest

    source.write_bytes(b"VALUE = 2\n")
    assert manifest_digest(manifest(root, excluded_roots=(output,))) != first_digest
