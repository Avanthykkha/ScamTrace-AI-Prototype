from __future__ import annotations

from math import asin, cos, radians, sin, sqrt


def distance_km(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    lat1, lon1 = origin
    lat2, lon2 = destination
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        raise ValueError("Longitude must be between -180 and 180 degrees.")
    lat_delta = radians(lat2 - lat1)
    lon_delta = radians(lon2 - lon1)
    value = sin(lat_delta / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(lon_delta / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(value))


def synthetic_geo_fixture() -> list[dict[str, object]]:
    # These arbitrary coordinates are isolated from ULB and real account records.
    return [
        {
            "id": "GEO-DEMO-001",
            "account_ref": "SYN-ACCOUNT-A",
            "occurred_at": "2026-11-05T08:00:00+00:00",
            "location_label": "Synthetic Point Alpha",
            "latitude": 10.0,
            "longitude": 10.0,
            "synthetic": True,
            "source": "built-in synthetic geography fixture",
        },
        {
            "id": "GEO-DEMO-002",
            "account_ref": "SYN-ACCOUNT-A",
            "occurred_at": "2026-11-05T09:00:00+00:00",
            "location_label": "Synthetic Point Beta",
            "latitude": 35.0,
            "longitude": 45.0,
            "synthetic": True,
            "source": "built-in synthetic geography fixture",
        },
        {
            "id": "GEO-DEMO-003",
            "account_ref": "SYN-ACCOUNT-B",
            "occurred_at": "2026-11-05T08:30:00+00:00",
            "location_label": "Synthetic Point Gamma",
            "latitude": -20.0,
            "longitude": 80.0,
            "synthetic": True,
            "source": "built-in synthetic geography fixture",
        },
    ]


def geo_indicators(observations: list[dict[str, object]]) -> list[dict[str, object]]:
    by_account: dict[str, list[dict[str, object]]] = {}
    for observation in observations:
        by_account.setdefault(str(observation["account_ref"]), []).append(observation)
    output = []
    for account, entries in by_account.items():
        ordered = sorted(entries, key=lambda row: str(row["occurred_at"]))
        for previous, current in zip(ordered, ordered[1:]):
            km = distance_km(
                (float(previous["latitude"]), float(previous["longitude"])),
                (float(current["latitude"]), float(current["longitude"])),
            )
            reasons = []
            if km > 1000:
                reasons.append("Large geographic displacement between observed locations")
            output.append(
                {
                    "account_ref": account,
                    "from_observation": previous["id"],
                    "to_observation": current["id"],
                    "distance_km": round(km, 1),
                    "reasons": reasons,
                    "synthetic": all(bool(row["synthetic"]) for row in (previous, current)),
                    "source": previous["source"],
                }
            )
    return output
