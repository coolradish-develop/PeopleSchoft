#!/usr/bin/env python3
"""Generate Dockerfile, docker-compose.yml and .dockerignore for PeopleSchoft.

Usage:
  python3 scripts/generate_docker.py                 # write files into the repo root
  python3 scripts/generate_docker.py --port 8080 --python 3.12 --no-mock
  python3 scripts/generate_docker.py --print         # show what would be written, write nothing

Afterwards:
  docker compose up -d --build        # PeopleSchoft on http://localhost:<port>, mock Okta on :9090
  docker compose logs -f peopleschoft
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DOCKERFILE = """# PeopleSchoft - PeopleSoft HCM emulator for identity lifecycle demos (stdlib only, no pip installs)
FROM python:{python}-slim

ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PS_HOST=0.0.0.0 \\
    PS_PORT={port} \\
    PS_DB_PATH=/app/data/peopleschoft.db

WORKDIR /app
COPY peopleschoft/ ./peopleschoft/
COPY scripts/ ./scripts/
COPY start.sh Makefile README.md .env.example ./

RUN mkdir -p /app/data && useradd --create-home --uid 10001 peoplesoft && chown -R peoplesoft:peoplesoft /app
USER peoplesoft

VOLUME ["/app/data"]
EXPOSE {port}

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \\
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:{port}/api/v1/health', timeout=2).status == 200 else 1)"

# Seeds the GBI demo organisation on first start (the data volume keeps it between restarts).
CMD ["python3", "-m", "peopleschoft", "serve"]
"""

COMPOSE = """services:
  peopleschoft:
    build: .
    image: peopleschoft:latest
    container_name: peopleschoft
    ports:
      - "{port}:{port}"
    env_file:
      - path: .env
        required: false
    environment:
      PS_PORT: "{port}"
      PS_PUBLIC_URL: "${{PS_PUBLIC_URL:-http://localhost:{port}}}"
      PS_RELOAD: "${{PS_RELOAD:-1}}"
      # HR-as-a-source SQL mirror (Okta On-prem Connector for Generic Databases); '' = off
      PS_SQL_EXPORT_DIALECT: "${{PS_SQL_EXPORT_DIALECT:-{sql_dialect}}}"
      PS_SQL_EXPORT_INTERVAL: "${{PS_SQL_EXPORT_INTERVAL:-{interval}}}"
      # Okta outbound: dryrun | webhook | users | identity-source  (see .env.example)
      OKTA_MODE: "${{OKTA_MODE:-dryrun}}"
      OKTA_ORG_URL: "${{OKTA_ORG_URL:-https://dev-000000.okta.com}}"
      OKTA_API_TOKEN: "${{OKTA_API_TOKEN:-}}"
      OKTA_IDENTITY_SOURCE_ID: "${{OKTA_IDENTITY_SOURCE_ID:-}}"
      OKTA_WEBHOOK_URL: "${{OKTA_WEBHOOK_URL:-}}"
      OKTA_WEBHOOK_TOKEN: "${{OKTA_WEBHOOK_TOKEN:-}}"
    volumes:
      - peopleschoft-data:/app/data
{live}    restart: unless-stopped
{mock}{hrdb}
volumes:
  peopleschoft-data:
{hrdb_volume}"""

LIVE_MOUNTS = """      # Live code: the container runs the source from this checkout, so edits need no image rebuild.
      # With PS_RELOAD=1 the server restarts itself when a file in peopleschoft/ changes.
      - ./peopleschoft:/app/peopleschoft:ro
      - ./scripts:/app/scripts:ro
"""

HR_DB_SERVICES = """
  # HR master mirror for the Okta On-prem Connector for Generic Databases: PeopleSchoft writes
  # data/export/hr_master.postgres.sql every PS_SQL_EXPORT_INTERVAL seconds; hr-mirror loads it into Postgres.
  # Point the Okta connector at this database (host: your machine, port 5432, db hrmaster, user hr / password hr).
  hr-db:
    image: postgres:16
    container_name: hr-db
    environment:
      POSTGRES_DB: hrmaster
      POSTGRES_USER: hr
      POSTGRES_PASSWORD: hr
    ports:
      - "5432:5432"
    volumes:
      - hr-db-data:/var/lib/postgresql/data
    restart: unless-stopped
  hr-mirror:
    image: postgres:16
    container_name: hr-mirror
    depends_on:
      - hr-db
      - peopleschoft
    environment:
      PGPASSWORD: hr
    volumes:
      - peopleschoft-data:/export:ro
    entrypoint: ["bash", "-c", "until pg_isready -h hr-db -U hr >/dev/null 2>&1; do sleep 2; done; while true; do if [ -f /export/export/hr_master.postgres.sql ]; then psql -h hr-db -U hr -d hrmaster -q -v ON_ERROR_STOP=0 -f /export/export/hr_master.postgres.sql >/dev/null 2>&1 && echo \\"$(date -u +%FT%TZ) mirrored hr_master.postgres.sql\\"; fi; sleep {interval}; done"]
    restart: unless-stopped
"""

HR_DB_MYSQL_SERVICES = """
  # HR master mirror (MySQL flavour) for the Okta On-prem Connector for Generic Databases. Port 3306 per Okta's port table.
  hr-db:
    image: mysql:8
    container_name: hr-db
    environment:
      MYSQL_DATABASE: hrmaster
      MYSQL_USER: hr
      MYSQL_PASSWORD: hr
      MYSQL_ROOT_PASSWORD: hr
    ports:
      - "3306:3306"
    volumes:
      - hr-db-data:/var/lib/mysql
    restart: unless-stopped
  hr-mirror:
    image: mysql:8
    container_name: hr-mirror
    depends_on:
      - hr-db
      - peopleschoft
    volumes:
      - peopleschoft-data:/export:ro
    entrypoint: ["bash", "-c", "until mysqladmin ping -h hr-db -uroot -phr --silent 2>/dev/null; do sleep 2; done; mysql -h hr-db -uroot -phr -e \\"GRANT ALL PRIVILEGES ON hrmaster.* TO 'hr'@'%'; FLUSH PRIVILEGES;\\" 2>/dev/null; while true; do if [ -f /export/export/hr_master.mysql.sql ]; then mysql -h hr-db -uhr -phr hrmaster < /export/export/hr_master.mysql.sql 2>/dev/null && echo \\"$(date -u +%FT%TZ) mirrored hr_master.mysql.sql\\"; fi; sleep {interval}; done"]
    restart: unless-stopped
"""

MOCK_SERVICE = """
  # Fake Okta org so the users / webhook / identity-source modes work without a tenant.
  # Point PeopleSchoft at it with: OKTA_MODE=users OKTA_ORG_URL=http://mock-okta:9090 OKTA_API_TOKEN=mock
  mock-okta:
    image: peopleschoft:latest
    container_name: mock-okta
    command: ["python3", "scripts/mock_okta.py", "--port", "9090"]
    ports:
      - "9090:9090"
    depends_on:
      - peopleschoft
    restart: unless-stopped
"""

DOCKERIGNORE = """.env
data/
tests/
__pycache__/
*.pyc
.git/
.claude/
"""


def render(port, python, with_mock, live=True, with_hr_db=False, interval=30, engine="postgres"):
    hrdb_tpl = HR_DB_MYSQL_SERVICES if engine == "mysql" else HR_DB_SERVICES
    return {
        "Dockerfile": DOCKERFILE.format(port=port, python=python),
        "docker-compose.yml": COMPOSE.format(port=port, mock=MOCK_SERVICE if with_mock else "", live=LIVE_MOUNTS if live else "",
                                             hrdb=hrdb_tpl.format(interval=interval) if with_hr_db else "",
                                             hrdb_volume="  hr-db-data:\n" if with_hr_db else "",
                                             sql_dialect=engine if with_hr_db else "", interval=interval),
        ".dockerignore": DOCKERIGNORE,
    }


def main():
    ap = argparse.ArgumentParser(description="Generate container files for PeopleSchoft")
    ap.add_argument("--port", type=int, default=8080, help="port PeopleSchoft listens on (default 8080)")
    ap.add_argument("--python", default="3.12", help="python base image tag (default 3.12)")
    ap.add_argument("--no-mock", action="store_true", help="omit the mock-okta service from the compose file")
    ap.add_argument("--no-live", action="store_true", help="do not mount the source tree; the image is self-contained and needs a rebuild per change")
    ap.add_argument("--with-hr-db", action="store_true", help="add an HR-master mirror database (hr-db) for the Okta On-prem Connector for Generic Databases")
    ap.add_argument("--hr-db-engine", choices=["postgres", "mysql"], default="postgres", help="mirror engine: postgres (port 5432) or mysql (port 3306), matching Okta's port table")
    ap.add_argument("--mirror-interval", type=int, default=30, help="seconds between HR mirror refreshes (default 30)")
    ap.add_argument("--out", default=str(ROOT), help="directory to write into (default: repo root)")
    ap.add_argument("--print", action="store_true", help="print the files instead of writing them")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    a = ap.parse_args()

    files = render(a.port, a.python, not a.no_mock, not a.no_live, a.with_hr_db, a.mirror_interval, a.hr_db_engine)
    out = Path(a.out)
    if a.print:
        for name, content in files.items():
            print(f"# ===== {name} =====\n{content}")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = out / name
        if target.exists() and not a.force:
            print(f"skip   {target} (exists; use --force to overwrite)")
            continue
        target.write_text(content)
        print(f"wrote  {target}")
    print(f"""
Next steps:
  docker compose up -d --build
  open http://localhost:{a.port}        (PeopleSchoft){'' if a.no_mock else chr(10) + '  open http://localhost:9090        (mock Okta)'}
  docker compose exec peopleschoft python3 -m peopleschoft demo     # run the lifecycle journey
  docker compose exec peopleschoft python3 -m peopleschoft reset --yes

After a code change: nothing to do{'' if a.no_live else ' - the source is mounted and PS_RELOAD=1 restarts the server by itself'}.
  docker compose logs -f peopleschoft      # watch for "[reload] ... restarting server"
Rebuild only if the Dockerfile itself changes:  docker compose up -d --build
{'' if not a.with_hr_db else f'''
HR master mirror for the Okta On-prem Connector (Generic Databases):
  {'MySQL at localhost:3306' if a.hr_db_engine == 'mysql' else 'Postgres at localhost:5432'}, database hrmaster, user hr, password hr (tables hr_worker, hr_entitlement, hr_worker_entitlement, view hr_worker_v)
  docker compose logs -f hr-mirror              # prints "mirrored hr_master.{a.hr_db_engine}.sql" every {a.mirror_interval}s
  Agent host preflight (RHEL 8/9/10, JDK 21, OpenSSL 3, JDBC, ports): python3 scripts/opc_preflight.py --db {a.hr_db_engine} --db-host <this machine> --jdbc <driver.jar> --okta-org https://<org>.okta.com
  Connector SQL values: open http://localhost:{a.port}/hr-master
'''}
Okta against the mock inside compose:
  OKTA_MODE=users OKTA_ORG_URL=http://mock-okta:9090 OKTA_API_TOKEN=mock docker compose up -d
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
