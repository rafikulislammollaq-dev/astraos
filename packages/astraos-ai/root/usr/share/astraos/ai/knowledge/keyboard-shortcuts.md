# Keyboard Shortcuts On AstraOS

keywords: keyboard, shortcuts, keys, super key, windows key, hotkeys, keybindings, xfce4-keyboard-shortcuts, whiskermenu, lock screen, screenshot key, setxkbmap

The keys that come from Windows work here. AstraOS binds `Super+E` to open the file
manager (Thunar), `Super+R` to open the run launcher (`xfce4-appfinder`, the box where
you type a command name), `Super+T` to open a terminal (`xfce4-terminal`), and `Super+L`
to lock the session (`xflock4`, the same lock Windows uses). The Super key is the one
with the Windows logo on it. `Super+S` opens the Start menu rather than taking a
screenshot, and `Super+D` shows the desktop. The screenshot keys are `Print` for the
whole screen and `Shift+Print` for a region, both of which run `xfce4-screenshooter`; if
you come from Windows expecting `Super+S` to capture, the one to press is `Print`.

The rest of the desktop keeps the conventional Xfce and Windows bindings, so nothing has
to be relearned: `Ctrl+Alt+T` opens a terminal, `Ctrl+Alt+H` the file manager,
`Ctrl+Alt+F` Firefox, `Ctrl+Alt+W` the Start menu, `Ctrl+Alt+I` an AstraOS information
window, and `Ctrl+Alt+Delete` logs out. `Ctrl+Shift+Escape` opens the task manager, which
is worth remembering when the desktop freezes. Windows and workspaces stay on the
familiar ones - `Alt+F4` closes, `Alt+F10` maximises, `Super+Left` and `Super+Right` tile
a window to one side, `Super+Up` maximises, and `Ctrl+Alt+Left` / `Ctrl+Alt+Right` switch
workspace.

These bindings live in the xfce4-keyboard-shortcuts channel of Xfconf, which on this
machine is the file
`~/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml`. It is plain
XML, one `<property>` per key, and it is copied into the home directory from `/etc/skel`
when the account is created - which is why a fresh install gets the AstraOS keys and an
account that already existed on the machine does not. The distribution cannot ship the
same file under `/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/` because Debian's Xfce
packages own that path and dpkg refuses a second owner.

To change one, use Settings, then Keyboard, then Application Shortcuts: double-click the
binding you want, press the new key combination, and it takes effect immediately. There
is no need to log out first for a change made in the GUI. Editing the XML by hand also
works, but only after logging out and back in, because the running Xfce configuration
daemon holds the values in memory - hand-editing a file the daemon has already read is
the usual reason "I changed the shortcut and nothing happened".

Two things follow from how Xfce works. First, once anything is changed in the settings
editor, Xfce writes its own complete copy of the channel, and that copy wins over the
skeleton default; the AstraOS bindings that were not touched stay in it, unchanged.
Second, a binding that the keyboard cannot produce simply never fires, which is harmless
- a key combination assigned to a program that is not installed does the same.
