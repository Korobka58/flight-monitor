#!/usr/bin/env python3
import os
import yaml
import requests
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def search_kiwi(origin, destination, cfg, api_key):
    s = cfg["settings"]
    date_from = datetime.now().strftime("%d/%m/%Y")
    date_to = (datetime.now() + timedelta(days=s["days_ahead"])).strftime("%d/%m/%Y")
    url = "https://tequila-api.kiwi.com/v2/search"
    params = {
        "fly_from": origin,
        "fly_to": destination["code"],
        "date_from": date_from,
        "date_to": date_to,
        "nights_in_dst_from": s["nights_min"],
        "nights_in_dst_to": s["nights_max"],
        "flight_type": "round",
        "adults": s["adults"],
        "currency": s["currency"],
        "limit": 3,
        "sort": "price",
        "one_for_city": 1,
    }
    headers = {"apikey": api_key}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for flight in data.get("data", []):
            results.append({
                "source": "Kiwi",
                "origin": origin,
                "destination": destination["code"],
                "destination_name": destination["name"],
                "price": flight["price"],
                "currency": s["currency"],
                "departure": flight["local_departure"][:10],
                "return": flight["route"][-1]["local_arrival"][:10] if flight.get("route") else "?",
                "duration_h": round(flight.get("duration", {}).get("total", 0) / 3600, 1),
                "airlines": ", ".join(set(r.get("airline", "") for r in flight.get("route", []))),
                "link": flight.get("deep_link", "https://www.kiwi.com"),
                "threshold": destination["threshold"],
            })
        return results
    except Exception as e:
        print(f"  Kiwi error {origin}->{destination['code']}: {e}")
        return []


def search_aviasales(origin, destination, cfg, token):
    s = cfg["settings"]
    url = "https://api.travelpayouts.com/v1/prices/cheap"
    params = {
        "origin": origin,
        "destination": destination["code"],
        "currency": s["currency"],
        "token": token,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        flights = data.get("data", {}).get(destination["code"], {})
        for _, flight in list(flights.items())[:3]:
            price = flight.get("price", 0)
            depart_date = flight.get("depart_date", "?")
            return_date = flight.get("return_date", "?")
            results.append({
                "source": "Aviasales",
                "origin": origin,
                "destination": destination["code"],
                "destination_name": destination["name"],
                "price": price,
                "currency": s["currency"],
                "departure": depart_date,
                "return": return_date,
                "duration_h": "?",
                "airlines": flight.get("airline", "?"),
                "link": f"https://www.aviasales.ru/search/{origin}{depart_date.replace('-','')}{destination['code']}1",
                "threshold": destination["threshold"],
            })
        return results
    except Exception as e:
        print(f"  Aviasales error {origin}->{destination['code']}: {e}")
        return []


def send_email(alerts, cfg):
    em = cfg["email"]
    sender = os.environ.get("EMAIL_SENDER", em.get("sender", ""))
    recipient = os.environ.get("EMAIL_RECIPIENT", em.get("recipient", ""))
    password = os.environ.get("EMAIL_PASSWORD", "")
    if not all([sender, recipient, password]):
        print("Email credentials not set — skipping send.")
        return
    subject = f"✈️ {len(alerts)} дешёвых рейса! [{datetime.now().strftime('%d.%m.%Y')}]"
    rows = ""
    for a in alerts:
        rows += f"""
        <tr>
          <td>{a['origin']} → {a['destination']}</td>
          <td>{a['destination_name']}</td>
          <td><b style="color:#e74c3c">€{a['price']}</b></td>
          <td>€{a['threshold']}</td>
          <td>{a['departure']}</td>
          <td>{a['return']}</td>
          <td>{a['airlines']}</td>
          <td>{a['source']}</td>
          <td><a href="{a['link']}">Купить →</a></td>
        </tr>"""
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333">
    <h2>✈️ Дешёвые рейсы — {datetime.now().strftime('%d.%m.%Y %H:%M')}</h2>
    <p>Найдено <b>{len(alerts)}</b> рейсов ниже порога:</p>
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
      <thead style="background:#2c3e50;color:white">
        <tr>
          <th>Маршрут</th><th>Город</th><th>Цена</th><th>Порог</th>
          <th>Вылет</th><th>Возврат</th><th>Авиакомпания</th><th>Источник</th><th>Ссылка</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    </body></html>
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(em["smtp_server"], em["smtp_port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"Email отправлен на {recipient}")
    except Exception as e:
        print(f"Email error: {e}")


def main():
    cfg = load_config()
    kiwi_key = os.environ.get("KIWI_API_KEY", "")
    aviasales_token = os.environ.get("AVIASALES_TOKEN", "")
    if not kiwi_key and not aviasales_token:
        print("Нет API ключей. Установи KIWI_API_KEY и/или AVIASALES_TOKEN.")
        return
    origins = cfg["origins"]
    destinations = cfg["destinations"]
    print(f"Проверяем {len(origins) * len(destinations)} маршрутов...\n")
    all_results = []
    for origin in origins:
        for dest in destinations:
            print(f"  {origin} → {dest['code']} ({dest['name']})")
            if kiwi_key:
                all_results.extend(search_kiwi(origin, dest, cfg, kiwi_key))
            if aviasales_token:
                all_results.extend(search_aviasales(origin, dest, cfg, aviasales_token))
    alerts = [r for r in all_results if r["price"] > 0 and r["price"] <= r["threshold"]]
    alerts.sort(key=lambda x: x["price"])
    print(f"\nВсего вариантов: {len(all_results)}, ниже порога: {len(alerts)}")
    if alerts:
        for a in alerts:
            print(f"  {a['origin']}→{a['destination']} ({a['destination_name']}): €{a['price']} | {a['departure']} | {a['source']}")
        send_email(alerts, cfg)
    else:
        print("Дешёвых рейсов не найдено.")


if __name__ == "__main__":
    main()
