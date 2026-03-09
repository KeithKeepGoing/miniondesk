"""
AD/LDAP Integration for MinionDesk.
Provides authentication and group-based RBAC synced with Active Directory.
"""
from __future__ import annotations
import os
import logging
from typing import Optional

log = logging.getLogger(__name__)

LDAP_URL = os.getenv("LDAP_URL", "")           # e.g. ldap://dc.corp.local:389
if LDAP_URL and not LDAP_URL.startswith("ldaps://"):
    log.warning("LDAP_URL uses plaintext protocol (%s) — credentials will be transmitted unencrypted. Use ldaps:// in production.", LDAP_URL.split("://")[0] + "://...")
LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "")   # e.g. DC=corp,DC=local
LDAP_USER_SEARCH_BASE = os.getenv("LDAP_USER_SEARCH_BASE", "")  # OU=Users,DC=corp,DC=local
LDAP_GROUP_ATTR = os.getenv("LDAP_GROUP_ATTR", "memberOf")

# Define role priority (higher index = higher privilege)
_ROLE_PRIORITY = {"readonly": 0, "user": 1, "manager": 2, "admin": 3}

# Map AD groups to MinionDesk roles
# e.g. "CN=IT-Admins,OU=Groups,DC=corp,DC=local" -> "admin"


def _ldap_escape(val: str) -> str:
    """Escape special characters for safe LDAP filter interpolation."""
    # Escape per RFC 4515
    val = val.replace("\\", "\\5c")
    val = val.replace("*", "\\2a")
    val = val.replace("(", "\\28")
    val = val.replace(")", "\\29")
    val = val.replace("\x00", "\\00")
    return val


def _parse_group_map() -> dict[str, str]:
    """Parse LDAP_GROUP_ROLE_MAP env var.
    Format: "CN=IT-Admins,...=admin;CN=HR-Staff,...=hr"
    """
    raw = os.getenv("LDAP_GROUP_ROLE_MAP", "")
    result = {}
    for pair in raw.split(";"):
        if not pair.strip():
            continue
        parts = pair.rsplit("=", 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            result[parts[0].strip()] = parts[1].strip()
        else:
            log.warning("Malformed LDAP_GROUP_ROLE_MAP entry: %r", pair)
    return result


GROUP_ROLE_MAP: dict[str, str] = _parse_group_map()

if LDAP_URL and not GROUP_ROLE_MAP:
    log.warning("LDAP configured but LDAP_GROUP_ROLE_MAP is empty — all users will receive 'employee' role")


def is_configured() -> bool:
    return bool(LDAP_URL and LDAP_BASE_DN and os.getenv("LDAP_BIND_DN", ""))


def authenticate(username: str, password: str) -> Optional[dict]:
    """
    Authenticate user against AD/LDAP.
    Returns user info dict on success, None on failure.
    """
    if not password:
        log.warning("LDAP auth rejected: empty password for %s", username)
        return None
    if not is_configured():
        log.debug("LDAP not configured, skipping authentication")
        return None
    try:
        from ldap3 import Server, Connection, ALL, SIMPLE, SUBTREE
        server = Server(LDAP_URL, get_info=ALL)
        # First bind with service account to search for user
        conn = None
        user_conn = None
        bind_dn = os.getenv("LDAP_BIND_DN", "")
        bind_pw = os.getenv("LDAP_BIND_PASSWORD", "")
        try:
            conn = Connection(server, user=bind_dn, password=bind_pw, authentication=SIMPLE)
            if not conn.bind():
                log.error(f"LDAP service bind failed: {conn.result}")
                return None
            # Search for user
            search_filter = f"(sAMAccountName={_ldap_escape(username)})"
            conn.search(
                search_base=LDAP_USER_SEARCH_BASE or LDAP_BASE_DN,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=["cn", "mail", "memberOf", "department", "title", "sAMAccountName"],
            )
            if not conn.entries:
                log.warning(f"LDAP user not found: {username}")
                return None
            user_entry = conn.entries[0]
            user_dn = user_entry.entry_dn
            # Now authenticate as user
            try:
                user_conn = Connection(server, user=user_dn, password=password, authentication=SIMPLE)
                if not user_conn.bind():
                    log.warning(f"LDAP auth failed for {username}")
                    return None
            finally:
                if user_conn:
                    try:
                        user_conn.unbind()
                    except Exception:
                        pass
            # Extract groups
            groups = []
            if LDAP_GROUP_ATTR in user_entry.entry_attributes_as_dict:
                groups = list(user_entry.entry_attributes_as_dict.get(LDAP_GROUP_ATTR, []))
            # Map groups to role — prefer highest-privilege role
            group_map = GROUP_ROLE_MAP
            roles = [group_map[grp] for grp in groups if grp in group_map]
            role = max(roles, key=lambda r: _ROLE_PRIORITY.get(r, 0)) if roles else "employee"
            return {
                "username": username,
                "dn": user_dn,
                "display_name": str(user_entry.cn) if hasattr(user_entry, "cn") else username,
                "email": str(user_entry.mail) if hasattr(user_entry, "mail") else "",
                "department": str(user_entry.department) if hasattr(user_entry, "department") else "",
                "title": str(user_entry.title) if hasattr(user_entry, "title") else "",
                "groups": groups,
                "role": role,
            }
        except Exception as e:
            log.error(f"LDAP operation error: {e}")
            return None
        finally:
            if conn:
                try:
                    conn.unbind()
                except Exception:
                    pass
    except ImportError:
        log.warning("ldap3 not installed. Run: pip install ldap3")
        return None
    except Exception as e:
        log.error(f"LDAP error: {e}")
        return None


def get_user_info(username: str) -> Optional[dict]:
    """
    Fetch user info from AD without password (using service account).
    Used for syncing employee records.
    """
    if not is_configured():
        return None
    conn = None
    try:
        from ldap3 import Server, Connection, ALL, SIMPLE, SUBTREE
        server = Server(LDAP_URL, get_info=ALL)
        bind_dn = os.getenv("LDAP_BIND_DN", "")
        bind_pw = os.getenv("LDAP_BIND_PASSWORD", "")
        conn = Connection(server, user=bind_dn, password=bind_pw, authentication=SIMPLE)
        if not conn.bind():
            log.error(f"LDAP bind failed: {conn.result}")
            return None
        conn.search(
            search_base=LDAP_USER_SEARCH_BASE or LDAP_BASE_DN,
            search_filter=f"(sAMAccountName={_ldap_escape(username)})",
            search_scope=SUBTREE,
            attributes=["cn", "mail", "memberOf", "department", "title", "sAMAccountName", "telephoneNumber"],
        )
        if not conn.entries:
            return None
        e = conn.entries[0]
        groups = list(e.entry_attributes_as_dict.get(LDAP_GROUP_ATTR, [])) if LDAP_GROUP_ATTR in e.entry_attributes_as_dict else []
        group_map = GROUP_ROLE_MAP
        roles = [group_map[grp] for grp in groups if grp in group_map]
        role = max(roles, key=lambda r: _ROLE_PRIORITY.get(r, 0)) if roles else "employee"
        return {
            "username": username,
            "dn": e.entry_dn,
            "display_name": str(e.cn) if hasattr(e, "cn") else username,
            "email": str(e.mail) if hasattr(e, "mail") else "",
            "department": str(e.department) if hasattr(e, "department") else "",
            "title": str(e.title) if hasattr(e, "title") else "",
            "phone": str(e.telephoneNumber) if hasattr(e, "telephoneNumber") else "",
            "groups": groups,
            "role": role,
        }
    except Exception as e:
        log.error(f"LDAP get_user_info error: {e}")
        return None
    finally:
        if conn:
            try:
                conn.unbind()
            except Exception:
                pass


def sync_employee_from_ad(username: str, ctx=None) -> bool:
    """
    Sync an employee record from AD into MinionDesk DB.
    Returns True if synced successfully.
    """
    info = get_user_info(username)
    if not info:
        return False
    try:
        from host import db
        conn = db.get_conn(ctx) if ctx else db.get_conn()
        try:
            conn.execute("""
                INSERT INTO employees (jid, name, dept, role, email)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(jid) DO UPDATE SET
                    name=excluded.name,
                    dept=excluded.dept,
                    role=excluded.role,
                    email=excluded.email
            """, (username, info["display_name"], info["department"], info["role"], info["email"]))
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        log.info(f"Synced employee from AD: {username}")
        return True
    except Exception as e:
        log.error(f"AD sync error for {username}: {e}")
        return False


def list_department_members(department: str) -> list[dict]:
    """List all AD users in a given department."""
    if not is_configured():
        return []
    conn = None
    try:
        from ldap3 import Server, Connection, ALL, SIMPLE, SUBTREE
        server = Server(LDAP_URL, get_info=ALL)
        bind_dn = os.getenv("LDAP_BIND_DN", "")
        bind_pw = os.getenv("LDAP_BIND_PASSWORD", "")
        conn = Connection(server, user=bind_dn, password=bind_pw, authentication=SIMPLE)
        if not conn.bind():
            log.error(f"LDAP bind failed: {conn.result}")
            return []
        conn.search(
            search_base=LDAP_USER_SEARCH_BASE or LDAP_BASE_DN,
            search_filter=f"(&(objectClass=user)(department={_ldap_escape(department)}))",
            search_scope=SUBTREE,
            attributes=["cn", "mail", "sAMAccountName", "title"],
        )
        return [
            {
                "username": str(e.sAMAccountName),
                "display_name": str(e.cn),
                "email": str(e.mail) if hasattr(e, "mail") else "",
                "title": str(e.title) if hasattr(e, "title") else "",
            }
            for e in conn.entries
        ]
    except Exception as e:
        log.error(f"LDAP list_department error: {e}")
        return []
    finally:
        if conn:
            try:
                conn.unbind()
            except Exception:
                pass
