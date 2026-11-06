"""Shared classification for Zoho request types that are not leave absence."""


def is_work_from_home_request(request: dict, configured_type_id: str = "") -> bool:
    name = str(request.get("leave_type_name") or request.get("type") or "").strip().casefold()
    type_id = str(request.get("leave_type_id") or "").strip()
    configured_type_id = configured_type_id.strip()
    return (
        "work from home" in name
        or "remote" in name
        or (bool(configured_type_id) and type_id == configured_type_id)
    )
