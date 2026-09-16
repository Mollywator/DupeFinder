"""
Review window for visually similar images.

Exact duplicates are byte-identical and safe to move without looking. Similar
images are not: a burst of photos or two shots of the same scene can hash
alike. So every similar group is shown with thumbnails, and only what stays
ticked here gets moved.
"""

import os
from pathlib import Path

from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageOps

from .scanner import format_size

THUMB = 220
COLUMNS = 4


def _thumbnail(path):
    try:
        with Image.open(path) as img:
            size = img.size
            img.draft("RGB", (THUMB * 2, THUMB * 2))
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((THUMB, THUMB))
            return ctk.CTkImage(light_image=img, dark_image=img, size=img.size), size
    except Exception:
        return None, None


class ReviewWindow(ctk.CTkToplevel):
    def __init__(self, master, groups, on_finish, icon=None):
        super().__init__(master)
        self.title("Ähnliche Bilder prüfen")
        self.geometry("1040x760")
        self.minsize(800, 560)
        if icon:
            self.after(250, lambda: self.iconbitmap(icon))

        self.groups = groups
        self.on_finish = on_finish
        self.index = 0
        self._images = []
        # Per group: set of paths to move. Starts with the suggestion.
        self.decisions = [{d["path"] for d in g["duplicates"]} for g in groups]
        self.vars = {}
        self.seen = set()

        self._build()
        self._show()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.transient(master)
        self.after(100, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass

    # ── Layout ───────────────────────────────────────────────────────────
    def _build(self):
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=15, pady=(12, 4))
        self.title_label = ctk.CTkLabel(head, text="", font=ctk.CTkFont(size=16, weight="bold"), anchor="w")
        self.title_label.pack(side="left")
        self.count_label = ctk.CTkLabel(head, text="", anchor="e", text_color="gray")
        self.count_label.pack(side="right")

        ctk.CTkLabel(
            self, anchor="w", justify="left", text_color="gray",
            text="Angehakte Bilder werden in den Aussortiert-Ordner verschoben, die anderen bleiben liegen. "
                 "Mindestens ein Bild pro Gruppe bleibt immer. Klick auf ein Bild öffnet es groß.",
        ).pack(fill="x", padx=15)

        self.grid_frame = ctk.CTkScrollableFrame(self)
        self.grid_frame.pack(fill="both", expand=True, padx=15, pady=8)
        for c in range(COLUMNS):
            self.grid_frame.grid_columnconfigure(c, weight=1)

        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=15, pady=(0, 12))
        self.prev_btn = ctk.CTkButton(nav, text="◀  Zurück", width=110, command=self._prev)
        self.prev_btn.pack(side="left")
        self.next_btn = ctk.CTkButton(nav, text="Weiter  ▶", width=110, command=self._next)
        self.next_btn.pack(side="left", padx=8)
        ctk.CTkButton(nav, text="Alle behalten", width=120, fg_color="gray40", hover_color="gray30",
                      command=self._keep_all).pack(side="left", padx=(8, 0))

        ctk.CTkButton(nav, text="Abbrechen", width=110, fg_color="gray40", hover_color="gray30",
                      command=self._cancel).pack(side="right")
        ctk.CTkButton(nav, text="✔  Fertig – übernehmen", width=190, fg_color="#15803d", hover_color="#166534",
                      command=self._finish).pack(side="right", padx=8)

    def _show(self):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self._images.clear()
        self.vars.clear()

        self.seen.add(self.index)
        group = self.groups[self.index]
        files = [group["original"]] + group["duplicates"]
        chosen = self.decisions[self.index]
        self.title_label.configure(text=f"Gruppe {self.index + 1} von {len(self.groups)}")
        self.count_label.configure(text=f"{len(files)} Bilder · {len(chosen)} zum Aussortieren angehakt")
        self.prev_btn.configure(state="normal" if self.index > 0 else "disabled")
        self.next_btn.configure(state="normal" if self.index < len(self.groups) - 1 else "disabled")

        for i, record in enumerate(files):
            path = record["path"]
            cell = ctk.CTkFrame(self.grid_frame)
            cell.grid(row=i // COLUMNS, column=i % COLUMNS, padx=6, pady=6, sticky="nsew")

            image, size = _thumbnail(path)
            if image:
                self._images.append(image)
                pic = ctk.CTkLabel(cell, image=image, text="", cursor="hand2")
            else:
                pic = ctk.CTkLabel(cell, text="(keine Vorschau)", width=THUMB, height=THUMB // 2)
            pic.pack(padx=6, pady=(6, 2))
            pic.bind("<Button-1>", lambda _e, p=path: self._open(p))

            details = []
            if size:
                details.append(f"{size[0]}×{size[1]}")
            if record.get("size"):
                details.append(format_size(record["size"]))
            if i == 0:
                details.append("beste Qualität")
            ctk.CTkLabel(cell, text=" · ".join(details), font=ctk.CTkFont(size=11)).pack()
            ctk.CTkLabel(cell, text=_short(Path(path).name, 32), font=ctk.CTkFont(size=11, weight="bold")).pack()
            ctk.CTkLabel(cell, text=_short(str(Path(path).parent), 36), font=ctk.CTkFont(size=10),
                         text_color="gray").pack()

            var = ctk.BooleanVar(value=path in chosen)
            self.vars[path] = var
            ctk.CTkCheckBox(cell, text="Aussortieren", variable=var,
                            command=lambda p=path: self._toggle(p)).pack(pady=(4, 8))

    # ── Actions ──────────────────────────────────────────────────────────
    def _toggle(self, path):
        chosen = self.decisions[self.index]
        if self.vars[path].get():
            group = self.groups[self.index]
            total = 1 + len(group["duplicates"])
            if len(chosen) + 1 >= total:
                self.vars[path].set(False)
                self.count_label.configure(text="Mindestens ein Bild muss in der Gruppe bleiben.")
                return
            chosen.add(path)
        else:
            chosen.discard(path)
        group = self.groups[self.index]
        self.count_label.configure(
            text=f"{1 + len(group['duplicates'])} Bilder · {len(chosen)} zum Aussortieren angehakt")

    def _keep_all(self):
        self.decisions[self.index] = set()
        self._show()

    def _open(self, path):
        try:
            os.startfile(path)
        except (OSError, AttributeError):
            pass

    def _prev(self):
        if self.index > 0:
            self.index -= 1
            self._show()

    def _next(self):
        if self.index < len(self.groups) - 1:
            self.index += 1
            self._show()

    def _cancel(self):
        self._close()
        self.on_finish(None)

    def _finish(self):
        unseen = [i for i in range(len(self.groups)) if i not in self.seen]
        if unseen:
            answer = messagebox.askyesnocancel(
                "Nicht alle Gruppen angesehen",
                f"{len(unseen)} von {len(self.groups)} Gruppen hast du noch nicht angesehen.\n\n"
                "Ja = für diese den Vorschlag übernehmen (alles außer dem besten Bild aussortieren)\n"
                "Nein = diese Gruppen nicht anfassen\n"
                "Abbrechen = weiter prüfen",
                parent=self,
            )
            if answer is None:
                return
            if answer is False:
                for i in unseen:
                    self.decisions[i] = set()
        self._close()
        self.on_finish(build_approved_groups(self.groups, self.decisions))

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


def build_approved_groups(groups, decisions):
    """
    Turn review decisions into move groups. Whatever is not ticked is kept; the
    first kept file becomes the group's original, which the mover checks still
    exists before it moves anything.
    """
    approved = []
    for group, chosen in zip(groups, decisions):
        files = [group["original"]] + group["duplicates"]
        keep = [f for f in files if f["path"] not in chosen]
        move = [f for f in files if f["path"] in chosen]
        if not move or not keep:
            continue
        approved.append({"type": "similar", "original": keep[0], "also_keep": keep[1:], "duplicates": move})
    return approved


def _short(text, limit):
    return text if len(text) <= limit else "…" + text[-(limit - 1):]
