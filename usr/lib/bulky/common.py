#!/usr/bin/python3
import gi
import magic
import os
import threading
from gi.repository import Gio, GObject, Gtk

# Used as a decorator to run things in the background
def _async(func):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.daemon = True
        thread.start()
        return thread
    return wrapper

# Used as a decorator to run things in the main loop, from another thread
def idle(func):
    def wrapper(*args):
        GObject.idle_add(func, *args)
    return wrapper

# This is a data structure representing
# the file object
class FileObject():

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.name = os.path.basename(path)
        if os.path.isdir(self.path):
            self.icon = "folder"
        else:
            self.icon = "text-x-generic"
            try:
                icon_theme = Gtk.IconTheme.get_default()
                mimetype = magic.from_file(self.path, mime=True)
                for name in Gio.content_type_get_icon(mimetype).get_names():
                    if icon_theme.has_icon(name):
                        self.icon = name
                        break
            except Exception as e:
                print(e)

        self.is_valid = True