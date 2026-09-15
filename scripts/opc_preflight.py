#!/usr/bin/env python3
"""Preflight check for the Okta On-prem Connector for Generic Databases agent host.

Checks the requirements from Okta's "System requirements for On-premises Connector - Generic Databases"
(Early Access): dedicated RHEL 8/9/10 host, 4+ cores, 4 GB RAM, 10 GB storage, JDK 21, OpenSSL 3+, the JDBC
driver for your database, Okta Provisioning Agent 3.0.6+ and On-prem SCIM Server agent 1.5.0+ (1.7.0+ for Db2),
reachability of the database port and of Okta over 443, and port 1443 if OPA and OPS run on separate servers.

Run on the agent host (python3 only, no extra packages):
  python3 opc_preflight.py --db postgres --db-host hr-db.example.com --jdbc /opt/okta/jdbc/postgresql.jar --okta-org https://your-org.okta.com
Exit code 0 = all required checks passed, 1 = at least one FAIL.
"""
import argparse
import os
import re
import shutil
import socket
import subprocess
import sys

DB_PORTS = {"postgres": 5432, "mysql": 3306, "mssql": 1433, "oracle": 1521, "db2": 50000}
JDBC_CLASSES = {"postgres": "org/postgresql/Driver.class", "mysql": "com/mysql/cj/jdbc/Driver.class",
                "mssql": "com/microsoft/sqlserver/jdbc/SQLServerDriver.class", "oracle": "oracle/jdbc/OracleDriver.class",
                "db2": "com/ibm/db2/jcc/DB2Driver.class"}
MIN_OPS = {"db2": (1, 7, 0)}
RESULTS = []


def rec(status, name, detail):
    RESULTS.append((status, name, detail))


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout + subprocess.run(cmd, capture_output=True, text=True, timeout=15).stderr
    except (OSError, subprocess.SubprocessError):
        return ""


def vtuple(s):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", s or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None


def check_os():
    info = {}
    if os.path.exists("/etc/os-release"):
        for line in open("/etc/os-release"):
            if "=" in line:
                k, _, v = line.strip().partition("=")
                info[k] = v.strip('"')
    name, ver = info.get("ID", ""), info.get("VERSION_ID", "")
    major = ver.split(".")[0]
    if name == "rhel" and major in ("8", "9", "10"):
        rec("PASS", "Operating system", f"Red Hat Enterprise Linux {ver}")
    elif name in ("rocky", "almalinux", "centos", "ol") and major in ("8", "9", "10"):
        rec("WARN", "Operating system", f"{info.get('PRETTY_NAME', name)}: RHEL-compatible, but Okta lists only RHEL 8/9/10 as supported")
    else:
        rec("FAIL", "Operating system", f"{info.get('PRETTY_NAME') or 'unknown'}; Okta requires a dedicated RHEL 8, 9 or 10 server")


def check_hardware(path):
    cores = os.cpu_count() or 0
    rec("PASS" if cores >= 4 else "FAIL", "CPU cores", f"{cores} (minimum 4)")
    mem_kb = 0
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                mem_kb = int(line.split()[1])
    except OSError:
        pass
    gb = mem_kb / 1024 / 1024
    rec("PASS" if gb >= 3.7 else "FAIL", "Memory", f"{gb:.1f} GB (minimum 4 GB)")
    try:
        free = shutil.disk_usage(path).free / 1024 ** 3
        rec("PASS" if free >= 10 else "FAIL", "Storage", f"{free:.1f} GB free at {path} (minimum 10 GB)")
    except OSError as ex:
        rec("WARN", "Storage", f"could not stat {path}: {ex}")


def check_java():
    out = run(["java", "-version"])
    v = vtuple(out)
    if not out:
        rec("FAIL", "JDK", "java not found on PATH; JDK 21 is required (install it and upload it to the agent server)")
    elif v and v[0] == 21:
        rec("PASS", "JDK", f"java {'.'.join(map(str, v))}")
    else:
        rec("FAIL", "JDK", f"found java {'.'.join(map(str, v)) if v else '?'}; Okta requires JDK 21")
    javac = shutil.which("javac")
    if not javac:
        rec("WARN", "JDK (javac)", "javac not on PATH: make sure this is a JDK, not just a JRE")


def check_openssl():
    out = run(["openssl", "version"])
    v = vtuple(out)
    if not out:
        rec("FAIL", "OpenSSL", "openssl not found; version 3 or later is required")
    else:
        rec("PASS" if v and v[0] >= 3 else "FAIL", "OpenSSL", out.strip() + " (minimum 3.0)")


def check_jdbc(db, path):
    if not path:
        rec("WARN", "JDBC driver", f"no --jdbc path given; upload the {db} JDBC driver jar to the agent server")
        return
    if not os.path.isfile(path):
        rec("FAIL", "JDBC driver", f"{path} not found")
        return
    import zipfile
    try:
        names = set(zipfile.ZipFile(path).namelist())
    except zipfile.BadZipFile:
        rec("FAIL", "JDBC driver", f"{path} is not a jar")
        return
    cls = JDBC_CLASSES[db]
    rec("PASS" if cls in names else "FAIL", "JDBC driver", f"{path} {'contains' if cls in names else 'does not contain'} {cls}")


def check_agents(db):
    rpm = run(["rpm", "-qa"]) if shutil.which("rpm") else ""
    pkgs = [l for l in rpm.splitlines() if "okta" in l.lower()]
    opa = next((p for p in pkgs if "provisioning" in p.lower()), None)
    ops = next((p for p in pkgs if "scim" in p.lower()), None)
    for label, pkg, minimum in (("Okta Provisioning Agent (OPA)", opa, (3, 0, 6)), ("Okta On-prem SCIM Server agent (OPS)", ops, MIN_OPS.get(db, (1, 5, 0)))):
        if not pkg:
            rec("WARN", label, f"not detected via rpm; required version {'.'.join(map(str, minimum))} or later")
            continue
        v = vtuple(pkg)
        rec("PASS" if v and v >= minimum else "FAIL", label, f"{pkg} (minimum {'.'.join(map(str, minimum))})")
    for d in ("/opt/OktaProvisioningAgent", "/opt/OktaOnPremScimServer"):
        if os.path.isdir(d):
            rec("PASS", "Agent directory", d)


def check_port(name, host, port, required=True):
    if not host:
        rec("WARN", name, f"no host given; port {port} not tested")
        return
    try:
        with socket.create_connection((host, port), timeout=5):
            rec("PASS", name, f"{host}:{port} reachable")
    except OSError as ex:
        rec("FAIL" if required else "WARN", name, f"{host}:{port} not reachable ({ex})")


def check_okta(org):
    if not org:
        rec("WARN", "Okta connectivity (443)", "no --okta-org given; outbound 443 not tested. Okta IP ranges must be allowlisted")
        return
    host = re.sub(r"^https?://", "", org).split("/")[0]
    check_port("Okta connectivity (443)", host, 443)
    try:
        import urllib.request
        with urllib.request.urlopen(f"https://{host}/.well-known/okta-organization", timeout=10) as r:
            rec("PASS", "Okta HTTPS", f"https://{host} answered {r.status}")
    except Exception as ex:  # noqa: BLE001
        rec("WARN", "Okta HTTPS", f"https://{host}: {ex}")


def check_db_user(db):
    rec("INFO", "Database user", f"the connector needs a {db} user with administrator privileges to run the configured SQL (Get Users, Get All Entitlements, Incremental Import)")


def main():
    ap = argparse.ArgumentParser(description="Okta On-prem Connector for Generic Databases: agent host preflight")
    ap.add_argument("--db", choices=sorted(DB_PORTS), required=True, help="database type the connector will read")
    ap.add_argument("--db-host", default="", help="database host (port defaults to Okta's table: 5432/3306/1433/1521/50000)")
    ap.add_argument("--db-port", type=int, default=None)
    ap.add_argument("--jdbc", default="", help="path to the JDBC driver jar uploaded to this server")
    ap.add_argument("--okta-org", default="", help="https://your-org.okta.com")
    ap.add_argument("--ops-host", default="", help="OPS agent host if it runs on a separate server (checks port 1443)")
    ap.add_argument("--install-path", default="/opt", help="where the agents are/will be installed (storage check)")
    a = ap.parse_args()

    check_os()
    check_hardware(a.install_path)
    check_java()
    check_openssl()
    check_jdbc(a.db, a.jdbc)
    check_agents(a.db)
    check_port(f"Database port ({a.db})", a.db_host, a.db_port or DB_PORTS[a.db])
    if a.ops_host:
        check_port("OPA -> OPS (1443)", a.ops_host, 1443)
    else:
        rec("INFO", "OPA -> OPS (1443)", "both agents on this host: port 1443 only matters when they run on separate servers")
    check_okta(a.okta_org)
    check_db_user(a.db)

    width = max(len(n) for _, n, _ in RESULTS)
    print(f"\nOkta On-prem Connector (Generic Databases) preflight - database: {a.db}\n")
    for status, name, detail in RESULTS:
        print(f"  [{status:<4}] {name:<{width}}  {detail}")
    fails = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    warns = sum(1 for s, _, _ in RESULTS if s == "WARN")
    print(f"\n{fails} FAIL, {warns} WARN. " + ("Host meets the documented requirements." if not fails else "Fix the FAIL items before installing the agents."))
    print("Reference: help.okta.com > Provisioning > On-prem Connector > System requirements for On-premises Connector - Generic Databases")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
