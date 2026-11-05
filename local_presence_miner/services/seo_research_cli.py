"""Record local source evidence without acquisition, API calls or outreach.

python -m local_presence_miner.services.seo_research_cli --database ... --lead 1 template --output ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.schema import Lead
from local_presence_miner.services.semrush_import import import_semrush_csv
from local_presence_miner.services.seo_research_service import (
    MAX_IMPORT_BYTES,
    append_research,
    parse_research_json,
    project_seo_research,
    research_binding,
    research_template,
)


def read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("Input exceeds the bounded import limit.")
    return parse_research_json(path.read_text(encoding="utf-8-sig"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--lead", type=int, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    template = sub.add_parser("template")
    template.add_argument("--output", type=Path, required=True)
    ingest = sub.add_parser("import-json")
    ingest.add_argument("--input", type=Path, required=True)
    csv = sub.add_parser("import-semrush-csv")
    csv.add_argument("--input", type=Path, required=True)
    csv.add_argument("--metadata", type=Path, required=True)
    sub.add_parser("show")
    args = parser.parse_args(argv)
    if not args.database.is_file():
        parser.error("Choose the existing MarketLens database; this command does not create a new business dataset.")
    factory = create_session_factory(args.database)
    try:
        initialize_database(factory)
        with factory() as session:
            lead = session.get(Lead, args.lead)
            if lead is None:
                raise ValueError("No such lead in the chosen database.")
            if args.command == "template":
                args.output.write_text(json.dumps(research_template(session, lead), indent=2), encoding="utf-8")
                return 0
            if args.command == "import-json":
                payload = read_json(args.input)
                append_research(session, lead, payload)
                session.commit()
            elif args.command == "import-semrush-csv":
                if args.input.stat().st_size > 1_000_000:
                    raise ValueError("CSV exceeds the bounded one-megabyte limit.")
                metadata = read_json(args.metadata)
                if set(metadata) - {"metadata", "local_ranks", "pages"}:
                    raise ValueError("CSV metadata only accepts metadata, local_ranks and optional pages.")
                payload = import_semrush_csv(
                    args.input.read_text(encoding="utf-8-sig"), subject=research_binding(session, lead)["subject"],
                    metadata=metadata.get("metadata", {}), local_ranks=metadata.get("local_ranks", {}), pages=metadata.get("pages"),
                )
                append_research(session, lead, payload)
                session.commit()
            print(json.dumps(project_seo_research(session, lead), indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    finally:
        factory.kw["bind"].dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
