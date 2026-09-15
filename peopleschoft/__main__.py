"""CLI:  python3 -m peopleschoft [serve|seed|reset|demo|okta-sync|export|status]"""
import argparse
import json
import sys

from .config import config, load_dotenv


def main(argv=None):
    load_dotenv()
    p = argparse.ArgumentParser(prog="peopleschoft", description="PeopleSoft HCM emulator for identity lifecycle demos")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the web UI + API (default)")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    sub.add_parser("seed", help="create schema and seed demo data if empty")
    r = sub.add_parser("reset", help="drop everything and re-seed")
    r.add_argument("--yes", action="store_true")
    sub.add_parser("demo", help="run the guided joiner/mover/leaver/rehire journey")
    sub.add_parser("okta-sync", help="flush the Okta outbox once")
    sub.add_parser("export", help="enqueue a full snapshot of every worker for Okta")
    sub.add_parser("status", help="print counts and Okta configuration")
    x = sub.add_parser("export-sql", help="print HR master SQL for the Okta Generic Databases connector")
    x.add_argument("--dialect", default="postgres", choices=["postgres", "mysql", "mssql", "sqlite"])
    x.add_argument("--since", default=None, help="only workers changed after this ISO timestamp")
    x.add_argument("--no-ddl", action="store_true")
    args = p.parse_args(argv)

    from . import db, hr, okta
    cmd = args.cmd or "serve"
    if cmd == "serve":
        from .server import serve
        serve(args.host, args.port)
        return 0
    conn = db.connect()
    db.init_db(conn)
    if cmd == "seed":
        if db.is_seeded(conn):
            print("Already seeded:", config.db_path)
        else:
            hr.seed(conn)
            print("Seeded:", config.db_path)
    elif cmd == "reset":
        if not args.yes:
            print(f"This drops all data in {config.db_path}. Re-run with --yes to confirm.")
            return 1
        db.reset_db(conn)
        hr.seed(conn)
        print("Reset and re-seeded:", config.db_path)
    elif cmd == "demo":
        from .journey import run_journey
        if not db.is_seeded(conn):
            hr.seed(conn)
        result = run_journey(conn)
        print(f"Journey for {result['name']} (EMPLID {result['emplid']}):")
        for st in result["steps"]:
            print(f"  [{st['stage']:<18}] {st['action']}  {st['description']}  -> {st['emplStatusDescr']}")
        s = okta.sync_pending(conn)
        print("Okta sync:", json.dumps({k: v for k, v in s.items() if k != 'errors'}))
        if s["errors"]:
            print("Errors:", json.dumps(s["errors"], indent=1)[:2000])
    elif cmd == "okta-sync":
        s = okta.sync_pending(conn)
        print(json.dumps(s, indent=1, default=str))
    elif cmd == "export":
        n = okta.full_export(conn)
        print(f"Queued {n} snapshot events")
    elif cmd == "export-sql":
        from . import sqlexport
        sys.stdout.write(sqlexport.render(conn, args.dialect, args.since, not args.no_ddl))
    elif cmd == "status":
        counts = {k: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for k, t in
                  (("workers", "PS_PERSONAL_DATA"), ("jobRows", "PS_JOB"), ("userProfiles", "PSOPRDEFN"), ("events", "PS_OKTA_EVENTS"))}
        counts["pendingEvents"] = conn.execute("SELECT COUNT(*) FROM PS_OKTA_EVENTS WHERE STATUS='PENDING'").fetchone()[0]
        print(json.dumps({"db": str(config.db_path), "counts": counts, "okta": config.okta_summary()}, indent=1))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
