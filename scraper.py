import os
import datetime
import pytz
from icalendar import Calendar, Event
from playwright.sync_api import sync_playwright

PESEL = os.environ.get("MY_PESEL")
LOGIN = os.environ.get("MY_LOGIN")
PASSWORD = os.environ.get("MY_PASSWORD")
TZ = pytz.timezone("Europe/Warsaw")

def create_event(date_str, time_str, summary):
    event = Event()
    event.add('summary', summary)
    
    # Tworzymy unikalne ID zdarzenia
    unique_id = f"rossmann-{date_str}-{summary.replace(' ', '')}@grafik"
    event.add('uid', unique_id)
    
    # Obsługa zdarzeń całodniowych
    if "00:00" in time_str or summary in ["Urlop Wypoczynkowy", "Odbiór za sobotę"]:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        event.add('dtstart', date_obj)
        event.add('dtend', date_obj + datetime.timedelta(days=1))
        
    # Obsługa standardowych godzin (np. 06:00 - 14:00)
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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Logowanie do portalu...")
        page.goto("https://panelpracownika.rossmann.pl/")

        # Czyszczenie ukrytych spacji ze zmiennych
        czysty_login = LOGIN.strip() if LOGIN else ""
        czysty_haslo = PASSWORD.strip() if PASSWORD else ""
        czysty_pesel = PESEL.strip() if PESEL else ""

        # Wypełnienie formularza logowania
        page.fill("input#login", czysty_login)
        page.fill("input#password", czysty_haslo)
        
        pesel_inputs = page.locator(".pesel-input").all()
        for index, input_field in enumerate(pesel_inputs):
            if input_field.is_enabled():
                input_field.click()
                page.keyboard.type(czysty_pesel[index], delay=100)
                page.wait_for_timeout(200)

        page.click('button[data-testid="main-login-submit-btn"]')
        page.wait_for_timeout(4000)
        
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
            # WAŻNA ZMIANA: Czekamy, aż na stronie pojawi się fizycznie komórka z datą,
            # co daje nam gwarancję, że dane z serwera dotarły do przeglądarki
            page.wait_for_selector('td[data-label="Dzień"]', state='visible', timeout=20000)
            
            # Dajemy Angularowi dodatkowe 2 sekundy na wyrenderowanie reszty wierszy
            page.wait_for_timeout(2000)
        except Exception as e:
            print("!!! BŁĄD: Dane grafiku nie załadowały się na czas !!!")
            browser.close()
            raise e

        print("Parsowanie grafiku...")
        cal = Calendar()
        cal.add('prodid', '-//Mój Grafik Rossmann//')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'Grafik Pracy')
        cal.add('x-wr-timezone', 'Europe/Warsaw')

        rows = page.locator("tbody.ross-table__body tr.ross-table__row").all()
        print(f"Znaleziono {len(rows)} wierszy w tabeli.")
        
        for row in rows:
            date_str = row.locator('td[data-label="Dzień"]').inner_text().strip()
            time_str = row.locator('td[data-label="Od - Do"]').inner_text().strip()
            summary = row.locator('td[data-label="Czynność"]').inner_text().strip()
            
            # Logowanie do konsoli (będziesz widział to w zakładce Actions)
            if date_str and summary:
                print(f"-> Dodaję do kalendarza: {date_str} | {time_str} | {summary}")
                event = create_event(date_str, time_str, summary)
                # Omijamy zdarzenia uszkodzone
                if event.get('dtstart'):
                    cal.add_component(event)
        
        with open('grafik.ics', 'wb') as f:
            f.write(cal.to_ical())
            
        print("Zakończono sukcesem. Wygenerowano plik grafik.ics")
        browser.close()

if __name__ == "__main__":
    main()
