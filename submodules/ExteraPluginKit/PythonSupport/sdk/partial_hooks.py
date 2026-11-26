# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Android's partial hooks intercept one bytecode instruction inside a method
# (`hook_call_site`, `hook_field_read`, `hook_field_write`,
# `hook_string_constant`, `hook_return_value`).  iOS has no JVM bytecode, so the
# kit installs the closest equivalent: an Objective-C hook on the member the
# target names.  The chain keeps the Android surface
# (`getThisObject()`, `getCaller()`, `getArgs()`, `arg()`, `proceed()`,
# `throwToCaller()`); `proceed()` runs the original implementation through
# `runtime.proceed`, and not calling it skips the original call or write the
# way Android skips the instruction.
#
# Deviations, all reported through `log_utils`/the host log instead of silently
# pretending:
#
#   * `getCaller()` is always `None` - a method-level hook cannot see which
#     method made the call.
#   * `InstructionMatcher.constString(...)` has no method-level equivalent, so
#     `ExteraHook.hook(...).intercept(...)` returns `None` and the SDK's
#     `hook_string_constant` reports "could not be installed", exactly like an
#     Android hook whose target cannot be resolved.
#   * `occurrence` is accepted and ignored: one selector is one hook point.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import extera_ios


def _log(text):
    try:
        extera_ios.log(str(text))
    except Exception:
        pass


def _class_name(member):
    name = getattr(member, "class_name", None)
    if name:
        return str(name)
    name = getattr(member, "_name", None) or getattr(member, "__name__", None)
    if name:
        return str(name)
    getter = getattr(member, "getDeclaringClass", None) or getattr(
        member, "get_declaring_class", None
    )
    if callable(getter):
        try:
            owner = getter()
            name = getattr(owner, "get_name", None)
            if callable(name):
                return str(name())
            name = getattr(owner, "_name", None)
            if name:
                return str(name)
        except Exception:
            pass
    return None


def _member_name(member):
    name = getattr(member, "name", None)
    if isinstance(name, str) and name:
        return name
    getter = getattr(member, "getName", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            pass
    return None


def _resolve(member):
    class_name = _class_name(member)
    name = _member_name(member)
    if not class_name or not name:
        return None
    return class_name, name


class InstructionMatcher:
    """`com.exteragram.hook.InstructionMatcher` (Android's instruction search)."""

    def __init__(self, kind, text=None, occurrence=-1):
        self.kind = kind
        self.text = text
        self.occurrence = int(occurrence)

    @classmethod
    def constString(cls, text, occurrence=-1):
        return cls("const_string", str(text), occurrence)

    @classmethod
    def returnValue(cls, occurrence=-1):
        return cls("return_value", None, occurrence)

    def __repr__(self):
        return "<InstructionMatcher %s %r>" % (self.kind, self.text)


class HookTarget:
    """`com.exteragram.hook.HookTarget`."""

    def __init__(self, kind, member=None, callee=None, matcher=None, occurrence=-1):
        self.kind = kind
        self.member = member
        self.callee = callee
        self.matcher = matcher
        self.occurrence = int(occurrence)

    @classmethod
    def callSite(cls, in_method, callee, occurrence=-1):
        return cls("call_site", member=in_method, callee=callee, occurrence=occurrence)

    @classmethod
    def fieldRead(cls, in_method, field, occurrence=-1):
        return cls("field_read", member=in_method, callee=field, occurrence=occurrence)

    @classmethod
    def fieldWrite(cls, in_method, field, occurrence=-1):
        return cls("field_write", member=in_method, callee=field, occurrence=occurrence)

    @classmethod
    def instruction(cls, in_method, matcher):
        return cls("instruction", member=in_method, matcher=matcher)

    def resolve(self):
        """Returns `(class_name, selector, description)` or `None`."""
        if self.kind == "call_site":
            resolved = _resolve(self.callee)
        elif self.kind == "field_read":
            resolved = _resolve(self.callee)
        elif self.kind == "field_write":
            resolved = _resolve(self.callee)
            if resolved is not None:
                class_name, name = resolved
                resolved = (class_name, "set" + name[:1].upper() + name[1:])
        elif self.kind == "instruction":
            matcher = self.matcher
            if matcher is None or matcher.kind != "return_value":
                _log(
                    "Partial hooks: instruction matchers other than returnValue "
                    "are not available on iOS; the hook was not installed"
                )
                return None
            resolved = _resolve(self.member)
        else:
            resolved = None
        if resolved is None:
            return None
        return resolved[0], resolved[1], "%s.%s" % (resolved[0], resolved[1])

    def __repr__(self):
        return "<HookTarget %s %r>" % (self.kind, self.resolve())


class PartialChain:
    """The chain an `Interceptor.intercept()` callback receives.

    Mirrors `base_plugin.PartialChain`/the Java `Interceptor.Chain` surface and
    writes through to the live Objective-C invocation.
    """

    def __init__(self, target, param):
        self._target = target
        self._param = param
        self._param_id = param.get("id") if hasattr(param, "get") else None
        self._this = param.get("this") if hasattr(param, "get") else None
        self._args = list(param.get("args") or []) if hasattr(param, "get") else []
        self._original = None
        self._has_original = False
        self.proceeded = False
        self.skipped = False
        self.threw = False
        if (
            target.kind == "instruction"
            and target.matcher is not None
            and target.matcher.kind == "return_value"
        ):
            # Android hands the callback the value at the return instruction, so
            # run the original first and present its result as `args[0]`.
            self._original = self._run_original(None)
            self._has_original = True
            self._args = [self._original]

    # -- Java `Interceptor.Chain` surface ------------------------------------

    @property
    def java(self):
        return self

    def getThisObject(self):
        return self._this

    def getCaller(self):
        return None

    def getArgs(self):
        return list(self._args)

    def arg(self, index):
        return self._args[index]

    def getThis(self):
        return self.getThisObject()

    def getArguments(self):
        return self.getArgs()

    # -- Proceeding ----------------------------------------------------------

    def _run_original(self, arguments):
        if not self._param_id:
            return None
        if arguments is None:
            return extera_ios.host("runtime.proceed", param_id=self._param_id)
        return extera_ios.host(
            "runtime.proceed", param_id=self._param_id, args=list(arguments)
        )

    def proceed(self, *args):
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            args = tuple(args[0])
        if self._target.kind == "instruction":
            if not self._has_original:
                self._original = self._run_original(None)
                self._has_original = True
            self.proceeded = True
            return args[0] if args else self._original
        value = self._run_original(args if args else None)
        self.proceeded = True
        return value

    def throwToCaller(self, throwable):
        self.threw = True
        if isinstance(throwable, BaseException):
            raise throwable
        raise RuntimeError(str(throwable))

    def mark_skipped(self):
        if not self._param_id:
            return
        try:
            extera_ios.host("runtime.skip", param_id=self._param_id)
        except Exception:
            pass

    def __repr__(self):
        return "<PartialChain %s args=%r>" % (self._target.kind, self._args)


class PartialHookHandle:
    def __init__(self, handle, callback_handle, description):
        self.handle = handle
        self.callback_handle = callback_handle
        self.description = description
        self.active = True

    def unhook(self):
        if not self.active:
            return
        self.active = False
        try:
            extera_ios.host("runtime.unswizzle", handle=self.handle)
        except Exception:
            pass
        try:
            extera_ios.release(self.callback_handle)
        except Exception:
            pass

    def __repr__(self):
        return "<PartialHookHandle %s %s>" % (
            "active" if self.active else "inactive",
            self.description,
        )


def _intercept_call(target, interceptor, param):
    chain = PartialChain(target, param)
    value = interceptor.intercept(chain)
    if chain.threw:
        return None
    if not chain.proceeded and not chain.skipped:
        if value is None and target.kind == "instruction":
            # The original already ran; keeping its value is the no-op filter.
            chain.skipped = True
            return chain._original
        if value is None:
            chain.mark_skipped()
            chain.skipped = True
    return value


class ExteraHookBuilder:
    def __init__(self, target):
        self._target = target
        self._priority = 0

    def priority(self, value):
        self._priority = int(value or 0)
        return self

    def intercept(self, interceptor):
        if interceptor is None or not hasattr(interceptor, "intercept"):
            return None
        resolved = self._target.resolve()
        if resolved is None:
            return None
        class_name, selector, description = resolved
        callback = extera_ios.retain(
            lambda param: _intercept_call(self._target, interceptor, param)
        )
        handle = extera_ios.host(
            "runtime.swizzle",
            class_name=class_name,
            selector=selector,
            callbacks={"replace": callback},
            filters=[],
        )
        if not handle:
            try:
                extera_ios.release(callback)
            except Exception:
                pass
            _log(
                "Partial hook: cannot install on %s (class or selector is not "
                "present in the app)" % description
            )
            return None
        return PartialHookHandle(str(handle), callback, description)


class ExteraHook:
    """`com.exteragram.hook.ExteraHook` entry point."""

    @classmethod
    def hook(cls, target):
        if target is None:
            return None
        return ExteraHookBuilder(target)


class Interceptor:
    """Subclass and override `intercept(chain)`."""

    def intercept(self, chain):
        raise NotImplementedError("Interceptor.intercept() must be implemented")
