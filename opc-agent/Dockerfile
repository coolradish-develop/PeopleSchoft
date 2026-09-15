# Host for the Okta On-prem SCIM Server agent (OktaOnPremScimServer rpm, agent mode) used by the
# On-prem Connector for Generic Databases. Okta supports a dedicated RHEL 8/9/10 server; this image is
# Red Hat UBI 9 with JDK 21 and OpenSSL 3, matching the documented software requirements.
# Running the agent in a container is NOT an Okta-supported topology: fine for demos, use a RHEL VM otherwise.
FROM registry.access.redhat.com/ubi9/ubi:latest

RUN dnf -y install java-21-openjdk-devel openssl shadow-utils acl procps-ng hostname util-linux iputils bind-utils && dnf clean all
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk
ENV PATH=$JAVA_HOME/bin:$PATH

# The rpm is an Okta download (Admin Console > Settings > Downloads) and is mounted at /agents, never baked in.
COPY entrypoint.sh /usr/local/bin/opc-entrypoint.sh
RUN chmod +x /usr/local/bin/opc-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/opc-entrypoint.sh"]
