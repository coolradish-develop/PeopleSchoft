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
{mock}
volumes:
  peopleschoft-data:
"""

LIVE_MOUNTS = """      # Live code: the container runs the source from this checkout, so edits need no image rebuild.
      # With PS_RELOAD=1 the server restarts itself when a file in peopleschoft/ changes.
      - ./peopleschoft:/app/peopleschoft:ro
      - ./scripts:/app/scripts:ro
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


def render(port, python, with_mock, live=True):
    return {
        "Dockerfile": DOCKERFILE.format(port=port, python=python),
        "docker-compose.yml": COMPOSE.format(port=port, mock=MOCK_SERVICE if with_mock else "", live=LIVE_MOUNTS if live else ""),
        ".dockerignore": DOCKERIGNORE,
    }


def main():
    ap = argparse.ArgumentParser(description="Generate container files for PeopleSchoft")
    ap.add_argument("--port", type=int, default=8080, help="port PeopleSchoft listens on (default 8080)")
    ap.add_argument("--python", default="3.12", help="python base image tag (default 3.12)")
    ap.add_argument("--no-mock", action="store_true", help="omit the mock-okta service from the compose file")
    ap.add_argument("--no-live", action="store_true", help="do not mount the source tree; the image is self-contained and needs a rebuild per change")
    ap.add_argument("--out", default=str(ROOT), help="directory to write into (default: repo root)")
    ap.add_argument("--print", action="store_true", help="print the files instead of writing them")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    a = ap.parse_args()

    files = render(a.port, a.python, not a.no_mock, not a.no_live)
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

Okta against the mock inside compose:
  OKTA_MODE=users OKTA_ORG_URL=http://mock-okta:9090 OKTA_API_TOKEN=mock docker compose up -d
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
