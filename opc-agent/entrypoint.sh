#!/usr/bin/env bash
# Okta On-prem SCIM Server agent (agent mode) in a container: install the rpm mounted at /agents, register the
# agent with the org through Okta's device-authorization flow, then run it as the okscimserver service user.
# This is a non-interactive port of /opt/OktaOnPremScimServer/bin/configure_agent.sh from the rpm.
set -Eeuo pipefail
AGENTS=/agents
APP=/opt/OktaOnPremScimServer; ETC=$APP/config; LOGS=$APP/logs
CONF=$ETC/ops.conf; KS=$ETC/ops-keystore.p12; MODE_FILE=$ETC/agent-mode.conf
: "${OKTA_ORG_URL:?set OKTA_ORG_URL (https://your-org.okta.com) in .env}"
echo "== Okta On-prem SCIM Server agent host: UBI 9, $(java -version 2>&1 | head -1), $(openssl version)"

RPM=$(ls "$AGENTS"/OktaOnPremScimServer*.rpm 2>/dev/null | head -1 || true)
if [ -z "$RPM" ]; then
  echo "!! no OktaOnPremScimServer-*.rpm in the agents folder. Download it from Admin Console > Settings > Downloads."; sleep infinity
fi

# service user (created by the rpm's %pre; recreate when the container was rebuilt but /opt/OktaOnPremScimServer persisted)
getent group okscimserver >/dev/null || groupadd -r okscimserver
getent passwd okscimserver >/dev/null || useradd -r -g okscimserver -d $APP -s /sbin/nologin okscimserver

if ! ls $APP/lib/OktaOnPremScimServer-*.jar >/dev/null 2>&1; then
  case "${OKTA_EULA_ACCEPT:-}" in y|Y|yes|YES|true|1) ;; *)
    echo "!! Set OKTA_EULA_ACCEPT=yes in .env to accept Okta's On-prem SCIM Server EULA (https://www.okta.com/legal/) before installing."; sleep infinity;; esac
  echo "== installing $RPM in agent mode (arch: $(uname -m))"
  # The rpm is stamped x86_64 but ships only shell scripts, a Java jar and systemd units, so it runs on
  # arm64 hosts (Apple Silicon) with the arm64 JDK: --ignorearch skips the architecture check.
  INSTALL_MODE=agent OKTA_EULA_ACCEPT=yes rpm -ivh --ignorearch "$RPM"
fi
JAR=$(ls $APP/lib/OktaOnPremScimServer-*.jar | head -1)
mkdir -p $APP/userlib $APP/userplugin $LOGS
for j in "$AGENTS"/*.jar; do [ -f "$j" ] && cp -f "$j" $APP/userlib/ && echo "JDBC driver loaded: $(basename "$j")"; done
[ -f "$ETC/jvm.conf" ] && . "$ETC/jvm.conf" || true

JAVA_COMMON=(${JAVA_OPTS:-} -Dloader.main=com.okta.server.scim.ScimServerApplication -Dlogging.file.name=$LOGS/configure-agent.log
             -Dspring.main.web-application-type=none -Dspring.profiles.active=agent -Dspring.main.banner-mode=off)
LAUNCHER=org.springframework.boot.loader.launch.PropertiesLauncher
step() { java "${JAVA_COMMON[@]}" -cp "$JAR" $LAUNCHER "$@" >> $LOGS/configure-agent.log 2>&1; }
prop() { sed -n "s/^$1[[:space:]]*=[[:space:]]*//p" "$CONF" | tr -d '[:space:]'; }

if [ ! -f "$MODE_FILE" ]; then
  PROXY=(-proxyEnabled false)
  [ -n "${OPC_PROXY_HOST:-}" ] && PROXY=(-proxyEnabled true -proxyScheme "${OPC_PROXY_SCHEME:-http}" -proxyHost "$OPC_PROXY_HOST" -proxyPort "${OPC_PROXY_PORT:-8080}")
  echo "== [1/3] requesting device authorization from ${OKTA_ORG_URL%/}"
  step -mode deviceAuthorizationStart -orgUrl "${OKTA_ORG_URL%/}" -configFilePath "$CONF" -keystoreFilePath "$KS" -noInstance true "${PROXY[@]}" \
    || { echo "!! device authorization failed; see $LOGS/configure-agent.log"; tail -20 $LOGS/configure-agent.log; sleep infinity; }
  echo; echo "  ================================================================================"
  echo "  APPROVE THIS AGENT: open  $(prop verificationUri)"
  echo "  and enter the code   $(prop userCode)   as an Okta admin (super admin recommended)."
  echo "  ================================================================================"; echo
  echo "== [2/3] waiting for approval in the browser ..."
  step -mode deviceAuthorizationPoll -configFilePath "$CONF" -keystoreFilePath "$KS" -serviceAccountName okscimserver \
    || { echo "!! authorization was not granted; restart the container to get a new code"; tail -20 $LOGS/configure-agent.log; sleep infinity; }
  echo "== [3/3] registering the agent with Okta"
  step -mode register -configFilePath "$CONF" -keystoreFilePath "$KS" \
    || { echo "!! registration failed; see $LOGS/configure-agent.log"; tail -20 $LOGS/configure-agent.log; sleep infinity; }
  echo "AGENT_MODE=true" > "$MODE_FILE"
  echo "== registered. The agent now appears under Directory > Directory Integrations / the app's Provisioning tab."
fi
chown -R okscimserver:okscimserver $ETC $LOGS $APP/userlib $APP/userplugin
chmod 600 "$CONF" "$KS" "$MODE_FILE"
touch $LOGS/application.log; tail -n 0 -F $LOGS/application.log &
echo "== starting OktaOnPremScimAgent (polling agent mode; JDBC drivers from $APP/userlib)"
exec runuser -u okscimserver -- $APP/bin/OktaOnPremScimAgent.sh
