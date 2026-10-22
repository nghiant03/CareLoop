"""Operator-only knowledge workflow. Actor labels are attestations, not authentication."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import psycopg

from backend.knowledge.store import KnowledgeStore, load_release
from backend.storage.postgres import database_url


def _read(path: Path):
    payload = path.read_bytes()
    return json.loads(payload), hashlib.sha256(payload).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="verify the separately migrated PostgreSQL knowledge schema")
    commands.add_parser("list", help="show drafts, current reviews, release IDs and validation disclosures")
    discovery = commands.add_parser("discover", help="propose unapproved guideline-backed rules without database writes")
    discovery.add_argument("--research-dir", type=Path, help="external research directory containing manifest.json and raw sources")
    discovery.add_argument("--rules-file", type=Path, help="baseline rulebook for comparison (default external rule fixture)")
    discovery.add_argument("--out-dir", type=Path, help="external report directory (default content-addressed artifact directory)")
    for name in ("import", "edit"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--draft-id", required=True)
        cmd.add_argument("--rules-file", type=Path, required=True)
        cmd.add_argument("--dishes-file", type=Path, required=True)
        cmd.add_argument("--actor", required=True)
        if name == "edit":
            cmd.add_argument("--expected-revision", type=int, required=True)
            cmd.add_argument("--note", required=True)
    clone = commands.add_parser("clone")
    clone.add_argument("--release-id", required=True)
    clone.add_argument("--draft-id", required=True)
    clone.add_argument("--actor", required=True)
    for name in ("review", "publish"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--draft-id", required=True)
        cmd.add_argument("--actor", required=True)
        cmd.add_argument("--expected-revision", type=int, required=True)
        cmd.add_argument("--note", required=True)
        if name == "review":
            cmd.add_argument("--decision", choices=("approve", "reject"), required=True)
        else:
            cmd.add_argument("--release-id", required=True)
    for name in ("show", "history"):
        commands.add_parser(name).add_argument("--draft-id", required=True)
    export = commands.add_parser("export")
    selection = export.add_mutually_exclusive_group(required=True)
    selection.add_argument("--draft-id")
    selection.add_argument("--release-id")
    export.add_argument("--out-dir", type=Path, required=True)
    export.add_argument("--revision", type=int, help="historical draft revision; only with --draft-id")
    args = parser.parse_args(argv)
    try:
        if args.command == "discover":
            from backend.datasets.paths import dataset_dir, dataset_path
            from backend.knowledge.discovery import (
                discover_rules,
                write_discovery_report,
            )

            rules, _ = _read(args.rules_file or dataset_path("rules.json"))
            report = discover_rules(args.research_dir or dataset_dir() / "research", rules)
            output = write_discovery_report(report, args.out_dir)
            print(json.dumps({"report_path": str(output), "candidates": len(report["candidates"]),
                              "status": "NEEDS_REVIEW", "database_writes": False,
                              "missing_supported_sections": report["missing_supported_sections"]}, indent=2))
            return 0
        url = database_url("knowledge")
        if url is None:
            raise ValueError("configure CARELOOP_KNOWLEDGE_DATABASE_URL")
        store = KnowledgeStore(url)
        if args.command == "init":
            store.initialize()
            result = {"database": "PostgreSQL knowledge", "schema_version": 1}
        elif args.command in {"import", "edit"}:
            rules, rules_hash = _read(args.rules_file)
            dishes, dishes_hash = _read(args.dishes_file)
            if args.command == "import":
                provenance = {str(args.rules_file): rules_hash, str(args.dishes_file): dishes_hash}
                result = store.create_draft(args.draft_id, rules, dishes, actor=args.actor, provenance=provenance)
            else:
                result = store.edit_draft(args.draft_id, rules, dishes, actor=args.actor,
                                          expected_revision=args.expected_revision, note=args.note)
        elif args.command == "clone":
            release = load_release(store.database, args.release_id)
            result = store.create_draft(args.draft_id, release.rules_document(), release.dishes(), actor=args.actor,
                                        parent_release=args.release_id, provenance={"source_hashes": release.source_hashes()})
        elif args.command == "review":
            result = store.review(args.draft_id, actor=args.actor, decision=args.decision,
                                  expected_revision=args.expected_revision, note=args.note)
        elif args.command == "publish":
            release = store.publish(args.draft_id, args.release_id, actor=args.actor,
                                    expected_revision=args.expected_revision, note=args.note)
            result = {"release_id": release.release_id, "source_hashes": release.source_hashes(),
                      "published_at": release.published_at}
        elif args.command == "export":
            if args.release_id:
                if args.revision is not None:
                    raise ValueError("--revision is only supported with --draft-id")
                release = load_release(store.database, args.release_id)
                rules, dishes = release.rules_document(), release.dishes()
            else:
                rules, dishes = store.documents(args.draft_id, args.revision)
            args.out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
            for name, document in (("rules.json", rules), ("dishes.json", dishes)):
                with (args.out_dir / name).open("x", encoding="utf-8") as output:
                    json.dump(document, output, indent=2, ensure_ascii=False, allow_nan=False)
                    output.write("\n")
            result = {"output_directory": str(args.out_dir)}
        elif args.command == "list":
            result = store.list_drafts()
        elif args.command == "history":
            result = store.history(args.draft_id)
        else:
            result = store.show(args.draft_id)
    except psycopg.Error:
        parser.exit(1, "Knowledge PostgreSQL operation failed; inspect database access/schema without sharing credentials.\n")
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        parser.exit(1, f"Knowledge operation failed: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
