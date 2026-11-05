"""Session files in Notepad++'s session.xml format."""
import os
import xml.etree.ElementTree as ET

from PyQt6.Qsci import QsciScintilla as S

from . import styles as stl
from .langs import LANG_MENU


def _lang_display(main, lang):
    cid = LANG_MENU.get(lang)
    if cid and cid in main.actions:
        return main.actions[cid].text().replace("&", "")
    return lang


def _lang_from_display(main, s):
    if not s:
        return None
    if s in main.langdb.langs:
        return s
    low = s.lower()
    for name, cid in LANG_MENU.items():
        a = main.actions.get(cid)
        if a is not None and a.text().replace("&", "").lower() == low:
            return name
    if low in ("normal text", "none (normal text)"):
        return "normal"
    return None


def save_session(main, path, with_backups=False):
    root = ET.Element("NotepadPlus")
    sess = ET.SubElement(root, "Session", activeView=str(main.active_view.index))
    for v in main.views:
        tag = "mainView" if v.index == 0 else "subView"
        v.save_state()
        el = ET.SubElement(sess, tag, activeIndex=str(max(0, v.index_of(v.current))))
        for b in v.buffers:
            if b.untitled and not (with_backups and b.backup_path):
                continue
            st = b.view_state.get(v.index, {})
            fe = ET.SubElement(el, "File",
                               firstVisibleLine=str(st.get("first", 0)), xOffset=str(st.get("xoffset", 0)),
                               scrollWidth="1", startPos=str(st.get("anchor", 0)), endPos=str(st.get("caret", 0)),
                               selMode=str(st.get("selmode", 0)), offset="0", wrapCount="1",
                               lang=_lang_display(main, b.lang), encoding="-1",
                               userReadOnly="yes" if b.user_readonly else "no",
                               filename=b.path if b.path else b.title,
                               backupFilePath=(b.backup_path or "") if with_backups else "",
                               originalFileLastModifTimestamp=str(int(b.mtime or 0)),
                               originalFileLastModifTimestampHigh="0",
                               tabColourId=str(b.tab_color), RTL="no",
                               tabPinned="yes" if b.pinned else "no",
                               isMonitoring="yes" if b.monitoring else "no",
                               linpadEncoding=b.encoding, linpadLang=b.lang,
                               linpadLangForced="yes" if b.lang_forced else "no")
            with main.doc_editor(b) as ed:
                for ln in main.bookmark_lines(ed):
                    ET.SubElement(fe, "Mark", line=str(ln))
            for ln in st.get("folds", []):
                ET.SubElement(fe, "Fold", line=str(ln))
    ws = main.panels.get("workspace")
    fb = ET.SubElement(root, "FileBrowser", latestSelectedItem="")
    roots = ws.roots() if ws is not None else main.S["workspace_roots"]
    for r in roots:
        ET.SubElement(fb, "root", foldername=r)
    try:
        ET.indent(root, space="    ")
    except AttributeError:
        pass
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def load_session(main, path, restore_backups=True):
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return False
    sess = root.find("Session")
    if sess is None:
        return False
    from .editor import Buffer
    opened_any = False
    for tag, vi in (("mainView", 0), ("subView", 1)):
        el = sess.find(tag)
        if el is None:
            continue
        view = main.views[vi]
        active = int(el.get("activeIndex", "0") or 0)
        bufs = []
        for fe in el.findall("File"):
            fn = fe.get("filename", "")
            backup = fe.get("backupFilePath", "")
            lang = fe.get("linpadLang") or _lang_from_display(main, fe.get("lang"))
            b = None
            if backup and restore_backups and os.path.exists(backup):
                with open(backup, "rb") as f:
                    data = f.read()
                existing = main.find_buffer(fn) if os.path.isabs(fn) else None
                if existing is not None:
                    b = existing
                else:
                    ptr = main.create_doc(data, eol=main.detect_eol(data[:65536].decode("utf-8", "replace")) or main.S["new_eol"],
                                          lang=lang or "normal")
                    if os.path.isabs(fn):
                        b = Buffer(ptr, path=fn)
                        b.mtime = os.path.getmtime(fn) if os.path.exists(fn) else None
                    else:
                        b = Buffer(ptr, title=fn)
                        try:
                            n = int(fn.split()[-1])
                            Buffer._new_counter = max(Buffer._new_counter, n)
                        except (ValueError, IndexError):
                            pass
                    b.lang = lang or "normal"
                    b.encoding = fe.get("linpadEncoding") or "utf8"
                    b.backup_path = backup
                    # a restored backup differs from disk: keep it dirty
                    b.dirty = b.force_dirty = True
                    main.register(b)
                    view.add(b, activate=False)
            elif fn and os.path.isabs(fn) and os.path.exists(fn):
                ex = main.find_buffer(fn)
                if ex is not None:
                    b = ex
                    if b not in view.buffers:
                        view.add(b, activate=False)
                else:
                    b = main.open_file(fn, view=view, activate=False, lang=lang, quiet=True,
                                       encoding=fe.get("linpadEncoding") if fe.get("linpadEncoding") not in (None, "ansi") else None)
                    if b is not None and fe.get("linpadLangForced") == "yes":
                        b.lang_forced = True
            if b is None:
                continue
            opened_any = True
            b.user_readonly = fe.get("userReadOnly") == "yes"
            try:
                b.tab_color = int(fe.get("tabColourId", "-1"))
            except ValueError:
                pass
            b.pinned = fe.get("tabPinned") == "yes"
            b.view_state[vi] = {
                "first": int(fe.get("firstVisibleLine", "0") or 0),
                "anchor": int(fe.get("startPos", "0") or 0),
                "caret": int(fe.get("endPos", "0") or 0),
                "xoffset": int(fe.get("xOffset", "0") or 0),
                "selmode": int(fe.get("selMode", "0") or 0),
                "folds": [int(f.get("line")) for f in fe.findall("Fold") if (f.get("line") or "").isdigit()],
            }
            marks = [int(m.get("line")) for m in fe.findall("Mark") if (m.get("line") or "").isdigit()]
            with main.doc_editor(b) as ed:
                for ln in marks:
                    ed.SendScintilla(S.SCI_MARKERADD, ln, stl.MARK_BOOKMARK)
                if b.readonly():
                    ed.SendScintilla(S.SCI_SETREADONLY, True)
            if fe.get("isMonitoring") == "yes" and b.path:
                b.monitoring = True
                main.set_buf_readonly(b)
            bufs.append(b)
        if bufs:
            main.show_view(view)
            target = bufs[min(active, len(bufs) - 1)]
            view.current = None
            view.activate(target)
            for b in bufs:
                view.refresh_tab(b)
    av = int(sess.get("activeView", "0") or 0)
    if main.views[av].buffers:
        main.set_active_view(main.views[av])
    fb = root.find("FileBrowser")
    if fb is not None:
        roots = [r.get("foldername") for r in fb.findall("root") if r.get("foldername")]
        if roots:
            p = main.show_panel("workspace", None)
            for r in roots:
                p.add_root(r)
    return opened_any
