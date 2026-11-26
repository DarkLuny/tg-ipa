# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Settings rows are described by the same dataclasses as on Android.  The
# serializer accepts the descriptors and turns every callable into an opaque
# callback handle the Swift settings screen can invoke.
#
# `Custom` normally carries an Android `View` or a `UItem.Factory`.  On iOS a
# Python plugin cannot build a UIView, so the descriptor is preserved (a custom
# row with the given title), and `factory_args` is passed back to callbacks.
# A plugin that needs a native-looking control should use one of the standard
# rows.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional


# Chaquopy's DEX type helpers are part of the Android SDK module surface.  The
# iOS SDK has no DEX type system; keep the names importable and functional for
# code that calls them directly.
pyobject_type = object
object_array_type = list
typehelper = object


def pyobject_call_method(pyobject, *args):
    return pyobject(*args)


@dataclass
class Switch:
    key: str
    text: str
    default: bool = False
    subtext: Optional[str] = None
    icon: Optional[str] = None
    on_change: Optional[Callable[[bool], None]] = field(default=None, compare=False, repr=False)
    type: str = field(default="switch", init=False)
    on_long_click: Optional[Callable[[Any], None]] = field(default=None, compare=False, repr=False)
    link_alias: Optional[str] = None


@dataclass
class Selector:
    key: str
    text: str
    default: int = 0
    items: List[str] = field(default_factory=list)
    icon: Optional[str] = None
    on_change: Optional[Callable[[int], None]] = field(default=None, compare=False, repr=False)
    type: str = field(default="selector", init=False)
    on_long_click: Optional[Callable[[Any], None]] = field(default=None, compare=False, repr=False)
    link_alias: Optional[str] = None


@dataclass
class Input:
    key: str
    text: str
    default: str = ""
    subtext: Optional[str] = None
    icon: Optional[str] = None
    on_change: Optional[Callable[[str], None]] = field(default=None, compare=False, repr=False)
    type: str = field(default="input", init=False)
    on_long_click: Optional[Callable[[Any], None]] = field(default=None, compare=False, repr=False)
    link_alias: Optional[str] = None


@dataclass
class Text:
    text: str
    subtext: Optional[str] = None
    icon: Optional[str] = None
    accent: bool = False
    red: bool = False
    on_click: Optional[Callable[[Any], None]] = field(default=None, compare=False, repr=False)
    create_sub_fragment: Optional[Callable[[], List[Any]]] = field(default=None, compare=False, repr=False)
    type: str = field(default="text", init=False)
    on_long_click: Optional[Callable[[Any], None]] = field(default=None, compare=False, repr=False)
    link_alias: Optional[str] = None


@dataclass
class Header:
    text: str
    type: str = field(default="header", init=False)


@dataclass
class Divider:
    text: Optional[str] = None
    type: str = field(default="divider", init=False)


@dataclass
class EditText:
    key: str
    hint: str
    default: str = ""
    multiline: bool = False
    max_length: int = 256
    mask: Optional[str] = None
    on_change: Optional[Callable[[str], None]] = field(default=None, compare=False, repr=False)
    type: str = field(default="edit_text", init=False)


@dataclass
class Custom:
    type: str = field(default="custom", init=False)
    item: Any = field(default=None, compare=False, repr=False)
    view: Any = field(default=None, compare=False, repr=False)
    factory: Any = field(default=None, compare=False, repr=False)
    factory_args: Any = field(default=None, compare=False, repr=False)
    on_click: Optional[Callable[[Any], None]] = field(default=None, compare=False, repr=False)
    on_long_click: Optional[Callable[[Any], None]] = field(default=None, compare=False, repr=False)
    create_sub_fragment: Optional[Callable[[], List[Any]]] = field(default=None, compare=False, repr=False)
    link_alias: Optional[str] = None

    class Factory:
        """Base for `CustomSetting.Factory` custom rows.

        On Android a factory builds a native Android view.  iOS keeps the row
        and its data; `create` can still run to produce a descriptor.
        """

        view_type = 0

        @classmethod
        def setup(cls, java_factory):
            return java_factory

        @classmethod
        def getClass(cls):
            from extera_utils.classes import ClassRef

            return ClassRef(
                "com.exteragram.messenger.plugins.models.CustomSetting$Factory"
            )

        def create(self, *args, **kwargs):
            return None

        def createSettingView(self, *args, **kwargs):
            return None

    def __post_init__(self):
        if self.item is None and self.view is None and self.factory is None:
            raise ValueError("Either item or view or factory must be provided")


# -- Custom setting factories ------------------------------------------------
#
class UItem(dict):
    """`org.telegram.ui.Components.UItem` facade.

    Android plugins may build their settings list with `UItem.asSwitch(...)`
    and friends instead of the Python dataclasses. The row is a dictionary so
    the serializer can pass it through unchanged; Android's field names are
    aliased to the keys the iOS host reads.
    """

    _ALIASES = {
        "id": "key",
        "checked": "default",
        "value": "default",
        "onClick": "on_click",
        "onLongClick": "on_long_click",
        "onChange": "on_change",
        "createSubFragment": "create_sub_fragment",
        "linkAlias": "link_alias",
        "factoryArgs": "factory_args",
        "maxLength": "max_length",
    }

    def __getattr__(self, name):
        key = self._ALIASES.get(name, name)
        if key in self:
            return self[key]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        self[self._ALIASES.get(name, name)] = value

    _factories = {}

    class UItemFactory:
        """`org.telegram.ui.Components.UItem.UItemFactory` stand-in."""

        @classmethod
        def setup(cls, java_factory):
            return java_factory

        @classmethod
        def getClass(cls):
            from extera_utils.classes import ClassRef

            return ClassRef("org.telegram.ui.Components.UItem$UItemFactory")

        @classmethod
        def getDeclaredMethods(cls):
            return []

    @classmethod
    def getClass(cls):
        from extera_utils.classes import ClassRef

        return ClassRef("org.telegram.ui.Components.UItem")

    @classmethod
    def findFactory(cls, view_type):
        return cls._factories.get(view_type)

    @classmethod
    def registerFactory(cls, view_type, factory):
        cls._factories[view_type] = factory
        return factory

    @classmethod
    def asHeader(cls, text):
        return cls({"type": "header", "text": str(text or "")})

    @classmethod
    def asTopView(cls, text, subtext=None, id=None, icon=None, **kwargs):
        item = cls({"type": "text", "text": str(text or ""), "subtext": subtext, "icon": icon})
        if id is not None:
            item["key"] = id
        return item

    @classmethod
    def asButton(cls, id=None, drawable=None, text="", **kwargs):
        return cls({"type": "text", "key": id, "text": str(text or ""), "accent": True})

    @classmethod
    def asShadow(cls, text):
        return cls({"type": "text", "text": str(text or "")})

    @classmethod
    def asCustom(cls, factory_or_id=None, **kwargs):
        if isinstance(factory_or_id, int):
            return cls({"type": "custom", "key": factory_or_id})
        return cls({"type": "custom", "factory": factory_or_id})

    @classmethod
    def asSwitch(cls, id, checked_or_text=False, text=None, **kwargs):
        # Android overloads: (id, text) and (id, checked, text).
        if isinstance(checked_or_text, str) and text is None:
            checked, label = False, checked_or_text
        else:
            checked, label = bool(checked_or_text), text
        return cls({
            "type": "switch",
            "key": id,
            "default": checked,
            "text": str(label or ""),
        })

    @classmethod
    def asSwitch2(cls, id, checked, text, subtext=None, **kwargs):
        return cls({
            "type": "switch",
            "key": id,
            "default": bool(checked),
            "text": str(text or ""),
            "subtext": subtext,
        })

    @classmethod
    def asSelector(cls, id, text, items=None, default=0, **kwargs):
        return cls({
            "type": "selector",
            "key": id,
            "text": str(text or ""),
            "items": list(items or []),
            "default": default,
        })

    @classmethod
    def asText(cls, id, text):
        return cls({"type": "text", "key": id, "text": str(text or "")})

    @classmethod
    def asEditText(cls, id, text):
        return cls({"type": "edit_text", "key": id, "hint": str(text or ""), "default": ""})

    @classmethod
    def asInput(cls, id, text):
        return cls({"type": "input", "key": id, "text": str(text or ""), "default": ""})

    @classmethod
    def asDivider(cls, text=None):
        return cls({"type": "divider", "text": text})

    @classmethod
    def asSticker(cls, id, document=None):
        return cls({"type": "custom", "key": id, "item": document})

    @classmethod
    def asRadio(cls, id, checked, text):
        return cls.asSwitch(id, checked, text)

    def setEnabled(self, value):
        self["enabled"] = bool(value)
        return self

    def setOnClickListener(self, listener):
        self["on_click"] = listener
        return self

    def setOnLongClickListener(self, listener):
        self["on_long_click"] = listener
        return self

    def setOnChangeListener(self, listener):
        self["on_change"] = listener
        return self

    def setLinkAlias(self, alias):
        self["link_alias"] = alias
        return self

    def setAccent(self):
        self["accent"] = True
        return self

    def setRed(self):
        self["red"] = True
        return self


# Android registers a DexMaker-generated `UItem.UItemFactory` so the settings
# list can ask a plugin to build a row.  iOS has no such bridge: the host draws
# rows from descriptors.  The Python side keeps the same registry and factory
# object, so `SimpleSettingFactory(...)` and `Custom(factory=...)` keep working;
# `to_json()` exposes enough metadata for the host to show a placeholder row and
# invoke the callbacks it understands.

_uitem_factories = {}


def _uitem_registry(name):
    return _uitem_factories.setdefault(name, {})


def _register_factory(java_factory):
    if java_factory is None:
        return
    view_type = getattr(java_factory, "viewType", None)
    if view_type is not None:
        _uitem_registry("factories").setdefault(view_type, java_factory)
    _uitem_registry("factoryInstances")[type(java_factory).__name__] = java_factory


def _unregister_factory(java_factory):
    if java_factory is None:
        return
    factories = _uitem_registry("factories")
    for view_type, registered in list(factories.items()):
        if registered is java_factory:
            factories.pop(view_type, None)
    instances = _uitem_registry("factoryInstances")
    for class_name, registered in list(instances.items()):
        if registered is java_factory:
            instances.pop(class_name, None)


class _SimpleCustomSettingFactory:
    """Python stand-in for the generated `CustomSetting.Factory` subclass."""

    viewType = "extera_custom_setting"

    def __init__(self, create_item_fn=None, create_view_fn=None, bind_view_fn=None):
        self.create_item_fn = create_item_fn
        self.create_view_fn = create_view_fn
        self.bind_view_fn = bind_view_fn
        self.attached_view_handler = None
        self.equals_handler = None
        self.content_equals_handler = None
        self.on_click_handler = None
        self.on_long_click_handler = None
        self.isShadowValue = False
        self.isClickableValue = False

    @classmethod
    def new_instance(cls, *args, init_args=None):
        values = list(init_args or args)
        while len(values) < 3:
            values.append(None)
        return cls(*values[:3])

    @property
    def java(self):
        return self

    def create(self, plugin, setting, args):
        if self.create_item_fn is None:
            return {"viewType": self.viewType, "object": args}
        return self.create_item_fn(plugin, setting, args)

    def createView(self, context, list_view, current_account, class_guid, resources_provider):
        if self.create_view_fn is None:
            return None
        return self.create_view_fn(context, list_view, current_account, class_guid, resources_provider)

    def bindView(self, view, item, divider, adapter, list_view):
        if self.bind_view_fn is not None:
            self.bind_view_fn(view, item, divider, adapter, list_view)

    def setAttachedViewHandler(self, value):
        self.attached_view_handler = value

    def setEqualsHandler(self, value):
        self.equals_handler = value

    def setContentEqualsHandler(self, value):
        self.content_equals_handler = value

    def setOnClickHandler(self, value):
        self.on_click_handler = value

    def setOnLongClickHandler(self, value):
        self.on_long_click_handler = value

    def getAttachedViewHandler(self):
        return self.attached_view_handler

    def getEqualsHandler(self):
        return self.equals_handler

    def getContentEqualsHandler(self):
        return self.content_equals_handler

    def getOnClickHandler(self):
        return self.on_click_handler

    def getOnLongClickHandler(self):
        return self.on_long_click_handler

    def jrelease(self):
        for name in (
            "attached_view_handler", "equals_handler", "content_equals_handler",
            "on_click_handler", "on_long_click_handler",
        ):
            setattr(self, name, None)
        self.create_item_fn = self.create_view_fn = self.bind_view_fn = None
        _unregister_factory(self)
        return True

    def to_json(self):
        return {
            "viewType": self.viewType,
            "isShadow": bool(self.isShadowValue),
            "isClickable": bool(self.isClickableValue),
            "handlers": [
                name for name in (
                    "attached_view_handler", "equals_handler", "content_equals_handler",
                    "on_click_handler", "on_long_click_handler",
                ) if getattr(self, name) is not None
            ],
        }


_factory_class = None


def _simple_custom_setting_factory_class():
    global _factory_class
    if _factory_class is None:
        _factory_class = _SimpleCustomSettingFactory
    return _factory_class


def _gen_simple_custom_setting_factory_class():
    return _simple_custom_setting_factory_class()


class SimpleSettingFactory:
    def __init__(
        self,
        create_view: Callable,
        bind_view: Callable,
        *,
        is_clickable: bool = False,
        is_shadow: bool = False,
        create_item: Optional[Callable] = None,
        on_click: Optional[Callable] = None,
        on_long_click: Optional[Callable] = None,
        attached_view: Optional[Callable] = None,
        equals: Optional[Callable] = None,
        content_equals: Optional[Callable] = None,
    ):
        self.create_view = create_view
        self.bind_view = bind_view
        self.is_clickable = is_clickable
        self.is_shadow = is_shadow
        self.create_item = create_item
        self.on_click = on_click
        self.on_long_click = on_long_click
        self.attached_view = attached_view
        self.equals = equals
        self.content_equals = content_equals

        self.instance = _simple_custom_setting_factory_class().new_instance(
            init_args=[create_item, create_view, bind_view]
        )
        if attached_view:
            self.instance.setAttachedViewHandler(attached_view)
        if equals:
            self.instance.setEqualsHandler(equals)
        if content_equals:
            self.instance.setContentEqualsHandler(content_equals)
        if on_click:
            self.instance.setOnClickHandler(on_click)
        if on_long_click:
            self.instance.setOnLongClickHandler(on_long_click)

        _register_factory(self.instance)
        self.instance.isShadowValue = is_shadow
        self.instance.isClickableValue = is_clickable

    def release(self):
        return self.instance.jrelease()

    def __call__(self, *args, create_sub_fragment=None, link_alias=None):
        factory_args = None
        if args:
            try:
                from extera_utils.classes import PyObj

                factory_args = PyObj.create(args)
            except Exception:
                factory_args = list(args)
        return Custom(
            factory=self.instance,
            factory_args=factory_args,
            link_alias=link_alias,
            create_sub_fragment=create_sub_fragment,
        )


def is_divider(control):
    return isinstance(control, Divider)


def is_header(control):
    return isinstance(control, Header)
