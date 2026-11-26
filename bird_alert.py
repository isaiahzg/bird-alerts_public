"""Bird alerts: owls, raptors, and rare birds reported near you on eBird.

Runs on a schedule (GitHub Actions). Each run:
  1. Gets recent eBird sightings around your location.
  2. Keeps owls, raptors (hawks, eagles, ospreys, vultures, falcons),
     and any sighting eBird marks as notable (rare for the area).
  3. Drops anything farther than RADIUS_MILES.
  4. Sends a phone notification through ntfy for sightings not sent before.

Needs these environment variables (set as GitHub secrets):
  EBIRD_API_KEY   free key from https://ebird.org/api/keygen
  NTFY_TOPIC      a long random topic name you subscribe to in the ntfy app
  HOME_LAT        your latitude, e.g. 40.7998
  HOME_LNG        your longitude, e.g. -73.9678
Optional:
  RADIUS_MILES    default 2
  NTFY_SERVER     default https://ntfy.sh
  DRY_RUN=1       print alerts instead of sending them
"""

import hashlib
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EBIRD = "https://api.ebird.org/v2"
SEEN_FILE = Path(__file__).with_name("seen.json")
KEEP_SEEN_DAYS = 30

# Only alert on birds seen within this many hours. eBird times are local (New York).
MAX_AGE_HOURS = 2
LOCAL_TZ = ZoneInfo("America/New_York")

# eBird taxonomic orders to always alert on.
TARGET_ORDERS = {
    "Strigiformes": "Owl",
    "Accipitriformes": "Raptor",  # hawks, eagles, harriers, kites, osprey, vultures
    "Falconiformes": "Raptor",  # falcons, kestrels, merlins
}


def ebird_get(path, params, api_key):
    url = f"{EBIRD}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-eBirdApiToken": api_key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def miles_between(lat1, lng1, lat2, lng2):
    r = 3958.8  # Earth radius in miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def get_orders(species_codes, api_key):
    """Map species code -> taxonomic order, asking eBird only about codes we saw."""
    orders = {}
    codes = sorted(set(species_codes))
    for i in range(0, len(codes), 100):
        batch = codes[i : i + 100]
        rows = ebird_get(
            "/ref/taxonomy/ebird",
            {"species": ",".join(batch), "fmt": "json", "locale": "en"},
            api_key,
        )
        for row in rows:
            orders[row["speciesCode"]] = row.get("order", "")
    return orders


def is_fresh(obs, max_age_hours, now=None):
    """True if the sighting has a time and it was within the last max_age_hours."""
    try:
        seen_at = datetime.strptime(obs.get("obsDt", ""), "%Y-%m-%d %H:%M")
    except ValueError:
        return False  # date only, no time given: can't tell if it's live
    seen_at = seen_at.replace(tzinfo=LOCAL_TZ)
    now = now or datetime.now(LOCAL_TZ)
    return now - seen_at <= timedelta(hours=max_age_hours)


def find_alerts(recent, notable, orders, lat, lng, radius):
    """Combine both feeds into one list of alerts within the radius."""
    alerts = {}

    def add(obs, reason):
        if "lat" not in obs or "lng" not in obs:
            return
        dist = miles_between(lat, lng, obs["lat"], obs["lng"])
        if dist > radius:
            return
        key = f"{obs.get('subId', obs.get('obsDt'))}:{obs['speciesCode']}"
        if key in alerts:
            if reason not in alerts[key]["reasons"]:
                alerts[key]["reasons"].append(reason)
            return
        alerts[key] = {"key": key, "obs": obs, "dist": dist, "reasons": [reason]}

    for obs in recent:
        reason = TARGET_ORDERS.get(orders.get(obs["speciesCode"], ""))
        if reason:
            add(obs, reason)
    for obs in notable:
        add(obs, "Rare")
        # Rare owls and raptors get both labels.
        extra = TARGET_ORDERS.get(orders.get(obs["speciesCode"], ""))
        if extra:
            add(obs, extra)

    order = {"Rare": 0, "Owl": 1, "Raptor": 2}
    for a in alerts.values():
        a["reasons"].sort(key=lambda r: order[r])
    return sorted(alerts.values(), key=lambda a: (order[a["reasons"][0]], a["dist"]))


def format_alert(a):
    obs = a["obs"]
    name = obs["comName"]
    labels = " + ".join(a["reasons"])
    title = f"{labels}: {name}"
    count = obs.get("howMany")
    lines = [
        f"{count} seen" if count else "Number not reported",
        f"{obs.get('locName', 'Unknown location')} ({a['dist']:.1f} mi away)",
        f"Reported {obs.get('obsDt', '')}",
    ]
    if obs.get("obsValid") is False or obs.get("obsReviewed") is False:
        lines.append("Not yet confirmed by an eBird reviewer")
    if "subId" in obs:
        click = f"https://ebird.org/checklist/{obs['subId']}"
    else:
        click = f"https://ebird.org/species/{obs['speciesCode']}"
    maps = f"https://www.google.com/maps/search/?api=1&query={obs['lat']},{obs['lng']}"
    tags = {"Rare": "star", "Owl": "owl", "Raptor": "eagle"}
    return {
        "title": title,
        "message": "\n".join(lines),
        "click": click,
        "tags": [tags[a["reasons"][0]]],
        "priority": 4 if "Rare" in a["reasons"] or "Owl" in a["reasons"] else 3,
        "actions": [{"action": "view", "label": "Open map", "url": maps}],
    }


def send_ntfy(server, topic, payload):
    body = json.dumps({"topic": topic, **payload}).encode()
    req = urllib.request.Request(
        server, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def hide(key):
    """Store a scrambled version of each sighting ID so seen.json reveals no locations."""
    if len(key) == 16 and all(c in "0123456789abcdef" for c in key):
        return key
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def load_seen():
    if SEEN_FILE.exists():
        return {hide(k): v for k, v in json.loads(SEEN_FILE.read_text()).items()}
    return {}


def save_seen(seen):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_SEEN_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN_FILE.write_text(json.dumps(seen, indent=0, sort_keys=True) + "\n")


def main():
    api_key = os.environ["EBIRD_API_KEY"]
    lat = float(os.environ["HOME_LAT"])
    lng = float(os.environ["HOME_LNG"])
    radius = float(os.environ.get("RADIUS_MILES") or 2)
    back = 1  # eBird's shortest lookback; is_fresh() trims to MAX_AGE_HOURS
    dry_run = os.environ.get("DRY_RUN") == "1"
    topic = os.environ.get("NTFY_TOPIC", "")
    server = os.environ.get("NTFY_SERVER") or "https://ntfy.sh"
    if not dry_run and not topic:
        sys.exit("NTFY_TOPIC is not set")

    # eBird searches in whole km; search a bit wider, then trim by exact miles.
    km = math.ceil(radius * 1.609) + 1
    params = {"lat": lat, "lng": lng, "dist": km, "back": back}
    recent = ebird_get("/data/obs/geo/recent", {**params, "includeProvisional": "true"}, api_key)
    notable = ebird_get("/data/obs/geo/recent/notable", {**params, "detail": "simple"}, api_key)

    orders = get_orders([o["speciesCode"] for o in recent + notable], api_key)
    alerts = find_alerts(recent, notable, orders, lat, lng, radius)

    seen = load_seen()
    now = datetime.now(timezone.utc).isoformat()
    sent = 0
    alerts = [a for a in alerts if is_fresh(a["obs"], MAX_AGE_HOURS)]
    for a in alerts:
        if hide(a["key"]) in seen:
            continue
        payload = format_alert(a)
        if dry_run:
            print(json.dumps(payload, indent=2))
        else:
            send_ntfy(server, topic, payload)
        seen[hide(a["key"])] = now
        sent += 1
    save_seen(seen)
    print(f"{len(recent)} recent, {len(notable)} notable, {len(alerts)} in range from the last {MAX_AGE_HOURS} hours, {sent} new alerts")


if __name__ == "__main__":
    main()
