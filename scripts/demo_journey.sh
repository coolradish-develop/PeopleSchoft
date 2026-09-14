#!/usr/bin/env bash
# Drives a joiner -> mover -> leaver -> rehire journey over the REST API with curl.
# Usage: scripts/demo_journey.sh [base_url] [user:password]
set -euo pipefail
B="${1:-http://localhost:8080}"; AUTH="${2:-PS:PS}"; H='Content-Type: application/json'
TODAY=$(date +%F)
j() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({k:d.get(k) for k in ("emplid","displayName","emplStatus","emplStatusDescr")}), "job:", json.dumps({k:(d.get("job") or {}).get(k) for k in ("action","deptDescr","jobTitle","location","supervisorName")}))'; }
step() { echo; echo "== $1"; }

step "JOINER: hire"
W=$(curl -sf -u "$AUTH" -H "$H" -d "{\"firstName\":\"Ada\",\"lastName\":\"Lovelace\",\"deptid\":\"13000\",\"jobcode\":\"SWE1\",\"supervisorId\":\"100010\",\"hireDate\":\"$TODAY\",\"compRate\":115000}" "$B/api/v1/workers")
ID=$(echo "$W" | python3 -c 'import json,sys; print(json.load(sys.stdin)["emplid"])'); echo "$W" | j
step "MOVER: promotion"
curl -sf -u "$AUTH" -H "$H" -d '{"jobcode":"SWE2","compRate":140000,"reason":"MER"}' "$B/api/v1/workers/$ID/promote" | j
step "MOVER: transfer (dept + location + manager)"
curl -sf -u "$AUTH" -H "$H" -d '{"deptid":"13100","location":"AUS01","supervisorId":"100014"}' "$B/api/v1/workers/$ID/transfer" | j
step "MOVER: name change"
curl -sf -u "$AUTH" -X PATCH -H "$H" -d '{"lastName":"Lovelace-King"}' "$B/api/v1/workers/$ID" | j
step "LEAVE: leave of absence (Okta suspend)"
curl -sf -u "$AUTH" -H "$H" -d '{"reason":"PAR"}' "$B/api/v1/workers/$ID/leave" | j
step "RETURN from leave (Okta unsuspend)"
curl -sf -u "$AUTH" -H "$H" -d '{}' "$B/api/v1/workers/$ID/return" | j
step "LEAVER: termination (Okta deactivate)"
curl -sf -u "$AUTH" -H "$H" -d '{"reason":"RES"}' "$B/api/v1/workers/$ID/terminate" | j
step "JOINER: rehire (Okta reactivate)"
curl -sf -u "$AUTH" -H "$H" -d '{"deptid":"16000","jobcode":"IAMENG","supervisorId":"100023"}' "$B/api/v1/workers/$ID/rehire" | j
step "Flush outbox to Okta"
curl -sf -u "$AUTH" -X POST "$B/api/v1/okta/sync"
step "Events for $ID"
curl -sf -u "$AUTH" "$B/api/v1/workers/$ID/events" | python3 -c 'import json,sys; [print("  #%-4s %-28s %s" % (e["event_id"], e["event_type"], e["status"])) for e in reversed(json.load(sys.stdin)["events"])]'
echo; echo "Open $B/employees/$ID and $B/okta"
