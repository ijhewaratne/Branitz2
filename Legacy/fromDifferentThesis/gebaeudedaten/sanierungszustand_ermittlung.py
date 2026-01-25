import json
from shapely.geometry import Point, Polygon, LineString, MultiLineString
from shapely.ops import nearest_points


def lade_gebaeude(gebaeude_json):
    """
    Lädt die Gebäudedaten aus der GeoJSON-Datei
    Return: Liste von Gebäuden mit ID und Geometrie
    """
    gebaeude = []
    for merkmal in gebaeude_json['features']:
        if merkmal['geometry']['type'] == 'Polygon':
            try:
                gebaeude.append({
                    'oi': merkmal['properties']['oi'],
                    'geometrie': Polygon(merkmal['geometry']['coordinates'][0])
                })
            except Exception as e:
                print(f"Fehler beim Laden des Gebäudes {merkmal['properties'].get('oi')}: {e}")
    return gebaeude


def lade_waermelinien(waerme_json):
    """
    Lädt die Wärmedichte-Linien aus der GeoJSON-Datei
    Return: Liste von Wärmelinien mit Dichtewert und Geometrie
    """
    waermelinien = []
    for eintrag in waerme_json['data']['reduce_scenario_set_heat_line_density']:
        try:
            dichte = eintrag.get('density_class', 0)
            koordinaten = eintrag['geometry']['coordinates']

            # Überprüfen des Geometrietyps
            if eintrag['geometry']['type'] == 'MultiLineString':
                linien = []
                for linie in koordinaten:
                    try:
                        linien.append(LineString(linie))
                    except Exception as e:
                        print(f"Fehler beim Erstellen der Linie: {e}")

                if linien:  # Nur hinzufügen, wenn gültige Linien vorhanden sind
                    waermelinien.append({
                        'dichte': dichte,
                        'geometrie': linien
                    })
            elif eintrag['geometry']['type'] == 'LineString':
                try:
                    waermelinien.append({
                        'dichte': dichte,
                        'geometrie': [LineString(koordinaten)]
                    })
                except Exception as e:
                    print(f"Fehler beim Erstellen der einzelnen Linie: {e}")

        except Exception as e:
            print(f"Fehler beim Verarbeiten eines Wärmelinien-Eintrags: {e}")
            continue

    return waermelinien


def klassifiziere_gebaeude(dichte):
    """
    Bestimmt den Sanierungszustand basierend auf dem Wärmedichtewert
    Return: Sanierungszustand als String

    Klassifizierung:
    - 0-10: vollsaniert
    - 11-999: teilsaniert
    - >= 1000: unsaniert
    """
    if dichte <= 10:
        return "vollsaniert"
    elif dichte < 1000:
        return "teilsaniert"
    else:
        return "unsaniert"


def finde_naechste_waermedichte(gebaeude_polygon, waermelinien):
    """
    Ermittelt den Wärmedichtewert der nächstgelegenen Wärmelinie für ein Gebäude
    Return: Wärmedichtewert der nächsten Linie
    """
    min_abstand = float('inf')
    naechste_dichte = 0
    gebaeude_schwerpunkt = gebaeude_polygon.centroid

    for waermelinie in waermelinien:
        for linie in waermelinie['geometrie']:
            try:
                abstand = gebaeude_schwerpunkt.distance(linie)
                if abstand < min_abstand:
                    min_abstand = abstand
                    naechste_dichte = waermelinie['dichte']
            except Exception as e:
                print(f"Fehler bei der Abstandsberechnung: {e}")
                continue

    return naechste_dichte


def analysiere_gebaeude(gebaeude_daten, waerme_daten):
    """
    Hauptfunktion zur Analyse der Gebäude
    Return: Dictionary mit Analyseergebnissen
    """
    # Daten laden und verarbeiten
    print("Lade Gebäudedaten...")
    gebaeude = lade_gebaeude(gebaeude_daten)
    print(f"{len(gebaeude)} Gebäude geladen.")

    print("Lade Wärmelinien...")
    waermelinien = lade_waermelinien(waerme_daten)
    print(f"{len(waermelinien)} Wärmelinien geladen.")

    # Jedes Gebäude analysieren
    ergebnisse = []
    gesamt = len(gebaeude)
    for i, gebaeude_obj in enumerate(gebaeude, 1):
        if i % 100 == 0:
            print(f"Analysiere Gebäude {i} von {gesamt}...")

        try:
            # Nächste Wärmedichte finden
            dichte = finde_naechste_waermedichte(gebaeude_obj['geometrie'], waermelinien)

            # Gebäude klassifizieren
            zustand = klassifiziere_gebaeude(dichte)

            # Zu Ergebnissen hinzufügen
            ergebnisse.append({
                'gebaeude_id': gebaeude_obj['oi'],
                'sanierungszustand': zustand,
                'waermedichte': dichte
            })
        except Exception as e:
            print(f"Fehler bei der Analyse von Gebäude {gebaeude_obj['oi']}: {e}")
            continue

    return {'gebaeude': ergebnisse}


if __name__ == "__main__":
    try:
        print("Starte Gebäudeanalyse...")

        # Gebäudedaten laden
        print("Lade Gebäude-JSON...")
        with open('hausumringe_branitzer_siedlung.json', 'r', encoding='utf-8') as f:
            gebaeude_daten = json.load(f)

        # Wärmedichtedaten laden
        print("Lade Wärmedichte-JSON...")
        with open('heat_line_density_cottbus.json', 'r', encoding='utf-8') as f:
            waerme_daten = json.load(f)

        # Gebäude analysieren
        ergebnisse = analysiere_gebaeude(gebaeude_daten, waerme_daten)

        # Ergebnisse speichern
        print("Speichere Ergebnisse...")
        with open('gebaeudeanalyse.json', 'w', encoding='utf-8') as f:
            json.dump(ergebnisse, f, indent=2, ensure_ascii=False)

        # Zusammenfassung ausgeben
        zustand_zaehler = {}
        for gebaeude in ergebnisse['gebaeude']:
            zustand = gebaeude['sanierungszustand']
            zustand_zaehler[zustand] = zustand_zaehler.get(zustand, 0) + 1

        print("\nAnalyse-Zusammenfassung:")
        print("------------------------")
        for zustand, anzahl in zustand_zaehler.items():
            print(f"{zustand}: {anzahl} Gebäude")

        print("\nAnalyse erfolgreich abgeschlossen!")

    except Exception as e:
        print(f"Ein Fehler ist aufgetreten: {e}")