# 📄 NameScanner — QR-Anker-System

> Automatisches Sortieren und Benennen von gescannten Schularbeiten per OCR und QR-Code-Erkennung.

---

## Was macht dieses Script?

NameScanner liest Fotos oder Scans von Schularbeiten ein, erkennt automatisch **Name**, **Klasse**, **Testname** und **Note** — und sortiert die Dateien danach in eine übersichtliche Ordnerstruktur. Am Ende wird pro Klasse und Test eine **Notenliste** als `.txt` Datei erstellt.

---

## Voraussetzungen

### Python-Pakete installieren

```bash
pip install easyocr thefuzz pillow numpy opencv-python pyzbar
```

### Zusätzlich auf Linux/Mac

```bash
sudo apt install libzbar0   # Linux
brew install zbar           # Mac
```

> Auf **Windows** ist kein zusätzlicher Schritt nötig.

---

## Erste Schritte

### 1. Script starten

```bash
python namescanner.py
```

Beim **ersten Start** werden automatisch alle benötigten Ordner erstellt:

```
📁 inbox/        ← Hier die Bilder reinlegen
📁 sorted/       ← Hier landen die sortierten Dateien
📁 sorted/UNBEKANNT/  ← Hierhin kommen nicht erkannte Dateien
```

### 2. Bilder in den `inbox/` Ordner legen

Unterstützte Formate: `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`

### 3. Script erneut starten — fertig

---

## Wie funktioniert die Erkennung?

Das System verwendet **QR-Codes als Anker**. Jeder QR-Code auf dem Dokument markiert ein Textfeld direkt daneben. Der QR-Code selbst enthält dabei seinen eigenen Typ als Text.

```
┌──────────┐    ┌─────────────────────────┐
│ QR-Code  │───▶│  Kitting-Muhr Jakob     │
│ "NAME"   │    └─────────────────────────┘
└──────────┘

┌──────────┐    ┌─────────────────────────┐
│ QR-Code  │───▶│  2AHIT                  │
│ "KLASSE" │    └─────────────────────────┘
└──────────┘

┌──────────┐    ┌─────────────────────────┐
│ QR-Code  │───▶│  1. Test SYT            │
│ "TEST"   │    └─────────────────────────┘
└──────────┘

┌──────────┐    ┌─────────────────────────┐
│ QR-Code  │───▶│  5                      │
│ "NOTE"   │    └─────────────────────────┘
└──────────┘
```

### QR-Code Inhalte

Die QR-Codes müssen exakt diese Texte kodieren (Groß-/Kleinschreibung egal):

| QR-Code Inhalt | Zugehöriges Feld |
|----------------|-----------------|
| `NAME`         | Name der Schülerin / des Schülers |
| `KLASSE`       | Klasse (z.B. `2AHIT`) |
| `TEST`         | Testname (z.B. `1. Test SYT`) |
| `NOTE`         | Note (z.B. `3` oder `2.5`) |

---

## Ergebnis-Struktur

Nach dem Durchlauf sieht der `sorted/` Ordner so aus:

```
sorted/
├── 2AHIT/
│   └── 1. Test SYT/
│       ├── 2AHIT_1.Test-SYT_Kitting-Muhr_Jakob.png
│       ├── 2AHIT_1.Test-SYT_Müller_Max.png
│       └── notenliste.txt
├── 3BHIF/
│   └── 2. Test AM/
│       ├── 3BHIF_2.Test-AM_Häusler_Valentin.png
│       └── notenliste.txt
└── UNBEKANNT/
    └── nicht_erkannte_datei.png
```

### Notenliste

Die `notenliste.txt` im jeweiligen Ordner sieht so aus:

```
Notenliste – 2AHIT – 1. Test SYT
==================================================
Häusler Valentin                    2
Kitting-Muhr Jakob                  5
Müller Max                          3
```

---

## Konfiguration

Alle Einstellungen befinden sich am Anfang des Scripts im Abschnitt `KONFIGURATION`.

### Referenzdaten anpassen

Das sind die Listen mit denen der OCR-Text verglichen wird (Fuzzy-Matching). Hier trägst du deine Schüler, Klassen und Tests ein:

```python
REFERENCE_ENTITIES = [
    "Kitting-Muhr Jakob",
    "Müller Max",
    # weitere Schüler...
]

REFERENCE_CLASSES = [
    "2AHIT",
    "3BHIF",
    # weitere Klassen...
]

REFERENCE_TESTS = [
    "1. Test SYT",
    "2. Test SYT",
    # weitere Tests...
]
```

### Textfeld-Größe anpassen

Falls der erkannte Bereich neben dem QR-Code zu klein oder zu groß ist:

```python
TEXT_OFFSET_X      = 0     # Abstand zwischen QR-Code und Textfeld (Pixel)
TEXT_WIDTH         = 950   # Breite des Textfeldes (Pixel)
TEXT_HEIGHT_FACTOR = 2.5   # Höhe = QR-Höhe × dieser Wert
```

### Erkennungs-Schwellwert anpassen

Wie sicher muss die Erkennung sein, bevor ein Treffer akzeptiert wird (0–100):

```python
MATCH_THRESHOLD_NAME  = 60   # Name (niedriger = toleranter)
MATCH_THRESHOLD_CLASS = 70   # Klasse
MATCH_THRESHOLD_TEST  = 55   # Testname
MATCH_THRESHOLD_NOTE  = 80   # Note (höher = strenger)
```

---

## Fehlersuche (Debugging)

Wenn ein Feld nicht richtig erkannt wird, kannst du Debug-Bilder aktivieren. Dazu in `process_file_qr` den Parameter `enhance` und `debug_label` prüfen — das Script speichert dann automatisch folgende Dateien im Scriptordner:

| Datei | Inhalt |
|---|---|
| `debug_name.png` | Ausschnitt des Namensfeldes |
| `debug_klasse.png` | Ausschnitt des Klassenfeldes |
| `debug_test.png` | Ausschnitt des Testnamens |
| `debug_note.png` | Ausschnitt des Notenfeldes |

Anhand dieser Bilder siehst du sofort ob der Ausschnitt korrekt positioniert ist und ob der Text lesbar ist.

---

## Fallback-Verhalten

| Situation | Verhalten |
|---|---|
| `pyzbar`/`opencv` nicht installiert | Läuft im alten Modus mit Fixkoordinaten (nur Name) |
| QR-Code nicht lesbar | Warnung wird ausgegeben, Feld wird übersprungen |
| Gar nichts erkannt | Datei wird in `sorted/UNBEKANNT/` verschoben |
| Dateiname bereits vergeben | Automatisch `_1`, `_2` etc. anhängen |

---

## Unterstützte Bildformate

`.png` · `.jpg` · `.jpeg` · `.tiff` · `.bmp`
