#!/usr/bin/python3
import gettext
import gi
import locale
import os
import re
import setproctitle
import warnings
import sys
import functools
import unidecode

# Suppress GTK deprecation warnings
warnings.filterwarnings("ignore")

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Gio, GdkPixbuf, GLib

setproctitle.setproctitle("bulky")

# i18n
APP = 'bulky'
LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

COL_ICON, COL_NAME, COL_NEW_NAME, COL_FILE, COL_PIXBUF = range(5)
SCOPE_NAME_ONLY = "name"
SCOPE_EXTENSION_ONLY = "extension"
SCOPE_ALL = "all"

SETTINGS_SCHEMA_ID = "org.x.bulky"
MRU_OPERATION = "mru-operation"
MRU_SCOPE = "mru-scope"

class FolderFileChooserDialog(Gtk.Dialog):
    def __init__(self, window_title, transient_parent, starting_location):
        super(FolderFileChooserDialog, self).__init__(title=window_title,
                                                      parent=transient_parent,
                                                      default_width=750,
                                                      default_height=500)

        self.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL,
                         _("Add"), Gtk.ResponseType.OK)

        self.chooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN, select_multiple=True)
        self.chooser.set_current_folder_file(starting_location)
        self.chooser.connect("file-activated", lambda chooser: self.response(Gtk.ResponseType.OK))
        self.chooser.show_all()

        self.get_content_area().add(self.chooser)
        self.get_content_area().set_border_width(0)
        self.get_uris = self.chooser.get_uris
        self.get_current_folder_file = self.chooser.get_current_folder_file
        self.connect("key-press-event", self.on_button_press)

    def on_button_press(self, widget, event, data=None):
        multi = len(self.chooser.get_uris()) != 1
        if event.keyval in (Gdk.KEY_KP_Enter, Gdk.KEY_Return) and multi:
            self.response(Gtk.ResponseType.OK)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

# This is a data structure representing
# the file object
class FileObject():
    def __init__(self, path_or_uri, scale):
        self.gfile = self.create_gfile(path_or_uri)
        self.scale = scale
        self._update_info()

    def create_gfile(self, path_or_uri):
        gfile = None

        if "://" in path_or_uri:
            gfile = Gio.File.new_for_uri(path_or_uri)
        else:
            gfile = Gio.File.new_for_path(path_or_uri)

        return gfile

    def _update_info(self):
        self.info = None
        self.uri = self.gfile.get_uri()
        self.name = self.gfile.get_basename() # temp in case query_info fails to get edit-name
        self.icon = Gio.ThemedIcon.new("text-x-generic")
        self.pixbuf = None

        attrs = ",".join([
            "standard::type",
            "standard::icon",
            "standard::edit-name",
            "access::can-write",
            "thumbnail::path",
            "thumbnail::is-valid"
        ])

        try:
            self.info = self.gfile.query_info(attrs, Gio.FileQueryInfoFlags.NONE, None)
            self.name = self.info.get_edit_name()

            if self.info.get_file_type() == Gio.FileType.DIRECTORY:
                self.icon = Gio.ThemedIcon.new("folder")
            else:
                thumb_ok = self.info.get_attribute_boolean("thumbnail::is-valid")

                if thumb_ok:
                    thumb_path = self.info.get_attribute_byte_string("thumbnail::path")
                    if thumb_path and os.path.exists(thumb_path):
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(thumb_path, 22 *  self.scale, 22 * self.scale, True)
                        if pixbuf is not None:
                            self.pixbuf = pixbuf

                info_icon = self.info.get_icon()

                if info_icon:
                    self.icon = info_icon
                else:
                    self.icon = Gio.ThemedIcon.new("text-x-generic")
        except GLib.Error as e:
            if e.code == Gio.IOErrorEnum.NOT_FOUND:
                print("file %s does not exist" % self.uri)
            else:
                print(e.message)
            self.is_valid = False
            return

        self.is_valid = True

    def rename(self, new_name):
        backup_gfile = self.gfile.dup()
        try:
            new_gfile = self.gfile.set_display_name(new_name, None)
        except:
            # This can fail - make sure the GFile is still in a pre-fail state
            # (not sure this is necessary), then let the caller handle telling
            # the user.
            self.gfile = backup_gfile
            raise

        self.gfile = new_gfile
        self._update_info()

        return True

    def get_pending_uri(self, new_name):
        parent = self.gfile.get_parent()
        return parent.get_child(new_name).get_uri()

    def get_path_or_uri_for_display(self):
        if self.uri.startswith("file://"):
            return self.gfile.get_path().replace(os.path.expanduser("~"), "~")
        else:
            return self.name

    def get_parent_path_or_uri_for_display(self):
        parent = self.gfile.get_parent()
        uri = parent.get_uri()
        if uri.startswith("file://"):
            return parent.get_path().replace(os.path.expanduser("~"), "~")
        else:
            return parent.get_basename()

    def writable(self):
        return self.info.get_attribute_boolean("access::can-write")

    def parent_writable(self):
        parent = self.gfile.get_parent()

        if parent.equal(self.gfile):
            return False

        parent_fileobj = FileObject(parent.get_uri(), self.scale)
        return parent_fileobj.writable()

    def is_a_dir(self):
        return self.info.get_file_type() == Gio.FileType.DIRECTORY

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
        self.icon_theme = Gtk.IconTheme.get_default()
        self.operation_function = self.replace_text
        self.scope = SCOPE_NAME_ONLY
        # used to prevent collisions
        self.uris = []
        self.renamed_uris = []
        self.last_chooser_location = Gio.File.new_for_path(GLib.get_home_dir())

        # Set the Glade file
        gladefile = "/usr/share/bulky/bulky.ui"
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP)
        self.builder.add_from_file(gladefile)
        self.window = self.builder.get_object("main_window")
        self.window.set_title(_("Rename..."))
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

        # DND
        self.dnd_box = self.builder.get_object("dnd")  # DND target, topmost window child
        entry_uri = Gtk.TargetEntry.new("text/uri-list",  0, 0)
        entry_text = Gtk.TargetEntry.new("text/plain",  0, 0)
        self.dnd_box.drag_dest_set(Gtk.DestDefaults.ALL,
                                   (entry_uri, entry_text),
                                   Gdk.DragAction.COPY)

        # Box highlighting happens automatically, as does restricting the type of dnd data, so
        # all we need to connect to is the post drop signal to get our uris.
        self.dnd_box.connect("drag-data-received", self.on_drag_data_received)
        # /DND

        # Menubar
        accel_group = Gtk.AccelGroup()
        self.window.add_accel_group(accel_group)
        menu = self.builder.get_object("main_menu")
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
        renderer_pixbuf = Gtk.CellRendererPixbuf()
        renderer_text = Gtk.CellRendererText()
        renderer_text.set_property("xalign", 0.00)
        column = Gtk.TreeViewColumn()
        column.set_title(_("Name"))
        column.set_spacing(6)
        column.set_cell_data_func(renderer_pixbuf, self.data_func_icon)
        column.pack_start(renderer_pixbuf, False)
        column.pack_start(renderer_text, True)
        # column.add_attribute(renderer_pixbuf, "gicon", COL_ICON)
        column.add_attribute(renderer_text, "text", COL_NAME)
        column.set_sort_column_id(COL_NAME)
        column.set_expand(True)
        self.treeview.append_column(column)

        column = Gtk.TreeViewColumn(_("New name"), Gtk.CellRendererText(), text=COL_NEW_NAME)
        column.set_expand(True)
        self.treeview.append_column(column)

        self.treeview.show()
        self.model = Gtk.TreeStore(Gio.Icon, str, str, object, GdkPixbuf.Pixbuf) # icon, name, new_name, file, pixbuf
        self.model.set_sort_column_id(COL_NAME, Gtk.SortType.ASCENDING)
        self.treeview.set_model(self.model)
        self.treeview.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.treeview.get_selection().connect("changed", self.on_files_selected)

        # Combos
        self.combo_operation = self.builder.get_object("combo_operation")
        self.combo_operation.set_active_id(self.settings.get_string(MRU_OPERATION))
        self.combo_operation.connect("changed", self.on_operation_changed)
        self.combo_scope = self.builder.get_object("combo_scope")
        self.combo_scope.set_active_id(self.settings.get_string(MRU_SCOPE))
        self.combo_scope.connect("changed", self.on_scope_changed)

        self.stack = self.builder.get_object("stack")
        self.infobar = self.builder.get_object("infobar")
        self.error_label = self.builder.get_object("error_label")

        # Replace widgets
        self.find_entry = self.builder.get_object("find_entry")
        self.replace_entry = self.builder.get_object("replace_entry")
        self.replace_regex_check = self.builder.get_object("replace_regex_check")
        self.replace_case_check = self.builder.get_object("replace_case_check")
        self.find_entry.connect("changed", self.on_widget_change)
        self.replace_entry.connect("changed", self.on_widget_change)
        self.replace_regex_check.connect("toggled", self.on_widget_change)
        self.replace_case_check.connect("toggled", self.on_widget_change)

        self.replace_start_spin = self.builder.get_object("replace_start_spin")
        self.replace_start_spin.connect("value-changed", self.on_widget_change)
        self.replace_start_spin.set_range(0, 10000)
        self.replace_start_spin.set_value(1)
        self.replace_start_spin.set_increments(1, 10)

        self.replace_inc_spin = self.builder.get_object("replace_inc_spin")
        self.replace_inc_spin.connect("value-changed", self.on_widget_change)
        self.replace_inc_spin.set_range(1, 1000)
        self.replace_inc_spin.set_value(1)
        self.replace_inc_spin.set_increments(1, 10)


        # Set focus chain
        # Not that this is deprecated (but not implemented differently) in Gtk3.
        # If we move to GTK4, we'll just drop this line of code.
        self.builder.get_object("grid_replace").set_focus_chain([self.find_entry, self.replace_entry, self.replace_regex_check, self.replace_case_check])

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
        self.remove_from_spin.set_increments(1, 10)
        self.remove_to_spin.set_range(1, 100)
        self.remove_to_spin.set_increments(1, 10)

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
        self.insert_spin.set_increments(1, 10)

        self.insert_start_spin = self.builder.get_object("insert_start_spin")
        self.insert_start_spin.connect("value-changed", self.on_widget_change)
        self.insert_start_spin.set_range(0, 10000)
        self.insert_start_spin.set_value(1)
        self.insert_start_spin.set_increments(1, 10)

        self.insert_inc_spin = self.builder.get_object("insert_inc_spin")
        self.insert_inc_spin.connect("value-changed", self.on_widget_change)
        self.insert_inc_spin.set_range(1, 1000)
        self.insert_inc_spin.set_value(1)
        self.insert_inc_spin.set_increments(1, 10)


        # Case widgets
        self.radio_titlecase = self.builder.get_object("radio_titlecase")
        self.radio_lowercase = self.builder.get_object("radio_lowercase")
        self.radio_uppercase = self.builder.get_object("radio_uppercase")
        self.radio_firstuppercase = self.builder.get_object("radio_firstuppercase")
        self.radio_accents = self.builder.get_object("radio_accents")

        self.radio_titlecase.connect("toggled", self.on_widget_change)
        self.radio_lowercase.connect("toggled", self.on_widget_change)
        self.radio_uppercase.connect("toggled", self.on_widget_change)
        self.radio_firstuppercase.connect("toggled", self.on_widget_change)
        self.radio_accents.connect("toggled", self.on_widget_change)

        # Tooltips
        variables_tooltip = _("Use %n, %0n, %00n, %000n, etc. to enumerate.")
        self.replace_entry.set_tooltip_text(variables_tooltip)
        self.insert_entry.set_tooltip_text(variables_tooltip)

        self.load_files(sys.argv[1:], initial_load=True)

    def on_drag_data_received(self, widget, context, x, y, data, info, _time, user_data=None):
        if data:
            dtype = data.get_data_type().name()
            if context.get_selected_action() == Gdk.DragAction.COPY:
                if dtype.startswith("text/uri-list"):
                    uris = data.get_uris()
                    self.load_files(uris)
                elif dtype == "text/plain":
                    text = data.get_text()
                    self.load_files([text])


        Gtk.drag_finish(context, True, False, _time)

    def data_func_icon(self, column, cell, model, iter_, *args):
        pixbuf = model.get_value(iter_, COL_PIXBUF)
        icon = model.get_value(iter_, COL_ICON)

        if pixbuf is not None:
            surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, self.window.get_scale_factor())
            cell.set_property("gicon", None)
            cell.set_property("surface", surface)
        else:
            cell.set_property("surface", None)
            cell.set_property("gicon", icon)

    def open_about(self, widget):
        dlg = Gtk.AboutDialog()
        dlg.set_transient_for(self.window)
        dlg.set_title(_("About"))
        dlg.set_program_name("Bulky")
        dlg.set_comments(_("Rename Files"))
        try:
            with open('/usr/share/common-licenses/GPL', encoding="utf-8") as h:
                gpl= h.read()
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
        paths = selection.get_selected_rows()
        self.remove_button.set_sensitive(len(paths) > 0)

    def on_key_press_event(self, widget, event):
        ctrl = (event.state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl:
            if event.keyval == Gdk.KEY_n:
                self.on_add_button(self.add_button)
            elif event.keyval == Gdk.KEY_d:
                self.on_remove_button(self.remove_button)

    def on_remove_button(self, widget):
        iters = []
        model, paths = self.treeview.get_selection().get_selected_rows()
        for path in paths:
            # Add selected iters to a list, we can't remove while we iterate
            # since removing changes the paths
            iters.append(self.model.get_iter(path))
        for iter in iters:
            file_uri = self.model.get_value(iter, COL_FILE).uri
            self.uris.remove(file_uri)
            self.model.remove(iter)
        self.treeview.columns_autosize()
        self.preview_changes()

    def on_add_button(self, widget):
        dialog = FolderFileChooserDialog(_("Add files"), self.window, self.last_chooser_location)

        def update_last_location(dialog, response_id, data=None):
            if response_id != Gtk.ResponseType.OK:
                return
            self.last_chooser_location = dialog.get_current_folder_file()

        dialog.connect("response", update_last_location)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            for uri in dialog.get_uris():
                self.add_file(uri)
        self.preview_changes()
        dialog.destroy()

    def on_clear_button(self, widget):
        self.model.clear()
        self.uris.clear()

    def on_close_button(self, widget):
        self.application.quit()

    def report_os_error(self, file_obj, new_path, error):
        message = ""
        # Gio's error prints the too-long filename as part of its
        # error message, which looks really bad. Maybe we'll need
        # to add more exceptions here for other error codes.
        if Gio.IOErrorEnum(error.code) == Gio.IOErrorEnum.FILENAME_TOO_LONG:
            message = _("Unable to rename '%s': File name too long") \
                % file_obj.get_path_or_uri_for_display()
        else:
            message = _("Unable to rename '%s': %s") \
                % (file_obj.get_path_or_uri_for_display(), error.message)

        self.error_label.set_text(message)
        self.infobar.show()

    def on_rename_button(self, widget):
        iters = []
        iter = self.model.get_iter_first()
        while iter != None:
            iters.append(iter)
            iter = self.model.iter_next(iter)
        # We're modifying the model here, so we iterate
        # through our own list of iters rather than the model
        # itself
        rename_list = []
        for iter in iters:
            try:
                file_obj = self.model.get_value(iter, COL_FILE)
                name = self.model.get_value(iter, COL_NAME)
                new_name = self.model.get_value(iter, COL_NEW_NAME)
                rename_list.append((iter, file_obj, name, new_name))
            except Exception as e:
                print(e)

        rename_list = self.sort_list_by_depth(rename_list)

        # for i in rename_list:
        #     print(i[0].gfile.get_uri())

        for tup in rename_list:
                iter, file_obj, name, new_name = tup
                if new_name != name:
                    try:
                        old_uri = file_obj.uri
                        # print("Renaming %s --> %s" % (file_obj.get_path_or_uri_for_display(), new_name))
                        if file_obj.rename(new_name):
                            self.uris.remove(old_uri)
                            self.uris.append(file_obj.uri)
                            self.model.set_value(iter, COL_NAME, new_name)
                    except GLib.Error as e:
                        self.report_os_error(file_obj, new_name, e)
                        break

        self.rename_button.set_sensitive(False)

    def sort_list_by_depth(self, rename_list):
        # Rename files first, followed by directories from deep to shallow.
        def file_cmp(tup_a, tup_b):
            fo_a = tup_a[1]
            fo_b = tup_b[1]

            if fo_a.is_a_dir() and (not fo_b.is_a_dir()):
                return 1
            elif fo_b.is_a_dir() and (not fo_a.is_a_dir()):
                return -1

            if fo_a.gfile.has_prefix(fo_b.gfile):
                return -1
            elif fo_b.gfile.has_prefix(fo_a.gfile):
                return 1

            return GLib.utf8_collate(fo_a.uri, fo_b.uri)

        rename_list.sort(key=lambda tup: tup[1].gfile.get_uri_scheme())
        rename_list.sort(key=functools.cmp_to_key(file_cmp))
        return rename_list

    def load_files(self, uris, initial_load=False):
        # Clear treeview and selection
        if len(uris) > 0:
            if initial_load:
                self.builder.get_object("file_toolbox").hide()
            for path in uris:
                self.add_file(path)
        else:
            self.builder.get_object("headerbar").set_title(_("File Renamer"))
            self.builder.get_object("headerbar").set_subtitle(_("Rename files and directories"))

        self.preview_changes()

    def add_file(self, uri_or_path):
        file_obj = FileObject(uri_or_path, self.window.get_scale_factor())

        if file_obj.is_valid:
            if file_obj.uri in self.uris:
                print("%s is already loaded, ignoring" % file_obj.uri)
                return
            self.uris.append(file_obj.uri)
            iter = self.model.insert_before(None, None)
            self.model.set_value(iter, COL_ICON, file_obj.icon)
            self.model.set_value(iter, COL_NAME, file_obj.name)
            self.model.set_value(iter, COL_NEW_NAME, file_obj.name)
            self.model.set_value(iter, COL_FILE, file_obj)
            self.model.set_value(iter, COL_PIXBUF, file_obj.pixbuf)

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

        self.settings.set_string(MRU_OPERATION, operation_id)
        self.preview_changes()

    def on_scope_changed(self, widget):
        self.scope = widget.get_active_id()

        self.settings.set_string(MRU_SCOPE, self.scope)
        self.preview_changes()

    def on_widget_change(self, widget):
        self.preview_changes()

    def preview_changes(self):
        self.infobar.hide()

        # Adjust scope first if necessary
        any_dirs = False
        iter = self.model.get_iter_first()
        while iter != None:
            try:
                file_obj = self.model.get_value(iter, COL_FILE)
                any_dirs = file_obj.is_a_dir() or any_dirs
                iter = self.model.iter_next(iter)
            except:
                pass

        combo = self.builder.get_object("combo_scope")

        if any_dirs:
            # on_scope_changed will update self.scope
            combo.set_active_id(SCOPE_ALL)
            combo.set_sensitive(False)
        else:
            combo.set_sensitive(True)

        self.renamed_uris = []
        any_changes = False

        iter = self.model.get_iter_first()
        index = 1
        while iter != None:
            try:
                file_obj = self.model.get_value(iter, COL_FILE)
                orig_name = self.model.get_value(iter, COL_NAME)
                name, ext = os.path.splitext(orig_name)
                if ext and ext.startswith('.'):
                    ext = ext[1:]
                if self.scope == SCOPE_NAME_ONLY:
                    name = self.operation_function(index, name)
                elif self.scope == SCOPE_EXTENSION_ONLY:
                    ext = self.operation_function(index, ext)
                else:
                    full_name = self.operation_function(index, orig_name)
                if self.scope == SCOPE_ALL:
                    new_name = full_name
                else:
                    new_name = name + ('.' if ext else '') + ext

                self.model.set_value(iter, COL_NEW_NAME, new_name)
                renamed_uri = file_obj.get_pending_uri(new_name)
                if renamed_uri in self.renamed_uris:
                    self.infobar.show()
                    self.error_label.set_text(_("Name collision on '%s'.") % file_obj.get_path_or_uri_for_display())
                    self.rename_button.set_sensitive(False)
                elif not file_obj.parent_writable():
                    self.infobar.show()
                    self.error_label.set_text(_("'%s' is not writeable.") % file_obj.get_parent_path_or_uri_for_display())
                    self.rename_button.set_sensitive(False)
                elif not file_obj.writable():
                    self.infobar.show()
                    self.error_label.set_text(_("'%s' is not writeable.") % file_obj.get_path_or_uri_for_display())
                    self.rename_button.set_sensitive(False)
                self.renamed_uris.append(renamed_uri)
                any_changes = (new_name != orig_name) or any_changes
            except Exception as e:
                print(e)
                self.infobar.show()
                self.error_label.set_text("'%s' %s." % (file_obj.get_path_or_uri_for_display(), str(e)))
                self.model.set_value(iter, COL_NEW_NAME, orig_name)
                self.renamed_uris.append(file_obj.uri)
            iter = self.model.iter_next(iter)
            index += 1
        self.rename_button.set_sensitive(any_changes)

    def replace_text(self, index, string):
        case = self.replace_case_check.get_active()
        regex = self.replace_regex_check.get_active()
        find = self.find_entry.get_text()
        if not find:  #ignore empty search string
            return string
        inc  = self.replace_inc_spin.get_value_as_int()
        start= self.replace_start_spin.get_value_as_int()
        replace = self.replace_entry.get_text()
        replace = self.inject((index-1)*inc + start, replace)
        try:
            if regex:
                if case:
                    return re.sub(find, replace, string)
                else:
                    reg = re.compile(find, re.IGNORECASE)
                    return reg.sub(replace, string)
            else:
                find = find.replace("*", "~~~REGSTAR~~~")
                find = find.replace("?", "~~~REGQUES~~~")
                find = re.escape(find)
                find = find.replace(re.escape("~~~REGSTAR~~~"), ".+")
                find = find.replace(re.escape("~~~REGQUES~~~"), ".")
                if case:
                    reg = re.compile(find)
                    return reg.sub(replace, string)
                else:
                    reg = re.compile(find, re.IGNORECASE)
                    return reg.sub(replace, string)
        except re.error:
            return string

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
        inc  = self.insert_inc_spin.get_value_as_int()
        start= self.insert_start_spin.get_value_as_int()
        text = self.inject((index-1)*inc + start, text)
        from_index = self.insert_spin.get_value_as_int() - 1
        a = len(string)
        b = len(text)
        if self.insert_reverse_check.get_active():
            diff = max(0, a - from_index)
            if self.overwrite_check.get_active():
                return string[0:diff] + text + string[diff + b:]
            else:
                return string[0:diff] + text + string[diff:]
        else:
            if self.overwrite_check.get_active():
                return string[0:from_index] + text + string[from_index + b:]
            else:
                return string[0:from_index] + text + string[from_index:]

    def change_case(self, index, string):
        if self.radio_titlecase.get_active():
            return string.title()
        elif self.radio_lowercase.get_active():
            return string.lower()
        elif self.radio_uppercase.get_active():
            return string.upper()
        elif self.radio_firstuppercase.get_active():
            return string.capitalize()
        else:
            return unidecode.unidecode(string)

    def inject(self, index, string):
        def repl(match):
            zeros = match.group(1)
            width = len(zeros) + 1
            return f"{index:0{width}d}"
        return re.sub(r'%([0]*)n', repl, string)

'''
TODO
----
- translations

'''

if __name__ == "__main__":
    application = MyApplication("org.x.bulky", Gio.ApplicationFlags.FLAGS_NONE)
    application.run()
