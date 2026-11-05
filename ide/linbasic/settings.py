"""Persistent preferences (the equivalent of Notepad++'s config.xml GUIConfigs)."""
import json
import os

from . import paths

DEFAULTS = {
    "help_path": "", "qb_command_args": "", "qb_console": False, "qb_gcc": False, "qb_crlf": False, "qb_exe_target": "linux-window",
    # General / UI
    "localization": "english.xml",
    "toolbar_hidden": False,
    "toolbar_icons": "small",          # small | large
    "statusbar_hidden": False,
    "menubar_hidden": False,
    "tabbar_hidden": False,
    "tab_close_button": True,
    "tab_dblclick_close": False,
    "tab_exit_on_last": False,
    "tab_lock": False,
    "tab_max_len": 0,
    "tab_reduce": False,
    "tab_multiline": False,
    "dark_mode": "light",              # light | dark | system
    "theme": "",                       # "" = stylers.xml
    "light_theme": "",                 # theme remembered for light mode
    "dark_theme": "DarkModeDefault.xml",  # theme remembered for dark mode
    # Editing
    "caretline_mode": 1,               # 0 none, 1 background, 2 frame
    "caretline_frame_width": 1,
    "caret_width": 1,
    "caret_blink": 600,
    "wrap_mode": 0,                    # 0 default, 1 aligned, 2 indent
    "virtual_space": False,
    "scroll_beyond_last": False,
    "fold_style": "box",               # simple | arrow | circle | box | none
    "line_numbers": True,
    "line_numbers_dynamic": True,
    "bookmark_margin": True,
    "change_history": True,
    "edge_mode": 0,                    # 0 none, 1 line, 2 background
    "edge_columns": "80",
    "padding_left": 0,
    "padding_right": 0,
    "multi_edit": True,
    "column_to_multi": True,
    "smooth_font": True,
    "border_width": 2,
    "npc_appearance": "abbrev",        # abbrev | codepoint
    # New document
    "new_eol": 2,                      # SC_EOL_CRLF=0, CR=1, LF=2
    "new_encoding": "utf8",
    "new_lang": "freebasic",
    "apply_utf8_to_ansi": False,
    # Default directory
    "open_dir_mode": "follow",         # follow | remember | custom
    "open_dir_custom": "",
    "last_dir": "",
    # Recent files
    "recent_max": 10,
    "recent_submenu": False,
    "recent_display": "full",          # name | full
    "recent_maxlen": 100,
    "recent_dont_check": False,
    "recent_files": [],
    # Language
    "lang_compact": False,
    "tab_size": 4,
    "use_spaces": False,
    "lang_tabs": {},                   # lang -> [size, use_spaces]
    "backspace_unindent": False,
    "auto_indent": "advanced",         # none | basic | advanced
    "disabled_langs": [],
    # Highlighting
    "token_match_case": False,
    "token_whole_word": True,
    "smart_hl": True,
    "smart_hl_case": False,
    "smart_hl_word": True,
    "smart_hl_use_find": False,
    "smart_hl_other_view": False,
    "tag_match": True,
    "tag_attr": True,
    "tag_comment": False,
    # Print
    "print_linenums": False,
    "print_color": "wysiwyg",          # wysiwyg | invert | bw | nobg
    "print_margins": [5, 5, 5, 5],     # top left right bottom (mm)
    "print_header": "$(FULL_CURRENT_PATH)",
    "print_footer": "",
    # Searching
    "find_fill_selected": True,
    "find_fill_word": True,
    "find_maxchars": 1024,
    "find_in_sel_auto": True,
    "find_in_sel_min": 1024,
    "find_stay_open": False,
    "confirm_replace_all_docs": True,
    "replace_no_move": False,
    "find_mono": False,
    "find_transparency": "lose",       # none | lose | always
    "find_alpha": 150,
    "find_history": [], "replace_history": [], "filter_history": [], "dir_history": [],
    "find_opts": {},
    # Backup / session
    "remember_session": True,
    "snapshot": True,
    "snapshot_interval": 7,
    "backup_mode": "none",             # none | simple | verbose
    "backup_dir": "",
    # Auto-completion
    "ac_enable": True,
    "ac_mode": "both",                 # func | word | both
    "ac_from": 1,
    "ac_ignore_numbers": True,
    "ac_brief": False,
    "param_hint": True,
    "ai_paren": False, "ai_bracket": False, "ai_brace": False,
    "ai_dquote": False, "ai_squote": False, "ai_tag": False,
    # Multi-instance / date
    "multi_instance": "mono",          # mono | multi | session
    "date_format": "yyyy-MM-dd HH:mm:ss",
    "date_reverse": False,
    # Delimiter
    "extra_word_chars": "",
    "delim_open": "(",
    "delim_close": ")",
    "delim_multiline": False,
    # Performance
    "large_file_restrict": True,
    "large_file_mb": 200,
    "large_no_wrap": True,
    "large_ac": False,
    "large_smart": False,
    "large_brace": False,
    "large_links": False,
    # Cloud & link
    "link_enable": True,
    "link_underline": True,
    "link_fullbox": False,
    "uri_schemes": "svn:// cvs:// git:// imap:// irc:// irc6:// ircs:// ldap:// ldaps:// news: telnet:// gopher:// ssh:// sftp:// smb:// skype: snmp:// spotify: steam:// sms: slack:// chrome:// bitcoin:",
    # Search engine
    "search_engine": "https://duckduckgo.com/?q=$(CURRENT_WORD)",
    # MISC
    "file_autodetect": "enabled",      # enabled | silent | disabled
    "autodetect_scroll_end": False,
    "docswitcher_mru": True,
    "minimize_to_tray": False,
    "close_to_tray": False,
    "title_filename_only": False,
    "autodetect_encoding": True,
    "ansi_codepage": "",               # "" = derived from the locale
    "session_ext": "",
    "workspace_ext": "",
    "mute_sounds": True,
    # View toggles
    "always_on_top": False,
    "word_wrap": False,
    "show_ws": False,
    "show_eol": False,
    "show_npc": False,
    "show_cc": False,
    "show_indent": True,
    "show_wrap_symbol": False,
    "sync_v": False,
    "sync_h": False,
    "zoom_sync": False,
    "panels": {},
    "geometry": "",
    "window_state": "",
    "splitter": "",
    "split_orientation": 1,            # Qt.Orientation.Horizontal
    "workspace_roots": [],
    "projects": ["", "", ""],
    "run_last": "",
    "column_editor": {},
    "hash_treat_lines": False,
}


class Settings:
    def __init__(self):
        self.path = paths.cfg("config.json")
        self.data = {}
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def __getitem__(self, key):
        if key in self.data:
            return self.data[key]
        v = DEFAULTS.get(key)
        if isinstance(v, (list, dict)):
            v = json.loads(json.dumps(v))
            self.data[key] = v
        return v

    def get(self, key, default=None):
        if key in self.data:
            return self.data[key]
        return DEFAULTS.get(key, default)

    def __setitem__(self, key, value):
        self.data[key] = value


S = None


def init():
    global S
    S = Settings()
    return S
