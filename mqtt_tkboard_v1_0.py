# tk_designer_full.py
# Großer Tkinter-Designer — komplette Version
# Deutschsprachige GUI / Funktionen:
# - Widgets links (Button, Label, Entry, ...),
# - Aktionen (Neuer Tab, Hintergrund setzen, Löschen, Undo, Redo, Save, Load, Preview, Export)
# - Eigenschaften rechts (Text, Hintergrundfarbe, Größe)
# - Tabs mit Canvas-Hintergründen (klick-durchlässig)
# - Widgets auf einem Layer (platzierbar & verschiebbar)
# - Undo/Redo, Save/Load, Vorschau, Export .py inklusive Bildkopien

import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox, simpledialog
from PIL import Image, ImageTk
import json, os, shutil, datetime, copy, threading

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# ---------------------------
# Helper: sichere int konvertierung
def to_int(s, default=0):
    try:
        return int(s)
    except Exception:
        return default

class MQTTProgressbar(tk.Canvas):
    """Progressbar mit sichtbarer Prozentzahl (0 bis 100) in beiden Richtungen."""
    def __init__(self, master, orient="horizontal", value=0, **kwargs):
        self.orient = orient
        self.label_font_size = 10
        if orient == "vertical":
            kwargs.setdefault("width", 48)
            kwargs.setdefault("height", 170)
        else:
            kwargs.setdefault("width", 200)
            kwargs.setdefault("height", 32)
        kwargs.setdefault("bg", "#2674c7")  # Hintergrundfarbe = Füllfarbe
        kwargs.setdefault("highlightthickness", 1)
        kwargs.setdefault("highlightbackground", "#778899")
        super().__init__(master, **kwargs)
        self.value = 0.0
        self.bind("<Configure>", self.redraw, add="+")
        self.set_value(value)

    def set_value(self, value):
        """Ungültige MQTT-Werte ignorieren; gültige Werte auf 0–100 begrenzen."""
        try:
            number = float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return False
        if not 0 <= number <= 100:
            # Außerhalb des Bereichs auf den nächsten Grenzwert begrenzen.
            if number == float("inf") or number == float("-inf") or number != number:
                return False
            number = min(100.0, max(0.0, number))
        self.value = number
        self.redraw()
        return True

    def set_font_size(self, size):
        self.label_font_size = int(size)
        self.redraw()

    def redraw(self, event=None):
        self.delete("progress_visual")
        width = self.winfo_width() if self.winfo_width() > 1 else int(self.cget("width"))
        height = self.winfo_height() if self.winfo_height() > 1 else int(self.cget("height"))
        x0, y0, x1, y1 = 1, 1, max(2, width - 1), max(2, height - 1)
        self.create_rectangle(x0, y0, x1, y1, fill="#e7ecf1", outline="", tags="progress_visual")
        if self.orient == "vertical":
            top = y1 - (y1 - y0) * self.value / 100
            if self.value > 0:
                self.create_rectangle(x0, top, x1, y1, fill=self.cget("bg"), outline="", tags="progress_visual")
        else:
            right = x0 + (x1 - x0) * self.value / 100
            if self.value > 0:
                self.create_rectangle(x0, y0, right, y1, fill=self.cget("bg"), outline="", tags="progress_visual")
        value_text = f"{self.value:g}%"
        self.create_text(width / 2, height / 2, text=value_text,
                         font=("TkDefaultFont", self.label_font_size, "bold"),
                         fill="#132437", tags="progress_visual")

# ---------------------------
class TkDesigner(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MQTT-Tkboard")
        self.language = "de"
        self.language_choice = tk.StringVar(master=self, value="de")
        self._static_ui_items = []
        self._preview_windows = []
        self._mqtt_status_source = "Nicht verbunden"
        self.geometry("1400x750")		# alt 1400x850

        # widget palette
        self.widget_types = ["Button","Button press on","Button switch","Progressbar Horizontal","Progressbar Vertikal","Label","Entry","Checkbutton","Radiobutton","Text"]

        # State
        self.selected_widget_type = None          # Typ, der gerade aus Sidebar ausgewählt ist
        self.selected_widget = None               # (tab_name, wid)
        self.id_counter = 0

        # tabs: dict by tab_name -> { frame, canvas, layer, widgets: {wid: {...}}, bg_path, bg_pil, bg_image }
        self.tabs = {}

        # MQTT-Verbindung (paho-mqtt optional)
        self.mqtt_client = None
        self.mqtt_connected = False
        self.mqtt_subscriptions = set()
        self._preview_progress_widgets = []  # (tab_name, widget_id, preview_widget)

        # undo/redo: store serialized JSON snapshots
        self.undo_stack = []
        self.redo_stack = []

        # drag info
        self.drag_info = {"wid": None, "tab": None, "start_x": 0, "start_y": 0}

        # build UI
        self._build_ui()
        # start with a default tab
        self.add_tab_with_name("Tab1")
        # push initial snapshot
        self.push_undo(initial=True)

    # ---------------------------
    # GUI-Sprache (nur Oberflächentexte; Widget-Typen und Projektdaten bleiben unverändert)
    _english_ui = {
        "Sprache": "Language",
        "Aktionen": "Actions",
        "Neuer Tab": "New tab",
        "Tab löschen": "Delete tab",
        "Hintergrund setzen": "Set background",
        "Widget löschen": "Delete widget",
        "Speichern": "Save",
        "Laden": "Load",
        "Vorschau": "Preview",
        "Export .py+Bilder": "Export .py + images",
        "Eigenschaften": "Properties",
        "Übernehmen (Text)": "Apply text",
        "Hintergrundfarbe": "Background color",
        "Farbe anwenden": "Apply color",
        "Farbe wählen": "Choose color",
        "Größe (Breite / Höhe)": "Size (width / height)",
        "Größe anwenden": "Apply size",
        "Schriftgröße (Punkt)": "Font size (points)",
        "Schriftgröße anwenden": "Apply font size",
        "Tab-Fenstergröße (Breite / Höhe)": "Tab size (width / height)",
        "Tab-Größe fixieren": "Set tab size",
        "Wähle ein Widget im Designer (Klick).\nZum Platzieren: zuerst Widget links auswählen":
            "Select a widget in the designer (click).\nTo place one, first select a widget on the left",
        "MQTT-Verbindung": "MQTT connection",
        "Broker / Port": "Broker / port",
        "Nicht verbunden": "Not connected",
        "Verbunden": "Connected",
        "Mit MQTT verbinden": "Connect to MQTT",
        "Mit MQTT verbinden beenden": "Disconnect from MQTT",
        "MQTT Topic zum Senden": "MQTT topic for publishing",
        "MQTT Topic zum Empfangen": "MQTT topic for subscribing",
        "Sende-Wert (Button / Entry)": "Publish value (Button / Entry)",
        "MQTT-Einstellungen übernehmen": "Apply MQTT settings",
        "Farbregel: MQTT-Wert 1": "Color rule: MQTT value 1",
        "Farbe für Wert 1": "Color for value 1",
        "Farbregel: MQTT-Wert 2": "Color rule: MQTT value 2",
        "Farbe für Wert 2": "Color for value 2",
        "Tab-Name": "Tab name",
        "Name für neuen Tab:": "Name for new tab:",
        "Kein Tab ausgewählt.": "No tab selected.",
        "Der letzte Tab kann nicht gelöscht werden.": "The last tab cannot be deleted.",
        "Tab „{}“ wirklich löschen?": "Really delete tab ‘{}’?",
        "Tab-Größe": "Tab size",
        "Bitte gültige Werte ab 100 Pixel eingeben.": "Please enter valid values of at least 100 pixels.",
        "Fehler": "Error",
        "Widget konnte nicht erstellt werden: {}": "Could not create widget: {}",
        "Ungültige Farbe": "Invalid color",
        "Bitte eine gültige Farbe eingeben (z. B. #ff0000).": "Please enter a valid color (e.g. #ff0000).",
        "Schriftgröße": "Font size",
        "Bitte eine Schriftgröße zwischen 1 und 200 Punkt eingeben.": "Please enter a font size between 1 and 200 points.",
        "Schriftgröße konnte nicht gesetzt werden: {}": "Could not set font size: {}",
        "MQTT nicht verfügbar": "MQTT unavailable",
        "Bitte paho-mqtt installieren: python -m pip install paho-mqtt":
            "Please install paho-mqtt: python -m pip install paho-mqtt",
        "Farbe für MQTT-Wert {} wählen": "Choose color for MQTT value {}",
        "Bitte zuerst ein Widget auswählen.": "Please select a widget first.",
        "MQTT-Einstellungen für das Widget übernommen.": "MQTT settings applied to widget.",
        "Info": "Information",
        "Kein Widget ausgewählt.": "No widget selected.",
        "Hintergrundbild konnte nicht geladen werden: {}": "Could not load background image: {}",
        "Bilder": "Images",
        "Gespeichert": "Saved",
        "Layout gespeichert: {}": "Layout saved: {}",
        "Geladen": "Loaded",
        "Layout geladen: {}": "Layout loaded: {}",
        "Ordner für Export auswählen": "Select folder for export",
        "Bildexport": "Image export",
        "{} konnte nicht kopiert werden:\n{}": "Could not copy {}:\n{}",
        "Export erfolgreich:\n{}\n\nMQTT-Funktionen wurden übernommen. Im Exportprogramm bitte auf 'MQTT verbinden' klicken.":
            "Export successful:\n{}\n\nMQTT functionality was included. In the exported program, click 'Connect MQTT'.",
        "Export Fehler": "Export error",
        "Konnte Export-Datei nicht schreiben: {}": "Could not write export file: {}",
    }

    def tr(self, german):
        return self._english_ui.get(german, german) if self.language == "en" else german

    def _translate_status(self, german):
        if self.language != "en":
            return german
        for source, target in (("Verbinde mit ", "Connecting to "),
                               ("Verbindung fehlgeschlagen: ", "Connection failed: "),
                               ("Verbindungsfehler (", "Connection error (")):
            if german.startswith(source):
                return target + german[len(source):]
        return self.tr(german)

    def _set_mqtt_status(self, german, fg="#666"):
        self._mqtt_status_source = german
        self.mqtt_status.config(text=self._translate_status(german), fg=fg)

    def _register_static_ui(self, *parents):
        def collect(parent):
            for element in parent.winfo_children():
                if isinstance(element, (tk.Label, tk.Button)) and element is not self.mqtt_status:
                    text = element.cget("text")
                    # Die Widget-Palette darf niemals übersetzt werden.
                    if text not in self.widget_types and text in self._english_ui:
                        self._static_ui_items.append((element, text))
                collect(element)
        for parent in parents:
            collect(parent)

    def set_language(self, language):
        if language not in ("de", "en"):
            return
        self.language = language
        self.language_choice.set(language)
        self.title("MQTT-Tkboard")
        self._menu_bar.entryconfigure(0, label=self.tr("Sprache"))
        self.prop_notebook.tab(self.prop_tab, text=self.tr("Eigenschaften"))
        for element, german in self._static_ui_items:
            if not element.winfo_exists():
                continue
            current = element.cget("text")
            if element in (self.prop_mqtt_color1, self.prop_mqtt_color2):
                # Gewählte Farbwerte auf den Buttons nicht überschreiben.
                if current not in (german, self._english_ui.get(german, german)):
                    continue
            element.config(text=self.tr(german))
        self.mqtt_status.config(text=self._translate_status(self._mqtt_status_source))
        self._preview_windows = [win for win in self._preview_windows if win.winfo_exists()]
        for win in self._preview_windows:
            win.title(self.tr("Vorschau"))

    # ---------------------------
    # UI Aufbau: left sidebar, center notebook, right properties
    def _build_ui(self):
        self._menu_bar = tk.Menu(self, tearoff=False)
        self._language_menu = tk.Menu(self._menu_bar, tearoff=False)
        self._menu_bar.add_cascade(label="Sprache", menu=self._language_menu)
        self._language_menu.add_radiobutton(label="Deutsch", value="de", variable=self.language_choice,
                                             command=lambda: self.set_language("de"))
        self._language_menu.add_radiobutton(label="Englisch", value="en", variable=self.language_choice,
                                             command=lambda: self.set_language("en"))
        self.config(menu=self._menu_bar)
        # Left sidebar
        sidebar = tk.Frame(self, width=240, bg="#f0f0f0")
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Widgets", bg="#ddd", font=(None,11,"bold")).pack(fill="x", pady=(8,4))
        for wt in self.widget_types:
            b = tk.Button(sidebar, text=wt, command=lambda w=wt: self.select_widget(w))
            b.pack(fill="x", padx=8, pady=3)

        tk.Label(sidebar, text="", bg="#f0f0f0").pack(pady=4)
        tk.Label(sidebar, text="Aktionen", bg="#ddd", font=(None,11,"bold")).pack(fill="x", pady=(4,4))

        acts = [
            ("Neuer Tab", self.add_tab_dialog),
            ("Tab löschen", self.delete_tab),
            ("Hintergrund setzen", self.set_tab_background),  # supports optional args
            ("Widget löschen", self.delete_selected),
            ("Undo", self.undo),
            ("Redo", self.redo),
            ("Speichern", self.save_layout),
            ("Laden", self.load_layout),
            ("Vorschau", self.preview_mode),
            ("Export .py+Bilder", self.export_project)
        ]
        for label, cmd in acts:
            tk.Button(sidebar, text=label, command=cmd).pack(fill="x", padx=8, pady=3)

        # Center: Notebook (Tabs)
        center = tk.Frame(self)
        center.pack(side="left", fill="both", expand=True)
        self.notebook = ttk.Notebook(center)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._refresh_tab_size_fields())

        # Right: Properties editor mit zwei getrennten Tabs
        prop = tk.Frame(self, width=320, bg="#fafafa")
        prop.pack(side="right", fill="y")
        prop.pack_propagate(False)
        prop_notebook = ttk.Notebook(prop)
        prop_notebook.pack(fill="both", expand=True, padx=4, pady=4)
        prop_tab = tk.Frame(prop_notebook, bg="#fafafa")
        mqtt_tab = tk.Frame(prop_notebook, bg="#fafafa")
        self.prop_notebook = prop_notebook
        self.prop_tab = prop_tab
        prop_notebook.add(prop_tab, text="Eigenschaften")
        prop_notebook.add(mqtt_tab, text="MQTT")

        tk.Label(prop_tab, text="Eigenschaften", bg="#eee", font=(None,11,"bold")).pack(fill="x", pady=(8,4))

        # Text
        tk.Label(prop_tab, text="Text", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_text = tk.Entry(prop_tab)
        self.prop_text.pack(fill="x", padx=8, pady=(0,6))
        tk.Button(prop_tab, text="Übernehmen (Text)", command=self.apply_text).pack(fill="x", padx=8, pady=(0,8))

        # Background color
        tk.Label(prop_tab, text="Hintergrundfarbe", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_bg_color = tk.Entry(prop_tab)
        self.prop_bg_color.pack(fill="x", padx=8, pady=(0,4))
        self.prop_bg_color.bind("<Return>", lambda event: self.apply_bg_color_from_entry())
        tk.Button(prop_tab, text="Farbe anwenden", command=self.apply_bg_color_from_entry).pack(fill="x", padx=8, pady=(0,4))
        tk.Button(prop_tab, text="Farbe wählen", command=self.apply_bg_color).pack(fill="x", padx=8, pady=(0,8))

        # Size
        tk.Label(prop_tab, text="Größe (Breite / Höhe)", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        size_frame = tk.Frame(prop_tab, bg="#fafafa")
        size_frame.pack(fill="x", padx=8, pady=(0,6))
        self.prop_w = tk.Entry(size_frame, width=8)
        self.prop_w.pack(side="left")
        self.prop_h = tk.Entry(size_frame, width=8)
        self.prop_h.pack(side="left", padx=6)
        tk.Button(prop_tab, text="Größe anwenden", command=self.apply_size).pack(fill="x", padx=8, pady=(0,8))

        # Schriftgröße
        tk.Label(prop_tab, text="Schriftgröße (Punkt)", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_font_size = tk.Entry(prop_tab)
        self.prop_font_size.pack(fill="x", padx=8, pady=(0,4))
        tk.Button(prop_tab, text="Schriftgröße anwenden", command=self.apply_font_size).pack(fill="x", padx=8, pady=(0,8))

        # Aktueller Tab: feste Fenster-/Arbeitsfläche
        ttk.Separator(prop_tab, orient="horizontal").pack(fill="x", padx=8, pady=8)
        tk.Label(prop_tab, text="Tab-Fenstergröße (Breite / Höhe)", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        tab_size_frame = tk.Frame(prop_tab, bg="#fafafa")
        tab_size_frame.pack(fill="x", padx=8, pady=(0,6))
        self.tab_prop_w = tk.Entry(tab_size_frame, width=8)
        self.tab_prop_w.pack(side="left")
        self.tab_prop_h = tk.Entry(tab_size_frame, width=8)
        self.tab_prop_h.pack(side="left", padx=6)
        tk.Button(prop_tab, text="Tab-Größe fixieren", command=self.apply_tab_size).pack(fill="x", padx=8, pady=(0,8))

        # small help
        tk.Label(prop_tab, text="Wähle ein Widget im Designer (Klick).\nZum Platzieren: zuerst Widget links auswählen" , wraplength=300, fg="#666", bg="#fafafa").pack(padx=8, pady=6)

        # MQTT-Konfiguration für das ausgewählte Widget
        ttk.Separator(mqtt_tab, orient="horizontal").pack(fill="x", padx=8, pady=8)
        tk.Label(mqtt_tab, text="MQTT-Verbindung", bg="#eee", font=(None, 10, "bold")).pack(fill="x", padx=8, pady=(0,4))
        tk.Label(mqtt_tab, text="Broker / Port", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        broker_row = tk.Frame(mqtt_tab, bg="#fafafa")
        broker_row.pack(fill="x", padx=8, pady=(0,4))
        self.mqtt_host = tk.Entry(broker_row)
        self.mqtt_host.insert(0, "localhost")
        self.mqtt_host.pack(side="left", fill="x", expand=True)
        self.mqtt_port = tk.Entry(broker_row, width=7)
        self.mqtt_port.insert(0, "1883")
        self.mqtt_port.pack(side="left", padx=(5,0))
        self.mqtt_status = tk.Label(mqtt_tab, text="Nicht verbunden", fg="#666", bg="#fafafa", anchor="w")
        self.mqtt_status.pack(fill="x", padx=8)
        tk.Button(mqtt_tab, text="Mit MQTT verbinden", command=self.connect_mqtt).pack(fill="x", padx=8, pady=(2,4))
        tk.Button(mqtt_tab, text="Mit MQTT verbinden beenden", command=self.disconnect_mqtt).pack(fill="x", padx=8, pady=(0,8))

        tk.Label(mqtt_tab, text="MQTT Topic zum Senden", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_mqtt_pub = tk.Entry(mqtt_tab)
        self.prop_mqtt_pub.pack(fill="x", padx=8, pady=(0,4))
        tk.Label(mqtt_tab, text="MQTT Topic zum Empfangen", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_mqtt_sub = tk.Entry(mqtt_tab)
        self.prop_mqtt_sub.pack(fill="x", padx=8, pady=(0,4))
        tk.Label(mqtt_tab, text="Sende-Wert (Button / Entry)", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_mqtt_payload = tk.Entry(mqtt_tab)
        self.prop_mqtt_payload.pack(fill="x", padx=8, pady=(0,4))
        tk.Button(mqtt_tab, text="MQTT-Einstellungen übernehmen", command=self.apply_mqtt_settings).pack(fill="x", padx=8, pady=(2,8))

        # Widget-Hintergrund anhand zweier MQTT-Eingangswerte einfärben
        tk.Label(mqtt_tab, text="Farbregel: MQTT-Wert 1", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_mqtt_color_value1 = tk.Entry(mqtt_tab)
        self.prop_mqtt_color_value1.pack(fill="x", padx=8, pady=(0,4))
        tk.Label(mqtt_tab, text="Farbe für Wert 1", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_mqtt_color1 = tk.Button(mqtt_tab, text="Farbe wählen", command=lambda: self.choose_mqtt_color(1))
        self.prop_mqtt_color1.pack(fill="x", padx=8, pady=(0,4))

        tk.Label(mqtt_tab, text="Farbregel: MQTT-Wert 2", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_mqtt_color_value2 = tk.Entry(mqtt_tab)
        self.prop_mqtt_color_value2.pack(fill="x", padx=8, pady=(0,4))
        tk.Label(mqtt_tab, text="Farbe für Wert 2", anchor="w", bg="#fafafa").pack(fill="x", padx=8)
        self.prop_mqtt_color2 = tk.Button(mqtt_tab, text="Farbe wählen", command=lambda: self.choose_mqtt_color(2))
        self.prop_mqtt_color2.pack(fill="x", padx=8, pady=(0,4))

        self._register_static_ui(sidebar, prop)
        self.set_language("de")

    # ---------------------------
    # Tab-Operationen
    def add_tab_dialog(self):
        name = simpledialog.askstring(self.tr("Tab-Name"), self.tr("Name für neuen Tab:"), parent=self)
        if not name:
            return
        # ensure unique
        base = name
        i = 1
        while name in self.tabs:
            i += 1
            name = f"{base}_{i}"
        self.add_tab_with_name(name)
        self.push_undo()

    def delete_tab(self):
        tab_name = self.get_current_tab_name()
        if not tab_name:
            messagebox.showinfo(self.tr("Tab löschen"), self.tr("Kein Tab ausgewählt."))
            return
        if len(self.tabs) <= 1:
            messagebox.showwarning(self.tr("Tab löschen"), self.tr("Der letzte Tab kann nicht gelöscht werden."))
            return
        if not messagebox.askyesno(self.tr("Tab löschen"), self.tr("Tab „{}“ wirklich löschen?").format(tab_name)):
            return
        tab = self.tabs.pop(tab_name, None)
        if tab:
            try:
                tab["frame"].destroy()
            except Exception:
                pass
        self.selected_widget = None
        self.push_undo()
        self._refresh_tab_size_fields()

    def add_tab_with_name(self, name):
        # create frame for tab
        tab_frame = tk.Frame(self.notebook)
        # Canvas ist zugleich Hintergrund- und Widget-Ebene.
        # Ein vollflächiger Frame über dem Canvas würde das Hintergrundbild verdecken.
        canvas = tk.Canvas(tab_frame, bg="white", highlightthickness=0, bd=0)
        tab_width, tab_height = 800, 600
        tab_frame.configure(width=tab_width, height=tab_height)
        tab_frame.pack_propagate(False)
        canvas.place(x=0, y=0, width=tab_width, height=tab_height)
        layer = canvas
        # Neue Widgets direkt auf dem Canvas platzieren; Canvas-Bild bleibt darunter.
        canvas.bind("<Button-1>", lambda e, t=name: self.on_layer_click(e, t))
        # Hintergrund beim Ändern der Tab-Größe neu zeichnen
        canvas.bind("<Configure>", lambda e, t=name: self._on_canvas_configure(t))

        self.tabs[name] = {
            "frame": tab_frame,
            "canvas": canvas,
            "layer": layer,
            "widgets": {},   # wid -> {obj,type,x,y,options}
            "bg_path": None,
            "bg_pil": None,
            "bg_image": None,
            "width": tab_width,
            "height": tab_height
        }
        self.notebook.add(tab_frame, text=name)
        # select this tab
        self.notebook.select(self.notebook.index("end")-1)

    def get_current_tab_name(self):
        sel = self.notebook.select()
        if not sel:
            return None
        try:
            return self.notebook.tab(sel, "text")
        except Exception:
            return None

    def get_tab_data(self, tab_name):
        return self.tabs.get(tab_name)

    def apply_tab_size(self):
        tab_name = self.get_current_tab_name()
        if not tab_name:
            messagebox.showinfo(self.tr("Tab-Größe"), self.tr("Kein Tab ausgewählt."))
            return
        width = to_int(self.tab_prop_w.get(), None)
        height = to_int(self.tab_prop_h.get(), None)
        if not width or not height or width < 100 or height < 100:
            messagebox.showerror(self.tr("Tab-Größe"), self.tr("Bitte gültige Werte ab 100 Pixel eingeben."))
            return
        tab = self.tabs[tab_name]
        tab["width"], tab["height"] = width, height
        frame, canvas = tab["frame"], tab["canvas"]
        frame.configure(width=width, height=height)
        frame.pack_propagate(False)
        canvas.place(x=0, y=0, width=width, height=height)
        self._draw_bg_for_tab(tab_name)
        self.push_undo()

    def _refresh_tab_size_fields(self):
        tab_name = self.get_current_tab_name()
        self.tab_prop_w.delete(0, "end")
        self.tab_prop_h.delete(0, "end")
        if tab_name and tab_name in self.tabs:
            tab = self.tabs[tab_name]
            self.tab_prop_w.insert(0, str(tab.get("width", 800)))
            self.tab_prop_h.insert(0, str(tab.get("height", 600)))

    # ---------------------------
    # Widget selection & placement
    def select_widget(self, widget_type):
        self.selected_widget_type = widget_type
        # user feedback could be added

    def on_layer_click(self, event, tab_name):
        """Platzieren eines neuen Widgets im angegebenen Tab"""
        if not self.selected_widget_type:
            return
        tab = self.get_tab_data(tab_name)
        if not tab:
            return
        layer = tab["layer"]
        # coordinates relative to layer
        x = event.x
        y = event.y
        wid = self._next_widget_id()

        inst = self._create_widget_instance(tab, self.selected_widget_type, layer, wid)
        if not inst:
            return

        obj = inst["obj"]
        # absolute placement using place on the layer
        obj.place(x=x, y=y)
        inst["x"] = x
        inst["y"] = y
        tab["widgets"][wid] = inst

        # bind widget events: select & drag
        obj.bind("<Button-1>", lambda e, t=tab_name, id=wid: self.on_widget_click(e, t, id))
        obj.bind("<B1-Motion>", lambda e, t=tab_name, id=wid: self.on_widget_drag(e, t, id))
        obj.bind("<ButtonRelease-1>", lambda e, t=tab_name, id=wid: self.on_widget_release(e, t, id))

        self._configure_special_button(tab_name, wid)
        # select it
        self.selected_widget = (tab_name, wid)
        self.update_property_editor()
        self.push_undo()

    def _next_widget_id(self):
        """Vergibt eine global eindeutige Widget-ID (w1, w2, ...)."""
        used = {wid for tab in self.tabs.values() for wid in tab.get("widgets", {})}
        while True:
            self.id_counter += 1
            candidate = f"w{self.id_counter}"
            if candidate not in used:
                return candidate

    def _create_widget_instance(self, tab, wtype, parent, wid):
        opts = {}
        obj = None
        try:
            if wtype in ("Button", "Button press on", "Button switch"):
                default_text = wtype if wtype != "Button" else wid
                obj = tk.Button(parent, text=default_text)
                if wtype == "Button switch":
                    opts["mqtt_switch_on"] = False
            elif wtype in ("Progressbar Horizontal", "Progressbar Vertikal"):
                orient = "vertical" if wtype == "Progressbar Vertikal" else "horizontal"
                obj = MQTTProgressbar(parent, orient=orient)
                opts["mqtt_progress_value"] = 0.0
            elif wtype == "Label":
                obj = tk.Label(parent, text=wid)
            elif wtype == "Entry":
                obj = tk.Entry(parent)
            elif wtype == "Checkbutton":
                var = tk.IntVar(value=0)
                obj = tk.Checkbutton(parent, text=wid, variable=var)
                opts["variable"] = var
                opts["mqtt_check_state"] = False
            elif wtype == "Radiobutton":
                obj = tk.Radiobutton(parent, text=wid, value=1)
            elif wtype == "Text":
                obj = tk.Text(parent, width=20, height=5)
            elif wtype == "Frame":
                obj = tk.Frame(parent, bg="#ddd", width=160, height=100)
            elif wtype == "Spinbox":
                obj = tk.Spinbox(parent, from_=0, to=10)
            elif wtype == "Scale":
                obj = tk.Scale(parent, from_=0, to=100, orient="horizontal")
            elif wtype == "Listbox":
                obj = tk.Listbox(parent, height=4)
                obj.insert("end", "Item 1", "Item 2")
            else:
                return None
        except Exception as e:
            messagebox.showerror(self.tr("Fehler"), self.tr("Widget konnte nicht erstellt werden: {}").format(e))
            return None
        return {"obj": obj, "type": wtype, "options": opts, "x": 0, "y": 0}

    # ---------------------------
    # Widget interaction: select, drag, release
    def on_widget_click(self, event, tab_name, wid):
        # prevent layer click handler from firing
        event.widget.focus_set()
        self.selected_widget = (tab_name, wid)
        self.drag_info["wid"] = wid
        self.drag_info["tab"] = tab_name
        self.drag_info["start_x"] = event.x
        self.drag_info["start_y"] = event.y
        self.update_property_editor()

    def on_widget_drag(self, event, tab_name, wid):
        info = self.drag_info
        if info["wid"] != wid:
            return
        tab = self.get_tab_data(tab_name)
        inst = tab["widgets"][wid]
        obj = inst["obj"]
        dx = event.x - info["start_x"]
        dy = event.y - info["start_y"]
        new_x = obj.winfo_x() + dx
        new_y = obj.winfo_y() + dy
        obj.place(x=new_x, y=new_y)
        inst["x"] = new_x
        inst["y"] = new_y

    def on_widget_release(self, event, tab_name, wid):
        # finalize drag
        self.drag_info = {"wid": None, "tab": None, "start_x": 0, "start_y": 0}
        self.push_undo()

    # ---------------------------
    # Properties editor
    def update_property_editor(self):
        # clear fields and populate based on selected_widget
        self._refresh_tab_size_fields()
        self.prop_text.delete(0, "end")
        self.prop_bg_color.delete(0, "end")
        self.prop_w.delete(0, "end")
        self.prop_h.delete(0, "end")
        self.prop_font_size.delete(0, "end")
        self.prop_mqtt_pub.delete(0, "end")
        self.prop_mqtt_sub.delete(0, "end")
        self.prop_mqtt_payload.delete(0, "end")
        self.prop_mqtt_color_value1.delete(0, "end")
        self.prop_mqtt_color_value2.delete(0, "end")
        self.prop_mqtt_color1.config(text=self.tr("Farbe wählen"), bg=self.cget("bg"))
        self.prop_mqtt_color2.config(text=self.tr("Farbe wählen"), bg=self.cget("bg"))
        if not self.selected_widget:
            return
        tab_name, wid = self.selected_widget
        tab = self.get_tab_data(tab_name)
        inst = tab["widgets"][wid]
        obj = inst["obj"]
        opts = inst.setdefault("options", {})
        try:
            self.prop_bg_color.insert(0, str(obj.cget("bg")))
        except (tk.TclError, KeyError):
            pass
        self.prop_font_size.insert(0, str(opts.get("font_size", 10)))
        self.prop_mqtt_pub.insert(0, opts.get("mqtt_publish_topic", ""))
        self.prop_mqtt_sub.insert(0, opts.get("mqtt_subscribe_topic", ""))
        self.prop_mqtt_payload.insert(0, opts.get("mqtt_payload", "ON"))
        self.prop_mqtt_color_value1.insert(0, opts.get("mqtt_color_value1", ""))
        self.prop_mqtt_color_value2.insert(0, opts.get("mqtt_color_value2", ""))
        if opts.get("mqtt_color1"):
            self.prop_mqtt_color1.config(text=opts["mqtt_color1"], bg=opts["mqtt_color1"])
        if opts.get("mqtt_color2"):
            self.prop_mqtt_color2.config(text=opts["mqtt_color2"], bg=opts["mqtt_color2"])
        if "text" in obj.keys():
            try:
                self.prop_text.insert(0, obj.cget("text"))
            except Exception:
                pass
        try:
            self.prop_w.insert(0, str(obj.cget("width")))
            self.prop_h.insert(0, str(obj.cget("height")))
        except Exception:
            pass

    def apply_text(self):
        if not self.selected_widget:
            return
        tab_name, wid = self.selected_widget
        tab = self.get_tab_data(tab_name)
        obj = tab["widgets"][wid]["obj"]
        txt = self.prop_text.get()
        try:
            if "text" in obj.keys():
                obj.config(text=txt)
        except Exception:
            pass
        self.push_undo()

    def apply_bg_color_from_entry(self):
        if not self.selected_widget:
            return
        color = self.prop_bg_color.get().strip()
        if not color:
            return
        tab_name, wid = self.selected_widget
        tab = self.get_tab_data(tab_name)
        obj = tab["widgets"][wid]["obj"]
        try:
            obj.config(bg=color)
            if isinstance(obj, MQTTProgressbar):
                obj.redraw()
        except tk.TclError:
            messagebox.showerror(self.tr("Ungültige Farbe"), self.tr("Bitte eine gültige Farbe eingeben (z. B. #ff0000)."))
            return
        self.push_undo()

    def apply_bg_color(self):
        if not self.selected_widget:
            return
        color = colorchooser.askcolor()[1]
        if not color:
            return
        self.prop_bg_color.delete(0, "end")
        self.prop_bg_color.insert(0, color)
        self.apply_bg_color_from_entry()

    def apply_size(self):
        if not self.selected_widget:
            return
        w = to_int(self.prop_w.get(), None)
        h = to_int(self.prop_h.get(), None)
        tab_name, wid = self.selected_widget
        tab = self.get_tab_data(tab_name)
        obj = tab["widgets"][wid]["obj"]
        try:
            if w is not None:
                obj.config(width=w)
            if h is not None:
                obj.config(height=h)
            if isinstance(obj, MQTTProgressbar):
                obj.redraw()
        except Exception:
            pass
        self.push_undo()

    def apply_font_size(self):
        if not self.selected_widget:
            return
        size = to_int(self.prop_font_size.get(), None)
        if size is None or not 1 <= size <= 200:
            messagebox.showerror(self.tr("Schriftgröße"), self.tr("Bitte eine Schriftgröße zwischen 1 und 200 Punkt eingeben."))
            return
        tab_name, wid = self.selected_widget
        inst = self.tabs[tab_name]["widgets"][wid]
        try:
            if isinstance(inst["obj"], MQTTProgressbar):
                inst["obj"].set_font_size(size)
            else:
                inst["obj"].config(font=("TkDefaultFont", size))
            inst.setdefault("options", {})["font_size"] = size
        except Exception as exc:
            messagebox.showerror(self.tr("Schriftgröße"), self.tr("Schriftgröße konnte nicht gesetzt werden: {}").format(exc))
            return
        self.push_undo()

    # ---------------------------
    # MQTT
    def connect_mqtt(self):
        if mqtt is None:
            messagebox.showerror(self.tr("MQTT nicht verfügbar"),
                                 self.tr("Bitte paho-mqtt installieren: python -m pip install paho-mqtt"))
            return
        self.disconnect_mqtt()
        host = self.mqtt_host.get().strip() or "localhost"
        port = to_int(self.mqtt_port.get(), 1883)
        try:
            try:
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            except (AttributeError, TypeError):
                client = mqtt.Client()
            client.on_connect = self._mqtt_on_connect
            client.on_disconnect = self._mqtt_on_disconnect
            client.on_message = self._mqtt_on_message
            self.mqtt_client = client
            self.mqtt_connected = False
            self._set_mqtt_status(f"Verbinde mit {host}:{port} ...", fg="#996600")
            client.connect(host, port, 60)
            client.loop_start()
        except Exception as exc:
            self.mqtt_connected = False
            self.mqtt_client = None
            self._set_mqtt_status(f"Verbindung fehlgeschlagen: {exc}", fg="red")

    def disconnect_mqtt(self):
        """MQTT-Verbindung bewusst beenden; erneutes Verbinden bleibt möglich."""
        client = self.mqtt_client
        self.mqtt_connected = False
        self.mqtt_client = None
        if client is not None:
            try:
                client.disconnect()
                client.loop_stop()
            except Exception:
                pass
        self._set_mqtt_status("Nicht verbunden", fg="#666")

    def _mqtt_on_connect(self, client, userdata, flags, rc, *extra):
        if client is not self.mqtt_client:
            return
        success = (rc == 0)
        self.mqtt_connected = success
        try:
            self.after(0, lambda c=client, ok=success, code=rc:
                       self._set_mqtt_status(
                            "Verbunden" if ok else f"Verbindungsfehler ({code})",
                            fg="green" if ok else "red")
                       if c is self.mqtt_client else None)
        except Exception:
            pass
        if success:
            for topic in list(self.mqtt_subscriptions):
                try:
                    client.subscribe(topic)
                except Exception:
                    pass

    def _mqtt_on_disconnect(self, client, userdata, rc, *extra):
        if client is not self.mqtt_client:
            return
        self.mqtt_connected = False
        try:
            self.after(0, lambda c=client: self._set_mqtt_status("Nicht verbunden", fg="#666") if c is self.mqtt_client else None)
        except Exception:
            pass

    def _mqtt_on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")
        # Tkinter-Widgets nur im GUI-Thread verändern
        try:
            self.after(0, lambda t=topic, p=payload: self._apply_mqtt_message(t, p))
        except Exception:
            pass

    def _apply_mqtt_message(self, topic, payload):
        for tab_name, tab in self.tabs.items():
            for wid, inst in tab["widgets"].items():
                opts = inst.setdefault("options", {})
                if opts.get("mqtt_subscribe_topic") != topic:
                    continue
                obj = inst["obj"]
                # MQTT payload steuert optional die Widget-Hintergrundfarbe.
                color = None
                if payload == str(opts.get("mqtt_color_value1", "")) and opts.get("mqtt_color_value1", "") != "":
                    color = opts.get("mqtt_color1")
                elif payload == str(opts.get("mqtt_color_value2", "")) and opts.get("mqtt_color_value2", "") != "":
                    color = opts.get("mqtt_color2")
                if color:
                    try:
                        obj.config(bg=color)
                        if isinstance(obj, MQTTProgressbar):
                            obj.redraw()
                    except Exception:
                        pass
                try:
                    wtype = inst["type"]
                    if wtype in ("Label", "Button", "Checkbutton", "Radiobutton"):
                        obj.config(text=payload)
                    elif wtype == "Entry":
                        obj.delete(0, "end")
                        obj.insert(0, payload)
                    elif wtype == "Text":
                        obj.delete("1.0", "end")
                        obj.insert("1.0", payload)
                    elif wtype in ("Progressbar Horizontal", "Progressbar Vertikal"):
                        if obj.set_value(payload):
                            opts["mqtt_progress_value"] = obj.value
                            # Bereits geöffnete Vorschaufenster aktuell halten.
                            active = []
                            for pt, pi, pw in self._preview_progress_widgets:
                                if pw.winfo_exists():
                                    active.append((pt, pi, pw))
                                    if (pt, pi) == (tab_name, wid):
                                        if color:
                                            pw.config(bg=color)
                                            pw.redraw()
                                        pw.set_value(payload)
                            self._preview_progress_widgets = active
                    elif wtype == "Scale":
                        obj.set(float(payload))
                    elif wtype == "Spinbox":
                        obj.delete(0, "end")
                        obj.insert(0, payload)
                except Exception:
                    pass

    def choose_mqtt_color(self, number):
        color = colorchooser.askcolor(parent=self, title=self.tr("Farbe für MQTT-Wert {} wählen").format(number))[1]
        if not color or not self.selected_widget:
            return
        tab_name, wid = self.selected_widget
        opts = self.tabs[tab_name]["widgets"][wid].setdefault("options", {})
        key = f"mqtt_color{number}"
        opts[key] = color
        getattr(self, f"prop_mqtt_color{number}").config(text=color, bg=color)
        self.push_undo()

    def apply_mqtt_settings(self):
        if not self.selected_widget:
            messagebox.showinfo("MQTT", self.tr("Bitte zuerst ein Widget auswählen."))
            return
        tab_name, wid = self.selected_widget
        inst = self.tabs[tab_name]["widgets"][wid]
        opts = inst.setdefault("options", {})
        old_topic = opts.get("mqtt_subscribe_topic", "")
        pub_topic = self.prop_mqtt_pub.get().strip()
        sub_topic = self.prop_mqtt_sub.get().strip()
        payload = self.prop_mqtt_payload.get()
        color_value1 = self.prop_mqtt_color_value1.get()
        color_value2 = self.prop_mqtt_color_value2.get()
        opts["mqtt_color_value1"] = color_value1
        opts["mqtt_color_value2"] = color_value2
        opts.setdefault("mqtt_color1", "")
        opts.setdefault("mqtt_color2", "")
        opts["mqtt_publish_topic"] = pub_topic
        opts["mqtt_subscribe_topic"] = sub_topic
        opts["mqtt_payload"] = payload

        if old_topic and old_topic != sub_topic:
            self.mqtt_subscriptions.discard(old_topic)
            if self.mqtt_client:
                try:
                    self.mqtt_client.unsubscribe(old_topic)
                except Exception:
                    pass
        if sub_topic:
            self.mqtt_subscriptions.add(sub_topic)
            if self.mqtt_client:
                try:
                    self.mqtt_client.subscribe(sub_topic)
                except Exception:
                    pass

        obj = inst["obj"]
        self._configure_special_button(tab_name, wid)
        # Vorherige benutzerdefinierte Bindings entfernen, ohne Designer-Bindings zu löschen
        if inst["type"] == "Button":
            obj.config(command=lambda t=tab_name, i=wid: self._mqtt_publish_widget(t, i))
        elif inst["type"] == "Entry":
            obj.bind("<Return>", lambda e, t=tab_name, i=wid: self._mqtt_publish_widget(t, i), add="+")
        elif inst["type"] == "Scale":
            obj.config(command=lambda value, t=tab_name, i=wid: self._mqtt_publish_widget(t, i, value))
        self.push_undo()
        messagebox.showinfo("MQTT", self.tr("MQTT-Einstellungen für das Widget übernommen."))

    def _configure_special_button(self, tab_name, wid):
        """Bindet MQTT-Schaltfunktionen, ohne Auswahl und Drag zu entfernen."""
        inst = self.tabs.get(tab_name, {}).get("widgets", {}).get(wid)
        if not inst:
            return
        kind = inst["type"]
        obj = inst["obj"]
        if kind == "Button press on":
            # Bindings einmalig setzen; die vorhandenen Designer-Events bleiben erhalten.
            obj.bind("<ButtonPress-1>",
                     lambda e, t=tab_name, i=wid: self._mqtt_publish_widget(t, i, "on"),
                     add="+")
            obj.bind("<ButtonRelease-1>",
                     lambda e, t=tab_name, i=wid: self._mqtt_publish_widget(t, i, "off"),
                     add="+")
        elif kind == "Button switch":
            obj.config(command=lambda t=tab_name, i=wid: self._mqtt_toggle_widget(t, i))
        elif kind == "Checkbutton":
            # Nach dem Umschalten ruft Tkinter command auf: fester Payload on/off.
            obj.config(command=lambda t=tab_name, i=wid: self._mqtt_checkbutton_changed(t, i))

    def _mqtt_checkbutton_changed(self, tab_name, wid):
        inst = self.tabs.get(tab_name, {}).get("widgets", {}).get(wid)
        if not inst:
            return
        opts = inst.setdefault("options", {})
        var = opts.get("variable")
        if var is None:
            return
        checked = bool(var.get())
        opts["mqtt_check_state"] = checked
        # Ohne Verbindung wird die MQTT-Veröffentlichung still ignoriert.
        self._mqtt_publish_widget(tab_name, wid, "on" if checked else "off")
        self.push_undo()

    def _mqtt_toggle_widget(self, tab_name, wid):
        inst = self.tabs.get(tab_name, {}).get("widgets", {}).get(wid)
        if not inst:
            return
        opts = inst.setdefault("options", {})
        next_state = not bool(opts.get("mqtt_switch_on", False))
        if self._mqtt_publish_widget(tab_name, wid, "on" if next_state else "off"):
            opts["mqtt_switch_on"] = next_state
            self.push_undo()

    def _mqtt_publish_widget(self, tab_name, wid, value=None):
        # Ohne aktive MQTT-Verbindung still ignorieren, keine Meldungsfenster.
        if not self.mqtt_connected or self.mqtt_client is None:
            return False
        inst = self.tabs.get(tab_name, {}).get("widgets", {}).get(wid)
        if not inst:
            return False
        opts = inst.setdefault("options", {})
        topic = opts.get("mqtt_publish_topic", "").strip()
        if not topic:
            return False
        if value is None:
            if inst["type"] == "Entry":
                value = inst["obj"].get()
            elif inst["type"] == "Checkbutton":
                value = "on" if inst["options"]["variable"].get() else "off"
            else:
                value = opts.get("mqtt_payload", "ON")
        try:
            result = self.mqtt_client.publish(topic, str(value))
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception:
            return False

    # ---------------------------
    # delete
    def delete_selected(self):
        if not self.selected_widget:
            messagebox.showinfo(self.tr("Info"), self.tr("Kein Widget ausgewählt."))
            return
        tab_name, wid = self.selected_widget
        tab = self.get_tab_data(tab_name)
        entry = tab["widgets"].pop(wid, None)
        if entry:
            try:
                entry["obj"].destroy()
            except Exception:
                pass
        self.selected_widget = None
        self.push_undo()

    # ---------------------------
    # Undo / Redo (snapshot of full model)
    def push_undo(self, initial=False):
        state = self.serialize_model()
        # don't push duplicate consecutive states
        if not initial and self.undo_stack and self.undo_stack[-1] == state:
            return
        self.undo_stack.append(state)
        # cap length
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        # clear redo on new action
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return
        cur = self.serialize_model()
        # move current to redo
        self.redo_stack.append(cur)
        prev = self.undo_stack.pop()
        self.deserialize_model(prev)

    def redo(self):
        if not self.redo_stack:
            return
        cur = self.serialize_model()
        self.undo_stack.append(cur)
        nxt = self.redo_stack.pop()
        self.deserialize_model(nxt)

    # ---------------------------
    # Serialization: JSON model of tabs + widgets + bg paths
    def serialize_model(self):
        model = {"tabs": {}, "bg_paths": {}, "mqtt": {"host": self.mqtt_host.get().strip() or "localhost", "port": to_int(self.mqtt_port.get(), 1883)}}
        for tab_name, tab in self.tabs.items():
            t = {"widgets": {}, "width": tab.get("width", 800), "height": tab.get("height", 600)}
            for wid, inst in tab["widgets"].items():
                obj = inst["obj"]
                if inst["type"] == "Checkbutton":
                    inst["options"]["mqtt_check_state"] = bool(inst["options"]["variable"].get())
                text = obj.cget("text") if "text" in obj.keys() else ""
                bg = obj.cget("bg") if "bg" in obj.keys() else ""
                width = obj.cget("width") if "width" in obj.keys() else None
                height = obj.cget("height") if "height" in obj.keys() else None
                t["widgets"][wid] = {"type": inst["type"], "text": text, "bg": bg, "width": width, "height": height, "x": inst["x"], "y": inst["y"], "options": {k: v for k, v in inst.get("options", {}).items() if k.startswith("mqtt_") or k == "font_size"}}
            model["tabs"][tab_name] = t
            if tab.get("bg_path"):
                model["bg_paths"][tab_name] = tab.get("bg_path")
        return json.dumps(model)

    def deserialize_model(self, json_str):
        try:
            data = json.loads(json_str)
        except Exception:
            return
        # Restore global MQTT broker settings saved in the JSON file.
        mqtt_data = data.get("mqtt", {})
        if hasattr(self, "mqtt_host"):
            self.mqtt_host.delete(0, "end")
            self.mqtt_host.insert(0, str(mqtt_data.get("host", "localhost")))
        if hasattr(self, "mqtt_port"):
            self.mqtt_port.delete(0, "end")
            self.mqtt_port.insert(0, str(mqtt_data.get("port", 1883)))
        # destroy all existing tabs
        for name in list(self.tabs.keys()):
            try:
                self.tabs[name]["frame"].destroy()
            except Exception:
                pass
            del self.tabs[name]
        # recreate tabs and widgets. IDs are globally unique across all tabs.
        used_widget_ids = set()
        self.id_counter = max(self.id_counter, max(
            (int(wid[1:]) for td in data.get("tabs", {}).values()
             for wid in td.get("widgets", {})
             if isinstance(wid, str) and wid.startswith("w") and wid[1:].isdigit()),
            default=0
        ))
        for tab_name, tdata in data.get("tabs", {}).items():
            self.add_tab_with_name(tab_name)
            tab = self.get_tab_data(tab_name)
            tab_width = to_int(tdata.get("width", 800), 800)
            tab_height = to_int(tdata.get("height", 600), 600)
            tab["width"], tab["height"] = tab_width, tab_height
            tab["frame"].configure(width=tab_width, height=tab_height)
            tab["frame"].pack_propagate(False)
            tab["canvas"].place(x=0, y=0, width=tab_width, height=tab_height)
            # set background if exists and file present
            bgp = data.get("bg_paths", {}).get(tab_name)
            if bgp and os.path.exists(bgp):
                self._set_bg_for_tab(tab_name, bgp)
            # create widgets
            for saved_wid, w in tdata.get("widgets", {}).items():
                wid = saved_wid
                if wid in used_widget_ids:
                    wid = self._next_widget_id()
                used_widget_ids.add(wid)
                if isinstance(wid, str) and wid.startswith("w") and wid[1:].isdigit():
                    self.id_counter = max(self.id_counter, int(wid[1:]))
                inst = self._create_widget_instance(tab, w["type"], tab["layer"], wid)
                if not inst:
                    continue
                obj = inst["obj"]
                inst.setdefault("options", {}).update(w.get("options", {}))
                if inst["type"] == "Checkbutton":
                    inst["options"]["variable"].set(int(bool(inst["options"].get("mqtt_check_state", False))))
                inst["x"] = to_int(w.get("x", 0), 0)
                inst["y"] = to_int(w.get("y", 0), 0)
                obj.place(x=inst["x"], y=inst["y"])
                try:
                    if w.get("text") and "text" in obj.keys():
                        obj.config(text=w.get("text"))
                    if w.get("bg") and "bg" in obj.keys():
                        obj.config(bg=w.get("bg"))
                    if w.get("width") is not None and "width" in obj.keys():
                        obj.config(width=w.get("width"))
                    if w.get("height") is not None and "height" in obj.keys():
                        obj.config(height=w.get("height"))
                    font_size = to_int(inst.get("options", {}).get("font_size", 10), 10)
                    if isinstance(obj, MQTTProgressbar):
                        obj.set_font_size(font_size)
                        obj.set_value(inst.get("options", {}).get("mqtt_progress_value", 0))
                    else:
                        obj.config(font=("TkDefaultFont", font_size))
                except Exception:
                    pass
                tab["widgets"][wid] = inst
                # bind events
                obj.bind("<Button-1>", lambda e, t=tab_name, id=wid: self.on_widget_click(e, t, id))
                obj.bind("<B1-Motion>", lambda e, t=tab_name, id=wid: self.on_widget_drag(e, t, id))
                obj.bind("<ButtonRelease-1>", lambda e, t=tab_name, id=wid: self.on_widget_release(e, t, id))
                self._configure_special_button(tab_name, wid)
                opts = inst.get("options", {})
                if opts.get("mqtt_subscribe_topic"):
                    self.mqtt_subscriptions.add(opts["mqtt_subscribe_topic"])
                if opts.get("mqtt_publish_topic"):
                    if inst["type"] == "Button":
                        obj.config(command=lambda t=tab_name, i=wid: self._mqtt_publish_widget(t, i))
                    elif inst["type"] == "Entry":
                        obj.bind("<Return>", lambda e, t=tab_name, i=wid: self._mqtt_publish_widget(t, i), add="+")
                    elif inst["type"] == "Scale":
                        obj.config(command=lambda value, t=tab_name, i=wid: self._mqtt_publish_widget(t, i, value))

    # ---------------------------
    # Background handling (canvas + PIL)
    def _set_bg_for_tab(self, tab_name, path):
        tab = self.get_tab_data(tab_name)
        if not tab:
            return
        try:
            pil = Image.open(path).convert("RGBA")
            tab["bg_pil"] = pil
            tab["bg_path"] = path
            # draw now
            self._draw_bg_for_tab(tab_name)
        except Exception as e:
            messagebox.showerror(self.tr("Fehler"), self.tr("Hintergrundbild konnte nicht geladen werden: {}").format(e))

    def set_tab_background(self, tab_name=None, image_path=None):
        """
        Aufruf ohne Parameter (Button): fragt aktuellen Tab und Dateiauswahl ab.
        Aufruf mit (tab_name,image_path) möglich (z.B. beim Laden).
        """
        if tab_name is None:
            tab_name = self.get_current_tab_name()
        if tab_name is None:
            messagebox.showinfo(self.tr("Info"), self.tr("Kein Tab ausgewählt."))
            return
        if image_path is None:
            file = filedialog.askopenfilename(filetypes=[(self.tr("Bilder"),"*.png;*.jpg;*.jpeg;*.gif")])
            if not file:
                return
            image_path = file
        # set
        self._set_bg_for_tab(tab_name, image_path)
        self.push_undo()

    def _on_canvas_configure(self, tab_name):
        self._draw_bg_for_tab(tab_name)

    def _draw_bg_for_tab(self, tab_name):
        tab = self.get_tab_data(tab_name)
        if not tab:
            return
        pil = tab.get("bg_pil")
        canvas = tab.get("canvas")
        if pil is None or canvas is None:
            return
        # size
        w = max(1, canvas.winfo_width())
        h = max(1, canvas.winfo_height())
        try:
            img = pil.resize((w, h), Image.LANCZOS)
            tkimg = ImageTk.PhotoImage(img)
            tab["bg_image"] = tkimg   # keep reference
            # draw with tag 'bg'
            canvas.delete("bg")
            canvas.create_image(0, 0, image=tkimg, anchor="nw", tags=("bg",))
            # lower tag to bottom
            canvas.tag_lower("bg")
        except Exception as e:
            print("BG draw error:", e)

    # ---------------------------
    # Save / Load layout (JSON)
    def save_layout(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if not path:
            return
        data = json.loads(self.serialize_model())
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        messagebox.showinfo(self.tr("Gespeichert"), self.tr("Layout gespeichert: {}").format(path))

    def load_layout(self):
        path = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.deserialize_model(json.dumps(data))
        self.push_undo()
        messagebox.showinfo(self.tr("Geladen"), self.tr("Layout geladen: {}").format(path))

    # ---------------------------
    # Preview (separate window)
    def preview_mode(self):
        win = tk.Toplevel(self)
        win.title(self.tr("Vorschau"))
        self._preview_windows.append(win)
        current_tab = next(iter(self.tabs.values()), {"width": 800, "height": 600})
        win.geometry(f"{current_tab.get('width', 800)}x{current_tab.get('height', 600)}")
        pnb = ttk.Notebook(win)
        pnb.pack(fill="both", expand=True)
        for tab_name, tab in self.tabs.items():
            page = tk.Frame(pnb, bg="white")
            pnb.add(page, text=tab_name)
            # background
            if tab.get("bg_path") and os.path.exists(tab.get("bg_path")):
                try:
                    img = Image.open(tab.get("bg_path")).resize((tab.get("width", 800), tab.get("height", 600)), Image.LANCZOS)
                    tkimg = ImageTk.PhotoImage(img)
                    lbl = tk.Label(page, image=tkimg)
                    lbl.image = tkimg
                    lbl.place(x=0,y=0,relwidth=1,relheight=1)
                    lbl.lower()
                except Exception:
                    pass
            # widgets
            for wid, inst in tab["widgets"].items():
                wtype = inst["type"]
                try:
                    cls = tk.Button if wtype in ("Button press on", "Button switch") else getattr(tk, wtype, None)
                    if wtype in ("Progressbar Horizontal", "Progressbar Vertikal"):
                        opts = inst.get("options", {})
                        w = MQTTProgressbar(page, orient="vertical" if wtype == "Progressbar Vertikal" else "horizontal",
                                            value=opts.get("mqtt_progress_value", 0))
                        self._preview_progress_widgets.append((tab_name, wid, w))
                    elif not cls:
                        continue
                    elif wtype == "Checkbutton":
                        preview_var = tk.IntVar(master=win, value=int(bool(inst.get("options", {}).get("mqtt_check_state", False))))
                        label = inst["obj"].cget("text")
                        w = tk.Checkbutton(page, text=label, variable=preview_var)
                        w.config(command=lambda v=preview_var, t=tab_name, i=wid:
                                 self._mqtt_publish_widget(t, i, "on" if v.get() else "off"))
                    elif wtype in ("Entry","Text","Listbox"):
                        w = cls(page)
                    else:
                        # pass text if available
                        text = inst["obj"].cget("text") if "text" in inst["obj"].keys() else ""
                        w = cls(page, text=text)
                    w.place(x=inst["x"], y=inst["y"])
                    font_size = to_int(inst.get("options", {}).get("font_size", 10), 10)
                    if isinstance(w, MQTTProgressbar):
                        w.set_font_size(font_size)
                        w.config(width=inst["obj"].cget("width"), height=inst["obj"].cget("height"))
                    else:
                        w.config(font=("TkDefaultFont", font_size))
                    if wtype == "Button press on":
                        w.bind("<ButtonPress-1>", lambda e, t=tab_name, i=wid: self._mqtt_publish_widget(t, i, "on"))
                        w.bind("<ButtonRelease-1>", lambda e, t=tab_name, i=wid: self._mqtt_publish_widget(t, i, "off"))
                    elif wtype == "Button switch":
                        w.config(command=lambda t=tab_name, i=wid: self._mqtt_toggle_widget(t, i))
                    if "bg" in w.keys() and "bg" in inst["obj"].keys():
                        try:
                            w.config(bg=inst["obj"].cget("bg"))
                            if isinstance(w, MQTTProgressbar):
                                w.redraw()
                        except Exception:
                            pass
                except Exception:
                    pass

    # ---------------------------
    # Export: create folder selected by user, create script .py and copy images
    def export_project(self):
        folder = filedialog.askdirectory(title=self.tr("Ordner für Export auswählen"))
        if not folder:
            return
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        export_py = os.path.join(folder, f"export_gui_{timestamp}.py")
        model = json.loads(self.serialize_model())

        # Hintergrundbilder in den Exportordner kopieren
        for tab_name, tab in self.tabs.items():
            if tab.get("bg_path"):
                src = tab["bg_path"]
                dst = os.path.join(folder, os.path.basename(src))
                try:
                    if os.path.abspath(src) != os.path.abspath(dst):
                        shutil.copy2(src, dst)
                except Exception as exc:
                    messagebox.showwarning(self.tr("Bildexport"), self.tr("{} konnte nicht kopiert werden:\n{}").format(src, exc))

        host = self.mqtt_host.get().strip() or "localhost"
        port = to_int(self.mqtt_port.get(), 1883)

        generated = r'''# Automatisch exportierte Tkinter-MQTT-Oberfläche
# Installation: python -m pip install pillow paho-mqtt
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import json

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

BROKER_HOST = __HOST__
BROKER_PORT = __PORT__
MODEL = json.loads(__MODEL__)
LANGUAGE = __LANG__

def ui_text(de, en):
    return en if LANGUAGE == "en" else de

class MQTTProgressbar(tk.Canvas):
    """Progressbar mit sichtbarer Prozentzahl (0 bis 100) in beiden Richtungen."""
    def __init__(self, master, orient="horizontal", value=0, **kwargs):
        self.orient = orient
        self.label_font_size = 10
        if orient == "vertical":
            kwargs.setdefault("width", 48)
            kwargs.setdefault("height", 170)
        else:
            kwargs.setdefault("width", 200)
            kwargs.setdefault("height", 32)
        kwargs.setdefault("bg", "#2674c7")  # Hintergrundfarbe = Füllfarbe
        kwargs.setdefault("highlightthickness", 1)
        kwargs.setdefault("highlightbackground", "#778899")
        super().__init__(master, **kwargs)
        self.value = 0.0
        self.bind("<Configure>", self.redraw, add="+")
        self.set_value(value)

    def set_value(self, value):
        """Ungültige MQTT-Werte ignorieren; gültige Werte auf 0–100 begrenzen."""
        try:
            number = float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return False
        if not 0 <= number <= 100:
            # Außerhalb des Bereichs auf den nächsten Grenzwert begrenzen.
            if number == float("inf") or number == float("-inf") or number != number:
                return False
            number = min(100.0, max(0.0, number))
        self.value = number
        self.redraw()
        return True

    def set_font_size(self, size):
        self.label_font_size = int(size)
        self.redraw()

    def redraw(self, event=None):
        self.delete("progress_visual")
        width = self.winfo_width() if self.winfo_width() > 1 else int(self.cget("width"))
        height = self.winfo_height() if self.winfo_height() > 1 else int(self.cget("height"))
        x0, y0, x1, y1 = 1, 1, max(2, width - 1), max(2, height - 1)
        self.create_rectangle(x0, y0, x1, y1, fill="#e7ecf1", outline="", tags="progress_visual")
        if self.orient == "vertical":
            top = y1 - (y1 - y0) * self.value / 100
            if self.value > 0:
                self.create_rectangle(x0, top, x1, y1, fill=self.cget("bg"), outline="", tags="progress_visual")
        else:
            right = x0 + (x1 - x0) * self.value / 100
            if self.value > 0:
                self.create_rectangle(x0, y0, right, y1, fill=self.cget("bg"), outline="", tags="progress_visual")
        value_text = f"{self.value:g}%"
        self.create_text(width / 2, height / 2, text=value_text,
                         font=("TkDefaultFont", self.label_font_size, "bold"),
                         fill="#132437", tags="progress_visual")

root = tk.Tk()
root.title("MQTT-Tkboard")
# Fenstergröße aus der eingestellten Tab-Arbeitsfläche ableiten.
_first_tab = next(iter(MODEL.get("tabs", {}).values()), {})
_tab_width = max(100, int(_first_tab.get("width", 800)))
_tab_height = max(100, int(_first_tab.get("height", 600)))
_STATUS_HEIGHT = 36
# Notebook benötigt zusätzlich Platz für die Tab-Leiste; sonst wird die
# Arbeitsfläche samt unterer MQTT-Statuszeile im Export abgeschnitten.
_NOTEBOOK_HEADER_HEIGHT = 28
_WINDOW_WIDTH = max(_tab_width, 420)
root.geometry(
    f"{_WINDOW_WIDTH}x{_tab_height + _NOTEBOOK_HEADER_HEIGHT + _STATUS_HEIGHT}"
)
root.resizable(False, False)
notebook = ttk.Notebook(root, width=_tab_width, height=_tab_height)
notebook.pack(side="top", anchor="nw", fill="none", expand=False)
bg_images = {}
mqtt_client = None
mqtt_connected = False
mqtt_subscriptions = set()
mqtt_widgets = {}
switch_states = {}

def toggle_switch(widget_id, topic):
    next_state = not switch_states.get(widget_id, False)
    if publish(topic, "on" if next_state else "off"):
        switch_states[widget_id] = next_state

def publish(topic, value):
    if mqtt_client is None or not mqtt_connected or not topic:
        return False
    try:
        result = mqtt_client.publish(topic, str(value))
        return result.rc == mqtt.MQTT_ERR_SUCCESS
    except Exception:
        return False

def apply_message(topic, payload):
    for item in mqtt_widgets.get(topic, []):
        w, kind = item["widget"], item["type"]
        opts = item.get("options", {})
        # MQTT-Eingangswert steuert die Hintergrundfarbe:
        # exakter Treffer auf Wert 1 -> Farbe 1, Wert 2 -> Farbe 2.
        if payload == str(opts.get("mqtt_color_value1", "")) and opts.get("mqtt_color_value1", "") != "":
            color = opts.get("mqtt_color1")
        elif payload == str(opts.get("mqtt_color_value2", "")) and opts.get("mqtt_color_value2", "") != "":
            color = opts.get("mqtt_color2")
        else:
            color = None
        if color:
            try:
                w.config(bg=color)
                if isinstance(w, MQTTProgressbar):
                    w.redraw()
            except Exception:
                pass
        try:
            if kind in ("Progressbar Horizontal", "Progressbar Vertikal"):
                if w.set_value(payload):
                    opts["mqtt_progress_value"] = w.value
            elif kind in ("Label", "Button", "Checkbutton", "Radiobutton"):
                w.config(text=payload)
            elif kind == "Entry":
                w.delete(0, "end"); w.insert(0, payload)
            elif kind == "Text":
                w.delete("1.0", "end"); w.insert("1.0", payload)
            elif kind == "Spinbox":
                w.delete(0, "end"); w.insert(0, payload)
            elif kind == "Scale":
                w.set(float(payload))
        except Exception as exc:
            print("Widget-Update:", exc)

def on_connect(client, userdata, flags, rc, *extra):
    global mqtt_connected
    if client is not mqtt_client:
        return
    mqtt_connected = (rc == 0)
    root.after(0, lambda c=client, ok=mqtt_connected:
               status.config(text=ui_text("MQTT: verbunden", "MQTT: connected") if ok else ui_text("MQTT: Verbindungsfehler", "MQTT: connection error"))
               if c is mqtt_client else None)
    if mqtt_connected:
        for topic in mqtt_subscriptions:
            client.subscribe(topic)

def on_disconnect(client, userdata, rc, *extra):
    global mqtt_connected
    if client is not mqtt_client:
        return
    mqtt_connected = False
    root.after(0, lambda c=client:
               status.config(text=ui_text("MQTT: nicht verbunden", "MQTT: not connected"))
               if c is mqtt_client else None)

def on_message(client, userdata, msg):
    value = msg.payload.decode("utf-8", errors="replace")
    root.after(0, lambda t=msg.topic, v=value: apply_message(t, v))

def disconnect_mqtt():
    global mqtt_client, mqtt_connected
    client = mqtt_client
    mqtt_client = None
    mqtt_connected = False
    if client is not None:
        try:
            client.disconnect()
            client.loop_stop()
        except Exception:
            pass
    status.config(text=ui_text("MQTT: nicht verbunden", "MQTT: not connected"))

def connect_mqtt():
    global mqtt_client, mqtt_connected
    if mqtt is None:
        messagebox.showerror("MQTT", ui_text("Bitte installieren: python -m pip install paho-mqtt", "Please install: python -m pip install paho-mqtt"))
        return
    disconnect_mqtt()
    try:
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except (AttributeError, TypeError):
            client = mqtt.Client()
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        mqtt_client = client
        mqtt_connected = False
        client.connect(BROKER_HOST, BROKER_PORT, 60)
        client.loop_start()
        status.config(text=ui_text(f"MQTT: Verbindung zu {BROKER_HOST}:{BROKER_PORT} wird aufgebaut",
                                   f"MQTT: connecting to {BROKER_HOST}:{BROKER_PORT}"))
    except Exception as exc:
        mqtt_client = None
        mqtt_connected = False
        status.config(text=ui_text(f"MQTT: Verbindungsfehler ({exc})", f"MQTT: connection error ({exc})"))

for tab_name, tab_data in MODEL.get("tabs", {}).items():
    tab_width = max(100, int(tab_data.get("width", 800)))
    tab_height = max(100, int(tab_data.get("height", 600)))
    frame = tk.Frame(notebook, bg="white", width=tab_width, height=tab_height)
    frame.pack_propagate(False)
    notebook.add(frame, text=tab_name)
    bg_name = MODEL.get("bg_paths", {}).get(tab_name)
    if bg_name:
        try:
            image = Image.open(bg_name).resize((tab_width, tab_height), Image.LANCZOS)
            bg_images[tab_name] = ImageTk.PhotoImage(image)
            bg = tk.Label(frame, image=bg_images[tab_name], bd=0)
            bg.place(x=0, y=0, relwidth=1, relheight=1)
            bg.lower()
        except Exception as exc:
            print("Hintergrundbild:", exc)

    for wid, data in tab_data.get("widgets", {}).items():
        kind = data.get("type", "Label")
        opts = data.get("options", {})
        try:
            if kind in ("Progressbar Horizontal", "Progressbar Vertikal"):
                widget = MQTTProgressbar(frame, orient="vertical" if kind == "Progressbar Vertikal" else "horizontal",
                                          value=opts.get("mqtt_progress_value", 0))
            elif kind == "Checkbutton":
                check_var = tk.IntVar(master=root, value=int(bool(opts.get("mqtt_check_state", False))))
                widget = tk.Checkbutton(frame, text=data.get("text", ""), variable=check_var)
            elif kind in ("Entry", "Text", "Listbox"):
                widget = getattr(tk, kind)(frame)
            elif kind == "Scale":
                widget = tk.Scale(frame, from_=0, to=100, orient="horizontal")
            else:
                cls = tk.Button if kind in ("Button press on", "Button switch") else getattr(tk, kind)
                widget = cls(frame, text=data.get("text", ""))
            widget.place(x=data.get("x", 0), y=data.get("y", 0))
            if data.get("bg"):
                try: widget.config(bg=data["bg"])
                except Exception: pass
            if data.get("width") is not None:
                try: widget.config(width=int(data["width"]))
                except Exception: pass
            if data.get("height") is not None:
                try: widget.config(height=int(data["height"]))
                except Exception: pass
            if isinstance(widget, MQTTProgressbar):
                widget.set_font_size(int(opts.get("font_size", 10)))
                widget.redraw()
            else:
                try: widget.config(font=("TkDefaultFont", int(opts.get("font_size", 10))))
                except Exception: pass

            pub = opts.get("mqtt_publish_topic", "").strip()
            sub = opts.get("mqtt_subscribe_topic", "").strip()
            payload = opts.get("mqtt_payload", "ON")
            if sub:
                mqtt_subscriptions.add(sub)
                mqtt_widgets.setdefault(sub, []).append({"widget": widget, "type": kind, "options": opts})
            if kind == "Button press on":
                widget.bind("<ButtonPress-1>", lambda e, t=pub: publish(t, "on"))
                widget.bind("<ButtonRelease-1>", lambda e, t=pub: publish(t, "off"))
            elif kind == "Button switch":
                switch_states[wid] = bool(opts.get("mqtt_switch_on", False))
                widget.config(command=lambda i=wid, t=pub: toggle_switch(i, t))
            elif kind == "Checkbutton":
                widget.config(command=lambda v=check_var, t=pub:
                              publish(t, "on" if v.get() else "off"))
            elif pub and kind == "Button":
                widget.config(command=lambda t=pub, v=payload: publish(t, v))
            elif pub and kind == "Entry":
                widget.bind("<Return>", lambda e, w=widget, t=pub: publish(t, w.get()), add="+")
            elif pub and kind == "Scale":
                widget.config(command=lambda value, t=pub: publish(t, value))
        except Exception as exc:
            print("Widget konnte nicht erstellt werden:", wid, exc)

bar = tk.Frame(root)
bar.pack(side="bottom", fill="x")
status = tk.Label(bar, text=ui_text(f"MQTT: nicht verbunden ({BROKER_HOST}:{BROKER_PORT})",
                                    f"MQTT: not connected ({BROKER_HOST}:{BROKER_PORT})"))
status.pack(side="left", padx=8, pady=4)
tk.Button(bar, text=ui_text("MQTT trennen", "Disconnect MQTT"), command=disconnect_mqtt).pack(side="right", padx=8, pady=4)
tk.Button(bar, text=ui_text("MQTT verbinden", "Connect MQTT"), command=connect_mqtt).pack(side="right", padx=8, pady=4)

def close_app():
    disconnect_mqtt()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", close_app)
root.mainloop()
'''
        generated = generated.replace("__HOST__", repr(host))
        generated = generated.replace("__PORT__", repr(port))
        generated = generated.replace("__MODEL__", repr(json.dumps(model, ensure_ascii=False)))
        generated = generated.replace("__LANG__", repr(self.language))
        try:
            with open(export_py, "w", encoding="utf-8") as f:
                f.write(generated)
            messagebox.showinfo(
                "Export",
                self.tr("Export erfolgreich:\n{}\n\nMQTT-Funktionen wurden übernommen. Im Exportprogramm bitte auf 'MQTT verbinden' klicken.").format(export_py)
            )
        except Exception as exc:
            messagebox.showerror(self.tr("Export Fehler"), self.tr("Konnte Export-Datei nicht schreiben: {}").format(exc))

    # ---------------------------
    # Utility: serialize wrapper used elsewhere
    def serialize_model(self):
        return self.serialize_model() if False else self.serialize_model_internal()

    def serialize_model_internal(self):
        # identical to earlier serialize_model used above
        model = {"tabs": {}, "bg_paths": {}, "mqtt": {"host": self.mqtt_host.get().strip() or "localhost", "port": to_int(self.mqtt_port.get(), 1883)}}
        for tab_name, tab in self.tabs.items():
            t = {"widgets": {}, "width": tab.get("width", 800), "height": tab.get("height", 600)}
            for wid, inst in tab["widgets"].items():
                obj = inst["obj"]
                if inst["type"] == "Checkbutton":
                    inst["options"]["mqtt_check_state"] = bool(inst["options"]["variable"].get())
                text = obj.cget("text") if "text" in obj.keys() else ""
                bg = obj.cget("bg") if "bg" in obj.keys() else ""
                width = obj.cget("width") if "width" in obj.keys() else None
                height = obj.cget("height") if "height" in obj.keys() else None
                t["widgets"][wid] = {"type": inst["type"], "text": text, "bg": bg, "width": width, "height": height, "x": inst["x"], "y": inst["y"], "options": {k: v for k, v in inst.get("options", {}).items() if k.startswith("mqtt_") or k == "font_size"}}
            model["tabs"][tab_name] = t
            if tab.get("bg_path"):
                model["bg_paths"][tab_name] = tab.get("bg_path")
        return json.dumps(model)

    # Provide compatibility name (used in code above)
    def serialize(self):
        return self.serialize_model_internal()

# ---------------------------
if __name__ == "__main__":
    app = TkDesigner()
    app.mainloop()
