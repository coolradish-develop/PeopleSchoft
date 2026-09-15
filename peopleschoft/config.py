"""Configuration. Everything comes from environment variables (optionally loaded from .env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path=None):
    """Minimal .env loader: KEY=VALUE lines, '#' comments, does not override existing env."""
    path = Path(path or BASE_DIR / ".env")
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(key, default=None):
    return os.environ.get(key, default)


def _bool(key, default=False):
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Config:
    """Read on access so tests and the CLI can tweak the environment."""

    # --- server ---
    @property
    def host(self): return _env("PS_HOST", "0.0.0.0")
    @property
    def port(self): return int(_env("PS_PORT", "8080"))
    @property
    def db_path(self): return Path(_env("PS_DB_PATH", str(BASE_DIR / "data" / "peopleschoft.db")))
    @property
    def reload(self): return _bool("PS_RELOAD", False)
    @property
    def public_url(self): return _env("PS_PUBLIC_URL", f"http://localhost:{self.port}")

    # --- API auth (PeopleSoft Integration Broker style) ---
    @property
    def api_auth(self): return _env("PS_API_AUTH", "basic").lower()   # basic | off
    @property
    def api_user(self): return _env("PS_API_USER", "PS")
    @property
    def api_password(self): return _env("PS_API_PASSWORD", "PS")
    @property
    def api_token(self): return _env("PS_API_TOKEN", "peopleschoft-api-token")

    # --- UI sign-on: off (open) | header (Okta Access Gateway / reverse-proxy header auth) ---
    @property
    def ui_auth(self): return _env("PS_UI_AUTH", "off").lower()
    @property
    def sso_header(self): return _env("PS_SSO_HEADER", "PS_SSO_UID")
    @property
    def sso_email_header(self): return _env("PS_SSO_EMAIL_HEADER", "PS_SSO_EMAIL")
    @property
    def sso_name_header(self): return _env("PS_SSO_NAME_HEADER", "PS_SSO_NAME")
    @property
    def sso_groups_header(self): return _env("PS_SSO_GROUPS_HEADER", "PS_SSO_GROUPS")
    @property
    def sso_secret_header(self): return _env("PS_SSO_SECRET_HEADER", "PS_SSO_SECRET")
    @property
    def sso_secret(self): return _env("PS_SSO_SECRET", "")
    @property
    def sso_trusted_proxies(self): return _env("PS_SSO_TRUSTED_PROXIES", "")
    @property
    def sso_autocreate(self): return _bool("PS_SSO_AUTOCREATE", True)
    @property
    def sso_admin_roles(self): return _env("PS_SSO_ADMIN_ROLES", "PeopleSoft Administrator,HR Administrator,Okta Administrators")
    @property
    def sso_logout_url(self): return _env("PS_SSO_LOGOUT_URL", "/oag/logout")

    def sso_summary(self):
        return {"uiAuth": self.ui_auth, "uidHeader": self.sso_header, "emailHeader": self.sso_email_header, "nameHeader": self.sso_name_header,
                "groupsHeader": self.sso_groups_header, "secretHeader": self.sso_secret_header, "secretSet": bool(self.sso_secret),
                "trustedProxies": self.sso_trusted_proxies or "(any)", "autocreate": self.sso_autocreate,
                "adminRoles": self.sso_admin_roles, "logoutUrl": self.sso_logout_url}

    # --- SCIM inbound (Okta -> PeopleSoft user profiles) ---
    @property
    def scim_token(self): return _env("PS_SCIM_TOKEN", "peopleschoft-scim-token")

    # --- HR as a source: SCIM feed for the Okta Provisioning Agent + SQL export for the Generic Databases connector ---
    @property
    def hr_scim_auth(self): return _env("PS_HR_SCIM_AUTH", "token").lower()      # token | off
    @property
    def hr_scim_token(self): return _env("PS_HR_SCIM_TOKEN", "peopleschoft-hr-token")
    @property
    def hr_scim_header(self): return _env("PS_HR_SCIM_HEADER", "X-HR-Token")
    @property
    def hr_scim_writeback(self): return _bool("PS_HR_SCIM_WRITEBACK", False)
    @property
    def sql_export_dialect(self): return _env("PS_SQL_EXPORT_DIALECT", "").lower()  # '' = off | postgres | mysql | mssql
    @property
    def sql_export_interval(self): return int(_env("PS_SQL_EXPORT_INTERVAL", "30"))
    @property
    def sql_export_dir(self): return Path(_env("PS_SQL_EXPORT_DIR", str(self.db_path.parent / "export")))

    def hr_master_summary(self):
        return {"scimAuth": self.hr_scim_auth, "scimTokenSet": bool(self.hr_scim_token), "scimHeader": self.hr_scim_header,
                "scimWriteback": self.hr_scim_writeback, "sqlExportDialect": self.sql_export_dialect or None,
                "sqlExportInterval": self.sql_export_interval, "sqlExportDir": str(self.sql_export_dir)}

    # --- Okta outbound ---
    @property
    def okta_mode(self): return _env("OKTA_MODE", "dryrun").lower()   # dryrun | webhook | users | identity-source
    @property
    def okta_org_url(self): return (_env("OKTA_ORG_URL", "https://dev-000000.okta.com") or "").rstrip("/")
    @property
    def okta_api_token(self): return _env("OKTA_API_TOKEN", "")
    @property
    def okta_identity_source_id(self): return _env("OKTA_IDENTITY_SOURCE_ID", "")
    @property
    def okta_webhook_url(self): return _env("OKTA_WEBHOOK_URL", "")
    @property
    def okta_webhook_token(self): return _env("OKTA_WEBHOOK_TOKEN", "")
    @property
    def okta_custom_attrs(self): return _bool("OKTA_CUSTOM_ATTRS", False)
    @property
    def okta_sync_interval(self): return int(_env("OKTA_SYNC_INTERVAL", "10"))
    @property
    def okta_prehire_days(self): return int(_env("OKTA_PREHIRE_DAYS", "14"))
    @property
    def okta_loa_action(self): return _env("OKTA_LOA_ACTION", "suspend").lower()  # suspend | none
    @property
    def okta_activation(self): return _env("OKTA_ACTIVATION", "password").lower()  # password | welcome

    # --- branding ---
    @property
    def brand(self): return _env("PS_BRAND", "PeopleSchoft")

    # --- demo data ---
    @property
    def email_domain(self): return _env("PS_EMAIL_DOMAIN", "gbi.example.com")
    @property
    def company(self): return _env("PS_COMPANY", "GBI")

    def okta_summary(self):
        return {
            "mode": self.okta_mode,
            "orgUrl": self.okta_org_url,
            "apiTokenSet": bool(self.okta_api_token),
            "identitySourceId": self.okta_identity_source_id or None,
            "webhookUrl": self.okta_webhook_url or None,
            "webhookTokenSet": bool(self.okta_webhook_token),
            "customAttrs": self.okta_custom_attrs,
            "syncIntervalSeconds": self.okta_sync_interval,
            "preHireDays": self.okta_prehire_days,
            "loaAction": self.okta_loa_action,
            "activation": self.okta_activation,
        }


config = Config()
