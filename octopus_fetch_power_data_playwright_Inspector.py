

import asyncio
import json
from pathlib import Path
import pandas as pd
from playwright.async_api import async_playwright


CSV_FILE = "octopus_hourly.csv"
TARGET_DATE = "2026-03-13"  # Datum der Verbrauchswerte


CREDENTIALS_FILE = Path(__file__).parent / "octopus_credentials.json"

def load_credentials():
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(f"Credentials file not found: {CREDENTIALS_FILE}")
    with open(CREDENTIALS_FILE, "r") as f:
        creds = json.load(f)
    return creds["email"], creds["password"]

async def fetch_hourly_data():
    # Credentials laden
    email, password = load_credentials()  # ⚠️ hier wird email und password definiert

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Login
        await page.goto("https://octopusenergy.de/login/")
        await page.fill('input[name="email"]', email)
        await page.fill('input[name="password"]', password)
        await page.press('input[name="password"]', 'Enter')
        await page.wait_for_load_state("networkidle")
        print("Login erfolgreich")

        # Cookies für GraphQL Request holen
        cookies = await page.context.cookies()
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

        # GraphQL POST direkt absetzen
        url = "https://octopusenergy.de/api/graphql/kraken"
        headers = {
            "Content-Type": "application/json",
            "Cookie": cookie_header
        }
        payload = {
            "operationName": "getAccountMeasurements",
            "query": """
                query getAccountMeasurements(
                    $propertyId: ID!
                    $first: Int!
                    $utilityFilters: [UtilityFiltersInput!]
                    $startAt: DateTime
                    $endAt: DateTime
                    $timezone: String
                ) {
                    property(id: $propertyId) {
                        measurements(
                            first: $first
                            utilityFilters: $utilityFilters
                            startAt: $startAt
                            endAt: $endAt
                            timezone: $timezone
                        ) {
                            edges {
                                node {
                                    value
                                    unit
                                    ... on IntervalMeasurementType {
                                        startAt
                                        endAt
                                        durationInSeconds
                                    }
                                }
                            }
                        }
                    }
                }
            """,
            "variables": {
                "propertyId": "513541",
                "first": 100,
                "utilityFilters": [{"electricityFilters": {"readingFrequencyType": "HOUR_INTERVAL"}}],
                "startAt": f"{TARGET_DATE}T00:00:00.000Z",
                "endAt": f"{TARGET_DATE}T23:59:59.999Z",
                "timezone": "Europe/Berlin"
            }
        }

        response = await page.request.post(url, data=json.dumps(payload), headers=headers)
        data = await response.json()
        await browser.close()
        return data

def save_csv(data):
    edges = data.get("data", {}).get("property", {}).get("measurements", {}).get("edges", [])
    if not edges:
        print("Keine Messdaten gefunden.")
        return

    rows = []
    for entry in edges:
        node = entry["node"]
        if node.get("durationInSeconds") != 3600:
            continue
        rows.append({
            "startAt": node["startAt"],
            "endAt": node["endAt"],
            "value": node["value"],
            "unit": node["unit"],
            "durationSeconds": node["durationInSeconds"]
        })

    df = pd.DataFrame(rows)
    df.to_csv(CSV_FILE, index=False)
    print(f"CSV erstellt: {CSV_FILE}")

async def main():
    print("Daten abrufen...")
    data = await fetch_hourly_data()
    save_csv(data)
    print("Fertig.")

if __name__ == "__main__":
    asyncio.run(main())
