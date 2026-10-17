from collections.abc import Callable
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox


def build_file_import_menu(
        parent: tk.Misc,
        title: str,
        filetypes: tuple[tuple[str, str], ...],
        allowed_suffixes: frozenset[str],
        on_select: Callable[[tuple[str, ...], str | None], None]) -> tk.Menu:
    top = parent.winfo_toplevel()

    def is_supported(path: str) -> bool:
        return (not allowed_suffixes
                or Path(path).suffix.casefold() in allowed_suffixes)

    def choose_files() -> None:
        selected = filedialog.askopenfilenames(
            parent=top, title=title, filetypes=filetypes)
        paths = tuple(path for path in selected if is_supported(path))
        if paths:
            on_select(paths, None)
        elif selected:
            extensions = ", ".join(sorted(allowed_suffixes))
            messagebox.showwarning(
                title, f"Choose files with these extensions: {extensions}.",
                parent=top)

    def choose_folder() -> None:
        folder = filedialog.askdirectory(
            parent=top, title=title, mustexist=True)
        if not folder:
            return
        try:
            supported = any(path.is_file() and is_supported(str(path))
                            for path in Path(folder).iterdir())
        except OSError as exc:
            messagebox.showerror(title, str(exc), parent=top)
            return
        if not supported:
            extensions = (", ".join(sorted(allowed_suffixes))
                          if allowed_suffixes else "files")
            messagebox.showwarning(
                title, f"The selected folder contains no supported {extensions}.",
                parent=top)
            return
        on_select((), folder)

    menu = tk.Menu(parent, tearoff=0)
    menu.add_command(label="Choose files…", command=choose_files)
    menu.add_command(label="Choose folder…", command=choose_folder)
    menu.add_separator()
    menu.add_command(label="Clear files", command=lambda: on_select((), None))
    return menu
