"""Main window."""

import os
import threading
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import __version__, mover, scanner, storage
from .review import ReviewWindow

ICON = Path(__file__).parent / "icon.ico"


def _dots(number):
    return f"{number:,}".replace(",", ".")


class DupeFinderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"DupeFinder {__version__} – Doppelte Bilder finden")
        self.geometry("900x800")
        self.minsize(760, 640)
        if ICON.exists():
            try:
                self.iconbitmap(str(ICON))
            except Exception:
                pass

        self.queue = Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self._followups = []
        self._button_colors = {}
        self.exact_groups = []
        self.similar_groups = []
        self.resume_data = None
        self.settings = storage.load_settings()

        self._build()
        self._busy(False)
        self._restore()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Layout ───────────────────────────────────────────────────────────
    def _section(self, title):
        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(8, 2))
        return frame

    def _path_row(self, parent, label, var, pady):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=pady)
        ctk.CTkLabel(row, text=label, width=150, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=var).pack(side="left", padx=5, expand=True, fill="x")
        ctk.CTkButton(row, text="Ordner wählen…", width=120, command=lambda: self._browse(var)).pack(side="left")

    def _build(self):
        pictures = Path.home() / "Pictures"
        paths = self._section("1. Ordner")
        self.scan_var = ctk.StringVar(value=self.settings.get("scan_path", str(pictures)))
        self.output_var = ctk.StringVar(value=self.settings.get("output_path", str(pictures / "Aussortiert")))
        self._path_row(paths, "Hier suchen:", self.scan_var, 2)
        self._path_row(paths, "Aussortieren nach:", self.output_var, (2, 10))

        options = self._section("2. Suchart")
        row = ctk.CTkFrame(options, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(2, 4))
        self.mode_var = ctk.StringVar(value=self.settings.get("mode", "Exakt + Ähnlich"))
        self.mode_menu = ctk.CTkSegmentedButton(row, values=["Nur exakt", "Exakt + Ähnlich"],
                                                variable=self.mode_var, command=self._on_mode)
        self.mode_menu.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(row, text="Ähnlichkeit:").pack(side="left", padx=(0, 5))
        self.threshold_var = ctk.IntVar(value=self.settings.get("threshold", 100))
        self.slider = ctk.CTkSlider(row, from_=80, to=100, number_of_steps=20, width=160,
                                    variable=self.threshold_var, command=self._on_threshold)
        self.slider.pack(side="left", padx=(0, 5))
        self.threshold_label = ctk.CTkLabel(row, text=f"{self.threshold_var.get()} %", width=45)
        self.threshold_label.pack(side="left")
        self.mode_desc = ctk.CTkLabel(
            options, anchor="w", justify="left", text_color="gray", font=ctk.CTkFont(size=11),
            text="Nur exakt = findet Byte für Byte identische Kopien.   Exakt + Ähnlich = findet zusätzlich "
                 "optisch gleiche Bilder; sie werden vor dem Aussortieren zur Prüfung angezeigt.",
            wraplength=820,
        )
        self.mode_desc.pack(fill="x", padx=10, pady=(0, 2))
        self.level_desc = ctk.CTkLabel(options, anchor="w", justify="left", wraplength=820,
                                       font=ctk.CTkFont(size=12))
        self.level_desc.pack(fill="x", padx=10, pady=(4, 0))
        ctk.CTkLabel(options, text=scanner.LEVEL_FOOTNOTE, anchor="w", justify="left", wraplength=820,
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(fill="x", padx=10, pady=(2, 8))
        self._on_threshold(self.threshold_var.get())
        if not scanner.PERCEPTUAL_AVAILABLE:
            self.mode_var.set("Nur exakt")
            self.mode_menu.configure(state="disabled")
        self._on_mode(self.mode_var.get())

        actions = self._section("3. Los geht's")
        buttons = ctk.CTkFrame(actions, fg_color="transparent")
        buttons.pack(fill="x", padx=10, pady=(2, 10))
        bold = ctk.CTkFont(size=14, weight="bold")
        self.start_btn = ctk.CTkButton(buttons, text="▶  Suche starten", command=self._start_scan, height=38,
                                       width=170, font=bold, fg_color="#1d4ed8", hover_color="#1e40af")
        self.start_btn.pack(side="left", padx=(0, 8))
        self.move_btn = ctk.CTkButton(buttons, text="✔  Duplikate aussortieren", command=self._start_move,
                                      height=38, width=210, font=bold, fg_color="#15803d", hover_color="#166534",
                                      state="disabled")
        self.move_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ctk.CTkButton(buttons, text="✖  Abbrechen", command=self._stop, height=38, width=140,
                                      font=bold, fg_color="#b91c1c", hover_color="#991b1b", state="disabled")
        self.stop_btn.pack(side="left")

        extra = ctk.CTkFrame(actions, fg_color="transparent")
        extra.pack(fill="x", padx=10, pady=(0, 10))
        grey = {"fg_color": "gray35", "hover_color": "gray25", "height": 30}
        self.undo_btn = ctk.CTkButton(extra, text="Letztes Aussortieren rückgängig", command=self._undo,
                                      state="disabled", width=250, **grey)
        self.undo_btn.pack(side="left", padx=(0, 8))
        self.delete_btn = ctk.CTkButton(extra, text="Aussortierte Dateien löschen…", command=self._delete,
                                        state="disabled", width=240, **grey)
        self.delete_btn.pack(side="left", padx=(0, 8))
        self.report_btn = ctk.CTkButton(extra, text="Bericht öffnen", command=self._open_report, width=120, **grey)
        self.report_btn.pack(side="left")

        progress = self._section("Fortschritt")
        self.progress_bar = ctk.CTkProgressBar(progress)
        self.progress_bar.pack(fill="x", padx=10, pady=2)
        self.progress_bar.set(0)
        info = ctk.CTkFrame(progress, fg_color="transparent")
        info.pack(fill="x", padx=10)
        self.phase_label = ctk.CTkLabel(info, text="Schritt: –", anchor="w")
        self.phase_label.pack(side="left", padx=(0, 20))
        self.count_label = ctk.CTkLabel(info, text="", anchor="w")
        self.count_label.pack(side="left", padx=(0, 20))
        self.result_label = ctk.CTkLabel(info, text="", anchor="w", font=ctk.CTkFont(weight="bold"))
        self.result_label.pack(side="left")
        self.file_label = ctk.CTkLabel(progress, text="", anchor="w", text_color="gray")
        self.file_label.pack(fill="x", padx=10, pady=(0, 8))

        log = ctk.CTkFrame(self)
        log.pack(fill="both", expand=True, padx=15, pady=(5, 5))
        self.log_text = ctk.CTkTextbox(log, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text.configure(state="disabled")

        self.status_var = ctk.StringVar(value="Bereit")
        ctk.CTkLabel(self, textvariable=self.status_var, anchor="w", font=ctk.CTkFont(size=11)).pack(
            fill="x", padx=15, pady=(0, 8))

    # ── Small helpers ────────────────────────────────────────────────────
    def _on_mode(self, value):
        self.slider.configure(state="normal" if value == "Exakt + Ähnlich" else "disabled")

    def _on_threshold(self, value):
        self.threshold_label.configure(text=f"{int(value)} %")
        self.level_desc.configure(text=f"Bei {int(value)} %: {scanner.describe_level(int(value))}")

    def _browse(self, var):
        initial = var.get() if Path(var.get()).is_dir() else str(Path.home())
        path = filedialog.askdirectory(initialdir=initial, parent=self)
        if path:
            var.set(os.path.normpath(path))

    def _log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _open_report(self):
        report = storage.report_file()
        if report.exists():
            os.startfile(report)
        else:
            messagebox.showinfo("Bericht", "Es gibt noch keinen Bericht. Starte zuerst eine Suche.", parent=self)

    def _save_settings(self):
        self.settings.update({
            "scan_path": self.scan_var.get().strip(),
            "output_path": self.output_var.get().strip(),
            "mode": self.mode_var.get(),
            "threshold": int(self.threshold_var.get()),
        })
        storage.save_settings(self.settings)

    def _enable(self, button, on):
        """CustomTkinter only dims the label of a disabled button; grey it out fully."""
        colors = self._button_colors.setdefault(button, button.cget("fg_color"))
        button.configure(state="normal" if on else "disabled", fg_color=colors if on else "gray25")

    def _busy(self, busy):
        self._enable(self.start_btn, not busy)
        self._enable(self.stop_btn, busy)
        self._enable(self.report_btn, not busy)
        if busy:
            for btn in (self.move_btn, self.undo_btn, self.delete_btn):
                self._enable(btn, False)
        else:
            self._refresh_buttons()

    def _refresh_buttons(self):
        self._enable(self.move_btn, bool(self.exact_groups or self.similar_groups))
        has_journal = bool(mover.open_journals())
        self._enable(self.undo_btn, has_journal)
        self._enable(self.delete_btn, has_journal)

    def _show_results(self):
        exact = sum(len(g["duplicates"]) for g in self.exact_groups)
        similar = sum(len(g["duplicates"]) for g in self.similar_groups)
        self.result_label.configure(text=f"{_dots(exact)} exakt, {_dots(similar)} ähnlich")
        return exact, similar

    # ── Startup ──────────────────────────────────────────────────────────
    def _restore(self):
        data = storage.load_progress()
        if data:
            self.resume_data = data
            if data.get("scan_complete") and (data.get("duplicate_groups") or data.get("similar_groups")):
                self.scan_var.set(data.get("scan_path", self.scan_var.get()))
                self.output_var.set(data.get("output_path", self.output_var.get()))
                self.exact_groups = [scanner.normalize_group(g) for g in data.get("duplicate_groups", [])]
                self.similar_groups = [scanner.normalize_group(g) for g in data.get("similar_groups", [])]
                exact, similar = self._show_results()
                self._log(f"Ergebnis der letzten Suche ({data.get('last_updated', '?')}) geladen: "
                          f"{_dots(exact)} exakte und {_dots(similar)} ähnliche Duplikate.")
                self._log("Mit „Duplikate aussortieren“ weitermachen oder neu suchen.")
            elif data.get("file_hashes"):
                self._log(f"Zwischenstand gefunden: {_dots(len(data['file_hashes']))} Dateien sind schon geprüft. "
                          "Eine neue Suche im selben Ordner macht dort weiter.")
        journals = mover.open_journals()
        if journals:
            count = sum(len(mover.pending_files(j)) for j in journals)
            if count:
                self._log(f"Im Aussortiert-Ordner liegen noch {_dots(count)} Dateien aus früheren Durchgängen – "
                          "sie können gelöscht oder zurückgelegt werden.")
        self._refresh_buttons()

    # ── Scan ─────────────────────────────────────────────────────────────
    def _start_scan(self):
        scan_path = os.path.normpath(self.scan_var.get().strip()) if self.scan_var.get().strip() else ""
        output_path = os.path.normpath(self.output_var.get().strip()) if self.output_var.get().strip() else ""
        error = scanner.validate_paths(scan_path, output_path)
        if error:
            messagebox.showerror("Ordner prüfen", error, parent=self)
            return
        self.scan_var.set(scan_path)
        self.output_var.set(output_path)
        self._save_settings()

        threshold = int(self.threshold_var.get()) if self.mode_var.get() == "Exakt + Ähnlich" else None
        self.exact_groups, self.similar_groups = [], []
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.result_label.configure(text="")
        self._log(f"Suche in: {scan_path}")
        self._log(f"Suchart: {'Exakt + Ähnlich (' + str(threshold) + ' %)' if threshold else 'Nur exakt'}")
        self._run(scanner.scan, scan_path, output_path, self.stop_event, self.queue.put, self.resume_data, threshold)

    # ── Move ─────────────────────────────────────────────────────────────
    def _start_move(self):
        if not (self.exact_groups or self.similar_groups):
            return
        if self.similar_groups:
            self._log(f"{_dots(len(self.similar_groups))} Gruppen ähnlicher Bilder zur Prüfung geöffnet.")
            ReviewWindow(self, self.similar_groups, self._after_review,
                         icon=str(ICON) if ICON.exists() else None)
        else:
            self._after_review([])

    def _after_review(self, approved_similar):
        if approved_similar is None:
            self._log("Prüfung abgebrochen – nichts verschoben.")
            return
        groups = self.exact_groups + approved_similar
        total = sum(len(g["duplicates"]) for g in groups)
        if total == 0:
            messagebox.showinfo("Nichts zu tun", "Es wurde nichts zum Aussortieren ausgewählt.", parent=self)
            return
        exact = sum(len(g["duplicates"]) for g in self.exact_groups)
        output_path = self.output_var.get().strip()
        if not messagebox.askyesno(
            "Aussortieren bestätigen",
            f"{_dots(total)} Dateien werden verschoben nach:\n{output_path}\n\n"
            f"• {_dots(exact)} exakte Kopien\n• {_dots(total - exact)} ähnliche Bilder (von dir geprüft)\n\n"
            "Es wird noch nichts gelöscht. Du kannst das danach rückgängig machen.\n\nFortfahren?",
            parent=self,
        ):
            return
        self._log(f"\n{_dots(total)} Dateien werden nach {output_path} verschoben...")
        self._run(mover.move_duplicates, self.scan_var.get().strip(), output_path, groups,
                  self.stop_event, self.queue.put)

    def _after_move(self, info):
        self.exact_groups, self.similar_groups = [], []
        storage.clear_results(storage.load_progress())
        self.result_label.configure(text="")
        self.status_var.set(f"{_dots(info['moved'])} Dateien aussortiert")
        if info["moved"] == 0:
            messagebox.showinfo("Fertig", "Es wurde nichts verschoben. Details stehen im Protokoll.", parent=self)
            return
        output_path = self.output_var.get().strip()
        text = (f"{_dots(info['moved'])} Dateien liegen jetzt in:\n{output_path}\n")
        if info["skipped"] or info["errors"]:
            text += f"\n({_dots(info['skipped'])} übersprungen, {_dots(info['errors'])} Fehler – siehe Protokoll)\n"
        text += "\nSchau sie dir gerne vorher an.\n\nSollen die aussortierten Dateien jetzt gelöscht werden?"
        if messagebox.askyesno("Aussortieren abgeschlossen", text, default=messagebox.NO, parent=self):
            self._delete(confirmed=True)
        else:
            self._log("Die Dateien bleiben im Aussortiert-Ordner. Später löschen oder zurücklegen ist jederzeit möglich.")

    # ── Undo / delete ────────────────────────────────────────────────────
    def _undo(self):
        journals = mover.open_journals()
        if not journals:
            return
        journal = journals[0]
        count = len(mover.pending_files(journal))
        if not messagebox.askyesno("Rückgängig machen",
                                   f"{_dots(count)} Dateien vom letzten Aussortieren an ihren alten Platz "
                                   "zurücklegen?", parent=self):
            return
        self._run(mover.undo, journal, self.queue.put)

    def _delete(self, confirmed=False):
        journals = mover.open_journals()
        files = [f for j in journals for f in mover.pending_files(j)]
        if not files:
            messagebox.showinfo("Nichts zu löschen", "Es liegen keine aussortierten Dateien mehr vor.", parent=self)
            for j in journals:
                j.mark(mover.STATE_DELETED)
            self._refresh_buttons()
            return
        roots = {os.path.splitdrive(os.path.abspath(f))[0].lower() or f for f in files}
        permanent = not all(mover.has_recycle_bin(root + "\\") for root in roots)
        if permanent:
            if not messagebox.askyesno(
                "Achtung: kein Papierkorb",
                f"Die {_dots(len(files))} Dateien liegen auf einem Netzlaufwerk. Dort gibt es keinen Papierkorb – "
                "sie wären ENDGÜLTIG weg und können nicht wiederhergestellt werden.\n\nWirklich endgültig löschen?",
                icon="warning", default=messagebox.NO, parent=self,
            ):
                return
        elif not confirmed and not messagebox.askyesno(
            "Aussortierte Dateien löschen",
            f"{_dots(len(files))} aussortierte Dateien in den Papierkorb legen?", default=messagebox.NO, parent=self,
        ):
            return
        self._run(self._delete_all, journals, permanent)

    def _delete_all(self, journals, permanent):
        for journal in journals:
            mover.delete_moved(journal, self.queue.put, permanent=permanent)

    # ── Worker plumbing ──────────────────────────────────────────────────
    def _run(self, target, *args):
        self.stop_event.clear()
        self._busy(True)
        self.progress_bar.set(0)
        self.worker = threading.Thread(target=self._guard, args=(target, args), daemon=True)
        self.worker.start()
        self.after(100, self._poll)

    def _guard(self, target, args):
        try:
            target(*args)
        except Exception as e:  # never leave the window stuck in "busy"
            self.queue.put(("log", f"Unerwarteter Fehler: {e!r}"))
            self.queue.put(("failed", None))
        finally:
            self.queue.put(("worker_exit", None))

    def _stop(self):
        self.stop_event.set()
        self.status_var.set("Wird abgebrochen...")
        self._enable(self.stop_btn, False)

    def _poll(self):
        # Follow-ups (dialogs, the next job) wait for worker_exit, so they never
        # start while the previous worker still counts as busy.
        followups = self._followups
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self.status_var.set(msg[1])
                elif kind == "progress":
                    current, total, phase = msg[1], msg[2], msg[3]
                    self.progress_bar.set(current / total if total else 0)
                    self.phase_label.configure(text=f"Schritt: {phase}")
                    self.count_label.configure(text=f"{_dots(current)} / {_dots(total)}" if total else "")
                elif kind == "current_file":
                    path = msg[1]
                    self.file_label.configure(text=path if len(path) <= 100 else "…" + path[-99:])
                elif kind == "log":
                    self._log(msg[1])
                elif kind == "done":
                    followups.append(lambda s=msg[1]: self._scan_done(s))
                elif kind == "stopped":
                    self._log("Suche abgebrochen – der Zwischenstand ist gespeichert.")
                    self.status_var.set("Abgebrochen – Zwischenstand gespeichert")
                    self.resume_data = storage.load_progress()
                elif kind == "move_done":
                    followups.append(lambda i=msg[1]: self._after_move(i))
                elif kind == "move_stopped":
                    self.status_var.set("Aussortieren abgebrochen")
                    self._log("Bereits verschobene Dateien lassen sich mit „Rückgängig“ zurücklegen.")
                elif kind == "undo_done":
                    self.status_var.set(f"{_dots(msg[1]['restored'])} Dateien zurückgelegt")
                elif kind == "delete_done":
                    self.status_var.set(f"{_dots(msg[1]['deleted'])} Dateien gelöscht")
                elif kind == "failed":
                    self.status_var.set("Fehler – siehe Protokoll")
                elif kind == "worker_exit":
                    # Queue order guarantees every message of the run is handled by now.
                    self.file_label.configure(text="")
                    self.phase_label.configure(text="Schritt: fertig")
                    self.count_label.configure(text="")
                    self._busy(False)
                    self._followups = []
                    for followup in followups:
                        followup()
                    return
        except Empty:
            pass
        self.after(100, self._poll)

    def _scan_done(self, summary):
        self.exact_groups = summary["groups"]
        self.similar_groups = summary["similar_groups"]
        self.resume_data = storage.load_progress()
        exact, similar = self._show_results()
        self.progress_bar.set(1)
        self._log(f"\nSuche fertig: {_dots(exact)} exakte Duplikate, {_dots(similar)} ähnliche Bilder, "
                  f"{scanner.format_size(summary['saved_bytes'])} Platz freizugeben.")
        if exact or similar:
            self._log("Weiter mit „Duplikate aussortieren“.")
            self.status_var.set("Suche fertig")
        else:
            self.status_var.set("Suche fertig – keine Duplikate gefunden")
        self._refresh_buttons()

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Beenden",
                                       "Es läuft noch ein Vorgang. Abbrechen und beenden?\n"
                                       "(Der Zwischenstand wird gespeichert.)", parent=self):
                return
            self.stop_event.set()
            self.worker.join(timeout=10)
        self._save_settings()
        self.destroy()


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    DupeFinderApp().mainloop()
