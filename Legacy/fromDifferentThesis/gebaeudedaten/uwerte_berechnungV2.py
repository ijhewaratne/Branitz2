import json
import sys

# Alle Gebäudefunktionen mit Codes
gebaeude_codes = {
    "Garage": "2463",
    "Pumpstation": "2512",
    "Nach Quellenlage nicht zu spezifizieren": "9998",
    "Wohnhaus": "1010",
    "Umformer": "2523",
    "Gebäude zur Freizeitgestaltung": "1310",
    "Land- und forstwirtschaftliches Betriebsgebäude": "2720",
    "Heizwerk": "2580",
    "Schuppen": "2723",
    "Hallenbad": "3221",
    "Gebäude zum Parken": "2460",
    "Stall": "2724",
    "Fahrzeughalle": "2464",
    "Gebäude für Wirtschaft oder Gewerbe": "2000",
    "Produktionsgebäude": "2110",
    "Verwaltungsgebäude": "3010",
    "Wohngebäude": "1000",
    "Geschäftsgebäude": "2050",
    "Hotel, Motel, Pension": "2071",
    "Werkstatt": "2120",
    "Bürogebäude": "2020",
    "Gebäude für Handel und Dienstleistungen": "2010",
    "Badegebäude": "3220",
    "Gartenhaus": "1313",
    "Gebäude für Erholungszwecke": "3200",
    "Friedhofsgebäude": "3080",
    "Gebäude für Vorratshaltung": "2140",
    "Lagerhalle, Lagerschuppen, Lagerhaus": "2143",
    "Gebäude für Bewirtung": "2080",
    "Gebäude für soziale Zwecke": "3060",
    "Gebäude zur Elektrizitätsversorgung": "2520",
    "Veranstaltungsgebäude": "3036",
    "Gaststätte, Restaurant": "2081",
    "Treibhaus, Gewächshaus": "2740",
    "Wohngebäude mit Handel und Dienstleistungen": "1120",
    "Wohngebäude mit Gewerbe und Industrie": "1130",
    "Gebäude im botanischen Garten": "3270",
    "Betriebsgebäude für Straßenverkehr": "2410",
    "Gebäude für Beherbergung": "2070",
    "Betriebsgebäude": "2112",
    "Überdachung": "1610",
    "Schornstein": "1290"
}

# Standardwärmeübergangswiderstände nach DIN EN ISO 6946
R_si = 0.13
R_se = 0.04

# Beispielhafte Materialien (Dicke [m], λ [W/mK]) aus Normwerten
materialien = {
    "Innenputz": {"d": 0.015, "lambda": 0.35},
    "Mauerwerk_standard": {"d": 0.24, "lambda": 0.70},   # normaler Ziegel
    "Mauerwerk_hochdaemmend": {"d": 0.425, "lambda": 0.10}, # hochwärmedämmender Ziegel
    "Aussenputz": {"d": 0.025, "lambda": 0.87},
    "Dach_innenverkleidung": {"d": 0.015, "lambda": 0.35},
    "Dach_daemmung": {"d": 0.20, "lambda": 0.035},
    "Dach_abdichtung": {"d": 0.005, "lambda": 0.20},
    "Boden_estrich": {"d": 0.04, "lambda": 2.10},
    "Boden_daemmung": {"d": 0.10, "lambda": 0.035},
    "Beton": {"d": 0.20, "lambda": 2.30},
    "Trapezblech": {"d": 0.001, "lambda": 50.0},
    "Holzrahmen": {"d": 0.20, "lambda": 0.13},
    "EPS": {"d": 0.10, "lambda": 0.035},
    "Mineralwolle": {"d": 0.10, "lambda": 0.035}
}

# Typische Standardaufbauten für unterschiedliche Kategorien:
# Wir definieren Funktionen, die anhand des Gebäudenamens einen typischen Aufbau zurückgeben.
# Die Berechnungen erfolgen aus diesen Aufbauten.

def berechne_u_wert(schichten):
    R = 0.0
    for s in schichten:
        if s in materialien:
            d = materialien[s]["d"]
            lam = materialien[s]["lambda"]
            R += d/lam
        else:
            # Unbekanntes Material -> Warnung und R=1.0 addieren (konservativ)
            print(f"Warnung: Material '{s}' ist nicht bekannt, R=1.0 angenommen.", file=sys.stderr)
            R += 1.0
    R_total = R_si + R + R_se
    return 1.0 / R_total

def klassifiziere_gebaeude(geb_typ):
    # Aus Schlüsselwörtern Kategorien ableiten
    g = geb_typ.lower()

    # Vereinfachte Heuristiken für Bauteilaufbauten.
    # Wohngebäude: hochwärmedämmendes Mauerwerk
    # Industriehalle: Trapezblech, weniger Dämmung etc.
    # Hier werden typische Aufbauten je Kategorie definiert.

    # Kategorien (verfeinerte Zuordnung):
    if "wohnhaus" in g or "wohngebäude" in g or "hotel" in g or "pension" in g or ("beherbergung" in g and "gewerbe" not in g):
        # Wohnartig, gut gedämmt
        wand = ["Innenputz", "Mauerwerk_hochdaemmend", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung", "Dach_abdichtung"]
        boden = ["Boden_estrich", "Boden_daemmung", "Beton"]
        fenster_u = 1.3
        fensterflaechenanteil = 0.20
        innentemperatur = 20
        luftwechselrate = 0.5
    elif "büro" in g or "verwaltungs" in g or "geschäftsgebäude" in g or "handel und dienstleistungen" in g:
        # Büro/Verwaltung, etwas erhöhtes Fensteranteil, aber noch relativ gut gedämmt
        wand = ["Innenputz", "Mauerwerk_standard", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung", "Dach_abdichtung"]
        boden = ["Boden_estrich", "Boden_daemmung", "Beton"]
        fenster_u = 1.3
        fensterflaechenanteil = 0.30
        innentemperatur = 20
        luftwechselrate = 2.0
    elif "gaststätte" in g or "restaurant" in g or "bewirtung" in g:
        # Gastronomie: ähnlich Wohnbau, aber höhere Luftwechselrate
        wand = ["Innenputz", "Mauerwerk_standard", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung", "Dach_abdichtung"]
        boden = ["Boden_estrich", "Boden_daemmung", "Beton"]
        fenster_u = 1.3
        fensterflaechenanteil = 0.25
        innentemperatur = 20
        luftwechselrate = 3.0
    elif "produktion" in g or ("gewerbe" in g and "handel" not in g) or "werkstatt" in g or ("betriebsgebäude" in g and "straßenverkehr" not in g):
        # Industrie/Produktion/Wirtschaft: weniger gedämmt, höherer U-Wert Wand
        # Wir nehmen standard Mauerwerk, aber ohne Hochdämmung, und weniger Dämmung im Boden.
        wand = ["Innenputz", "Mauerwerk_standard", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung"]  # etwas weniger Schichten
        boden = ["Boden_estrich", "Beton"]  # kaum Dämmung
        fenster_u = 2.0
        fensterflaechenanteil = 0.20
        innentemperatur = 18
        luftwechselrate = 2.0
    elif "lagerhalle" in g or "schuppen" in g or "fahrzeughalle" in g:
        # Lagerhalle, Schuppen: sehr einfach, trapezblech statt Mauerwerk
        wand = ["Trapezblech"]
        dach = ["Trapezblech"]
        boden = ["Beton"]
        fenster_u = 3.0
        fensterflaechenanteil = 0.10
        innentemperatur = 15
        luftwechselrate = 1.0
    elif "garage" in g or "parken" in g:
        # Garage/Parken: ähnlich einfach wie Lagerhalle, etwas Dämmung ist optional
        wand = ["Mauerwerk_standard"]  # minimaler Aufbau
        dach = ["Dach_innenverkleidung"]  # kaum Dämmung
        boden = ["Beton"]
        fenster_u = 3.0
        fensterflaechenanteil = 0.05
        innentemperatur = 12
        luftwechselrate = 1.5
    elif "stall" in g or "land- und forstwirtschaftlich" in g:
        # Landwirtschaftlich: ähnlich einfach, aber wir nehmen Holzrahmen für Wände
        wand = ["Holzrahmen", "EPS", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung"]
        boden = ["Beton"]
        fenster_u = 3.0
        fensterflaechenanteil = 0.10
        innentemperatur = 12
        luftwechselrate = 2.0
    elif "badegebäude" in g or "hallenbad" in g:
        # Hallenbad: sehr gut gedämmt, hohe Temperatur
        wand = ["Innenputz", "Mauerwerk_hochdaemmend", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung", "Dach_abdichtung"]
        boden = ["Boden_estrich", "Boden_daemmung", "Beton"]
        fenster_u = 1.2
        fensterflaechenanteil = 0.50
        innentemperatur = 24
        luftwechselrate = 3.0
    elif "treibhaus" in g or "gewächshaus" in g:
        # Gewächshaus: viel Glas, kaum Dämmung
        wand = ["Aussenputz"]  # Platzhalter
        dach = ["Dach_abdichtung"]
        boden = ["Beton"]
        fenster_u = 5.0
        fensterflaechenanteil = 0.90
        innentemperatur = 25
        luftwechselrate = 1.0
    elif "heizwerk" in g or "umformer" in g or "pumpstation" in g or "elektrizitätsversorgung" in g:
        # Technische Gebäude: einfach, aber nicht ganz so schlecht wie Lagerhalle
        wand = ["Mauerwerk_standard", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung"]
        boden = ["Beton"]
        fenster_u = 2.5
        fensterflaechenanteil = 0.05
        innentemperatur = 15
        luftwechselrate = 1.0
    elif "freizeitgestaltung" in g or "erholungszwecke" in g or "soziale zwecke" in g or "veranstaltungsgebäude" in g or "vorratshaltung" in g or ("beherbergung" in g and "wohn" not in g):
        # Öffentliche oder Sondernutzungen: mittlere Werte
        wand = ["Innenputz", "Mauerwerk_standard", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung", "Dach_abdichtung"]
        boden = ["Boden_estrich", "Boden_daemmung", "Beton"]
        fenster_u = 1.3
        fensterflaechenanteil = 0.20
        innentemperatur = 20
        luftwechselrate = 1.5
    elif "botanischen garten" in g:
        # Botanischer Garten: ähnlich öffentlich, aber mehr Glas
        wand = ["Innenputz", "Mauerwerk_standard", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung", "Dach_abdichtung"]
        boden = ["Boden_estrich", "Boden_daemmung", "Beton"]
        fenster_u = 1.3
        fensterflaechenanteil = 0.30
        innentemperatur = 20
        luftwechselrate = 1.5
    elif "gartenhaus" in g or "friedhofsgebäude" in g or "überdachung" in g or "schornstein" in g:
        # Sehr einfache Bauten
        wand = ["Mauerwerk_standard"]
        dach = ["Dach_innenverkleidung"]
        boden = ["Beton"]
        fenster_u = 3.0
        fensterflaechenanteil = 0.05
        innentemperatur = 12
        luftwechselrate = 1.0
    elif "nach quellenlage" in g:
        # Nicht spezifizierbar
        wand = ["Innenputz", "Mauerwerk_standard", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung", "Dach_abdichtung"]
        boden = ["Boden_estrich", "Boden_daemmung", "Beton"]
        fenster_u = 1.5
        fensterflaechenanteil = 0.20
        innentemperatur = 20
        luftwechselrate = 1.0
    else:
        # Standardfall, falls nichts erkannt
        wand = ["Innenputz", "Mauerwerk_standard", "Aussenputz"]
        dach = ["Dach_innenverkleidung", "Dach_daemmung", "Dach_abdichtung"]
        boden = ["Boden_estrich", "Boden_daemmung", "Beton"]
        fenster_u = 1.5
        fensterflaechenanteil = 0.20
        innentemperatur = 20
        luftwechselrate = 1.0

    # U-Werte berechnen
    u_wand = berechne_u_wert(wand)
    u_dach = berechne_u_wert(dach)
    u_boden = berechne_u_wert(boden)

    # Gemittelter U-Wert für Außenwand mit Fensteranteil
    u_ausenwand = u_wand * (1 - fensterflaechenanteil) + fenster_u * fensterflaechenanteil

    return {
        "fensterflaechenanteil": fensterflaechenanteil,
        "u_ausenwand": round(u_ausenwand, 2),
        "u_fenster": fenster_u,
        "u_dach": round(u_dach, 2),
        "u_bodenplatte": round(u_boden, 2),
        "innentemperatur": innentemperatur,
        "luftwechselrate": luftwechselrate
    }

ergebnis = []
for geb_typ, code_str in gebaeude_codes.items():
    vals = klassifiziere_gebaeude(geb_typ)
    eintrag = {
        "code": int(code_str),
        "gebaeude_typ": geb_typ,
        "fensterflaechenanteil": vals["fensterflaechenanteil"],
        "u_ausenwand": vals["u_ausenwand"],
        "u_fenster": vals["u_fenster"],
        "u_dach": vals["u_dach"],
        "u_bodenplatte": vals["u_bodenplatte"],
        "innentemperatur": vals["innentemperatur"],
        "luftwechselrate": vals["luftwechselrate"]
    }
    ergebnis.append(eintrag)

with open("uwerte3.json", "w", encoding="utf-8") as f:
    json.dump(ergebnis, f, indent=2, ensure_ascii=False)

print("Berechnung abgeschlossen. Die Ergebnisse sind in 'gebaeude_funktionen_uwerte.json' gespeichert.")
