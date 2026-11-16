"""Demo environment: which organizations are demo ones and who can be impersonated.

``LEARNING_TRACKER_DEMO_MODE=true`` (``web/config.py``, only valid with
authentication off) makes the UI show a banner and a persona switcher. The
switcher is grouped by organization and read from here, from the members the
demo seed recorded (``scripts/seed_demo.py``), so a persona added to the seed
shows up without touching the front end.

``GET /demo/config`` is deliberately outside ``require_session``: the page
asks it before anyone has chosen an identity. It reveals nothing unless demo
mode is on, and demo mode cannot be on with authentication on.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request

#: The synthetic organizations the seed creates, and the only ones the
#: switcher offers or ``--reset`` touches.
SCHOOL_ORG_ID = "org_demo"
PUBLIC_SERVICE_ORG_ID = "org_servicio_publico"


@dataclass(frozen=True)
class DemoOrganization:
    org_id: str
    name: str
    #: How the UI names the org:admin and the plain members of this organization.
    admin_label: str
    member_label: str


DEMO_ORGANIZATIONS = (
    DemoOrganization(SCHOOL_ORG_ID, "Colegio Demo", "docente", "estudiante"),
    DemoOrganization(PUBLIC_SERVICE_ORG_ID, "Servicio Público Demo", "coordinación", "funcionario/a"),
)

router = APIRouter(tags=["demo"])


@router.get("/demo/config")
def demo_config(request: Request) -> dict:
    """``{"enabled": false}``, or the demo identities grouped by organization."""
    if not request.app.state.settings.demo_mode:
        return {"enabled": False, "groups": []}
    members = request.app.state.resources.members
    groups = []
    for org in DEMO_ORGANIZATIONS:
        listed = sorted(
            members.list_members(org.org_id),
            key=lambda m: (m.role != "org:admin", m.display_name or m.user_id),
        )
        groups.append(
            {
                "org_id": org.org_id,
                "name": org.name,
                "identities": [
                    {
                        "id": m.user_id,
                        "name": m.display_name or m.user_id,
                        "org": org.org_id,
                        "role": m.role,
                        "label": f"{m.display_name or m.user_id} "
                        f"({org.admin_label if m.role == 'org:admin' else org.member_label})",
                    }
                    for m in listed
                ],
            }
        )
    return {"enabled": True, "groups": groups}


__all__ = ["DEMO_ORGANIZATIONS", "DemoOrganization", "PUBLIC_SERVICE_ORG_ID", "SCHOOL_ORG_ID", "router"]
