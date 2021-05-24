#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gi

gi.require_version('Caja', '2.0')
gi.require_version('Gtk', '3.0')

import os
import gettext
import locale
from gi.repository import Caja, Gtk, GObject, Gio

locale.setlocale(locale.LC_ALL, '')
gettext.bindtextdomain('bulky', '/usr/share/locale')
gettext.textdomain('bulky')
_ = gettext.gettext

class BulkyMenu(GObject.GObject, Caja.MenuProvider):

    def __init__(self):
        pass

    def get_file_items(self, window, items):
        if len(items) > 1:
            item = Caja.MenuItem(name='bulky', label=_('Rename...'))
            item.connect('activate', self.on_activate, items)
            return [item]

    def on_activate(self, widget, items):
        paths = []
        for item in items:
            paths.append(item.get_location().get_path())
        os.system("bulky %s" % " ".join(paths))

