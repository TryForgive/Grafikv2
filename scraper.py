import os
import datetime
import urllib.request
import json
import pytz
from icalendar import Calendar, Event
from playwright.sync_api import sync_playwright

PESEL = os.environ.get("MY_PESEL")
LOGIN = os.environ.get("MY_LOGIN")
PASSWORD = os.environ.get("MY_PASSWORD")

# Adres Webhooka z Discorda
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

TZ = pytz.timezone("Europe/Warsaw")
HISTORY_SEPARATOR = b"\n\n================= HISTORIA ZMIAN =================\n"

def send_discord_notification(message):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        # Formatowanie wiadomości dla Discorda
        payload = {
            "content": f"🚨 **Zmiana w grafiku Rossmann!**\n```{message}```"
        }
        data = json.dumps(payload).encode("utf-8")
        
        req = urllib.request.Request(
            DISCORD_WEBHOOK_URL, 
            data=data, 
            headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        )
        urllib.request.urlopen(req)
        print("Wysłano powiadomienie na Discord.")
    except Exception as e:
        print(f"Błąd wysyłania powiadomienia Discord: {e}")

def create_event(date_str, time_str, summary):
    event = Event()
    event.add('summary', summary)
    
    unique_id = f"rossmann-{date_str}-{summary.replace(' ', '')}@grafik"
    event.add('uid', unique_id)
    
    if "00:00" in time_str or summary in ["Urlop Wypoczynkowy", "Odbiór za sobotę"]:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        event.add('dtstart', date_obj)
        event.add('dtend', date_obj + datetime.timedelta(days=1))
    else:
        times = time_str.replace("–", "-").split("-")
        if len(times) == 2:
            start_time = times[0].strip()
            end_time = times[1].strip()
            try:
                start_dt = TZ.localize(datetime.datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M"))
                end_dt = TZ.localize(datetime.datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M"))
                event.add('dtstart', start_dt)
                event.add('dtend', end_dt)
            except Exception as e:
                print(f"Błąd konwersji czasu dla: {date_str} {time_str} - {e}")
                
    return event

def main():
    old_schedule = {}
    history_content = b""

    if os.path.exists('grafik.ics'):
        try:
            with open('grafik.ics', 'rb') as f:
                content = f.read()
                
            parts = content.split(HISTORY_SEPARATOR)
            ics_data = parts[0]
            if len(parts) > 1:
                history_content = parts[1]
                
            old_cal = Calendar.from_ical(ics_data)
            for component in old_cal.walk('VEVENT'):
                start = component.get('dtstart').dt
                summary = str(component.get('summary'))
                
                if type(start) is datetime.date:
                    date_str = start.strftime("%Y-%m-%d")
                    old_schedule[date_str] = summary
                else:
                    start_local = start.astimezone(TZ)
                    end_local = component.get('dtend').dt.astimezone(TZ)
                    date_str = start_local.strftime("%Y-%m-%d")
                    old_schedule[date_str] = f"{summary} {start_local.strftime('%H:%M')} - {end_local.strftime('%H:%M')}"
        except Exception as e:
            print(f"Informacja: Tworzenie pliku od zera lub błąd odczytu: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Logowanie do portalu...")
        page.goto("https://panelpracownika.rossmann.pl/")

        czysty_login = LOGIN.strip() if LOGIN else ""
        czysty_haslo = PASSWORD.strip() if PASSWORD else ""
        czysty_pesel = PESEL.strip() if PESEL else ""

        page.fill("input#login", czysty_login)
        page.fill("input#password", czysty_haslo)
        
        pesel_inputs = page.locator(".pesel-input").all()
        for index, input_field in enumerate(pesel_inputs):
            if input_field.is_enabled():
                input_field.click()
                page.keyboard.type(czysty_pesel[index], delay=100)
                page.wait_for_timeout(200)

        page.click('button[data-testid="main-login-submit-btn"]')
        page.wait_for_timeout(10000)
        
        error_element = page.locator(".error-message")
        if error_element.is_visible():
            error_text = error_element.inner_text().strip()
            if error_text:
                print(f"!!! BŁĄD LOGOWANIA OD SERWERA: {error_text} !!!")
                browser.close()
                exit(1)
        
        print("Przechodzenie do grafiku...")
        page.goto("https://panelpracownika.rossmann.pl/management-shop-module/#/schedule")
        
        try:
            page.wait_for_selector('td[data-label="Dzień"]', state='visible', timeout=20000)
            page.wait_for_timeout(2000)
        except Exception as e:
            print("!!! BŁĄD: Dane grafiku nie załadowały się na czas !!!")
            browser.close()
            raise e

        print("Parsowanie grafiku i szukanie zmian...")
        cal = Calendar()
        cal.add('prodid', '-//Mój Grafik Rossmann//')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'Grafik Pracy')
        cal.add('x-wr-timezone', 'Europe/Warsaw')

        rows = page.locator("tbody.ross-table__body tr.ross-table__row").all()
        new_schedule = {}
        
        for row in rows:
            date_str = row.locator('td[data-label="Dzień"]').inner_text().strip()
            time_str = row.locator('td[data-label="Od - Do"]').inner_text().strip()
            summary = row.locator('td[data-label="Czynność"]').inner_text().strip()
            
            if not date_str:
                continue
                
            if summary == "" and time_str == "":
                new_state = "Dzień wolny"
            elif "00:00" in time_str or summary in ["Urlop Wypoczynkowy", "Odbiór za sobotę"]:
                new_state = summary
            else:
                times = time_str.replace("–", "-").split("-")
                if len(times) == 2:
                    new_state = f"{summary} {times[0].strip()} - {times[1].strip()}"
                else:
                    new_state = f"{summary} {time_str}"
                    
            new_schedule[date_str] = new_state
            
            if summary and date_str:
                event = create_event(date_str, time_str, summary)
                if event.get('dtstart'):
                    cal.add_component(event)

        changes = []
        for date_str in sorted(new_schedule.keys()):
            if date_str in old_schedule:
                old_state = old_schedule[date_str]
                new_state = new_schedule[date_str]
                
                if old_state != new_state:
                    changes.append(f'Dzień: "{date_str}" Godziny "{old_state}" zmieniono na Godziny "{new_state}"')
        
        if changes:
            now_str = datetime.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
            history_content += f"\nAktualizacja: {now_str}\n".encode('utf-8')
            
            notification_text = f"Aktualizacja: {now_str}\n"
            for change in changes:
                history_content += f"- {change}\n".encode('utf-8')
                notification_text += f"- {change}\n"
                print(f"WYKRYTO ZMIANĘ: {change}")
            
            # Wysłanie powiadomienia na Discord
            send_discord_notification(notification_text)
        else:
            print("Brak nowych zmian w grafiku.")

        with open('grafik.ics', 'wb') as f:
            f.write(cal.to_ical())
            if history_content:
                f.write(HISTORY_SEPARATOR)
                f.write(history_content)
                
        print("Zakończono sukcesem. Wygenerowano plik grafik.ics")
        browser.close()

if __name__ == "__main__":
    main()
