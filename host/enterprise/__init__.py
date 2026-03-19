"""MinionDesk Enterprise package."""
try:
    from .dept_init import init_department_groups
except ImportError:
    pass

try:
    from .weekly_report import weekly_report_loop, set_send_callback
except ImportError:
    pass

try:
    from . import jira_webhook
except ImportError:
    pass

try:
    from .workflow import check_expiry_and_reminders
except ImportError:
    pass
