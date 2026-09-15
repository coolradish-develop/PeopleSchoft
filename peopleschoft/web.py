"""Server-rendered web UI modelled on PeopleSoft 9.2: Fluid header + homepage tiles, classic transaction pages."""
import json
from datetime import date, timedelta

from . import db, hr, okta
from .config import config
from .journey import run_journey
from .routing import e, html_response, redirect, route

CSS = """
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{font:12px/1.4 Arial,Helvetica,sans-serif;color:#000;background:#e9ebee}
a{color:#0b5cad;text-decoration:none}a:hover{text-decoration:underline}
/* ---- Fluid header (PeopleTools 8.5x) ---- */
.pthdr{background:#0f2540;color:#fff;height:52px;display:flex;align-items:center;padding:0 12px;position:relative}
.pthdr .home{width:36px;height:36px;border-radius:50%;background:#1c3a5e;display:flex;align-items:center;justify-content:center;margin-right:10px}
.pthdr .home svg{width:18px;height:18px;fill:#fff}
.pthdr .brand{color:#fff;font-size:17px;font-weight:700;letter-spacing:.3px;margin-right:14px;white-space:nowrap}.pthdr .brand:hover{text-decoration:none}
.pthdr .brand small{font-weight:400;font-size:10px;color:#a9b8c8;margin-left:6px;vertical-align:middle;border:1px solid #3d5a7a;border-radius:3px;padding:1px 4px}
.pthdr .title{flex:1;text-align:center;display:flex;align-items:baseline;justify-content:center;gap:14px}
.pthdr .brandbig{font-size:22px;font-weight:700;letter-spacing:.5px;color:#fff}.pthdr .pgname{font-size:15px;font-weight:400;color:#c9d6e3}
.pthdr .who-wrap{display:flex;gap:4px;margin-right:10px}.pthdr .who{color:#fff;font-size:12px;line-height:1.2;padding:4px 10px;border-radius:14px;background:#1c3a5e;display:flex;flex-direction:column;justify-content:center}.pthdr .who small{font-size:10px;color:#a9b8c8}.pthdr .who:hover{text-decoration:none;background:#274b75}
.pthdr .icons{display:flex;gap:6px}.pthdr .icons a,.pthdr .icons label{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer}
.pthdr .icons a:hover,.pthdr .icons label:hover{background:#1c3a5e}.pthdr .icons svg{width:20px;height:20px;fill:#fff}
#navtoggle{display:none}.navbar{position:fixed;top:0;right:-300px;width:290px;height:100%;background:#fff;box-shadow:-2px 0 8px rgba(0,0,0,.3);transition:right .2s;z-index:50;overflow:auto}
#navtoggle:checked ~ .navbar{right:0}.navbar h3{margin:0;padding:14px 16px;background:#0f2540;color:#fff;font-size:16px;font-weight:400}
.navbar a{display:flex;align-items:center;gap:10px;padding:11px 16px;border-bottom:1px solid #eee;color:#222;font-size:13px}.navbar a:hover{background:#f2f5f9;text-decoration:none}
.navbar .ico{width:30px;height:30px;border-radius:4px;background:#e8792b;color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700}
.navbar .close{display:block;text-align:right;padding:6px 12px;color:#0b5cad;border:none}
/* ---- Fluid homepage ---- */
.fluidhome{background:linear-gradient(180deg,#e2e6eb,#eef0f3);min-height:calc(100% - 52px);padding:22px 30px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,215px);gap:18px;justify-content:start}
.tile{width:215px;height:215px;background:#fff;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,.2);padding:12px 14px;color:#222;display:flex;flex-direction:column;position:relative}
.tile:hover{box-shadow:0 2px 8px rgba(0,0,0,.3);text-decoration:none}
.tile .t{font-size:14px;color:#0f2540;font-weight:600}.tile .big{font-size:44px;font-weight:300;color:#0f2540;margin:auto 0 0}
.tile .sub{font-size:11px;color:#666}.tile .rows{margin:auto 0 0;font-size:11.5px;line-height:1.7;color:#333}.tile .rows b{display:inline-block;width:30px;color:#0f2540}
.tile .ico{position:absolute;right:12px;top:10px;width:26px;height:26px;fill:#c9d1da}
/* ---- classic page frame ---- */
.crumbs{background:#fff;border-bottom:1px solid #cfd3d8;padding:6px 14px;font-size:11.5px;color:#444}.crumbs a{color:#0b5cad}.crumbs b{color:#000}
.page{background:#fff;margin:10px 14px 24px;border:1px solid #cfd3d8;padding:0 0 14px;min-height:400px}
.pgtitle{font-size:20px;font-weight:400;color:#000;padding:12px 16px 8px}
.pstabs{display:flex;border-bottom:1px solid #9a9a9a;margin:0 16px;padding-left:2px;align-items:flex-end}.pstabs a{padding:5px 14px;font-size:12px;color:#222;background:#e4e4e4;border:1px solid #9a9a9a;border-bottom:none;margin-right:3px;border-radius:3px 3px 0 0;position:relative;top:1px}
.pstabs a.on{background:#fff;font-weight:700;border-bottom:1px solid #fff}.pstabs a:hover{text-decoration:none;background:#f3f3f3}
.pgbody{padding:14px 16px}
.hdrrow{display:flex;gap:26px;padding:8px 16px 4px;font-size:12px;align-items:center;flex-wrap:wrap}.hdrrow b{font-weight:700}.hdrrow .nm{font-size:14px;font-weight:700}
.grp{border:1px solid #c8c8c8;margin:8px 0 14px;background:#fff}.grp>.gh{background:linear-gradient(#f4f4f4,#dedede);border-bottom:1px solid #c8c8c8;padding:4px 8px;font-weight:700;font-size:12px;display:flex;align-items:center;gap:14px;min-height:28px}
.grp>.gb{padding:8px 10px}
.rownav{margin-left:auto;font-weight:400;font-size:11px;color:#444;display:flex;align-items:center;gap:6px;white-space:nowrap}.rownav a{color:#0b5cad}
.rownav .pm{display:inline-block;width:18px;height:18px;line-height:16px;text-align:center;border:1px solid #777;background:linear-gradient(#fff,#ddd);color:#000;font-weight:700;border-radius:2px}
.rownav .pm.dis{color:#aaa;border-color:#bbb;background:#f3f3f3}
.fl{display:grid;grid-template-columns:170px minmax(0,1fr);gap:4px 8px;align-items:center;font-size:12px;max-width:640px}
.fl.two{grid-template-columns:170px minmax(0,1fr) 170px minmax(0,1fr);column-gap:8px;max-width:100%}
.fl .lb{text-align:right;color:#222;padding-right:6px;min-height:24px;display:flex;align-items:center;justify-content:flex-end}
.fl .lb.req:after{content:'*';color:#c00;margin-left:3px}
.fl .vl{min-height:24px;display:flex;align-items:center;flex-wrap:wrap;gap:0 6px}
.fl .vl .cd{display:inline-block;min-width:70px}.fl .vl .ds{color:#333}.fl .vl .muted{white-space:nowrap}
.fl .vl select,.fl .vl input{margin:0}
@media (max-width:1000px){.fl.two{grid-template-columns:170px minmax(0,1fr)}}
.lk{display:inline-block;width:16px;height:16px;vertical-align:middle;margin-left:3px}.lk svg{width:16px;height:16px;fill:#0b5cad}
input[type=text],input[type=date],input[type=number],select{padding:2px 4px;border:1px solid #8a8a8a;font:12px Arial;background:#fff;height:22px;vertical-align:middle;box-sizing:border-box}
input[type=text],input[type=number]{width:200px}input[type=date]{width:140px}select{max-width:330px;min-width:110px}
input[type=checkbox]{vertical-align:middle;margin:0 3px 0 0}
.btn,button{font:12px Arial;padding:0 10px;border:1px solid #7a7a7a;border-radius:3px;background:linear-gradient(#fdfdfd,#d8d8d8);color:#000;cursor:pointer;display:inline-flex;align-items:center;height:24px;line-height:22px;vertical-align:middle;box-sizing:border-box}
.btn:hover,button:hover{background:linear-gradient(#fff,#e9e9e9);text-decoration:none}
.btn.primary,button.primary{background:linear-gradient(#5f8fc8,#2f64a6);color:#fff;border-color:#24507f;font-weight:700}
.btn.primary:hover,button.primary:hover{background:linear-gradient(#6c9bd2,#3670b5)}
.toolbar{border-top:1px solid #c8c8c8;margin:8px 16px 0;padding:10px 0 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center}.toolbar .sep{margin-left:auto}
.toolbar .btn,.toolbar button{min-width:70px;justify-content:center}
.grid{width:100%;border-collapse:collapse;font-size:12px;background:#fff}
.grid th{background:linear-gradient(#f4f4f4,#dcdcdc);border:1px solid #c0c0c0;padding:4px 6px;text-align:left;font-weight:700;white-space:nowrap}
.grid td{border:1px solid #d5d5d5;padding:3px 6px;vertical-align:top}.grid tr:nth-child(even) td{background:#f6f6f6}.grid tr.cur td{background:#e6eef8}
.gridhdr{background:linear-gradient(#f4f4f4,#dedede);border:1px solid #c8c8c8;border-bottom:none;padding:4px 8px;font-weight:700;display:flex;align-items:center}
.gridhdr .rownav{margin-left:auto}
.msg{margin:10px 16px 0;padding:8px 12px;border:1px solid;font-size:12px}.msg.ok{background:#eef8ee;border-color:#8fc98f;color:#1d5a1d}.msg.err{background:#fdeeee;border-color:#e09a9a;color:#7a1c1c}
.badge{display:inline-block;padding:0 6px;border-radius:8px;font-size:10.5px;font-weight:700;color:#fff;background:#8a97a6;vertical-align:middle}
.badge.A{background:#3a9d5d}.badge.L,.badge.P{background:#e8862c}.badge.S{background:#b7770d}.badge.T,.badge.R,.badge.D{background:#c0392b}.badge.PRE{background:#2e6bb0}
.badge.SENT{background:#3a9d5d}.badge.SCHEDULED{background:#b7770d}.badge.DRYRUN{background:#2e6bb0}.badge.PENDING{background:#8a97a6}.badge.FAILED{background:#c0392b}
.muted{color:#666;font-size:11px}.note{background:#fff8e6;border:1px solid #e9d38a;padding:6px 10px;font-size:11.5px;margin:6px 0 10px}
pre{background:#f5f5f5;border:1px solid #d5d5d5;padding:8px;font-size:11px;overflow:auto;max-height:420px;margin:6px 0}code{background:#eef2f6;padding:0 3px}
details{margin:6px 0}summary{cursor:pointer;font-weight:700}
.hide{display:none}
/* legacy helpers used by admin pages */
.box{border:1px solid #c8c8c8;padding:10px 12px;margin-bottom:12px;background:#fff}.box h2,.pgbody h2{font-size:13px;margin:12px 0 6px;color:#000;border-bottom:1px solid #d5d5d5;padding-bottom:3px}
.box h3{font-size:12px;margin:0 0 6px}.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}
.kv{display:grid;grid-template-columns:190px minmax(0,1fr);gap:4px 10px;font-size:12px;align-items:start}.kv .k{color:#444;text-align:right;padding-top:1px}.kv .v{font-weight:400;word-break:break-word}
table.ps{border-collapse:collapse;width:100%;font-size:12px;background:#fff}table.ps th{background:linear-gradient(#f4f4f4,#dcdcdc);border:1px solid #c0c0c0;padding:4px 6px;text-align:left}table.ps td{border:1px solid #d5d5d5;padding:3px 6px;vertical-align:top}table.ps tr:nth-child(even) td{background:#f6f6f6}
form.inline{display:inline}label{display:block;font-size:11.5px;color:#222;margin:5px 0 1px}
button.sec{font-weight:400}button.danger{background:linear-gradient(#e07b6d,#b83a2b);color:#fff;border-color:#8f2a1f}
.journey{display:flex;flex-wrap:wrap;gap:8px}.journey .st{flex:1 1 150px;border:1px solid #c8c8c8;background:#fff;padding:8px;border-left:4px solid #2e6bb0;font-size:11.5px}
.journey .st.L{border-left-color:#e8862c}.journey .st.T{border-left-color:#c0392b}.journey .st.A{border-left-color:#3a9d5d}
"""

SVG_HOME = '<svg viewBox="0 0 24 24"><path d="M12 3 2 12h3v8h5v-6h4v6h5v-8h3z"/></svg>'
SVG_NAV = '<svg viewBox="0 0 24 24"><path d="M3 3h6v6H3zm8 0h6v6h-6zm8 0h4v6h-4zM3 11h6v6H3zm8 0h6v6h-6zm8 0h4v6h-4zM3 19h6v3H3zm8 0h6v3h-6zm8 0h4v3h-4z"/></svg>'
SVG_SEARCH = '<svg viewBox="0 0 24 24"><path d="M15.5 14h-.8l-.3-.3A6.5 6.5 0 1 0 9.5 16a6.5 6.5 0 0 0 4.2-1.6l.3.3v.8l5 5 1.5-1.5-5-5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z"/></svg>'
SVG_BELL = '<svg viewBox="0 0 24 24"><path d="M12 22a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2zm6-6v-5a6 6 0 0 0-5-5.9V4a1 1 0 0 0-2 0v1.1A6 6 0 0 0 6 11v5l-2 2v1h16v-1z"/></svg>'
LOOKUP = '<span class="lk" title="Look up">' + SVG_SEARCH + '</span>'

NAV = [("/", "Homepage", "HM"), ("/employees", "Job Data", "JD"), ("/hire", "Add Employment Instance", "AE"),
       ("/journey", "Lifecycle Journey", "LJ"), ("/okta", "Okta Integration", "OK"), ("/users", "User Profiles", "UP"),
       ("/setup", "Foundation Tables", "FT"), ("/api-docs", "Integration Broker / API", "IB"), ("/signon", "Sign-on Status (OAG)", "SO")]


def _oprid(req):
    return req.user.oprid if getattr(req, "user", None) else "PS"


def header(title, req=None):
    links = "".join(f'<a href="{p}"><span class="ico">{ico}</span>{n}</a>' for p, n, ico in NAV)
    u = getattr(req, "user", None)
    if u:
        who = f'<a class="who" href="/signon" title="Signed on through Okta Access Gateway">{e(u.name or u.oprid)}<small>{"Administrator" if u.is_admin else "Read only"} &middot; via gateway</small></a><a class="who" href="/signout">Sign out</a>'
    elif config.ui_auth == "header":
        who = '<a class="who" href="/signon">Not signed on</a>'
    else:
        who = '<a class="who" href="/signon" title="UI sign-on is off (PS_UI_AUTH=off)">User PS<small>open UI</small></a>'
    return f"""<input type="checkbox" id="navtoggle"><div class="navbar"><h3>{e(config.brand)} NavBar</h3><label for="navtoggle" class="close">Close &times;</label>{links}
<a href="http://localhost:9090" target="_blank"><span class="ico" style="background:#0b5cad">MO</span>Mock Okta (if running)</a></div>
<div class="pthdr"><a class="home" href="/" title="Home">{SVG_HOME}</a><div class="title"><span class="brandbig">{e(config.brand)}</span><span class="pgname">{e(title)}</span></div>
<div class="who-wrap">{who}</div><div class="icons"><a href="/employees" title="Search">{SVG_SEARCH}</a><a href="/okta" title="Notifications">{SVG_BELL}</a><label for="navtoggle" title="NavBar">{SVG_NAV}</label></div></div>"""


def layout(req, title, body, crumb="", active="/", fluid=False, header_title=None):
    msg, err = req.query.get("msg"), req.query.get("err")
    banner = (f'<div class="msg ok">{e(msg)}</div>' if msg else "") + (f'<div class="msg err">{e(err)}</div>' if err else "")
    if fluid:
        content = f'<div class="fluidhome">{banner}{body}</div>'
    else:
        content = f'<div class="crumbs">{crumb or "<b>" + e(title) + "</b>"}</div>{banner}<div class="page">{body}</div><div class="muted" style="padding:0 14px 14px">{e(config.brand)} &middot; PeopleSoft HCM emulator for identity lifecycle demos &middot; Okta mode {e(config.okta_mode)}</div>'
    return html_response(f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(config.brand)} - {e(title)}</title><style>{CSS}</style></head>
<body>{header(header_title or ("Workforce Administrator" if fluid else title), req)}{content}</body></html>""")


def status_badge(w):
    if w.get("preHire"):
        return f'<span class="badge PRE">Pre-hire ({e(w["hireDate"])})</span>'
    return f'<span class="badge {e(w["emplStatus"])}">{e(w["emplStatusDescr"])}</span>'


def _select(name, options, selected=None, blank=True, attrs=""):
    opts = ('<option value=""></option>' if blank else "") + "".join(
        f'<option value="{e(v)}" {"selected" if str(v) == str(selected) else ""}>{e(v)} - {e(l)}</option>' for v, l in options)
    return f'<select name="{name}" {attrs}>{opts}</select>'


def _depts(conn):
    return [(r["DEPTID"], r["DESCR"]) for r in db.rows(conn, "SELECT DEPTID, DESCR FROM PS_DEPT_TBL ORDER BY DEPTID")]


def _jobs(conn):
    return [(r["JOBCODE"], r["DESCR"]) for r in db.rows(conn, "SELECT JOBCODE, DESCR FROM PS_JOBCODE_TBL ORDER BY DESCR")]


def _locs(conn):
    return [(r["LOCATION"], r["DESCR"]) for r in db.rows(conn, "SELECT LOCATION, DESCR FROM PS_LOCATION_TBL ORDER BY LOCATION")]


def _people(conn, exclude=None):
    return [(r["EMPLID"], r["NAME_DISPLAY"]) for r in db.rows(conn, "SELECT EMPLID, NAME_DISPLAY FROM PS_PERSONAL_DATA ORDER BY NAME_DISPLAY") if r["EMPLID"] != exclude]


def fld(label, value, descr=None, req=False):
    d = f'<span class="ds">{e(descr)}</span>' if descr else ""
    return f'<div class="lb{" req" if req else ""}">{label}</div><div class="vl"><span class="cd">{e(value if value not in (None, "") else "")}</span>{d}</div>'


def toolbar(buttons, right=None):
    return f'<div class="toolbar">{"".join(buttons)}<span class="sep"></span>{"".join(right or [])}</div>'


BTN_STD = ['<a class="btn" href="/employees">Return to Search</a>', '<a class="btn" href="#">Notify</a>']
BTN_MODES = ['<span class="muted">&nbsp;</span>']


# ---------------------------------------------------------------------- Fluid homepage
@route("GET", r"/")
def home(req, conn):
    workers, _ = hr.list_workers(conn, limit=10000)
    c = {"A": 0, "L": 0, "T": 0, "PRE": 0}
    for w in workers:
        if w["preHire"]:
            c["PRE"] += 1
        elif w["emplStatus"] == "A":
            c["A"] += 1
        elif w["emplStatus"] in ("L", "P", "S"):
            c["L"] += 1
        else:
            c["T"] += 1
    ev = {r["STATUS"]: r["n"] for r in db.rows(conn, "SELECT STATUS, COUNT(*) n FROM PS_OKTA_EVENTS GROUP BY STATUS")}
    users = conn.execute("SELECT COUNT(*) FROM PSOPRDEFN").fetchone()[0]
    recent = db.rows(conn, "SELECT * FROM PS_AUDIT_LOG ORDER BY AUDIT_ID DESC LIMIT 5")
    rec = "".join(f'<div><b>{e(r["ACTION"])}</b> {e(r["EMPLID"])} <span class="muted">{e(r["DETAIL"])[:34]}</span></div>' for r in recent) or '<div class="muted">No activity yet</div>'
    tiles = f"""
<a class="tile" href="/employees"><div class="t">Job Data</div><div class="sub">Workforce Administration</div><div class="big">{c['A']}</div><div class="sub">Active employees &middot; {c['L']} on leave &middot; {c['T']} terminated</div></a>
<a class="tile" href="/hire"><div class="t">Add Employment Instance</div><div class="sub">Hire a person</div><div class="rows"><b>{c['PRE']}</b> pre-hires (future dated)<br><b>{len(workers)}</b> people total<br><b>10</b> departments</div></a>
<a class="tile" href="/journey"><div class="t">Lifecycle Journey</div><div class="sub">Joiner &middot; Mover &middot; Leaver</div><div class="rows">HIR &rarr; PRO &rarr; XFR &rarr; DTA<br>LOA &rarr; RFL &rarr; TER &rarr; REH<br><b>1</b> click</div></a>
<a class="tile" href="/okta"><div class="t">Okta Integration</div><div class="sub">Integration Broker outbox &middot; mode {e(config.okta_mode)}</div><div class="rows"><b>{ev.get('PENDING', 0)}</b> pending<br><b>{ev.get('SCHEDULED', 0)}</b> scheduled<br><b>{ev.get('SENT', 0) + ev.get('DRYRUN', 0)}</b> sent / dry-run<br><b>{ev.get('FAILED', 0)}</b> failed</div></a>
<a class="tile" href="/users"><div class="t">User Profiles</div><div class="sub">PeopleTools &gt; Security</div><div class="big">{users}</div><div class="sub">provisioned by Okta over SCIM</div></a>
<a class="tile" href="/setup"><div class="t">Foundation Tables</div><div class="sub">Set Up HCM</div><div class="rows">Departments &middot; Job Codes<br>Locations &middot; Company<br>Reset demo data</div></a>
<a class="tile" href="/api-docs"><div class="t">Integration Broker</div><div class="sub">REST / IB / SCIM reference</div><div class="rows">/api/v1/workers<br>/PSIGW/RESTListeningConnector<br>/scim/v2</div></a>
<a class="tile" href="/okta"><div class="t">Recent Activity</div><div class="sub">Audit log</div><div class="rows">{rec}</div></a>"""
    return layout(req, "Homepage", f'<div class="tiles">{tiles}</div>', fluid=True, header_title="Workforce Administrator")


# ---------------------------------------------------------------------- Job Data: search page
@route("GET", r"/employees")
def employees(req, conn):
    q = req.query
    emplid, name, last, status, deptid = q.get("emplid", ""), q.get("name", ""), q.get("last", ""), q.get("status", ""), q.get("deptid", "")
    searched = any(k in q for k in ("emplid", "name", "last", "status", "deptid", "all"))
    workers, total = hr.list_workers(conn, status=status or None, q=(name or last or emplid) or None, deptid=deptid or None, limit=1000)
    if emplid:
        workers = [w for w in workers if w["emplid"].startswith(emplid)]
    if last:
        workers = [w for w in workers if w["lastName"].lower().startswith(last.lower())]
    rows = "".join(f"""<tr><td><a href="/employees/{e(w['emplid'])}">{e(w['emplid'])}</a></td><td>0</td><td><a href="/employees/{e(w['emplid'])}">{e(w['displayName'])}</a></td>
<td>{e(w['lastName'])}</td><td>{status_badge(w)}</td><td>{e(w['job']['deptid'] if w['job'] else '')} {e(w['job']['deptDescr'] if w['job'] else '')}</td>
<td>{e(w['job']['jobTitle'] if w['job'] else '')}</td><td>{e(w['job']['location'] if w['job'] else '')}</td><td>{e(w['workEmail'])}</td></tr>""" for w in workers)
    results = f"""<div class="gridhdr">Search Results <span class="rownav">View All &nbsp;|&nbsp; First &#9664; 1-{len(workers)} of {len(workers)} &#9654; Last</span></div>
<table class="grid"><tr><th>Empl ID</th><th>Empl Record</th><th>Name</th><th>Last Name</th><th>Payroll Status</th><th>Department</th><th>Job Title</th><th>Location</th><th>Business Email</th></tr>{rows}</table>""" if searched else ""
    body = f"""<div class="pgtitle">Job Data</div>
<div class="pgbody"><p style="margin:0 0 10px">Enter any information you have and click Search. Leave fields blank for a list of all values.</p>
<div class="grp"><div class="gh">Find an Existing Value</div><div class="gb"><form method="get">
<div class="fl">
<div class="lb">Empl ID:</div><div class="vl"><select name="op" style="width:110px;min-width:110px"><option>begins with</option><option>=</option></select> <input type="text" name="emplid" value="{e(emplid)}" style="width:200px">{LOOKUP}</div>
<div class="lb">Name:</div><div class="vl"><select style="width:110px"><option>contains</option></select> <input type="text" name="name" value="{e(name)}"></div>
<div class="lb">Last Name:</div><div class="vl"><select style="width:110px"><option>begins with</option></select> <input type="text" name="last" value="{e(last)}"></div>
<div class="lb">Payroll Status:</div><div class="vl"><select style="width:110px"><option>=</option></select> {_select('status', list(hr.STATUS_LABELS.items()), status)}</div>
<div class="lb">Department:</div><div class="vl"><select style="width:110px"><option>=</option></select> {_select('deptid', _depts(conn), deptid)}{LOOKUP}</div>
<div class="lb"></div><div class="vl"><label style="display:inline-flex;align-items:center;margin:0 14px 0 0"><input type="checkbox" name="hist" checked>Include History</label><label style="display:inline-flex;align-items:center;margin:0 14px 0 0"><input type="checkbox">Correct History</label><label style="display:inline-flex;align-items:center;margin:0"><input type="checkbox">Case Sensitive</label></div>
</div><div style="margin-top:10px"><button class="primary" name="all" value="1">Search</button> <a class="btn" href="/employees">Clear</a> <a class="btn" href="/employees">Basic Search</a> <a href="#" style="margin-left:8px">Save Search Criteria</a></div></form></div></div>
{results}
<p class="muted" style="margin-top:10px">Find an Existing Value &nbsp;|&nbsp; <a href="/hire">Add a New Value</a></p></div>"""
    return layout(req, "Job Data", body, 'Workforce Administration &gt; Job Information &gt; <b>Job Data</b>')


# ---------------------------------------------------------------------- Job Data: transaction page
INSERT_JS = """
<script>
var REASONS = %s;
var FIELDS = {XFR:['deptid','location','supervisorId'], PRO:['jobcode','compRate','deptid','supervisorId'], DEM:['jobcode','compRate'],
              PAY:['compRate'], DTA:['supervisorId'], POS:['positionNbr'], LOA:[], PLA:[], RFL:[], SUS:[], TER:['lastDateWorked'], RET:['lastDateWorked'],
              REH:['deptid','jobcode','location','supervisorId','compRate']};
function onAction(){
  var a=document.getElementById('action').value, r=document.getElementById('reason'), rs=REASONS[a]||{};
  r.innerHTML=''; for (var k in rs){var o=document.createElement('option');o.value=k;o.text=k+' - '+rs[k];r.add(o);}
  var show=FIELDS[a]||[]; var els=document.querySelectorAll('[data-f]');
  for (var i=0;i<els.length;i++){ els[i].classList.toggle('hide', show.indexOf(els[i].getAttribute('data-f'))<0); }
}
document.addEventListener('DOMContentLoaded', onAction);
</script>"""

TABS = [("work", "Work Location"), ("job", "Job Information"), ("comp", "Compensation"), ("okta", "Okta Provisioning")]


@route("GET", r"/employees/(?P<emplid>[^/]+)")
def employee(req, conn, emplid):
    w = hr.get_worker(conn, emplid)
    if not w:
        return layout(req, "Job Data", f'<div class="pgtitle">Job Data</div><div class="pgbody">No matching values were found for Empl ID {e(emplid)}.</div>')
    tab = req.query.get("tab", "work")
    insert = req.query.get("insert") == "1"
    hist = hr.job_history(conn, emplid)            # newest first
    n = len(hist)
    try:
        idx = max(1, min(n, int(req.query.get("row", "1"))))
    except ValueError:
        idx = 1
    r = hist[idx - 1]
    latest = hist[0]
    tdy = date.today().isoformat()
    tabs = "".join(f'<a class="{"on" if t == tab else ""}" href="/employees/{e(emplid)}?tab={t}&row={idx}">{lbl}</a>' for t, lbl in TABS)
    prev_link = f'<a href="?tab={tab}&row={idx - 1}">&#9664;</a>' if idx > 1 else '<span style="color:#aaa">&#9664;</span>'
    next_link = f'<a href="?tab={tab}&row={idx + 1}">&#9654;</a>' if idx < n else '<span style="color:#aaa">&#9654;</span>'
    plus = f'<a class="pm" href="?tab=work&insert=1" title="Insert a new row">+</a>' if not insert else '<span class="pm dis">+</span>'
    rownav = f'<span class="rownav">Find &nbsp;|&nbsp; <a href="?tab={tab}&row={idx}#hist">View All</a> &nbsp; First {prev_link} {idx} of {n} {next_link} Last &nbsp; {plus} <span class="pm dis">&minus;</span></span>'
    cj = hr.current_job(conn, emplid)
    cur = bool(cj and cj["EFFDT"] == r["EFFDT"] and cj["EFFSEQ"] == r["EFFSEQ"])
    top = f"""<div class="fl two" style="max-width:100%">{fld('Effective Date:', r['EFFDT'], ('future dated' if r['EFFDT'] > tdy else 'current row' if cur else ''))}{fld('Effective Sequence:', r['EFFSEQ'])}
{fld('Action:', r['ACTION'], hr.ACTIONS.get(r['ACTION']))}{fld('Reason:', r['ACTION_REASON'], hr.REASONS.get(r['ACTION'], {}).get(r['ACTION_REASON']))}
{fld('Payroll Status:', hr.STATUS_LABELS.get(r['EMPL_STATUS'], r['EMPL_STATUS']))}{fld('HR Status:', 'Active' if r['HR_STATUS'] == 'A' else 'Inactive')}</div>"""
    sup = db.row(conn, "SELECT NAME_DISPLAY FROM PS_PERSONAL_DATA WHERE EMPLID=?", (r["SUPERVISOR_ID"],)) if r["SUPERVISOR_ID"] else None

    if insert:
        content = insert_form(conn, emplid, w, latest, tdy)
    elif tab == "work":
        content = f"""<div class="grp"><div class="gh">Work Location Details {rownav}</div><div class="gb">{top}<hr style="border:0;border-top:1px solid #ddd">
<div class="fl two" style="max-width:100%">{fld('Position Number:', r['POSITION_NBR'] or '')}{fld('Regulatory Region:', 'USA', 'United States')}
{fld('Company:', r['COMPANY'], 'Global Business Institute')}{fld('Business Unit:', r['BUSINESS_UNIT'], 'US Business Unit')}
{fld('Department:', r['DEPTID'], r['DEPT_DESCR'])}{fld('Department Entry Date:', r['EFFDT'] if r['ACTION'] in ('HIR','REH','XFR') else '')}
{fld('Location:', r['LOCATION'], r['LOC_DESCR'])}{fld('Establishment ID:', 'GBI', 'Global Business Institute')}
{fld('Last Start Date:', w['hireDate'])}{fld('Termination Date:', w['terminationDate'] or '')}
{fld('Expected Job End Date:', '')}{fld('Last Date Worked:', w['lastDateWorked'] or '')}</div></div></div>
{personal_box(w)}"""
    elif tab == "job":
        jc = hr.jobcode(conn, r["JOBCODE"]) or {}
        content = f"""<div class="grp"><div class="gh">Job Information Details {rownav}</div><div class="gb">{top}<hr style="border:0;border-top:1px solid #ddd">
<div class="fl two" style="max-width:100%">{fld('Job Code:', r['JOBCODE'], r['JOB_DESCR'])}{fld('Entry Date:', r['EFFDT'] if r['ACTION'] in ('HIR','REH','PRO','DEM') else '')}
{fld('Supervisor Level:', jc.get('MANAGER_LEVEL') or '')}{fld('Job Family / Grade:', (jc.get('JOB_FAMILY') or '') + ' / ' + (jc.get('GRADE') or ''))}
{fld('Reports To:', r['REPORTS_TO'] or '')}{fld('Supervisor ID:', r['SUPERVISOR_ID'], sup['NAME_DISPLAY'] if sup else '')}
{fld('Regular/Temporary:', 'Regular' if r['REG_TEMP'] == 'R' else 'Temporary')}{fld('Full/Part:', 'Full-Time' if r['FULL_PART_TIME'] == 'F' else 'Part-Time')}
{fld('Empl Class:', r['EMPL_CLASS'], hr.EMPL_CLASS.get(r['EMPL_CLASS']))}{fld('Officer Code:', 'None')}
{fld('Regular Shift:', 'Not Applicable')}{fld('Shift Rate / Factor:', '')}</div>
<div class="grp" style="margin-top:12px"><div class="gh">Standard Hours</div><div class="gb"><div class="fl two" style="max-width:100%">{fld('Standard Hours:', r['STD_HOURS'])}{fld('Work Period:', 'W', 'Weekly')}{fld('FTE:', '%.2f' % (float(r['STD_HOURS'] or 0) / 40))}{fld('Adds to FTE Actual Count?', 'Yes' if r['EMPL_CLASS'] == 'E' else 'No')}</div></div></div></div></div>"""
    elif tab == "comp":
        content = f"""<div class="grp"><div class="gh">Compensation Details {rownav}</div><div class="gb">{top}<hr style="border:0;border-top:1px solid #ddd">
<div class="fl two" style="max-width:100%">{fld('Compensation Rate:', '{:,.2f}'.format(float(r['COMPRATE'] or 0)), r['CURRENCY_CD'])}{fld('Frequency:', r['COMP_FREQUENCY'], 'Annual' if r['COMP_FREQUENCY'] == 'A' else 'Hourly')}
{fld('Pay Group:', r['PAYGROUP'], 'KU1 Salaried Semi-Monthly')}{fld('Employee Type:', 'S', 'Salaried')}
{fld('Compensation Frequency:', r['COMP_FREQUENCY'])}{fld('Rate Code:', 'NAANNL', 'Annual Salary')}</div>
<div class="gridhdr" style="margin-top:12px">Pay Components</div><table class="grid"><tr><th>Rate Code</th><th>Seq</th><th>Comp Rate</th><th>Currency</th><th>Frequency</th><th>Percent</th></tr>
<tr><td>NAANNL</td><td>0</td><td>{'{:,.2f}'.format(float(r['COMPRATE'] or 0))}</td><td>{e(r['CURRENCY_CD'])}</td><td>{e(r['COMP_FREQUENCY'])}</td><td></td></tr></table></div></div>"""
    else:
        c = okta.OktaClient()
        events = db.rows(conn, "SELECT * FROM PS_OKTA_EVENTS WHERE EMPLID=? ORDER BY EVENT_ID DESC LIMIT 25", (emplid,))
        erows = "".join(f'<tr><td><a href="/okta/events/{x["EVENT_ID"]}">{x["EVENT_ID"]}</a></td><td>{e(x["CREATED_DTTM"])}</td><td>{e(x["ACTION"])}</td><td>{e(x["EVENT_TYPE"])}</td><td>{e(x["SUMMARY"])}</td><td><span class="badge {e(x["STATUS"])}">{e(x["STATUS"])}</span></td></tr>' for x in events)
        users = db.rows(conn, "SELECT * FROM PSOPRDEFN WHERE EMPLID=?", (emplid,))
        urows = "".join(f'<tr><td>{e(u["OPRID"])}</td><td>{e(u["EMAILID"])}</td><td>{"Locked" if u["ACCTLOCK"] else "Active"}</td><td>{e(u["EXTERNAL_ID"])}</td><td>{e(u["LASTUPDDTTM"])}</td></tr>' for u in users)
        content = f"""<div class="grp"><div class="gh">Okta Provisioning {rownav}</div><div class="gb">
<div class="fl" style="max-width:100%">{fld('Desired Okta status:', c.desired_status(w))}{fld('Okta login:', w['workEmail'])}{fld('employeeNumber:', emplid)}</div>
<details open><summary>Okta profile mapping (as of today)</summary><pre>{e(json.dumps(c.profile_from_worker(w, include_custom=True), indent=1))}</pre>
<a class="muted" href="/api/v1/okta/preview/{e(emplid)}">Full API-call plan (JSON)</a></details>
<div class="gridhdr" style="margin-top:10px">Integration Broker outbox for this person</div>
<table class="grid"><tr><th>#</th><th>Created</th><th>Action</th><th>Event type</th><th>Summary</th><th>Status</th></tr>{erows or '<tr><td colspan="6" class="muted">No events yet</td></tr>'}</table>
<div class="gridhdr" style="margin-top:10px">{e(config.brand)} User Profile (PSOPRDEFN) - provisioned by Okta over SCIM</div>
<table class="grid"><tr><th>User ID</th><th>Email</th><th>Account</th><th>Okta ID</th><th>Updated</th></tr>{urows or '<tr><td colspan="5" class="muted">No user profile yet</td></tr>'}</table></div></div>"""

    hrows = "".join(f"""<tr class="{'cur' if i + 1 == idx else ''}"><td><a href="?tab={tab}&row={i + 1}">{e(x['EFFDT'])}</a></td><td>{x['EFFSEQ']}</td><td>{e(x['ACTION'])} {e(hr.ACTIONS.get(x['ACTION'], ''))}</td>
<td>{e(x['ACTION_REASON'])} {e(hr.REASONS.get(x['ACTION'], {}).get(x['ACTION_REASON'], ''))}</td><td>{e(hr.STATUS_LABELS.get(x['EMPL_STATUS']))}</td><td>{e(x['DEPTID'])} {e(x['DEPT_DESCR'])}</td>
<td>{e(x['JOBCODE'])} {e(x['JOB_DESCR'])}</td><td>{e(x['LOCATION'])}</td><td>{e(x['SUPERVISOR_ID'])}</td><td>{'{:,.0f}'.format(float(x['COMPRATE'] or 0))}</td><td class="muted">{e(x['LASTUPDDTTM'])} {e(x['LASTUPDOPRID'])}</td></tr>""" for i, x in enumerate(hist))
    history = f"""<div class="gridhdr" id="hist">Job History &nbsp;<span class="muted">(PS_JOB, effective-dated, Include History)</span><span class="rownav">First 1-{n} of {n} Last</span></div>
<table class="grid"><tr><th>Effective Date</th><th>Seq</th><th>Action</th><th>Reason</th><th>Payroll Status</th><th>Department</th><th>Job Code</th><th>Location</th><th>Supervisor</th><th>Comp Rate</th><th>Last Updated</th></tr>{hrows}</table>"""
    modes = ['<a class="btn" href="/employees/{0}?tab={1}&row={2}">Refresh</a>'.format(e(emplid), tab, idx), '<a class="btn" href="/hire">Add</a>',
             '<a class="btn" href="?tab=work&row=1">Update/Display</a>', '<a class="btn" style="font-weight:700" href="?tab=work&row=1">Include History</a>', '<a class="btn" href="#">Correct History</a>']
    save = ['<button class="primary" form="jobform">Save</button>'] if insert else ['<a class="btn primary" href="?tab=work&insert=1">Save</a>']
    body = f"""<div class="pstabs" style="margin-top:8px">{tabs}</div>
<div class="hdrrow"><span class="nm">{e(w['displayName'])}</span><span><b>Empl ID</b> {e(emplid)}</span><span><b>Empl Record</b> 0</span><span>{status_badge(w)}</span>
<span style="margin-left:auto"><a href="/employees/{e(emplid)}/personal">Modify a Person (personal data)</a></span></div>
<div class="pgbody">{content}{history if not insert else ''}</div>
{toolbar(save + BTN_STD, modes)}
<div class="muted" style="padding:6px 16px">Work Location | Job Information | Compensation | Okta Provisioning</div>{INSERT_JS % json.dumps(hr.REASONS) if insert else ''}"""
    return layout(req, "Job Data", body, f'Workforce Administration &gt; Job Information &gt; <a href="/employees">Job Data</a> &gt; <b>{e(w["displayName"])}</b>')


def personal_box(w):
    return f"""<div class="grp"><div class="gh">Person Summary</div><div class="gb"><div class="fl two" style="max-width:100%">
{fld('Name:', w['displayName'])}{fld('Preferred Name:', w['preferredFirstName'] or '')}
{fld('Business Email:', w['workEmail'])}{fld('Mobile Phone:', w['mobilePhone'] or '')}
{fld('Original Hire Date:', w['originalHireDate'])}{fld('Rehire Date:', w['rehireDate'] or '')}
{fld('Last Modified:', w['lastModified'])}{fld('Empl ID:', w['emplid'])}</div></div></div>"""


def insert_form(conn, emplid, w, latest, tdy):
    st = latest["EMPL_STATUS"]
    if st in ("T", "R"):
        acts = ["REH"]
    elif st in ("L", "P", "S"):
        acts = ["RFL", "TER"]
    else:
        acts = ["XFR", "PRO", "DEM", "PAY", "DTA", "POS", "LOA", "PLA", "SUS", "TER", "RET"]
    act_opts = "".join(f'<option value="{a}">{a} - {hr.ACTIONS[a]}</option>' for a in acts)
    min_dt = latest["EFFDT"]
    default_dt = max(tdy, min_dt)
    return f"""<div class="note">Inserting a new effective-dated row. The previous row ({e(latest['EFFDT'])} {e(latest['ACTION'])}) is copied forward; change only what differs, then click <b>Save</b>.
Effective date must be on or after {e(min_dt)}. Saving queues an Okta event automatically.</div>
<form id="jobform" method="post" action="/employees/{e(emplid)}/job">
<div class="grp"><div class="gh">Work Location Details <span class="rownav">First &#9664; 1 of {len(hr.job_history(conn, emplid)) + 1} &#9654; Last &nbsp; <span class="pm dis">+</span> <a class="pm" href="/employees/{e(emplid)}" title="Cancel">&minus;</a></span></div><div class="gb">
<div class="fl two" style="max-width:100%">
<div class="lb req">Effective Date:</div><div class="vl"><input type="date" name="effdt" value="{default_dt}" min="{min_dt}" required></div>
<div class="lb">Effective Sequence:</div><div class="vl">auto</div>
<div class="lb req">Action:</div><div class="vl"><select name="action" id="action" onchange="onAction()">{act_opts}</select>{LOOKUP}</div>
<div class="lb req">Reason:</div><div class="vl"><select name="reason" id="reason"></select>{LOOKUP}</div>
<div class="lb">Payroll Status:</div><div class="vl">{e(hr.STATUS_LABELS.get(st))} &rarr; <span class="muted">derived from Action on save</span></div>
<div class="lb">HR Status:</div><div class="vl">{'Active' if latest['HR_STATUS'] == 'A' else 'Inactive'}</div>
</div><hr style="border:0;border-top:1px solid #ddd">
<div class="fl two" style="max-width:100%">
<div class="lb" data-f="positionNbr">Position Number:</div><div class="vl" data-f="positionNbr"><input type="text" name="positionNbr" value="{e(latest['POSITION_NBR'])}" style="width:110px">{LOOKUP}</div>
<div class="lb">Company:</div><div class="vl">{e(latest['COMPANY'])} <span class="ds">Global Business Institute</span></div>
<div class="lb">Business Unit:</div><div class="vl">{e(latest['BUSINESS_UNIT'])}</div>
<div class="lb" data-f="deptid">Department:</div><div class="vl" data-f="deptid">{_select('deptid', _depts(conn), latest['DEPTID'])}{LOOKUP}</div>
<div class="lb" data-f="location">Location:</div><div class="vl" data-f="location">{_select('location', _locs(conn), latest['LOCATION'])}{LOOKUP}</div>
<div class="lb" data-f="jobcode">Job Code:</div><div class="vl" data-f="jobcode">{_select('jobcode', _jobs(conn), latest['JOBCODE'])}{LOOKUP}</div>
<div class="lb" data-f="supervisorId">Supervisor ID:</div><div class="vl" data-f="supervisorId">{_select('supervisorId', _people(conn, emplid), latest['SUPERVISOR_ID'])}{LOOKUP}</div>
<div class="lb" data-f="compRate">Compensation Rate:</div><div class="vl" data-f="compRate"><input type="number" name="compRate" step="0.01" value="{e(latest['COMPRATE'])}" style="width:130px"> {e(latest['CURRENCY_CD'])}</div>
<div class="lb" data-f="lastDateWorked">Last Date Worked:</div><div class="vl" data-f="lastDateWorked"><input type="date" name="lastDateWorked"> <span class="muted">defaults to the day before the effective date</span></div>
</div></div></div></form>"""


@route("POST", r"/employees/(?P<emplid>[^/]+)/job")
def employee_job_post(req, conn, emplid):
    data = {k: v for k, v in req.form().items() if v != ""}
    action = data.get("action", "")
    latest = hr.latest_job(conn, emplid)
    # Only pass fields that changed, so untouched values are carried forward from the previous row.
    if latest:
        for form_key, col in (("deptid", "DEPTID"), ("location", "LOCATION"), ("jobcode", "JOBCODE"), ("supervisorId", "SUPERVISOR_ID"), ("positionNbr", "POSITION_NBR")):
            if data.get(form_key) == latest[col]:
                data.pop(form_key, None)
        if "compRate" in data and float(data["compRate"]) == float(latest["COMPRATE"] or 0):
            data.pop("compRate")
    if action == "XFR" and not any(k in data for k in ("deptid", "location", "supervisorId", "jobcode")):
        return redirect(f"/employees/{emplid}?tab=work&insert=1", err="Transfer (XFR) requires a change to Department, Location, Supervisor or Job Code.")
    if action in ("PRO", "DEM") and "jobcode" not in data:
        data["jobcode"] = latest["JOBCODE"]
    if action == "DTA" and "supervisorId" not in data:
        return redirect(f"/employees/{emplid}?tab=work&insert=1", err="Data Change (DTA) on Job Data requires a new Supervisor ID. Use Modify a Person for name or email changes.")
    if action == "PAY" and "compRate" not in data:
        return redirect(f"/employees/{emplid}?tab=work&insert=1", err="Pay Rate Change (PAY) requires a new Compensation Rate.")
    try:
        w = hr.generic_action(conn, emplid, data, oprid=_oprid(req), source="UI")
    except hr.HRError as ex:
        return redirect(f"/employees/{emplid}?tab=work&insert=1", err=str(ex))
    if config.okta_sync_interval <= 0:
        okta.sync_pending(conn)
    return redirect(f"/employees/{emplid}?tab=work&row=1", msg=f"Saved. New row {w['job']['effdt'] if w['job'] else ''} {hr.ACTIONS.get(action, action)}; payroll status {w['emplStatusDescr']}. Okta event queued.")


# ---------------------------------------------------------------------- Modify a Person (personal data)
@route("GET", r"/employees/(?P<emplid>[^/]+)/personal")
def personal_page(req, conn, emplid):
    w = hr.get_worker(conn, emplid)
    if not w:
        return redirect("/employees", err=f"Empl ID {emplid} not found")
    body = f"""<div class="pstabs" style="margin-top:8px"><a class="on" href="#">Biographical Details</a><a href="#contact">Contact Information</a><a href="#">Regional</a><a href="#">Organizational Relationships</a></div>
<div class="hdrrow"><span class="nm">{e(w['displayName'])}</span><span><b>Person ID</b> {e(emplid)}</span><span>{status_badge(w)}</span><span style="margin-left:auto"><a href="/employees/{e(emplid)}">Job Data</a></span></div>
<form method="post" id="pform"><div class="pgbody">
<div class="grp"><div class="gh">Name <span class="rownav">Effective Date {date.today().isoformat()} &nbsp; Format Type English &nbsp; <span class="pm">+</span> <span class="pm dis">&minus;</span></span></div><div class="gb"><div class="fl two" style="max-width:100%">
<div class="lb req">First Name:</div><div class="vl"><input type="text" name="firstName" value="{e(w['firstName'])}" required></div>
<div class="lb">Middle Name:</div><div class="vl"><input type="text" name="middleName" value="{e(w['middleName'])}"></div>
<div class="lb req">Last Name:</div><div class="vl"><input type="text" name="lastName" value="{e(w['lastName'])}" required></div>
<div class="lb">Preferred First Name:</div><div class="vl"><input type="text" name="preferredFirstName" value="{e(w['preferredFirstName'])}"></div>
<div class="lb">Display Name:</div><div class="vl">{e(w['displayName'])}</div><div class="lb">Formal Name:</div><div class="vl">{e(w['lastName'])}, {e(w['firstName'])}</div></div></div></div>
<div class="grp"><div class="gh">Biographic Information</div><div class="gb"><div class="fl two" style="max-width:100%">{fld('Date of Birth:', w['birthDate'] or '')}{fld('Gender:', {'M': 'Male', 'F': 'Female'}.get(w['sex'], 'Unknown'))}{fld('Highest Education Level:', 'G', 'Bachelor')}{fld('Country of Birth:', w['country'])}</div></div></div>
<div class="grp" id="contact"><div class="gh">Contact Information</div><div class="gb">
<div class="gridhdr">Email Addresses</div><table class="grid"><tr><th>Email Type</th><th>Email Address</th><th>Preferred</th></tr>
<tr><td>Business</td><td><input type="text" name="workEmail" value="{e(w['workEmail'])}" style="width:280px"></td><td>&#10003;</td></tr>
<tr><td>Home</td><td><input type="text" name="homeEmail" value="{e(w['homeEmail'])}" style="width:280px"></td><td></td></tr></table>
<div class="gridhdr" style="margin-top:10px">Phone Information</div><table class="grid"><tr><th>Phone Type</th><th>Telephone</th><th>Preferred</th></tr>
<tr><td>Mobile</td><td><input type="text" name="mobilePhone" value="{e(w['mobilePhone'])}"></td><td>&#10003;</td></tr>
<tr><td>Business</td><td><input type="text" name="workPhone" value="{e(w['workPhone'])}"></td><td></td></tr></table></div></div>
</div></form>
{toolbar(['<button class="primary" form="pform">Save</button>', '<a class="btn" href="/employees">Return to Search</a>', '<a class="btn" href="#">Notify</a>'], ['<a class="btn" href="/employees/' + e(emplid) + '/personal">Refresh</a>'])}
<div class="muted" style="padding:6px 16px">Saving a name or email change writes a DTA (Data Change) event to the Okta outbox.</div>"""
    return layout(req, "Modify a Person", body, f'Workforce Administration &gt; Personal Information &gt; <a href="/employees">Modify a Person</a> &gt; <b>{e(w["displayName"])}</b>')


@route("POST", r"/employees/(?P<emplid>[^/]+)/personal")
def personal_post(req, conn, emplid):
    data = req.form()
    try:
        hr.update_personal(conn, emplid, data, oprid=_oprid(req), source="UI")
    except hr.HRError as ex:
        return redirect(f"/employees/{emplid}/personal", err=str(ex))
    if config.okta_sync_interval <= 0:
        okta.sync_pending(conn)
    return redirect(f"/employees/{emplid}/personal", msg="Saved. Personal data updated; Okta event queued if anything changed.")


# legacy route kept for the API-docs examples and old bookmarks
@route("POST", r"/employees/(?P<emplid>[^/]+)/action")
def employee_action(req, conn, emplid):
    return employee_job_post(req, conn, emplid)


# ---------------------------------------------------------------------- Add Employment Instance (hire)
@route("GET", r"/hire")
def hire_form(req, conn):
    tdy = date.today().isoformat()
    body = f"""<div class="pstabs" style="margin-top:8px"><a class="on" href="#">Biographical Details</a><a href="#job">Work Location</a><a href="#job">Job Information</a><a href="#job">Compensation</a></div>
<div class="hdrrow"><span class="nm">Add Employment Instance</span><span><b>Empl ID</b> NEW</span><span><b>Empl Record</b> 0</span></div>
<form method="post" id="hform"><div class="pgbody">
<div class="grp"><div class="gh">Name</div><div class="gb"><div class="fl two" style="max-width:100%">
<div class="lb req">First Name:</div><div class="vl"><input type="text" name="firstName" required></div><div class="lb">Middle Name:</div><div class="vl"><input type="text" name="middleName"></div>
<div class="lb req">Last Name:</div><div class="vl"><input type="text" name="lastName" required></div><div class="lb">Preferred First Name:</div><div class="vl"><input type="text" name="preferredFirstName"></div>
<div class="lb">Business Email:</div><div class="vl"><input type="text" name="workEmail" placeholder="auto: first.last@{e(config.email_domain)}" style="width:260px"></div><div class="lb">Mobile Phone:</div><div class="vl"><input type="text" name="mobilePhone"></div>
<div class="lb">Date of Birth:</div><div class="vl"><input type="date" name="birthDate"></div><div class="lb">Gender:</div><div class="vl"><select name="sex"><option value="U">Unknown</option><option value="F">Female</option><option value="M">Male</option></select></div></div></div></div>
<div class="grp" id="job"><div class="gh">Work Location <span class="rownav">First &#9664; 1 of 1 &#9654; Last</span></div><div class="gb"><div class="fl two" style="max-width:100%">
<div class="lb req">Effective Date:</div><div class="vl"><input type="date" name="hireDate" value="{tdy}" required> <span class="muted">future date = pre-hire (Okta user STAGED)</span></div>
<div class="lb">Action / Reason:</div><div class="vl"><span class="cd">HIR - Hire</span>{_select('reason', list(hr.REASONS['HIR'].items()), 'NEW', False)}</div>
<div class="lb">Company:</div><div class="vl">GBI <span class="ds">Global Business Institute</span></div><div class="lb">Business Unit:</div><div class="vl">US001</div>
<div class="lb req">Department:</div><div class="vl">{_select('deptid', _depts(conn))}{LOOKUP}</div><div class="lb">Location:</div><div class="vl">{_select('location', _locs(conn))}{LOOKUP} <span class="muted">defaults to department location</span></div>
<div class="lb req">Job Code:</div><div class="vl">{_select('jobcode', _jobs(conn))}{LOOKUP}</div><div class="lb">Supervisor ID:</div><div class="vl">{_select('supervisorId', _people(conn))}{LOOKUP}</div>
<div class="lb">Empl Class:</div><div class="vl">{_select('emplClass', list(hr.EMPL_CLASS.items()), 'E', False)}</div><div class="lb">Regular/Temporary:</div><div class="vl"><select name="regTemp"><option value="R">Regular</option><option value="T">Temporary</option></select></div>
<div class="lb">Full/Part:</div><div class="vl"><select name="fullPartTime"><option value="F">Full-Time</option><option value="P">Part-Time</option></select></div>
<div class="lb">Compensation Rate:</div><div class="vl"><input type="number" name="compRate" value="100000" style="width:130px"> USD <span class="muted">Annual</span></div></div></div></div>
</div></form>
{toolbar(['<button class="primary" form="hform">Save</button>', '<a class="btn" href="/employees">Return to Search</a>', '<a class="btn" href="#">Notify</a>'], ['<a class="btn" href="/hire">Add</a>'])}
<div class="muted" style="padding:6px 16px">Saving creates PS_PERSONAL_DATA, PS_EMPLOYMENT and a PS_JOB row with ACTION = HIR, and queues an Okta event.</div>"""
    return layout(req, "Add Employment Instance", body, 'Workforce Administration &gt; Job Information &gt; <b>Add Employment Instance</b>')


@route("POST", r"/hire")
def hire_post(req, conn):
    data = {k: v for k, v in req.form().items() if v != ""}
    w = hr.hire(conn, data, oprid=_oprid(req), source="UI")
    if config.okta_sync_interval <= 0:
        okta.sync_pending(conn)
    return redirect(f"/employees/{w['emplid']}", msg=f"Saved. {w['displayName']} hired as Empl ID {w['emplid']}. Okta event queued.")


# ---------------------------------------------------------------------- journey
@route("GET", r"/journey")
def journey_page(req, conn):
    emplid = req.query.get("emplid")
    result = ""
    if emplid:
        events = db.rows(conn, "SELECT * FROM PS_OKTA_EVENTS WHERE EMPLID=? ORDER BY EVENT_ID", (emplid,))
        hist = list(reversed(hr.job_history(conn, emplid)))
        steps = "".join(f"""<div class="st {e(r['EMPL_STATUS'])}"><b>{e(r['ACTION'])}</b> {e(hr.ACTIONS.get(r['ACTION']))}<br><span class="muted">{e(r['EFFDT'])}</span><br>
{e(r['DEPT_DESCR'])}<br>{e(r['JOB_DESCR'])}<br><span class="badge {e(r['EMPL_STATUS'])}">{e(hr.STATUS_LABELS.get(r['EMPL_STATUS']))}</span></div>""" for r in hist)
        erows = "".join(f'<tr><td><a href="/okta/events/{r["EVENT_ID"]}">{r["EVENT_ID"]}</a></td><td>{e(r["ACTION"])}</td><td>{e(r["EVENT_TYPE"])}</td><td>{e(r["SUMMARY"])}</td><td><span class="badge {e(r["STATUS"])}">{e(r["STATUS"])}</span></td><td class="muted">{e(r["TARGET"] or "")}</td></tr>' for r in events)
        result = f"""<div class="box"><h2>Journey for <a href="/employees/{e(emplid)}">EMPLID {e(emplid)}</a></h2><div class="journey">{steps}</div>
<h2>Okta events generated</h2><table class="grid"><tr><th>#</th><th>Action</th><th>Event</th><th>Summary</th><th>Status</th><th>Target</th></tr>{erows}</table>
<p class="muted">Events are flushed by the background sync every {config.okta_sync_interval}s (mode: {e(config.okta_mode)}). Refresh this page or open <a href="/okta">Okta Integration</a>.</p></div>"""
    body = f"""<div class="pgtitle">Identity Lifecycle Journey (Joiner - Mover - Leaver)</div>
<div class="box"><p>Runs the full journey for a brand-new demo employee in one click, generating one Okta event per stage:</p>
<div class="journey">
<div class="st A"><b>1. HIR</b> Hire<br><span class="muted">Joiner - Okta user created (or STAGED if pre-hire)</span></div>
<div class="st A"><b>2. PRO</b> Promotion<br><span class="muted">Mover - title / grade update</span></div>
<div class="st A"><b>3. XFR</b> Transfer<br><span class="muted">Mover - department, location, manager</span></div>
<div class="st A"><b>4. DTA</b> Name change<br><span class="muted">Mover - profile update</span></div>
<div class="st L"><b>5. LOA</b> Leave<br><span class="muted">Okta user suspended</span></div>
<div class="st A"><b>6. RFL</b> Return<br><span class="muted">Okta user unsuspended</span></div>
<div class="st T"><b>7. TER</b> Termination<br><span class="muted">Leaver - Okta user deactivated</span></div>
<div class="st A"><b>8. REH</b> Rehire<br><span class="muted">Joiner - Okta user reactivated</span></div></div>
<form method="post" action="/journey/run" style="margin-top:12px"><button>Run the journey now</button> &nbsp;<span class="muted">Equivalent: <code>python3 -m peopleschoft demo</code> or <code>POST /api/v1/admin/journey</code></span></form></div>{result}"""
    return layout(req, "Lifecycle Journey", "<div class=\"pgbody\">" + body + "</div>", "<b>Lifecycle Journey</b>", "/journey")


@route("POST", r"/journey/run")
def journey_run(req, conn):
    r = run_journey(conn, oprid=_oprid(req), source="UI")
    okta.sync_pending(conn)
    return redirect(f"/journey?emplid={r['emplid']}", msg=f"Journey completed for {r['name']} (EMPLID {r['emplid']}); {len(r['steps'])} Okta events generated and synced.")


# ---------------------------------------------------------------------- okta
@route("GET", r"/okta")
def okta_page(req, conn):
    o = config.okta_summary()
    counts = {r["STATUS"]: r["n"] for r in db.rows(conn, "SELECT STATUS, COUNT(*) n FROM PS_OKTA_EVENTS GROUP BY STATUS")}
    status = req.query.get("status", "")
    where, params = ("STATUS=?", (status,)) if status else ("1=1", ())
    events = db.rows(conn, f"SELECT * FROM PS_OKTA_EVENTS WHERE {where} ORDER BY EVENT_ID DESC LIMIT 100", params)
    erows = "".join(f"""<tr><td><a href="/okta/events/{r['EVENT_ID']}">{r['EVENT_ID']}</a></td><td>{e(r['CREATED_DTTM'])}</td><td><a href="/employees/{e(r['EMPLID'])}">{e(r['EMPLID'])}</a></td>
<td>{e(r['ACTION'])}</td><td>{e(r['EVENT_TYPE'])}</td><td>{e(r['SUMMARY'])}</td><td><span class="badge {e(r['STATUS'])}">{e(r['STATUS'])}</span> <span class="muted">x{r['ATTEMPTS']}</span></td>
<td class="muted">{e(r['SENT_DTTM'] or '')}</td><td><form class="inline" method="post" action="/okta/events/{r['EVENT_ID']}/retry"><button class="sec">Re-send</button></form></td></tr>""" for r in events)
    modes = {
        "dryrun": "No network. Records the exact Okta requests that would be made. Default.",
        "webhook": "POST each event to OKTA_WEBHOOK_URL (Okta Workflows API Endpoint card, header x-api-client-token = OKTA_WEBHOOK_TOKEN).",
        "users": "Drive the Okta Users API directly with OKTA_API_TOKEN (SSWS): create / update / suspend / deactivate / reactivate.",
        "identity-source": "Okta Anything-as-a-Source: bulk-upsert / bulk-delete via OKTA_IDENTITY_SOURCE_ID import sessions.",
    }
    mrows = "".join(f'<tr><td><b>{m}</b>{" &larr; current" if m == o["mode"] else ""}</td><td>{d}</td></tr>' for m, d in modes.items())
    body = f"""<div class="pgtitle">Okta Integration</div>
<div class="grid2"><div class="box"><h2>Configuration (from environment / .env)</h2><div class="kv">
<div class="k">OKTA_MODE</div><div class="v">{e(o['mode'])}</div><div class="k">OKTA_ORG_URL</div><div class="v">{e(o['orgUrl'])}</div>
<div class="k">OKTA_API_TOKEN</div><div class="v">{'set' if o['apiTokenSet'] else '<span style="color:#c0392b">not set</span>'}</div>
<div class="k">OKTA_IDENTITY_SOURCE_ID</div><div class="v">{e(o['identitySourceId'] or '-')}</div>
<div class="k">OKTA_WEBHOOK_URL</div><div class="v">{e(o['webhookUrl'] or '-')}</div><div class="k">OKTA_WEBHOOK_TOKEN</div><div class="v">{'set' if o['webhookTokenSet'] else '-'}</div>
<div class="k">OKTA_CUSTOM_ATTRS</div><div class="v">{o['customAttrs']} <span class="muted">(send hireDate/terminationDate/etc. - define them on the Okta user schema first)</span></div>
<div class="k">OKTA_SYNC_INTERVAL</div><div class="v">{o['syncIntervalSeconds']}s</div><div class="k">OKTA_PREHIRE_DAYS</div><div class="v">{o['preHireDays']} days before start</div>
<div class="k">OKTA_LOA_ACTION</div><div class="v">{e(o['loaAction'])}</div></div>
<p class="muted">Edit <code>.env</code> and restart to change. Restart-free alternative: export the variables before <code>./start.sh</code>.</p></div>
<div class="box"><h2>Modes</h2><table class="grid">{mrows}</table>
<h2>Outbox</h2><div class="kv"><div class="k">Pending</div><div class="v">{counts.get('PENDING', 0)}</div><div class="k">Sent</div><div class="v">{counts.get('SENT', 0)}</div>
<div class="k">Scheduled (future-dated)</div><div class="v">{counts.get('SCHEDULED', 0)}</div><div class="k">Dry-run</div><div class="v">{counts.get('DRYRUN', 0)}</div><div class="k">Failed</div><div class="v">{counts.get('FAILED', 0)}</div></div>
<div style="margin-top:10px"><form class="inline" method="post" action="/okta/sync"><button>Sync to Okta now</button></form>
<form class="inline" method="post" action="/okta/export"><button class="sec">Queue full export (all workers)</button></form>
<form class="inline" method="post" action="/okta/requeue"><button class="sec">Re-queue everything</button></form></div></div></div>
<h2>Events <span class="muted">filter: <a href="/okta">all</a> · <a href="/okta?status=PENDING">pending</a> · <a href="/okta?status=SCHEDULED">scheduled</a> · <a href="/okta?status=SENT">sent</a> · <a href="/okta?status=DRYRUN">dry-run</a> · <a href="/okta?status=FAILED">failed</a></span></h2>
<table class="grid"><tr><th>#</th><th>Created</th><th>EMPLID</th><th>Action</th><th>Event type</th><th>Summary</th><th>Status</th><th>Sent</th><th></th></tr>{erows}</table>"""
    return layout(req, "Okta Integration", "<div class=\"pgbody\">" + body + "</div>", "Integration Broker &gt; <b>Okta Integration</b>", "/okta")


@route("GET", r"/okta/events/(?P<event_id>\d+)")
def okta_event(req, conn, event_id):
    r = db.row(conn, "SELECT * FROM PS_OKTA_EVENTS WHERE EVENT_ID=?", (event_id,))
    if not r:
        return redirect("/okta", err="Event not found")
    def pretty(s):
        try:
            return json.dumps(json.loads(s), indent=1)
        except (TypeError, ValueError):
            return s or ""
    body = f"""<div class="pgtitle">Event #{r['EVENT_ID']} <span class="badge {e(r['STATUS'])}">{e(r['STATUS'])}</span></div>
<div class="box"><div class="kv"><div class="k">EMPLID</div><div class="v"><a href="/employees/{e(r['EMPLID'])}">{e(r['EMPLID'])}</a></div>
<div class="k">Event type</div><div class="v">{e(r['EVENT_TYPE'])}</div><div class="k">Action / reason</div><div class="v">{e(r['ACTION'])} / {e(r['ACTION_REASON'])} eff {e(r['EFFDT'])}</div>
<div class="k">Summary</div><div class="v">{e(r['SUMMARY'])}</div><div class="k">Created / sent</div><div class="v">{e(r['CREATED_DTTM'])} / {e(r['SENT_DTTM'] or '-')}</div>
<div class="k">Target</div><div class="v">{e(r['TARGET'] or '-')}</div><div class="k">Attempts</div><div class="v">{r['ATTEMPTS']}</div></div>
<form method="post" action="/okta/events/{r['EVENT_ID']}/retry" style="margin-top:8px"><button>Re-send</button></form></div>
<div class="grid2"><div class="box"><h2>Okta request(s)</h2><pre>{e(pretty(r['REQUEST_PREVIEW']))}</pre></div>
<div class="box"><h2>Response</h2><pre>{e(pretty(r['RESPONSE']))}</pre></div></div>
<div class="box"><h2>Event payload (what a webhook receives)</h2><pre>{e(pretty(r['PAYLOAD']))}</pre></div>"""
    return layout(req, f"Event {event_id}", "<div class=\"pgbody\">" + body + "</div>", 'Integration Broker &gt; <a href="/okta">Okta Integration</a> &gt; <b>Event</b>', "/okta")


@route("POST", r"/okta/sync")
def okta_sync_ui(req, conn):
    s = okta.sync_pending(conn)
    if s["failed"]:
        return redirect("/okta", err=f"Sync ran (mode {s['mode']}): {s['failed']} failed, {s['sent']} sent. Open the failed event for the response.")
    return redirect("/okta", msg=f"Sync ran (mode {s['mode']}): processed {s['processed']}, sent {s['sent']}, dry-run {s['dryrun']}, deferred pre-hires {s['deferred']}.")


@route("POST", r"/okta/export")
def okta_export_ui(req, conn):
    return redirect("/okta", msg=f"Queued {okta.full_export(conn)} snapshot events.")


@route("POST", r"/okta/requeue")
def okta_requeue_ui(req, conn):
    okta.requeue_all(conn)
    return redirect("/okta", msg="All events re-queued as PENDING.")


@route("POST", r"/okta/events/(?P<event_id>\d+)/retry")
def okta_retry_ui(req, conn, event_id):
    okta.retry_event(conn, event_id)
    okta.sync_pending(conn)
    return redirect(f"/okta/events/{event_id}", msg="Event re-sent.")


# ---------------------------------------------------------------------- user profiles / setup / docs
@route("GET", r"/users")
def users_page(req, conn):
    users = db.rows(conn, "SELECT * FROM PSOPRDEFN ORDER BY OPRID")
    rows = "".join(f"""<tr><td>{e(u['OPRID'])}</td><td>{e(u['OPRDEFNDESC'])}</td><td>{e(u['EMAILID'])}</td><td>{'<span class="badge T">Locked</span>' if u['ACCTLOCK'] else '<span class="badge A">Active</span>'}</td>
<td>{('<a href="/employees/' + e(u['EMPLID']) + '">' + e(u['EMPLID']) + '</a>') if u['EMPLID'] else '<span class="muted">unlinked</span>'}</td><td>{e(u['EXTERNAL_ID'])}</td>
<td>{e(', '.join(r['ROLENAME'] for r in db.rows(conn, 'SELECT ROLENAME FROM PSROLEUSER WHERE ROLEUSER=?', (u['OPRID'],))))}</td><td class="muted">{e(u['SCIM_ID'])}</td><td class="muted">{e(u['LASTUPDDTTM'])}</td></tr>""" for u in users)
    body = f"""<div class="pgtitle">User Profiles (PSOPRDEFN) - provisioned by Okta over SCIM</div>
<div class="box"><p>Okta &rarr; {e(config.brand)} direction. Add a custom <b>SCIM 2.0</b> app in Okta with base URL <code>{e(config.public_url)}/scim/v2</code>, authentication <b>HTTP Header</b>,
token <code>{e(config.scim_token)}</code>. Users Okta assigns to the app appear here; deactivation locks the account (ACCTLOCK=1).</p>
<pre>curl -H "Authorization: Bearer {e(config.scim_token)}" {e(config.public_url)}/scim/v2/Users?filter=userName%20eq%20%22maggie%22</pre></div>
<table class="grid"><tr><th>OPRID</th><th>Description</th><th>Email</th><th>Account</th><th>EMPLID</th><th>Okta externalId</th><th>Roles</th><th>SCIM id</th><th>Updated</th></tr>{rows}</table>"""
    return layout(req, "User Profiles", "<div class=\"pgbody\">" + body + "</div>", "PeopleTools &gt; Security &gt; User Profiles &gt; <b>User Profiles</b>", "/users")


@route("GET", r"/setup")
def setup_page(req, conn):
    def tbl(title, rows, cols):
        head = "".join(f"<th>{c}</th>" for c in cols)
        body = "".join("<tr>" + "".join(f"<td>{e(r.get(c))}</td>" for c in cols) + "</tr>" for r in rows)
        return f'<div class="box"><h2>{title}</h2><table class="grid"><tr>{head}</tr>{body}</table></div>'
    body = "<div class=\"pgtitle\">Setup Tables</div><div class=\"grid2\">" + \
        tbl("Departments (PS_DEPT_TBL)", db.rows(conn, "SELECT * FROM PS_DEPT_TBL ORDER BY DEPTID"), ["DEPTID", "DESCR", "MANAGER_ID", "LOCATION"]) + \
        tbl("Locations (PS_LOCATION_TBL)", db.rows(conn, "SELECT * FROM PS_LOCATION_TBL ORDER BY LOCATION"), ["LOCATION", "DESCR", "CITY", "STATE", "COUNTRY"]) + \
        "</div>" + tbl("Job Codes (PS_JOBCODE_TBL)", db.rows(conn, "SELECT * FROM PS_JOBCODE_TBL ORDER BY JOB_FAMILY, GRADE"), ["JOBCODE", "DESCR", "DESCRSHORT", "GRADE", "JOB_FAMILY", "MANAGER_LEVEL"]) + \
        f"""<div class="box"><h2>Danger zone</h2><form method="post" action="/admin/reset" onsubmit="return confirm('Drop all data and re-seed the demo organisation?')"><button class="danger">Reset database to seed data</button></form></div>"""
    return layout(req, "Setup Tables", "<div class=\"pgbody\">" + body + "</div>", "Set Up HCM &gt; Foundation Tables &gt; <b>Organization</b>", "/setup")


@route("POST", r"/admin/reset")
def admin_reset_ui(req, conn):
    db.reset_db(conn)
    hr.seed(conn)
    return redirect("/", msg="Database reset and re-seeded.")


@route("GET", r"/api-docs")
def api_docs(req, conn):
    base = req.base_url
    u, p, t = config.api_user, config.api_password, config.api_token
    body = f"""<div class="pgtitle">API Reference</div>
<div class="box"><h2>Authentication</h2><p>REST and {e(config.brand)} Integration Broker style endpoints accept <b>Basic</b> auth (<code>{e(u)}</code> / <code>{e(p)}</code>) or <code>Authorization: Bearer {e(t)}</code>.
SCIM endpoints require <code>Authorization: Bearer {e(config.scim_token)}</code>. Set <code>PS_API_AUTH=off</code> to disable API auth. Health check is open.</p>
<pre>curl -u {e(u)}:{e(p)} {e(base)}/api/v1/workers
curl -H "Authorization: Bearer {e(t)}" "{e(base)}/api/v1/workers?changedSince=2026-01-01T00:00:00Z"</pre></div>
<div class="grid2"><div class="box"><h2>Workers (HR source of truth)</h2><table class="grid">
<tr><th>Method</th><th>Path</th><th>Notes</th></tr>
<tr><td>GET</td><td>/api/v1/workers</td><td>?status=A|L|T… &amp;changedSince=ISO &amp;asOf=YYYY-MM-DD &amp;q= &amp;deptid= &amp;active=true &amp;limit/offset. Use changedSince for polling deltas.</td></tr>
<tr><td>GET</td><td>/api/v1/workers/{{emplid}}</td><td>Worker composite (person + effective job + employment). ?asOf= for effective dating.</td></tr>
<tr><td>POST</td><td>/api/v1/workers</td><td>Hire. JSON: firstName, lastName, deptid, jobcode, hireDate, location, supervisorId, workEmail, compRate, emplClass, reason…</td></tr>
<tr><td>PATCH</td><td>/api/v1/workers/{{emplid}}</td><td>Personal data change (name, preferredFirstName, workEmail, mobilePhone) → DTA event.</td></tr>
<tr><td>POST</td><td>/api/v1/workers/{{emplid}}/actions</td><td>Generic: {{"action":"XFR|PRO|DEM|PAY|DTA|LOA|PLA|RFL|SUS|TER|RET|REH", "effdt":…, "reason":…, …}}</td></tr>
<tr><td>POST</td><td>/api/v1/workers/{{emplid}}/transfer | promote | demote | pay | manager | leave | return | terminate | retire | rehire | suspend</td><td>Shortcuts for the above.</td></tr>
<tr><td>GET</td><td>/api/v1/workers/{{emplid}}/job-history</td><td>All PS_JOB rows.</td></tr>
<tr><td>GET</td><td>/api/v1/workers/{{emplid}}/events</td><td>Okta events for this worker.</td></tr>
<tr><td>GET</td><td>/api/v1/departments · /jobcodes · /locations · /companies · /meta · /audit</td><td>Setup tables, code lists, audit log.</td></tr></table>
<h2>PeopleSoft Integration Broker aliases</h2><table class="grid"><tr><th>Path</th><th>Same as</th></tr>
<tr><td>GET /PSIGW/RESTListeningConnector/PSFT_HR/WORKER.v1/</td><td>/api/v1/workers</td></tr>
<tr><td>GET /PSIGW/RESTListeningConnector/PSFT_HR/WORKER.v1/{{emplid}}</td><td>/api/v1/workers/{{emplid}}</td></tr>
<tr><td>POST /PSIGW/RESTListeningConnector/PSFT_HR/WORKER.v1/</td><td>Hire</td></tr>
<tr><td>GET/POST /PSIGW/RESTListeningConnector/PSFT_HR/JOB.v1/{{emplid}}</td><td>Job history / job action</td></tr>
<tr><td>GET /PSIGW/RESTListeningConnector/PSFT_HR/EMPLOYEE.v1/…</td><td>Workers</td></tr></table></div>
<div class="box"><h2>Okta outbox</h2><table class="grid"><tr><th>Method</th><th>Path</th><th>Notes</th></tr>
<tr><td>GET</td><td>/api/v1/events?status=PENDING|SENT|DRYRUN|FAILED</td><td>Outbox with request previews and responses.</td></tr>
<tr><td>GET</td><td>/api/v1/events/{{id}}</td><td>One event.</td></tr>
<tr><td>POST</td><td>/api/v1/events/{{id}}/retry</td><td>Mark PENDING again.</td></tr>
<tr><td>POST</td><td>/api/v1/okta/sync</td><td>Flush the outbox now.</td></tr>
<tr><td>GET</td><td>/api/v1/okta/status</td><td>Config + counts.</td></tr>
<tr><td>GET</td><td>/api/v1/okta/preview/{{emplid}}</td><td>Okta profile mapping + planned API calls for a worker.</td></tr>
<tr><td>POST</td><td>/api/v1/okta/export</td><td>Queue a snapshot of every worker (initial import).</td></tr></table>
<h2>SCIM 2.0 (Okta → {e(config.brand)} user profiles)</h2><table class="grid"><tr><th>Method</th><th>Path</th></tr>
<tr><td>GET</td><td>/scim/v2/ServiceProviderConfig · /ResourceTypes · /Schemas</td></tr>
<tr><td>GET</td><td>/scim/v2/Users?filter=userName eq "x"&amp;startIndex=1&amp;count=100</td></tr>
<tr><td>POST / GET / PUT / PATCH / DELETE</td><td>/scim/v2/Users[/{{id}}]</td></tr>
<tr><td>GET</td><td>/scim/v2/Groups (empty list; groups not supported)</td></tr></table>
<h2>Admin</h2><table class="grid"><tr><th>Method</th><th>Path</th><th>Notes</th></tr>
<tr><td>POST</td><td>/api/v1/admin/journey</td><td>Run the guided joiner/mover/leaver/rehire journey; returns the steps.</td></tr>
<tr><td>POST</td><td>/api/v1/admin/reset</td><td>Drop and re-seed.</td></tr>
<tr><td>GET</td><td>/api/v1/health</td><td>No auth.</td></tr></table></div></div>
<div class="box"><h2>Examples</h2><pre>
# Joiner
curl -u {e(u)}:{e(p)} -H 'Content-Type: application/json' -d '{{"firstName":"Ada","lastName":"Lovelace","deptid":"13000","jobcode":"SWE2","supervisorId":"100010","hireDate":"{date.today().isoformat()}"}}' {e(base)}/api/v1/workers
# Mover
curl -u {e(u)}:{e(p)} -H 'Content-Type: application/json' -d '{{"deptid":"13100","location":"AUS01","supervisorId":"100014"}}' {e(base)}/api/v1/workers/100013/transfer
# Leaver
curl -u {e(u)}:{e(p)} -H 'Content-Type: application/json' -d '{{"reason":"RES","effdt":"{(date.today() + timedelta(days=1)).isoformat()}"}}' {e(base)}/api/v1/workers/100013/terminate
# Poll for changes (Okta Workflows / custom poller)
curl -u {e(u)}:{e(p)} "{e(base)}/api/v1/workers?changedSince=2026-01-01T00:00:00Z"
# Flush outbox to Okta
curl -u {e(u)}:{e(p)} -X POST {e(base)}/api/v1/okta/sync</pre></div>"""
    return layout(req, "API Docs", "<div class=\"pgbody\">" + body + "</div>", "<b>API Reference</b>", "/api-docs")


# ---------------- Sign-on status (Okta Access Gateway header auth)
def sso_error_page(req, ex):
    body = f"""<div class="pgtitle">{e(ex.title)}</div><div class="pgbody">
<div class="grp"><div class="gh">PeopleSoft Sign-on</div><div class="gb"><p>{e(ex.detail)}</p>
<p class="muted">Sign-on mode: header-based (PS_UI_AUTH=header). The application expects Okta Access Gateway to authenticate you and forward
<code>{e(config.sso_header)}</code>{' plus the shared secret header <code>' + e(config.sso_secret_header) + '</code>' if config.sso_secret else ''}.</p>
<p><a class="btn primary" href="/signon">Sign-on status</a> <a class="btn" href="{e(config.sso_logout_url)}">Sign out of the gateway</a></p></div></div></div>"""
    from .routing import Response
    page = layout(req, ex.title, body)
    return Response(page.body, ex.status)


@route("GET", r"/signon")
def signon_page(req, conn):
    from . import sso
    cfg = config.sso_summary()
    seen = sso.received_headers(req.headers)
    hrows = "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in seen.items()) or '<tr><td colspan="2" class="muted">No SSO headers on this request</td></tr>'
    crows = "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in cfg.items())
    u = req.user
    if u is None and config.ui_auth != "header" and sso.identity_from_headers(req.headers)[0]:
        try:
            u = sso.authenticate(conn, req.headers, req.client_ip)
            note = "Headers were resolved for display only: PS_UI_AUTH is off, so the UI does not require them."
        except sso.SSOError as ex:
            note = f"Headers present but not accepted: {ex.detail}"
    else:
        note = "" if u else ("Not signed on." if config.ui_auth == "header" else "UI sign-on is off (open UI). Set PS_UI_AUTH=header to require Okta Access Gateway.")
    if u:
        who = f"""<div class="fl" style="max-width:100%">{fld('User ID (OPRID):', u.oprid)}{fld('Description:', u.name)}{fld('Email:', u.email)}
{fld('Empl ID:', u.emplid or '', '' if not u.emplid else '')}{fld('Roles:', ', '.join(u.roles) or 'none')}{fld('Access:', 'Administrator (can change data)' if u.is_admin else 'Read only')}
{fld('Identity header used:', u.header_name or '')}{fld('Profile created just-in-time:', 'Yes' if u.created else 'No')}{fld('Client address seen:', req.client_ip)}</div>"""
        if u.emplid:
            who += f'<p><a href="/employees/{e(u.emplid)}">Open my Job Data</a></p>'
    else:
        who = f'<p class="muted">{e(note)}</p>'
    body = f"""<div class="pgtitle">Sign-on Status</div><div class="pgbody">
<div class="grid2"><div class="grp"><div class="gh">Signed-on user</div><div class="gb">{who}{('<p class="muted">' + e(note) + '</p>') if u and note else ''}
<p><a class="btn" href="{e(config.sso_logout_url)}">Sign out (gateway logout URL)</a></p></div></div>
<div class="grp"><div class="gh">Headers received on this request</div><div class="gb"><table class="grid"><tr><th>Header</th><th>Value</th></tr>{hrows}</table>
<p class="muted">Client address: {e(req.client_ip)}. Okta Access Gateway injects these after Okta sign-in; configure them under the application's Attributes tab.</p></div></div></div>
<div class="grp"><div class="gh">Configuration (.env)</div><div class="gb"><table class="grid"><tr><th>Setting</th><th>Value</th></tr>{crows}</table></div></div>
<div class="grp"><div class="gh">Okta Access Gateway setup</div><div class="gb"><ol style="margin:4px 0 0 18px;line-height:1.8">
<li>OAG Admin console &rarr; Applications &rarr; Add &rarr; <b>Header Based</b> (or the PeopleSoft template). Public domain = the URL users will open; Protected web resource = this server.</li>
<li>Attributes tab: add header <code>{e(config.sso_header)}</code> = Okta <code>login</code>, <code>{e(config.sso_email_header)}</code> = <code>email</code>, <code>{e(config.sso_name_header)}</code> = <code>displayName</code>, <code>{e(config.sso_groups_header)}</code> = <code>groups</code> (filtered to the PeopleSoft groups).</li>
<li>Optional but recommended: add a static header <code>{e(config.sso_secret_header)}</code> with a random value and put the same value in <code>PS_SSO_SECRET</code>; set <code>PS_SSO_TRUSTED_PROXIES</code> to the gateway's address so nobody can bypass it with hand-made headers.</li>
<li>Assign Okta users/groups to the OAG app. Members of a group named in <code>PS_SSO_ADMIN_ROLES</code> (e.g. <b>HR Administrator</b>) can change data; everyone else is read-only.</li>
<li>Set <code>PS_UI_AUTH=header</code> and restart. Without a gateway, test with <code>python3 scripts/mock_oag.py</code>.</li></ol></div></div></div>"""
    return layout(req, "Sign-on Status", body, 'PeopleTools &gt; Security &gt; <b>Sign-on Status</b>')


@route("GET", r"/signout")
def signout(req, conn):
    return redirect(config.sso_logout_url)
