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


def search_aviasales(origin, destination, cfg, token):
    s = cfg["settings"]
    url = "https://api.travelpayouts.com/v2/prices/latest"
    params = {
        "origin": origin,
        "destination": destination["code"],
        "currency": s["currency"],
        "token": token,
        "limit": 3,
        "sorting": "price",
        "trip_class": 0,
        "one_way": False,
        "period_type": "month",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for flight in data.get("data", []):
            price = flight.get("value", 0)
            depart_date = flight.get("depart_date", "?")
            return_date = flight.get("return_date", "?")
            airline = flight.get("airline", "?")
            results.append({
                "source": "Aviasales",
                "origin": origin,
                "destination": destination["code"],
                "destination_name": destination["name"],
                "price": price,
                "currency": s["currency"],
                "departure": depart_date,
                "return": return_date,
                "airlines": airline,
                "link": f"https://www.aviasales.com/search/{origin}{depart_date.replace('-','')}{destination['code']}1",
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
    aviasales_token = os.environ.get("AVIASALES_TOKEN", "")
    if not aviasales_token:
        print("Нет API ключей. Установи AVIASALES_TOKEN.")
        return
    origins = cfg["origins"]
    destinations = cfg["destinations"]
    print(f"Проверяем {len(origins) * len(destinations)} маршрутов...\n")
    all_results = []
    for origin in origins:
        for dest in destinations:
            print(f"  {origin} → {dest['code']} ({dest['name']})")
            all_results.extend(search_aviasales(origin, dest, cfg, aviasales_token))
    alerts = [r for r in all_results if r["price"] > 0 and r["price"] <= r["threshold"]]
    alerts.sort(key=lambda x: x["price"])
    print(f"\nВсего вариантов: {len(all_results)}, ниже порога: {len(alerts)}")
    if alerts:
        for a in alerts:
            print(f"  {a['origin']}→{a['destination']} ({a['destination_name']}): €{a['price']} | {a['departure']} → {a['return']} | {a['airlines']}")
        send_email(alerts, cfg)
    else:
        print("Дешёвых рейсов не найдено.")


if __name__ == "__main__":
    main()
