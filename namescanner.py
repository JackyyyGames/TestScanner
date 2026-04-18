import os
import shutil
from collections import defaultdict
import easyocr
from PIL import Image, ImageOps
import numpy as np
from thefuzz import process

# --- ABHÄNGIGKEITEN PRÜFEN ---
try:
    import cv2
    from pyzbar import pyzbar
    QR_SUPPORT = True
except ImportError:
    print("⚠ pyzbar/opencv nicht installiert – QR-Modus deaktiviert.")
    print("  Installiere mit: pip install opencv-python pyzbar")
    QR_SUPPORT = False

# ===========================================================================
# KONFIGURATION
# ===========================================================================

SOURCE_DIRECTORY  = "inbox"
TARGET_DIRECTORY  = "sorted"
UNKNOWN_DIRECTORY = os.path.join(TARGET_DIRECTORY, "UNBEKANNT")

# Fallback-Koordinaten (nur verwendet wenn QR-Modus deaktiviert / kein QR gefunden)
FALLBACK_NAME_COORDS = (200, 240, 900, 300)

# Relative Offsets für Textfelder neben dem jeweiligen QR-Code
TEXT_OFFSET_X      = 10     # Pixel-Abstand rechts vom QR-Code
TEXT_WIDTH         = 950   # Breite des Textfeldes in Pixeln
TEXT_HEIGHT_FACTOR = 2   # Höhe = QR-Höhe * dieser Faktor

# Mindest-Konfidenz für Fuzzy-Matches (0–100)
MATCH_THRESHOLD_NAME  = 60
MATCH_THRESHOLD_CLASS = 70
MATCH_THRESHOLD_TEST  = 55
MATCH_THRESHOLD_NOTE  = 80

# --- REFERENZDATEN ---
REFERENCE_ENTITIES = [
    "Janisch-Lang Fabian",
    "Häusler Valentin",
    "Müller Max",
    "Kitting-Muhr Jakob",
    "Schmidt Sarah",
]

REFERENCE_CLASSES = [
    "2AHIT",
    "3BHIF",
    "1AHWI",
    "2BHIT",
    "4AHIF",
]

REFERENCE_TESTS = [
    "1. Test SYT",
    "2. Test SYT",
    "3. Test SYT IT",
    "1. Test AM",
    "2. Test AM",
]

REFERENCE_NOTES = [
    "1", "2", "3", "4", "5",
]

# QR-Code-Inhalte → welches Feld sie ankern
QR_LABELS = {
    "NAME":   "name",
    "KLASSE": "klasse",
    "TEST":   "test",
    "NOTE":   "note",
}

# ===========================================================================
# SETUP – Ordner beim ersten Start erstellen
# ===========================================================================

def setup_directories():
    """Erstellt alle benötigten Verzeichnisse beim ersten Ausführen."""
    dirs = [SOURCE_DIRECTORY, TARGET_DIRECTORY, UNKNOWN_DIRECTORY]
    for d in dirs:
        if not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
            print(f"  📁 Ordner erstellt: {d}/")

    readme_path = os.path.join(SOURCE_DIRECTORY, "HIER_BILDER_ABLEGEN.txt")
    if not os.path.exists(readme_path):
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(
                "Lege hier die zu scannenden Bilder ab.\n"
                "Unterstützte Formate: .png, .jpg, .jpeg, .tiff, .bmp\n\n"
                "Das Script erkennt QR-Codes auf dem Dokument:\n"
                "  QR 'NAME'   → ankert das Namensfeld\n"
                "  QR 'KLASSE' → ankert das Klassenfeld\n"
                "  QR 'TEST'   → ankert das Testnamensfeld\n"
                "  QR 'NOTE'   → ankert das Notenfeld\n"
            )
        print(f"  📄 Vorlage erstellt: {readme_path}")

# ===========================================================================
# HILFSFUNKTIONEN
# ===========================================================================

def apply_image_enhancement(img_input: Image.Image) -> Image.Image:
    """Bereitet einen Bildausschnitt für die Texterkennung vor (invertiert)."""
    img_input = img_input.convert("RGB")
    red_channel, _, _ = img_input.split()
    enhanced_data = 255 - np.array(red_channel)
    result_img = Image.fromarray(enhanced_data)
    result_img = ImageOps.autocontrast(result_img, cutoff=5)
    return result_img


def sanitize_filename(raw_text: str) -> str:
    """Entfernt für Dateisysteme ungültige Zeichen."""
    allowed = set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "ÄÖÜäöüß0123456789-_. "
    )
    return "".join(c for c in raw_text if c in allowed).strip()


def fuzzy_match(raw_text: str, reference_list: list, threshold: int, label: str) -> str | None:
    """
    Vergleicht OCR-Text per Fuzzy-Match mit einer Referenzliste.
    Gibt den besten Treffer zurück oder None bei zu niedriger Konfidenz.
    """
    if not raw_text.strip():
        print(f"  ⚠ {label}: Kein OCR-Text erkannt.")
        return None

    match, confidence = process.extractOne(raw_text, reference_list)
    print(f"  {label}: '{raw_text}' → '{match}' ({confidence}%)")

    if confidence >= threshold:
        return match
    print(f"  ⚠ {label}: Konfidenz zu niedrig ({confidence}% < {threshold}%) – Rohtext wird verwendet.")
    return sanitize_filename(raw_text) or None


def ocr_region(ocr_engine, img: Image.Image, coords: tuple, debug_label: str = "", enhance: bool = True) -> str:
    """
    Schneidet eine Region aus und führt OCR durch.
    enhance=True  → invertieren + autocontrast (gut für dunkle Schrift auf hellem Grund nach Inversion)
    enhance=False → nur Graustufen (gut für helle Schrift auf dunklem Grund / Drucktext)
    """
    roi = img.crop(coords)
    if enhance:
        processed = apply_image_enhancement(roi)
    else:
        processed = roi.convert("L")  # nur Graustufen, kein Invertieren
    if debug_label:
        processed.save(f"debug_{debug_label}.png")
    results = ocr_engine.readtext(
        np.array(processed),
        detail=0,
        paragraph=True,
        allowlist=(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "ÄÖÜäöüß0123456789-_. "
        ),
    )
    return " ".join(results).strip()

# ===========================================================================
# QR-CODE ERKENNUNG
# ===========================================================================

def find_qr_anchors(image_path: str) -> dict:
    """
    Liest alle QR-Codes im Bild und gibt ihre Positionen zurück.
    Rückgabe: { "NAME": (x, y, w, h), "KLASSE": ..., "TEST": ..., "NOTE": ... }
    """
    anchors = {}
    if not QR_SUPPORT:
        return anchors

    img_cv = cv2.imread(image_path)
    if img_cv is None:
        return anchors

    decoded = pyzbar.decode(img_cv)
    for qr in decoded:
        data = qr.data.decode("utf-8").strip().upper()
        if data in QR_LABELS:
            rect = qr.rect  # namedtuple: left, top, width, height
            anchors[data] = (rect.left, rect.top, rect.width, rect.height)
            print(f"  📌 QR '{data}' gefunden @ x={rect.left}, y={rect.top}")

    return anchors


def qr_to_text_coords(qr_x, qr_y, qr_w, qr_h, img_width: int) -> tuple:
    """
    Berechnet die Koordinaten des Textfeldes rechts neben dem QR-Code.
    Gibt (left, top, right, bottom) zurück.
    """
    text_left   = qr_x + qr_w + TEXT_OFFSET_X
    text_height = int(qr_h * TEXT_HEIGHT_FACTOR)
    text_top    = qr_y + (qr_h - text_height) // 2
    text_right  = min(text_left + TEXT_WIDTH, img_width)
    text_bottom = text_top + text_height

    text_top    = max(0, text_top)
    text_bottom = max(text_top + 1, text_bottom)

    return (text_left, text_top, text_right, text_bottom)

# ===========================================================================
# HAUPTVERARBEITUNG
# ===========================================================================

def process_file_qr(ocr_engine, file_path: str) -> dict:
    """
    Verarbeitet eine Datei mit QR-Anker-System.
    Gibt ein Dict mit name/klasse/test/note zurück.
    """
    img = Image.open(file_path)
    img_w, _ = img.size

    anchors = find_qr_anchors(file_path)
    fields  = {"name": None, "klasse": None, "test": None, "note": None}

    for qr_label, field_key in QR_LABELS.items():
        if qr_label not in anchors:
            print(f"  ⚠ QR '{qr_label}' nicht gefunden – Feld '{field_key}' übersprungen.")
            continue

        qx, qy, qw, qh = anchors[qr_label]
        coords = qr_to_text_coords(qx, qy, qw, qh, img_w)

        if field_key == "name":
            raw_text = ocr_region(ocr_engine, img, coords, debug_label=field_key, enhance=True)
            fields["name"] = fuzzy_match(raw_text, REFERENCE_ENTITIES, MATCH_THRESHOLD_NAME, "Name")
        elif field_key == "klasse":
            raw_text = ocr_region(ocr_engine, img, coords, debug_label=field_key, enhance=True)
            fields["klasse"] = fuzzy_match(raw_text, REFERENCE_CLASSES, MATCH_THRESHOLD_CLASS, "Klasse")
        elif field_key == "test":
            raw_text = ocr_region(ocr_engine, img, coords, debug_label=field_key, enhance=False)
            fields["test"] = fuzzy_match(raw_text, REFERENCE_TESTS, MATCH_THRESHOLD_TEST, "Testname")
        elif field_key == "note":
            raw_text = ocr_region(ocr_engine, img, coords, debug_label=field_key, enhance=True)
            fields["note"] = fuzzy_match(raw_text, REFERENCE_NOTES, MATCH_THRESHOLD_NOTE, "Note")

    return fields


def process_file_fallback(ocr_engine, file_path: str) -> dict:
    """Fallback: Nur Name aus Fixkoordinaten auslesen (altes Verhalten)."""
    print("  ℹ Fallback-Modus: Nur Namensfeld mit Fixkoordinaten.")
    img      = Image.open(file_path)
    raw_text = ocr_region(ocr_engine, img, FALLBACK_NAME_COORDS)
    matched  = fuzzy_match(raw_text, REFERENCE_ENTITIES, MATCH_THRESHOLD_NAME, "Name")
    return {"name": matched, "klasse": None, "test": None, "note": None}


def build_filename(fields: dict, original_ext: str) -> tuple[str, str]:
    """
    Erstellt Dateinamen und Unterordner-Pfad aus den erkannten Feldern.
    Rückgabe: (subfolder_path, filename)
    """
    name   = fields.get("name")
    klasse = fields.get("klasse")
    test   = fields.get("test")

    if name:
        parts    = name.strip().split()
        name_str = "_".join(parts)
    else:
        name_str = "UNBEKANNT"

    folder_klasse = sanitize_filename(klasse) if klasse else "UNBEKANNT"
    folder_test   = sanitize_filename(test)   if test   else "UNBEKANNT"
    subfolder     = os.path.join(TARGET_DIRECTORY, folder_klasse, folder_test)

    test_str   = sanitize_filename(test).replace(" ", "-") if test   else "UNBEKANNT"
    klasse_str = sanitize_filename(klasse)                 if klasse else "UNBEKANNT"

    filename = f"{klasse_str}_{test_str}_{name_str}{original_ext}"
    return subfolder, filename


def move_file(src: str, subfolder: str, filename: str) -> str:
    """Verschiebt eine Datei in den Zielordner, löst Namenskonflikte auf."""
    os.makedirs(subfolder, exist_ok=True)
    dest = os.path.join(subfolder, filename)

    counter = 1
    base, ext = os.path.splitext(filename)
    while os.path.exists(dest):
        dest = os.path.join(subfolder, f"{base}_{counter}{ext}")
        counter += 1

    shutil.move(src, dest)
    return dest

# ===========================================================================
# NOTENLISTE
# ===========================================================================

def write_grade_lists(results: list):
    """
    Schreibt pro Klasse+Test eine notenliste.txt in den jeweiligen Ordner.
    Format:
        Notenliste – 2AHIT – 3. Test SYT IT
        ==================================================
        Müller Max                          3
        Schmidt Sarah                       1.5
    """
    if not results:
        return

    groups = defaultdict(list)
    for r in results:
        key = (r["klasse"] or "UNBEKANNT", r["test"] or "UNBEKANNT")
        groups[key].append(r)

    for (klasse, test), entries in groups.items():
        folder = os.path.join(
            TARGET_DIRECTORY,
            sanitize_filename(klasse),
            sanitize_filename(test),
        )
        os.makedirs(folder, exist_ok=True)

        list_path = os.path.join(folder, "notenliste.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            f.write(f"Notenliste – {klasse} – {test}\n")
            f.write("=" * 50 + "\n")
            sorted_entries = sorted(entries, key=lambda x: x["name"] or "")
            for e in sorted_entries:
                name_col = (e["name"] or "UNBEKANNT").ljust(35)
                note_col = e["note"] or "–"
                f.write(f"{name_col} {note_col}\n")

        print(f"  📋 Notenliste gespeichert: {list_path}")

# ===========================================================================
# BATCH-VERARBEITUNG
# ===========================================================================

def run_batch_process():
    print("=" * 60)
    print("  NameScanner – QR-Anker-System")
    print("=" * 60)

    setup_directories()

    supported_ext = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}
    files = [
        f for f in os.listdir(SOURCE_DIRECTORY)
        if os.path.splitext(f)[1].lower() in supported_ext
    ]

    if not files:
        print(f"\nKeine Bilddateien in '{SOURCE_DIRECTORY}/' gefunden.")
        return

    print(f"\n{len(files)} Datei(en) gefunden. OCR-Engine wird geladen …\n")
    ocr_engine = easyocr.Reader(["de", "en"], gpu=False)

    success_count = 0
    fail_count    = 0
    results       = []

    for filename in files:
        file_path = os.path.join(SOURCE_DIRECTORY, filename)
        ext       = os.path.splitext(filename)[1].lower()

        print(f"\n── {filename} " + "─" * max(0, 50 - len(filename)))

        try:
            fields = process_file_qr(ocr_engine, file_path) if QR_SUPPORT else process_file_fallback(ocr_engine, file_path)

            if not any(fields.values()):
                print("  ⚠ Keine Felder erkannt → wird in UNBEKANNT verschoben.")
                move_file(file_path, UNKNOWN_DIRECTORY, filename)
                fail_count += 1
                continue

            subfolder, new_filename = build_filename(fields, ext)
            dest = move_file(file_path, subfolder, new_filename)
            print(f"  ✓ Gespeichert: {dest}")

            results.append({
                "name":   fields.get("name"),
                "klasse": fields.get("klasse"),
                "test":   fields.get("test"),
                "note":   fields.get("note"),
            })
            success_count += 1

        except Exception as e:
            print(f"  ✗ Fehler: {e}")
            try:
                move_file(file_path, UNKNOWN_DIRECTORY, filename)
                print("  → In UNBEKANNT verschoben.")
            except Exception as move_err:
                print(f"  ✗ Verschieben fehlgeschlagen: {move_err}")
            fail_count += 1

    # Notenlisten schreiben
    if results:
        print("\n── Notenlisten werden erstellt …")
        write_grade_lists(results)

    print("\n" + "=" * 60)
    print(f"  Abgeschlossen: {success_count} ✓  {fail_count} ✗")
    print("=" * 60)


if __name__ == "__main__":
    run_batch_process()