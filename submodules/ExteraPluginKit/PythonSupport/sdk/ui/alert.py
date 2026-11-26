# This is the iOS counterpart of the exteraGram plugins SDK.
#
# `AlertDialogBuilder` keeps the Android builder API one-for-one: the same
# methods, the same button constants and the same fluent return.  The dialog is
# rendered by the Swift host as a native `UIAlertController`, which is the iOS
# control with the same role (title, message, up to three buttons, list of
# items, dismiss/cancel callbacks).
#
# Methods whose Android behaviour has no iOS analogue at all (custom top
# animations, Lottie resources, blur) accept their arguments and are recorded in
# `unsupported_options`, so a plugin can inspect what was ignored.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import traceback
from typing import Callable, Dict, List, Optional

import extera_ios
from extera_ios import AlertHandle
from log_utils import log


_RELEASED_MESSAGE = ("AlertDialogBuilder: this dialog was dismissed and released, so it can't be "
                     "shown again. Create a new AlertDialogBuilder instead.")


class AlertDialogBuilder:
    ALERT_TYPE_MESSAGE = 0
    ALERT_TYPE_LOADING = 2
    ALERT_TYPE_SPINNER = 3

    BUTTON_POSITIVE = -1
    BUTTON_NEGATIVE = -2
    BUTTON_NEUTRAL = -3

    def __init__(self, context=None, progress_style=ALERT_TYPE_MESSAGE,
                 resources_provider=None):
        self._context = context
        self._progress_style = progress_style
        self._resources_provider = resources_provider
        self._title = None
        self._message = None
        self._items = None
        self._items_icons = None
        self._positive = None
        self._negative = None
        self._neutral = None
        self._on_back = None
        self._on_dismiss = None
        self._on_cancel = None
        self._on_item = None
        self._on_show = None
        self._single_choice = 0
        self._single_listener = None
        self._multi_checked = []
        self._multi_listener = None
        self._checkbox = None
        self._custom_view = None
        self._height = None
        self._red_buttons = []
        self._dim = True
        self._cancelable = True
        self._canceled_on_touch_outside = True
        self._dialog = None
        self.unsupported_options = {}

    # -- content ---------------------------------------------------------

    def set_title(self, title):
        self._title = title
        return self

    def set_message(self, message):
        self._message = message
        return self

    def set_message_text_view_clickable(self, clickable):
        self.unsupported_options["message_text_view_clickable"] = bool(clickable)
        return self

    def set_view(self, view, height=-2):
        self._custom_view = view
        self._height = height
        return self

    def set_items(self, items, listener=None, icons=None):
        self._items = list(items or [])
        self._items_icons = icons
        self._on_item = listener
        return self

    # -- buttons ---------------------------------------------------------

    def set_positive_button(self, text, listener=None):
        self._positive = (text, listener)
        return self

    def set_negative_button(self, text, listener=None):
        self._negative = (text, listener)
        return self

    def set_neutral_button(self, text, listener=None):
        self._neutral = (text, listener)
        return self

    # Android names the builder methods in camelCase; plugins call them
    # directly (`AlertDialog.Builder(...).setTitle(...)`) as well as through the
    # SDK's snake_case helpers.
    def setTitle(self, title):
        return self.set_title(title)

    def setMessage(self, message):
        return self.set_message(message)

    def setItems(self, items, listener=None, icons=None):
        return self.set_items(items, listener, icons)

    def setPositiveButton(self, text, listener=None):
        return self.set_positive_button(text, listener)

    def setNegativeButton(self, text, listener=None):
        return self.set_negative_button(text, listener)

    def setNeutralButton(self, text, listener=None):
        return self.set_neutral_button(text, listener)

    def setView(self, view, height=-2):
        return self.set_view(view, height)

    def setCustomView(self, view, height=-2):
        return self.set_view(view, height)

    def setOnDismissListener(self, listener=None):
        return self.set_on_dismiss_listener(listener)

    def setOnCancelListener(self, listener=None):
        return self.set_on_cancel_listener(listener)

    def setOnBackButtonListener(self, listener=None):
        return self.set_on_back_button_listener(listener)

    def setOnShowListener(self, listener=None):
        self._on_show = listener
        return self

    def setDimEnabled(self, enabled):
        return self.set_dim_enabled(enabled)

    def setSingleChoiceItems(self, items, checked, listener=None):
        self._single_choice = int(checked or 0)
        self._single_listener = listener
        self._items = list(items or [])
        self._on_item = self._single_item
        return self

    def _single_item(self, index):
        self._single_choice = int(index)
        if self._single_listener is not None:
            self._safe(self._single_listener, self, int(index))

    def setMultiChoiceItems(self, items, checked, listener=None):
        self._multi_checked = list(checked or [])
        self._multi_listener = listener
        self._items = list(items or [])
        self._on_item = self._multi_item
        return self

    def _multi_item(self, index):
        index = int(index)
        while len(self._multi_checked) <= index:
            self._multi_checked.append(False)
        self._multi_checked[index] = not bool(self._multi_checked[index])
        if self._multi_listener is not None:
            self._safe(self._multi_listener, self, index, self._multi_checked[index])

    def setCheckBox(self, text, checked, listener=None):
        self._checkbox = (str(text or ""), bool(checked), listener)
        self._items = [str(text or "")]

        def toggle(_index):
            label, value, callback = self._checkbox
            value = not value
            self._checkbox = (label, value, callback)
            if callback is not None:
                self._safe(callback, self, value)

        self._on_item = toggle
        return self

    def make_button_red(self, button_type):
        if button_type not in self._red_buttons:
            self._red_buttons.append(button_type)
        return self

    def set_on_back_button_listener(self, listener=None):
        self._on_back = listener
        return self

    def set_on_dismiss_listener(self, listener=None):
        self._on_dismiss = listener
        return self

    def set_on_cancel_listener(self, listener=None):
        self._on_cancel = listener
        return self

    # -- presentation ----------------------------------------------------

    def set_top_image(self, res_id, background_color):
        self.unsupported_options["top_image"] = (res_id, background_color)
        return self

    def set_top_drawable(self, drawable, background_color):
        self.unsupported_options["top_drawable"] = background_color
        return self

    def set_top_animation(self, res_id, size, auto_repeat, background_color,
                          layer_colors=None):
        self.unsupported_options["top_animation"] = (res_id, size, bool(auto_repeat))
        return self

    def set_top_animation_is_new(self, is_new):
        self.unsupported_options["top_animation_is_new"] = bool(is_new)
        return self

    def set_dim_enabled(self, enabled):
        self._dim = bool(enabled)
        return self

    def set_dialog_button_color_key(self, theme_key):
        self.unsupported_options["button_color_key"] = theme_key
        return self

    def set_blurred_background(self, blur, blur_behind_if_possible=True):
        self.unsupported_options["blur"] = (bool(blur), bool(blur_behind_if_possible))
        return self

    def set_cancelable(self, cancelable):
        self._cancelable = bool(cancelable)
        if self._dialog is not None:
            self._dialog.set_cancelable(cancelable)
        return self

    def setCancelable(self, cancelable):
        return self.set_cancelable(cancelable)

    def set_canceled_on_touch_outside(self, cancel):
        self._canceled_on_touch_outside = bool(cancel)
        if self._dialog is not None:
            self._dialog.set_canceled_on_touch_outside(cancel)
        return self

    def setCanceledOnTouchOutside(self, cancel):
        return self.set_canceled_on_touch_outside(cancel)

    # -- lifecycle -------------------------------------------------------

    def _callbacks(self):
        def button(entry, code):
            if not entry:
                return None
            text, listener = entry
            if listener is None:
                return {"text": text, "callback": None}
            return {
                "text": text,
                "callback": extera_ios.retain(
                    lambda: self._safe(listener, self, code)
                ),
            }

        spec = {
            "title": self._title,
            "message": self._message,
            "items": self._items,
            "positive": button(self._positive, self.BUTTON_POSITIVE),
            "negative": button(self._negative, self.BUTTON_NEGATIVE),
            "neutral": button(self._neutral, self.BUTTON_NEUTRAL),
            "cancelable": self._cancelable,
            "canceled_on_touch_outside": self._canceled_on_touch_outside,
            "dim": self._dim,
            "loading": self._progress_style == self.ALERT_TYPE_LOADING,
            "red_buttons": list(self._red_buttons),
            "unsupported": sorted(self.unsupported_options.keys()),
        }
        if self._items is not None and self._on_item is not None:
            spec["items_callback"] = extera_ios.retain(
                lambda index: self._safe(self._on_item, self, int(index))
            )
        if self._on_dismiss is not None:
            spec["dismiss_callback"] = extera_ios.retain(
                lambda: self._safe(self._on_dismiss, self)
            )
        if self._on_cancel is not None:
            spec["cancel_callback"] = extera_ios.retain(
                lambda: self._safe(self._on_cancel, self)
            )
        if self._on_back is not None:
            spec["back_callback"] = extera_ios.retain(
                lambda: self._safe(self._on_back, self, 0)
            )
        return spec

    def _button_code(self, text):
        # Android passes AlertDialog.BUTTON_*; the iOS host reports the same
        # codes, so a listener that compares `which` keeps working.
        return 0

    @staticmethod
    def _safe(callback, *args):
        try:
            return callback(*args)
        except Exception:
            log("Error in AlertDialog callback: %s" % traceback.format_exc())
            return None

    def _build(self):
        if self._dialog is None:
            result = extera_ios.host_json("alert.show", self._callbacks())
            identifier = None
            if isinstance(result, dict):
                identifier = result.get("id")
            self._dialog = AlertHandle(identifier)
        else:
            spec = self._callbacks()
            spec["id"] = self._dialog.get_id()
            extera_ios.host_json("alert.show", spec)
            self._dialog._showing = True
        return self._dialog

    def create(self):
        if self._dialog is None:
            result = extera_ios.host_json("alert.create", self._callbacks())
            identifier = result.get("id") if isinstance(result, dict) else None
            self._dialog = AlertHandle(identifier)
            if isinstance(result, dict):
                self._dialog._showing = False
        return self

    def show(self):
        if self._dialog is not None and self._dialog.is_showing():
            return self
        self._build()
        if self._on_show is not None:
            self._safe(self._on_show, self)
        return self

    def dismiss(self):
        if self._dialog is not None:
            self._dialog.dismiss()

    def get_dialog(self):
        return self._dialog

    def getButton(self, button_type):
        return None

    def get_button(self, button_type):
        return None

    def set_progress(self, progress):
        if self._dialog is not None and self._progress_style == self.ALERT_TYPE_LOADING:
            self._dialog.set_progress(progress)

    def setProgress(self, progress):
        return self.set_progress(progress)

    def get_context(self):
        return self._context


AlertDialogBuilder.setTitle = AlertDialogBuilder.set_title
AlertDialogBuilder.setMessage = AlertDialogBuilder.set_message
AlertDialogBuilder.setView = AlertDialogBuilder.set_view
AlertDialogBuilder.setItems = AlertDialogBuilder.set_items
AlertDialogBuilder.setPositiveButton = AlertDialogBuilder.set_positive_button
AlertDialogBuilder.setNegativeButton = AlertDialogBuilder.set_negative_button
AlertDialogBuilder.setNeutralButton = AlertDialogBuilder.set_neutral_button
AlertDialogBuilder.makeButtonRed = AlertDialogBuilder.make_button_red
AlertDialogBuilder.setOnBackButtonListener = AlertDialogBuilder.set_on_back_button_listener
AlertDialogBuilder.setOnDismissListener = AlertDialogBuilder.set_on_dismiss_listener
AlertDialogBuilder.setOnCancelListener = AlertDialogBuilder.set_on_cancel_listener
AlertDialogBuilder.setTopImage = AlertDialogBuilder.set_top_image
AlertDialogBuilder.setTopDrawable = AlertDialogBuilder.set_top_drawable
AlertDialogBuilder.setTopAnimation = AlertDialogBuilder.set_top_animation
AlertDialogBuilder.setTopAnimationIsNew = AlertDialogBuilder.set_top_animation_is_new
AlertDialogBuilder.setDimEnabled = AlertDialogBuilder.set_dim_enabled
AlertDialogBuilder.setDialogButtonColorKey = AlertDialogBuilder.set_dialog_button_color_key
AlertDialogBuilder.setBlurredBackground = AlertDialogBuilder.set_blurred_background
AlertDialogBuilder.setMessageTextViewClickable = AlertDialogBuilder.set_message_text_view_clickable
AlertDialogBuilder.setProgress = AlertDialogBuilder.set_progress


class AlertDialog:
    """The bare Android class name, mapped to the builder for compatibility."""

    Builder = AlertDialogBuilder

    class OnButtonClickListener:
        def onClick(self, dialog, which):
            pass

    class OnDismissListener:
        def onDismiss(self, dialog):
            pass

    class OnCancelListener:
        def onCancel(self, dialog):
            pass

    class OnShowListener:
        def onShow(self, dialog):
            pass
