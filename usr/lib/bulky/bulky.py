#!/usr/bin/python3
import gettext
import gi
import locale
import os
import re
import setproctitle
import subprocess
import warnings
import sys

# Suppress GTK deprecation warnings
warnings.filterwarnings("ignore")

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Gio, GdkPixbuf, GLib

from common import *

setproctitle.setproctitle("bulky")

# i18n
APP = 'bulky'
LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

COL_ICON, COL_NAME, COL_NEW_NAME, COL_FILE = range(4)
SCOPE_NAME_ONLY = "name"
SCOPE_EXTENSION_ONLY = "extension"
SCOPE_ALL = "all"

class MyApplication(Gtk.Application):
    # Main initialization routine
    def __init__(self, application_id, flags):
        Gtk.Application.__init__(self, application_id=application_id, flags=flags)
        self.connect("activate", self.activate)

    def activate(self, application):
        windows = self.get_windows()
        if (len(windows) > 0):
            window = windows[0]
            window.present()
            window.show()
        else:
            window = MainWindow(self)
            self.add_window(window.window)
            window.window.show()

class MainWindow():

    def __init__(self, application):

        self.application = application
        self.settings = Gio.Settings(schema_id="org.x.bulky")
        self.selected_files = []
        self.icon_theme = Gtk.IconTheme.get_default()
        self.operation_function = self.replace_text
        self.scope = SCOPE_NAME_ONLY

        # Set the Glade file
        gladefile = "/usr/share/bulky/bulky.ui"
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP)
        self.builder.add_from_file(gladefile)
        self.window = self.builder.get_object("main_window")
        self.window.set_title(_("Rename Files"))
        self.window.set_icon_name("bulky")

        # Create variables to quickly access dynamic widgets
        self.headerbar = self.builder.get_object("headerbar")
        self.add_button = self.builder.get_object("add_button")
        self.remove_button = self.builder.get_object("remove_button")
        self.clear_button = self.builder.get_object("clear_button")
        self.close_button = self.builder.get_object("close_button")
        self.rename_button = self.builder.get_object("rename_button")

        # Widget signals
        self.add_button.connect("clicked", self.on_add_button)
        self.remove_button.connect("clicked", self.on_remove_button)
        self.clear_button.connect("clicked", self.on_clear_button)
        self.close_button.connect("clicked", self.on_close_button)
        self.rename_button.connect("clicked", self.on_rename_button)
        self.window.connect("key-press-event",self.on_key_press_event)

        # Menubar
        accel_group = Gtk.AccelGroup()
        self.window.add_accel_group(accel_group)
        menu = self.builder.get_object("main_menu")
        item = Gtk.ImageMenuItem()
        item.set_image(Gtk.Image.new_from_icon_name("preferences-desktop-keyboard-shortcuts-symbolic", Gtk.IconSize.MENU))
        item.set_label(_("Keyboard Shortcuts"))
        item.connect("activate", self.open_keyboard_shortcuts)
        key, mod = Gtk.accelerator_parse("<Control>K")
        item.add_accelerator("activate", accel_group, key, mod, Gtk.AccelFlags.VISIBLE)
        menu.append(item)
        item = Gtk.ImageMenuItem()
        item.set_image(Gtk.Image.new_from_icon_name("help-about-symbolic", Gtk.IconSize.MENU))
        item.set_label(_("About"))
        item.connect("activate", self.open_about)
        key, mod = Gtk.accelerator_parse("F1")
        item.add_accelerator("activate", accel_group, key, mod, Gtk.AccelFlags.VISIBLE)
        menu.append(item)
        item = Gtk.ImageMenuItem(label=_("Quit"))
        image = Gtk.Image.new_from_icon_name("application-exit-symbolic", Gtk.IconSize.MENU)
        item.set_image(image)
        item.connect('activate', self.on_menu_quit)
        key, mod = Gtk.accelerator_parse("<Control>Q")
        item.add_accelerator("activate", accel_group, key, mod, Gtk.AccelFlags.VISIBLE)
        key, mod = Gtk.accelerator_parse("<Control>W")
        item.add_accelerator("activate", accel_group, key, mod, Gtk.AccelFlags.VISIBLE)
        menu.append(item)
        menu.show_all()

        # Treeview
        self.treeview = self.builder.get_object("treeview")
        renderer = Gtk.CellRendererPixbuf()
        column = Gtk.TreeViewColumn("", renderer, pixbuf=COL_ICON)
        column.set_cell_data_func(renderer, self.data_func_surface)
        self.treeview.append_column(column)

        column = Gtk.TreeViewColumn(_("Name"), Gtk.CellRendererText(), text=COL_NAME)
        column.set_sort_column_id(COL_NAME)
        column.set_resizable(True)
        self.treeview.append_column(column)

        column = Gtk.TreeViewColumn(_("New name"), Gtk.CellRendererText(), text=COL_NEW_NAME)
        column.set_resizable(True)
        self.treeview.append_column(column)

        self.treeview.show()
        self.model = Gtk.TreeStore(GdkPixbuf.Pixbuf, str, str, object) # icon, name, new_name, file
        self.model.set_sort_column_id(COL_NAME, Gtk.SortType.ASCENDING)
        self.treeview.set_model(self.model)
        self.treeview.get_selection().connect("changed", self.on_files_selected)

        # Combos
        self.builder.get_object("combo_operation").connect("changed", self.on_operation_changed)
        self.builder.get_object("combo_scope").connect("changed", self.on_scope_changed)
        self.stack = self.builder.get_object("stack")

        # Replace widgets
        self.find_entry = self.builder.get_object("find_entry")
        self.replace_entry = self.builder.get_object("replace_entry")
        self.replace_regex_check = self.builder.get_object("replace_regex_check")
        self.replace_case_check = self.builder.get_object("replace_case_check")
        self.find_entry.connect("changed", self.on_widget_change)
        self.replace_entry.connect("changed", self.on_widget_change)
        self.replace_regex_check.connect("toggled", self.on_widget_change)
        self.replace_case_check.connect("toggled", self.on_widget_change)

        # Remove widgets
        self.remove_from_spin = self.builder.get_object("remove_from_spin")
        self.remove_to_spin = self.builder.get_object("remove_to_spin")
        self.remove_from_check = self.builder.get_object("remove_from_check")
        self.remove_to_check = self.builder.get_object("remove_to_check")
        self.remove_from_spin.connect("value-changed", self.on_widget_change)
        self.remove_to_spin.connect("value-changed", self.on_widget_change)
        self.remove_from_check.connect("toggled", self.on_widget_change)
        self.remove_to_check.connect("toggled", self.on_widget_change)
        self.remove_from_spin.set_range(1, 100)
        self.remove_from_spin.set_increments(1, 1)
        self.remove_to_spin.set_range(1, 100)
        self.remove_to_spin.set_increments(1, 1)

        # Insert widgets
        self.insert_entry = self.builder.get_object("insert_entry")
        self.insert_spin = self.builder.get_object("insert_spin")
        self.insert_reverse_check = self.builder.get_object("insert_reverse_check")
        self.overwrite_check = self.builder.get_object("overwrite_check")
        self.insert_entry.connect("changed", self.on_widget_change)
        self.insert_spin.connect("value-changed", self.on_widget_change)
        self.insert_reverse_check.connect("toggled", self.on_widget_change)
        self.overwrite_check.connect("toggled", self.on_widget_change)
        self.insert_spin.set_range(1, 100)
        self.insert_spin.set_increments(1, 1)

        # Case widgets
        self.radio_titlecase = self.builder.get_object("radio_titlecase")
        self.radio_lowercase = self.builder.get_object("radio_lowercase")
        self.radio_uppercase = self.builder.get_object("radio_uppercase")
        self.radio_firstuppercase = self.builder.get_object("radio_firstuppercase")
        self.radio_titlecase.connect("toggled", self.on_widget_change)
        self.radio_lowercase.connect("toggled", self.on_widget_change)
        self.radio_uppercase.connect("toggled", self.on_widget_change)
        self.radio_firstuppercase.connect("toggled", self.on_widget_change)

        self.load_files()

    def data_func_surface(self, column, cell, model, iter_, *args):
        pixbuf = model.get_value(iter_, COL_ICON)
        surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, self.window.get_scale_factor())
        cell.set_property("surface", surface)

    def open_keyboard_shortcuts(self, widget):
        gladefile = "/usr/share/bulky/shortcuts.ui"
        builder = Gtk.Builder()
        builder.set_translation_domain(APP)
        builder.add_from_file(gladefile)
        window = builder.get_object("shortcuts")
        window.set_title(_("Shortcuts"))
        window.show()

    def open_about(self, widget):
        dlg = Gtk.AboutDialog()
        dlg.set_transient_for(self.window)
        dlg.set_title(_("About"))
        dlg.set_program_name("Bulky")
        dlg.set_comments(_("Rename Files"))
        try:
            h = open('/usr/share/common-licenses/GPL', encoding="utf-8")
            s = h.readlines()
            gpl = ""
            for line in s:
                gpl += line
            h.close()
            dlg.set_license(gpl)
        except Exception as e:
            print (e)

        dlg.set_version("__DEB_VERSION__")
        dlg.set_icon_name("bulky")
        dlg.set_logo_icon_name("bulky")
        dlg.set_website("https://www.github.com/linuxmint/bulky")
        def close(w, res):
            if res == Gtk.ResponseType.CANCEL or res == Gtk.ResponseType.DELETE_EVENT:
                w.destroy()
        dlg.connect("response", close)
        dlg.show()

    def on_menu_quit(self, widget):
        self.application.quit()

    def on_files_selected(self, selection):
        model, iter = selection.get_selected()
        if iter is not None:
            #self.selected_files = ..
            self.remove_button.set_sensitive(True)

    def on_key_press_event(self, widget, event):
        ctrl = (event.state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl:
            if event.keyval == Gdk.KEY_n:
                self.on_add_button(self.add_button)
            elif event.keyval == Gdk.KEY_d:
                self.on_remove_button(self.remove_button)
            elif event.keyval == Gdk.KEY_c:
                self.on_clear_button(self.clear_button)

    def on_remove_button(self, widget):
        if len(self.selected_files) > 0:
            pass

    def on_add_button(self, widget):
        pass

    def on_clear_button(self, widget):
        pass

    def on_close_button(self, widget):
        self.application.quit()

    def on_rename_button(self, widget):
        pass

    def load_files(self):
        # Clear treeview and selection
        self.model.clear()
        self.selected_files = []
        self.remove_button.set_sensitive(False)
        if len(sys.argv) > 1:
            for path in sys.argv[1:]:
                if os.path.exists(path):
                    file_obj = FileObject(path)
                    if file_obj.is_valid:
                        pixbuf = self.icon_theme.load_icon(file_obj.icon, 22 * self.window.get_scale_factor(), 0)
                        iter = self.model.insert_before(None, None)
                        self.model.set_value(iter, COL_ICON, pixbuf)
                        self.model.set_value(iter, COL_NAME, file_obj.name)
                        self.model.set_value(iter, COL_NEW_NAME, file_obj.new_name)
                        self.model.set_value(iter, COL_FILE, file_obj)

    def on_operation_changed(self, widget):
        operation_id = widget.get_active_id()
        if operation_id == "replace":
            self.stack.set_visible_child_name("replace_page")
            self.operation_function = self.replace_text
        elif operation_id == "remove":
            self.stack.set_visible_child_name("remove_page")
            self.operation_function = self.remove_text
        elif operation_id == "insert":
            self.stack.set_visible_child_name("insert_page")
            self.operation_function = self.insert_text
        elif operation_id == "case":
            self.stack.set_visible_child_name("case_page")
            self.operation_function = self.change_case
        self.preview_changes()

    def on_scope_changed(self, widget):
        self.scope = widget.get_active_id()
        self.preview_changes()

    def on_widget_change(self, widget):
        self.preview_changes()

    def preview_changes(self):
        iter = self.model.get_iter_first()
        index = 1
        while iter != None:
            file_obj = self.model.get_value(iter, COL_FILE)
            name = self.model.get_value(iter, COL_NAME)
            name, ext = os.path.splitext(name)
            if self.scope == SCOPE_NAME_ONLY:
                name = self.operation_function(index, name)
            elif self.scope == SCOPE_EXTENSION_ONLY:
                ext = self.operation_function(index, ext)
            else:
                name = self.operation_function(index, name)
                ext = self.operation_function(index, ext)
            self.model.set_value(iter, COL_NEW_NAME, name+ext)
            iter = self.model.iter_next(iter)

    def replace_text(self, index, string):
        case = self.replace_case_check.get_active()
        regex = self.replace_regex_check.get_active()
        find = self.find_entry.get_text()
        replace = self.replace_entry.get_text()
        if regex:
            find = find.replace("*", ".+").replace("?", ".")
            if case:
                return re.sub(find, replace, string)
            else:
                reg = re.compile(find, re.IGNORECASE)
                return reg.sub(replace, string)
        else:
            if case:
                # Simple replace will do
                return string.replace(find, replace)
            else:
                reg = re.compile(re.escape(find), re.IGNORECASE)
                return reg.sub(replace, string)

    def remove_text(self, index, string):
        length = len(string) - 1
        from_index = min(self.remove_from_spin.get_value_as_int() - 1, length)
        to_index = min(self.remove_to_spin.get_value_as_int() - 1, length)
        if self.remove_from_check.get_active():
            from_index = length - from_index
        if self.remove_to_check.get_active():
            to_index = length - to_index
        to_index = max(to_index + 1, from_index)
        return string[0:from_index]+string[to_index:]

    def insert_text(self, index, string):
        text = self.insert_entry.get_text()
        length = len(string) - 1
        from_index = self.insert_spin.get_value_as_int() - 1
        if from_index >= length:
            if self.insert_reverse_check.get_active():
                return text+string
            else:
                return string+text
        else:
            if self.insert_reverse_check.get_active():
                from_index = length - from_index + 1
            if self.overwrite_check.get_active():
                if len(text) >= length:
                    return text
                else:
                    catchup = from_index + len(text)
                    return string[0:from_index] + text + string[catchup:]
            else:
                return string[0:from_index] + text + string[from_index:]

    def change_case(self, index, string):
        if self.radio_titlecase.get_active():
            return string.title()
        elif self.radio_lowercase.get_active():
            return string.lower()
        elif self.radio_uppercase.get_active():
            return string.upper()
        else:
            return string.capitalize()

'''
TODO
----

- try/catch exceptions on a line per line basis
- check new_name collisions for files in the same directory
- translations
- add special text for numbering, date, etc..

'''

if __name__ == "__main__":
    application = MyApplication("org.x.bulky", Gio.ApplicationFlags.FLAGS_NONE)
    application.run()
