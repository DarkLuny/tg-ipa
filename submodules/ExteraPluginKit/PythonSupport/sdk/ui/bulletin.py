# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Bulletins map to the native Telegram iOS "undo" overlay / toast presented by
# the host.  The class and method names are the Android ones, so a plugin calls
# `BulletinHelper.show_info("...")` unchanged.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

from typing import Optional

import extera_ios


class _OneShot:
    """Releases the retained callback after the host invokes it once."""

    def __init__(self, callback):
        self.callback = callback
        self.handle = None

    def __call__(self, *args):
        try:
            return self.callback(*args)
        finally:
            if self.handle:
                extera_ios.release(self.handle)
                self.handle = None


def _retain_once(callback):
    if callback is None:
        return None
    wrapper = _OneShot(callback)
    wrapper.handle = extera_ios.retain(wrapper)
    return wrapper.handle


class BulletinHelper:
    DURATION_SHORT = 1500
    DURATION_LONG = 2750
    DURATION_PROLONG = 5000

    @classmethod
    def _get_factory_and_provider(cls, fragment=None):
        """Android returns a BulletinFactory and a ResourcesProvider.

        iOS presents every bulletin through the host overlay, which owns the
        current screen; the pair is kept so plugin code that stores it works.
        """
        return None, None

    @classmethod
    def _show(cls, kind, text, subtext=None, duration=DURATION_LONG, fragment=None,
              icon=None, button_text=None, on_click=None, undo_text=None,
              on_undo=None, on_action=None):
        extera_ios.host(
            "ui.bulletin",
            kind=kind,
            text="" if text is None else str(text),
            subtext=None if subtext is None else str(subtext),
            duration=int(duration),
            icon=icon,
            button_text=button_text,
            on_click=_retain_once(on_click),
            undo_text=undo_text,
            on_undo=_retain_once(on_undo),
            on_action=_retain_once(on_action),
        )

    @classmethod
    def show_info(cls, message, fragment=None):
        cls._show("info", message, fragment=fragment)

    @classmethod
    def show_error(cls, message, fragment=None):
        cls._show("error", message, fragment=fragment)

    @classmethod
    def show_success(cls, message, fragment=None):
        cls._show("success", message, fragment=fragment)

    @classmethod
    def show_simple(cls, text, icon_res_id=None, fragment=None):
        cls._show("simple", text, icon=icon_res_id, fragment=fragment)

    @classmethod
    def show_two_line(cls, title, subtitle, icon_res_id=None, fragment=None):
        cls._show(
            "simple", title, subtext=subtitle, icon=icon_res_id, fragment=fragment
        )

    @classmethod
    def show_with_button(cls, text, icon_res_id, button_text, on_click,
                         fragment=None, duration=DURATION_PROLONG):
        cls._show(
            "simple",
            text,
            icon=icon_res_id,
            duration=duration,
            button_text=button_text,
            on_click=on_click,
            fragment=fragment,
        )

    @classmethod
    def show_undo(cls, text, on_undo, on_action=None, subtitle=None, fragment=None):
        cls._show(
            "simple",
            text,
            subtext=subtitle,
            undo_text="Undo",
            on_undo=on_undo,
            on_action=on_action,
            fragment=fragment,
        )

    @classmethod
    def show_copied_to_clipboard(cls, message=None, fragment=None):
        cls._show(
            "success",
            "Copied to clipboard" if message is None else message,
            fragment=fragment,
        )

    @classmethod
    def show_link_copied(cls, is_private_link_info=False, fragment=None):
        cls._show("success", "Link copied", fragment=fragment)

    @classmethod
    def show_file_saved_to_gallery(cls, is_video=False, amount=1, fragment=None):
        if amount > 1:
            text = "Videos saved to Photos" if is_video else "Photos saved to Photos"
        else:
            text = "Video saved to Photos" if is_video else "Photo saved to Photos"
        cls._show("success", text, fragment=fragment)

    @classmethod
    def show_file_saved_to_downloads(cls, file_type_enum_name="UNKNOWN", amount=1,
                                     fragment=None):
        if amount > 1:
            text = "Files saved to Files"
        else:
            text = "File saved to Files"
        cls._show("success", text, fragment=fragment)

    @classmethod
    def show_bulletin(cls, text, fragment=None):
        cls._show("simple", text, fragment=fragment)


class Bulletin:
    """Marker so `isinstance` checks in plugin code keep working."""

    DURATION_SHORT = 1500
    DURATION_LONG = 3200

    class EmptyBulletin:
        pass

    BottomSheet = type("BottomSheet", (), {})
