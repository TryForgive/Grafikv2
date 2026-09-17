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
    
    # Tworzymy unikalne ID zdarzenia (zapobiega to duplikatom przy aktualizacji)
    unique_id = f"rossmann-{date_str}-{summary.replace(' ', '')}@grafik"
    event.add('uid', unique_id)
    
    # Obsługa zdarzeń całodniowych (Urlop, Odbiór, 00:00-00:00)
    if "00:00" in time_str or summary in ["Urlop Wypoczynkowy", "Odbiór za sobotę"]:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        event.add('dtstart', date_obj)
        # Zgodnie ze standardem ICS wydarzenie całodniowe kończy się następnego dnia o północy
        event.add('dtend', date_obj + datetime.timedelta(days=1))
    
    # Obsługa standardowych godzin (np. 06:00 - 14:00)
    elif "-" in time_str:
        # Standaryzacja myślnika i usunięcie spacji, aby zapobiec błędom
        times = time_str.replace("–", "-").split("-")
        if len(times) == 2:
            start_time = times[0].strip()
            end_time = times[1].strip()
            
            start_dt = TZ.localize(datetime.datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M"))
            end_dt = TZ.localize(datetime.datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M"))
            
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)
    
    return event

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Logowanie do portalu...")
        page.goto("https://panelpracownika.rossmann.pl/")

        # Wypełnienie formularza logowania
        page.fill("#login", LOGIN)
        page.fill("#password", PASSWORD)
        
        pesel_inputs = page.locator(".pesel-input").all()
        for index, input_field in enumerate(pesel_inputs):
            if input_field.is_enabled():
                input_field.fill(PESEL[index])

        page.click('[data-testid="main-login-submit-btn"]')
        page.wait_for_load_state("networkidle")
        
        print("Przechodzenie do grafiku...")
        # Bezpośrednie przejście do modułu drogerii i grafiku
        page.goto("https://panelpracownika.rossmann.pl/management-shop-module/#/schedule")
        
        # Oczekujemy aż tabela grafiku pojawi się w kodzie HTML
        page.wait_for_selector("table.ross-table")
        page.wait_for_load_state("networkidle")

        print("Parsowanie grafiku...")
        cal = Calendar()
        cal.add('prodid', '-//Mój Grafik Rossmann//')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'Grafik Pracy')
        cal.add('x-wr-timezone', 'Europe/Warsaw')

        # Pobieramy wszystkie wiersze z danymi (omijamy nagłówek)
        rows = page.locator("tbody.ross-table__body tr.ross-table__row").all()
        
        for row in rows:
            # Używamy atrybutów data-label aby precyzyjnie trafić w odpowiednie kolumny
            date_str = row.locator('td[data-label="Dzień"]').inner_text().strip()
            time_str = row.locator('td[data-label="Od - Do"]').inner_text().strip()
            summary = row.locator('td[data-label="Czynność"]').inner_text().strip()
            
            # Dodajemy do kalendarza tylko te dni, w których jest przypisana jakakolwiek czynność
            # (To pomija dni wolne oznaczane na czerwono/szaro, które nie mają wpisu w kolumnie Czynność)
            if date_str and summary:
                event = create_event(date_str, time_str, summary)
                cal.add_component(event)
        
        # Zapis kalendarza do pliku
        with open('grafik.ics', 'wb') as f:
            f.write(cal.to_ical())
            
        print("Zakończono sukcesem. Wygenerowano plik grafik.ics")
        browser.close()

if __name__ == "__main__":
    main()
