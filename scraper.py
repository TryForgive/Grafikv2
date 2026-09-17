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

        # Wypełnienie formularza logowania (uderzamy precyzyjnie w tagi input)
        page.fill("input#login", LOGIN)
        page.fill("input#password", PASSWORD)
        
        pesel_inputs = page.locator(".pesel-input").all()
        for index, input_field in enumerate(pesel_inputs):
            if input_field.is_enabled():
                input_field.fill(PESEL[index])

        # Precyzyjne kliknięcie w przycisk
        page.click('button[data-testid="main-login-submit-btn"]')
        
        # WAŻNE: Dajemy stronie 4 sekundy na autoryzację i przetworzenie logowania
        page.wait_for_timeout(4000)
        
        # Diagnostyka: Sprawdzenie, czy formularz nie zwrócił błędu na czerwono
        error_element = page.locator(".error-message")
        if error_element.is_visible():
            error_text = error_element.inner_text().strip()
            if error_text:
                print(f"!!! BŁĄD LOGOWANIA OD SERWERA: {error_text} !!!")
                print("Sprawdź poprawność wpisanych zmiennych w GitHub Secrets.")
                browser.close()
                exit(1)
        
        print("Przechodzenie do grafiku...")
        page.goto("https://panelpracownika.rossmann.pl/management-shop-module/#/schedule")
        
        try:
            # Czekamy na załadowanie głównej tabeli z grafikiem (max 20 sekund)
            page.wait_for_selector("table.ross-table", timeout=20000)
        except Exception as e:
            print("!!! BŁĄD: Tabela nie załadowała się na czas !!!")
            print("--- CO AKTUALNIE WIDZI BOT NA EKRANIE? (Początek strony) ---")
            # Drukujemy do logów zawartość ekranu, by wiedzieć na czym utknął
            print(page.locator("body").inner_text()[:1500])
            print("----------------------------------------------------------")
            browser.close()
            raise e

        print("Parsowanie grafiku...")
        cal = Calendar()
        cal.add('prodid', '-//Mój Grafik Rossmann//')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'Grafik Pracy')
        cal.add('x-wr-timezone', 'Europe/Warsaw')

        # Pobieramy wszystkie wiersze z danymi (omijamy nagłówek)
        rows = page.locator("tbody.ross-table__body tr.ross-table__row").all()
        
        for row in rows:
            date_str = row.locator('td[data-label="Dzień"]').inner_text().strip()
            time_str = row.locator('td[data-label="Od - Do"]').inner_text().strip()
            summary = row.locator('td[data-label="Czynność"]').inner_text().strip()
            
            # Dodajemy do kalendarza tylko te dni, w których przypisana jest czynność
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
