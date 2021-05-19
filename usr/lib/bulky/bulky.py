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

if __name__ == "__main__":
    application = MyApplication("org.x.bulky", Gio.ApplicationFlags.FLAGS_NONE)
    application.run()
