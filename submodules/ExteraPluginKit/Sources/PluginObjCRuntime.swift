import Foundation
import ObjectiveC
import CoreFoundation
import ExteraPython
#if canImport(Darwin)
import Darwin
#endif

/// Objective-C method hooking: the iOS analogue of `XposedBridge.hookMethod`.
///
/// The method's implementation is replaced with the Objective-C forwarding
/// entry point. The runtime then calls `forwardInvocation:` on the class, where
/// this object builds a `MethodHookParam`, runs the Python callbacks, calls the
/// original implementation (unless a replacement or a `setResult` skipped it),
/// and applies the result.
///
/// A Swift method that is not exposed to Objective-C (`@objc`) is invisible to
/// the runtime and cannot be hooked; the install call returns nil and the
/// plugin's `hook_method` sees that instead of a silent no-op.
public final class PluginObjCRuntime: @unchecked Sendable {
    public static let shared = PluginObjCRuntime()

    private final class HookEntry {
        let handle: String
        let className: String
        let selectorName: String
        let method: Method
        let originalIMP: IMP
        let callbacks: [String: String]
        let filters: [[String: Any]]
        let beforeFilters: [[String: Any]]
        let afterFilters: [[String: Any]]

        init(handle: String, className: String, selectorName: String, method: Method, originalIMP: IMP, callbacks: [String: String], filters: [[String: Any]], beforeFilters: [[String: Any]] = [], afterFilters: [[String: Any]] = []) {
            self.handle = handle
            self.className = className
            self.selectorName = selectorName
            self.method = method
            self.originalIMP = originalIMP
            self.callbacks = callbacks
            self.filters = filters
            self.beforeFilters = beforeFilters.isEmpty ? filters : beforeFilters
            self.afterFilters = afterFilters.isEmpty ? filters : afterFilters
        }
    }

    private final class ParamState {
        let invocation: PluginInvocation
        let entry: HookEntry
        var result: Any?
        var originalRan = false
        var skipped = false
        var extras: [String: Any] = [:]

        init(invocation: PluginInvocation, entry: HookEntry) {
            self.invocation = invocation
            self.entry = entry
        }
    }

    private let lock = NSRecursiveLock()
    private var entries: [String: HookEntry] = [:]
    private var byHandle: [String: HookEntry] = [:]
    private var forwardingInstalled: Set<String> = []
    private var originalForward: [String: IMP] = [:]
    private var params: [String: ParamState] = [:]

    private let forwardIMP: IMP?

    private init() {
        // RTLD_DEFAULT is (void *)-2 on Darwin. `_objc_msgForward` is libobjc's
        // own entry point (the same one `forwardInvocation:` is reached from);
        // this is a system lookup, not a lookup of an app symbol.
        if let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "_objc_msgForward") {
            self.forwardIMP = unsafeBitCast(symbol, to: IMP.self)
        } else {
            self.forwardIMP = nil
        }
    }

    static func mappedSelector(_ name: String) -> String {
        if name.contains(":") {
            return name
        }
        let mapping: [String: String] = [
            "setText": "setText:",
            "getText": "text",
            "setVisibility": "setHidden:",
            "getVisibility": "isHidden",
            "setAlpha": "setAlpha:",
            "getAlpha": "alpha",
            "setBackgroundColor": "setBackgroundColor:",
            "setOnClickListener": "addTarget:action:forControlEvents:",
            "setOnLongClickListener": "addTarget:action:forControlEvents:",
            "invalidate": "setNeedsDisplay",
            "requestLayout": "setNeedsLayout",
            "getParent": "superview",
            "getContext": "viewController",
            "getWidth": "frame",
            "getHeight": "frame",
            "getTag": "tag",
            "setTag": "setTag:",
            "isEnabled": "isEnabled",
            "setEnabled": "setEnabled:"
        ]
        return mapping[name] ?? name
    }

    private func resolvedSelector(_ cls: AnyClass, name: String) -> Selector? {
        let candidates = [name, Self.mappedSelector(name), name + ":", "set" + name.prefix(1).uppercased() + String(name.dropFirst()) + ":"]
        for candidate in candidates {
            let sel = NSSelectorFromString(candidate)
            if class_getInstanceMethod(cls, sel) != nil || class_getClassMethod(cls, sel) != nil {
                return sel
            }
        }
        return nil
    }


    /// Maps Android class names that appear in plugins to the closest iOS class.
    public static func mappedClassName(_ name: String) -> String {
        let mapping: [String: String] = [
            "android.view.View": "UIView",
            "android.app.Activity": "UIViewController",
            "android.content.Context": "UIViewController",
            "android.widget.TextView": "UILabel",
            "android.widget.ImageView": "UIImageView",
            "android.widget.FrameLayout": "UIView",
            "android.widget.LinearLayout": "UIView",
            "android.widget.ScrollView": "UIScrollView",
            "android.widget.EditText": "UITextField",
            "android.view.ViewGroup": "UIView",
            "android.content.Intent": "NSURL",
            "org.telegram.ui.ActionBar.AlertDialog": "UIAlertController",
            "org.telegram.ui.ActionBar.AlertDialog$Builder": "UIAlertController",
            "org.telegram.ui.ActionBar.BaseFragment": "UIViewController",
            "org.telegram.ui.LaunchActivity": "UIApplication",
            "org.telegram.messenger.UserConfig": "NSUserDefaults",
            "org.telegram.messenger.AndroidUtilities": "UIView",
            "org.telegram.ui.Components.BulletinFactory": "UIView"
        ]
        return mapping[name] ?? name
    }

    public func install(className rawClassName: String, selector: String, callbacks: [String: String], filters: [[String: Any]], beforeFilters: [[String: Any]] = [], afterFilters: [[String: Any]] = [], isClassMethod: Bool = false) -> String? {
        guard let forwardIMP = self.forwardIMP else {
            PluginLog.log("Objective-C forwarding is unavailable in this process", level: .warning)
            return nil
        }
        let className = Self.mappedClassName(rawClassName)
        guard let cls = NSClassFromString(className) else {
            PluginLog.log("hook target class \(className) does not exist in Objective-C", level: .warning)
            return nil
        }
        let selectorName = selector
        let sel = self.resolvedSelector(cls, name: selectorName)
        guard let sel else {
            PluginLog.log("hook target \(className).\(selectorName) does not exist", level: .warning)
            return nil
        }
        var method: Method? = class_getInstanceMethod(cls, sel)
        var targetClass: AnyClass = cls
        if method == nil {
            method = class_getClassMethod(cls, sel)
            targetClass = object_getClass(cls) ?? cls
        }
        guard let method = method else {
            PluginLog.log("hook target \(className).\(selectorName) does not exist", level: .warning)
            return nil
        }
        let resolvedSelectorName = NSStringFromSelector(sel)

        self.lock.lock()
        let key = className + "|" + resolvedSelectorName
        if let existing = self.entries[key] {
            self.lock.unlock()
            return existing.handle
        }
        let handle = "hook-" + UUID().uuidString
        let entry = HookEntry(
            handle: handle,
            className: className,
            selectorName: resolvedSelectorName,
            method: method,
            originalIMP: method_getImplementation(method),
            callbacks: callbacks,
            filters: filters,
            beforeFilters: beforeFilters,
            afterFilters: afterFilters
        )
        self.entries[key] = entry
        self.byHandle[handle] = entry
        self.lock.unlock()

        self.ensureForwarding(on: targetClass)
        method_setImplementation(method, forwardIMP)
        return handle
    }

    public func uninstall(handle: String) {
        self.lock.lock()
        guard let entry = self.byHandle.removeValue(forKey: handle) else {
            self.lock.unlock()
            return
        }
        let key = entry.className + "|" + entry.selectorName
        self.entries.removeValue(forKey: key)
        method_setImplementation(entry.method, entry.originalIMP)
        self.lock.unlock()
    }

    public func hasHook(className: String, selector: String) -> Bool {
        self.lock.lock()
        defer { self.lock.unlock() }
        return self.entries[Self.mappedClassName(className) + "|" + selector] != nil
    }

    private func ensureForwarding(on cls: AnyClass) {
        let key = NSStringFromClass(cls)
        self.lock.lock()
        if self.forwardingInstalled.contains(key) {
            self.lock.unlock()
            return
        }
        self.forwardingInstalled.insert(key)
        self.lock.unlock()

        let selector = NSSelectorFromString("forwardInvocation:")
        let block: @convention(block) (AnyObject, AnyObject) -> Void = { [weak self] target, invocation in
            self?.handleForward(target: target, invocation: PluginInvocationFromObject(invocation))
        }
        let imp = imp_implementationWithBlock(block)
        if class_addMethod(cls, selector, imp, "v@:@") {
            return
        }
        if let method = class_getInstanceMethod(cls, selector) {
            self.lock.lock()
            self.originalForward[key] = method_getImplementation(method)
            self.lock.unlock()
            method_setImplementation(method, imp)
        }
    }

    // -- Forwarding ----------------------------------------------------------

    private func findEntry(target: AnyObject, selector: Selector) -> HookEntry? {
        self.lock.lock()
        let candidates = Array(self.entries.values)
        self.lock.unlock()
        let selectorName = NSStringFromSelector(selector)
        var current: AnyClass? = object_getClass(target)
        while let cls = current {
            let name = NSStringFromClass(cls)
            for entry in candidates where entry.selectorName == selectorName && entry.className == name {
                return entry
            }
            current = class_getSuperclass(cls)
        }
        return candidates.first { $0.selectorName == selectorName }
    }

    private func handleForward(target: AnyObject, invocation: PluginInvocation) {
        let selector = invocation.selector
        guard let entry = self.findEntry(target: target, selector: selector) else {
            self.callOriginalForward(target: target, invocation: invocation)
            return
        }

        let paramId = "param-" + UUID().uuidString
        let state = ParamState(invocation: invocation, entry: entry)
        self.lock.lock()
        self.params[paramId] = state
        self.lock.unlock()

        let parameter = self.buildParam(id: paramId, target: target, invocation: invocation, entry: entry, result: nil)
        if !entry.beforeFilters.isEmpty, !self.filtersMatch(entry.beforeFilters, parameter: parameter) {
            self.forwardOriginalMethod(entry: entry, invocation: invocation)
            self.lock.lock()
            self.params.removeValue(forKey: paramId)
            self.lock.unlock()
            return
        }
        if let before = entry.callbacks["before"] {
            _ = try? PythonRuntime.shared.invoke(callback: before, arguments: [parameter])
        }
        if state.result == nil, !state.originalRan, let replace = entry.callbacks["replace"] {
            if let value = try? PythonRuntime.shared.invoke(callback: replace, arguments: [parameter]) {
                if !(value is NSNull) {
                    state.result = value
                    self.applyResult(state: state, value: value)
                }
            }
        }
        if state.result == nil && !state.originalRan && !state.skipped {
            self.forwardOriginalMethod(entry: entry, invocation: invocation)
            if let after = entry.callbacks["after"] {
                let result = self.readResult(invocation: invocation)
                let afterParameter = self.buildParam(id: paramId, target: target, invocation: invocation, entry: entry, result: result)
                if entry.afterFilters.isEmpty || self.filtersMatch(entry.afterFilters, parameter: afterParameter, hasResult: true) {
                    _ = try? PythonRuntime.shared.invoke(callback: after, arguments: [afterParameter])
                    if let value = state.result {
                        self.applyResult(state: state, value: value)
                    }
                }
            }
        }

        self.lock.lock()
        self.params.removeValue(forKey: paramId)
        self.lock.unlock()
    }

    private func forwardOriginalMethod(entry: HookEntry, invocation: PluginInvocation) {
        self.lock.lock()
        method_setImplementation(entry.method, entry.originalIMP)
        self.lock.unlock()
        invocation.invoke()
        self.lock.lock()
        if let forward = self.forwardIMP {
            method_setImplementation(entry.method, forward)
        }
        self.lock.unlock()
    }

    private func callOriginalForward(target: AnyObject, invocation: PluginInvocation) {
        let key: String
        if let cls = object_getClass(target) {
            key = NSStringFromClass(cls)
        } else {
            key = String(describing: type(of: target))
        }
        self.lock.lock()
        let original = self.originalForward[key]
        self.lock.unlock()
        if let original {
            typealias ForwardFunction = @convention(c) (AnyObject, Selector, AnyObject) -> Void
            let function = unsafeBitCast(original, to: ForwardFunction.self)
            function(target, NSSelectorFromString("forwardInvocation:"), invocation.rawInvocation as AnyObject)
        } else if let object = target as? NSObject {
            object.doesNotRecognizeSelector(invocation.selector)
        }
    }

    // -- Param ---------------------------------------------------------------

    private func filtersMatch(_ filters: [[String: Any]], parameter: [String: Any], hasResult: Bool = false) -> Bool {
        let arguments = (parameter["args"] as? [Any]) ?? []
        let result: Any = parameter["result"] ?? NSNull()
        for filter in filters {
            let type = (filter["type"] as? String) ?? ""
            let index = (filter["arg_index"] as? NSNumber)?.intValue
            let expected = filter["object"]
            let expectedClass = filter["instance_of"] as? String

            switch type {
            case "or":
                let children = (filter["or"] as? [[String: Any]]) ?? []
                if children.isEmpty {
                    return false
                }
                if !children.contains(where: {
                    self.filtersMatch([$0], parameter: parameter, hasResult: hasResult)
                }) {
                    return false
                }
            case "condition":
                let expression = (filter["expression"] as? String) ?? (filter["condition"] as? String) ?? ""
                if expression.isEmpty {
                    return false
                }
                var context: [String: Any] = [
                    "param": parameter,
                    "object": expected ?? NSNull()
                ]
                context["result"] = hasResult ? result : NSNull()
                let value = try? PythonRuntime.shared.call(
                    "evaluate_condition",
                    [expression, PluginJSON.encodeString(context)]
                )
                if (value as? Bool) != true {
                    return false
                }
            case "argument_is_null", "argument_not_null", "argument_is_true",
                 "argument_is_false", "argument_is_instance_of", "argument_equal",
                 "argument_not_equal":
                guard let index, index >= 0, index < arguments.count else {
                    return false
                }
                let argument = arguments[index]
                switch type {
                case "argument_is_null":
                    if !(argument is NSNull) { return false }
                case "argument_not_null":
                    if argument is NSNull { return false }
                case "argument_is_true":
                    guard let number = argument as? NSNumber,
                          CFGetTypeID(number) == CFBooleanGetTypeID(),
                          number.boolValue else { return false }
                case "argument_is_false":
                    guard let number = argument as? NSNumber,
                          CFGetTypeID(number) == CFBooleanGetTypeID(),
                          !number.boolValue else { return false }
                case "argument_is_instance_of":
                    guard let expectedClass, Self.value(argument, isInstanceOf: expectedClass) else {
                        return false
                    }
                case "argument_equal":
                    if !Self.valuesEqual(argument, expected) { return false }
                case "argument_not_equal":
                    if Self.valuesEqual(argument, expected) { return false }
                default:
                    break
                }
            case "result_is_null", "result_not_null", "result_is_true",
                 "result_is_false", "result_is_instance_of", "result_equal",
                 "result_not_equal":
                guard hasResult else {
                    return false
                }
                switch type {
                case "result_is_null":
                    if !(result is NSNull) { return false }
                case "result_not_null":
                    if result is NSNull { return false }
                case "result_is_true":
                    guard let number = result as? NSNumber,
                          CFGetTypeID(number) == CFBooleanGetTypeID(),
                          number.boolValue else { return false }
                case "result_is_false":
                    guard let number = result as? NSNumber,
                          CFGetTypeID(number) == CFBooleanGetTypeID(),
                          !number.boolValue else { return false }
                case "result_is_instance_of":
                    guard let expectedClass, Self.value(result, isInstanceOf: expectedClass) else {
                        return false
                    }
                case "result_equal":
                    if !Self.valuesEqual(result, expected) { return false }
                case "result_not_equal":
                    if Self.valuesEqual(result, expected) { return false }
                default:
                    break
                }
            default:
                break
            }
        }
        return true
    }

    private static func valuesEqual(_ left: Any, _ right: Any?) -> Bool {
        let leftIsNull = left is NSNull
        let rightIsNull = right == nil || right is NSNull
        if leftIsNull || rightIsNull {
            return leftIsNull && rightIsNull
        }
        if let leftNumber = left as? NSNumber, let rightNumber = right as? NSNumber {
            return leftNumber.doubleValue == rightNumber.doubleValue
        }
        if let leftString = left as? String, let rightString = right as? String {
            return leftString == rightString
        }
        return Self.text(left) == Self.text(right)
    }

    private static func text(_ value: Any?) -> String {
        guard let value else { return "nil" }
        if value is NSNull { return "null" }
        if let number = value as? NSNumber { return number.stringValue }
        if let string = value as? String { return string }
        return String(describing: value)
    }

    private static func value(_ value: Any, isInstanceOf rawClassName: String) -> Bool {
        if value is NSNull { return false }
        let className = mappedClassName(rawClassName)
        if let dictionary = value as? [String: Any], let actual = dictionary["__class__"] as? String {
            if actual == rawClassName || actual == className { return true }
            if let expected = NSClassFromString(className), let actualClass = NSClassFromString(actual) {
                return actualClass == expected || class_getSuperclass(actualClass).map { $0 == expected } == true
            }
            return false
        }
        if let object = value as? NSObject, let expected = NSClassFromString(className) {
            return object.isKind(of: expected)
        }
        return false
    }

    private func buildParam(id: String, target: AnyObject, invocation: PluginInvocation, entry: HookEntry, result: Any?) -> [String: Any] {
        let signature = invocation.methodSignature
        var arguments: [Any] = []
        for index in 2 ..< signature.numberOfArguments {
            arguments.append(self.readArgument(invocation: invocation, index: index, type: signature.getArgumentType(at: index)))
        }
        let descriptor = PluginHostAPI.shared.descriptor(for: target)
        var value: [String: Any] = [
            "__param__": true,
            "id": id,
            "this": descriptor,
            "thisObject": descriptor,
            "args": arguments,
            "selector": entry.selectorName,
            "class": entry.className
        ]
        if let result {
            value["result"] = self.jsonValue(result)
        }
        return value
    }

    private func readArgument(invocation: PluginInvocation, index: Int, type: UnsafePointer<CChar>) -> Any {
        let encoding = String(cString: type)
        if encoding.hasPrefix("@") {
            var object: AnyObject?
            withUnsafeMutablePointer(to: &object) { invocation.getArgument(UnsafeMutableRawPointer($0), at: index) }
            if let object {
                return PluginHostAPI.shared.descriptor(for: object)
            }
            return NSNull()
        }
        if encoding == "i" || encoding == "I" {
            var value: Int32 = 0
            withUnsafeMutablePointer(to: &value) { invocation.getArgument(UnsafeMutableRawPointer($0), at: index) }
            return Int(value)
        }
        if encoding == "q" || encoding == "Q" || encoding == "l" || encoding == "L" {
            var value: Int64 = 0
            withUnsafeMutablePointer(to: &value) { invocation.getArgument(UnsafeMutableRawPointer($0), at: index) }
            return value
        }
        if encoding == "B" || encoding == "c" || encoding == "C" {
            var value: Int8 = 0
            withUnsafeMutablePointer(to: &value) { invocation.getArgument(UnsafeMutableRawPointer($0), at: index) }
            return value != 0
        }
        if encoding == "d" {
            var value: Double = 0
            withUnsafeMutablePointer(to: &value) { invocation.getArgument(UnsafeMutableRawPointer($0), at: index) }
            return value
        }
        if encoding == "f" {
            var value: Float = 0
            withUnsafeMutablePointer(to: &value) { invocation.getArgument(UnsafeMutableRawPointer($0), at: index) }
            return Double(value)
        }
        return NSNull()
    }

    private func readResult(invocation: PluginInvocation) -> Any? {
        let signature = invocation.methodSignature
        let encoding = String(cString: signature.methodReturnType)
        if encoding.hasPrefix("@") {
            var object: AnyObject?
            withUnsafeMutablePointer(to: &object) { invocation.getReturnValue(UnsafeMutableRawPointer($0)) }
            if let object {
                return PluginHostAPI.shared.descriptor(for: object)
            }
            return NSNull()
        }
        if encoding == "i" || encoding == "I" {
            var value: Int32 = 0
            withUnsafeMutablePointer(to: &value) { invocation.getReturnValue(UnsafeMutableRawPointer($0)) }
            return Int(value)
        }
        if encoding == "q" || encoding == "Q" || encoding == "l" || encoding == "L" {
            var value: Int64 = 0
            withUnsafeMutablePointer(to: &value) { invocation.getReturnValue(UnsafeMutableRawPointer($0)) }
            return value
        }
        if encoding == "B" || encoding == "c" || encoding == "C" {
            var value: Int8 = 0
            withUnsafeMutablePointer(to: &value) { invocation.getReturnValue(UnsafeMutableRawPointer($0)) }
            return value != 0
        }
        if encoding == "d" {
            var value: Double = 0
            withUnsafeMutablePointer(to: &value) { invocation.getReturnValue(UnsafeMutableRawPointer($0)) }
            return value
        }
        if encoding == "f" {
            var value: Float = 0
            withUnsafeMutablePointer(to: &value) { invocation.getReturnValue(UnsafeMutableRawPointer($0)) }
            return Double(value)
        }
        return nil
    }

    private func applyResult(state: ParamState, value: Any) {
        let signature = state.invocation.methodSignature
        let encoding = String(cString: signature.methodReturnType)
        if encoding.hasPrefix("@") {
            let object = PluginObjCRuntime.bridgeObject(value)
            var pointer = object
            withUnsafeMutablePointer(to: &pointer) { state.invocation.setReturnValue(UnsafeMutableRawPointer($0)) }
            return
        }
        if encoding == "i" || encoding == "I" {
            var number = Int32((value as? NSNumber)?.intValue ?? 0)
            withUnsafeMutablePointer(to: &number) { state.invocation.setReturnValue(UnsafeMutableRawPointer($0)) }
        } else if encoding == "q" || encoding == "Q" || encoding == "l" || encoding == "L" {
            var number = Int64((value as? NSNumber)?.int64Value ?? 0)
            withUnsafeMutablePointer(to: &number) { state.invocation.setReturnValue(UnsafeMutableRawPointer($0)) }
        } else if encoding == "B" || encoding == "c" || encoding == "C" {
            var number = Int8((value as? NSNumber)?.boolValue == true ? 1 : 0)
            withUnsafeMutablePointer(to: &number) { state.invocation.setReturnValue(UnsafeMutableRawPointer($0)) }
        } else if encoding == "d" {
            var number = (value as? NSNumber)?.doubleValue ?? 0
            withUnsafeMutablePointer(to: &number) { state.invocation.setReturnValue(UnsafeMutableRawPointer($0)) }
        } else if encoding == "f" {
            var number = Float((value as? NSNumber)?.doubleValue ?? 0)
            withUnsafeMutablePointer(to: &number) { state.invocation.setReturnValue(UnsafeMutableRawPointer($0)) }
        }
    }

    private static func bridgeObject(_ value: Any) -> AnyObject? {
        switch value {
        case is NSNull:
            return nil
        case let value as String:
            return value as NSString
        case let value as NSNumber:
            return value
        case let value as [String: Any]:
            if let handle = value["__handle__"] as? String, let object = PluginHostAPI.shared.object(for: handle) {
                return object
            }
            return value as NSDictionary
        case let value as [Any]:
            return value as NSArray
        default:
            return String(describing: value) as NSString
        }
    }

    private func jsonValue(_ value: Any) -> Any {
        if let object = value as? NSString {
            return object as String
        }
        if let object = value as? NSNumber {
            return object
        }
        if let object = value as? String {
            return object
        }
        if let object = value as? [String: Any] {
            return object
        }
        return String(describing: value)
    }

    func setParamResult(id: String, value: Any) -> Bool {
        self.lock.lock()
        guard let state = self.params[id] else {
            self.lock.unlock()
            return false
        }
        state.result = value
        self.applyResult(state: state, value: value)
        self.lock.unlock()
        return true
    }

    func setParamArgument(id: String, index: Int, value: Any) -> Bool {
        self.lock.lock()
        guard let state = self.params[id] else {
            self.lock.unlock()
            return false
        }
        let signature = state.invocation.methodSignature
        let argumentIndex = index + 2
        guard argumentIndex < signature.numberOfArguments else {
            self.lock.unlock()
            return false
        }
        let encoding = String(cString: signature.getArgumentType(at: argumentIndex))
        if encoding.hasPrefix("@") {
            var object = PluginObjCRuntime.bridgeObject(value)
            withUnsafeMutablePointer(to: &object) { state.invocation.setArgument(UnsafeMutableRawPointer($0), at: argumentIndex) }
        } else if encoding == "i" || encoding == "I" {
            var number = Int32((value as? NSNumber)?.intValue ?? 0)
            withUnsafeMutablePointer(to: &number) { state.invocation.setArgument(UnsafeMutableRawPointer($0), at: argumentIndex) }
        } else if encoding == "q" || encoding == "Q" || encoding == "l" || encoding == "L" {
            var number = Int64((value as? NSNumber)?.int64Value ?? 0)
            withUnsafeMutablePointer(to: &number) { state.invocation.setArgument(UnsafeMutableRawPointer($0), at: argumentIndex) }
        } else if encoding == "B" || encoding == "c" || encoding == "C" {
            var number = Int8((value as? NSNumber)?.boolValue == true ? 1 : 0)
            withUnsafeMutablePointer(to: &number) { state.invocation.setArgument(UnsafeMutableRawPointer($0), at: argumentIndex) }
        } else if encoding == "d" {
            var number = (value as? NSNumber)?.doubleValue ?? 0
            withUnsafeMutablePointer(to: &number) { state.invocation.setArgument(UnsafeMutableRawPointer($0), at: argumentIndex) }
        } else if encoding == "f" {
            var number = Float((value as? NSNumber)?.doubleValue ?? 0)
            withUnsafeMutablePointer(to: &number) { state.invocation.setArgument(UnsafeMutableRawPointer($0), at: argumentIndex) }
        }
        self.lock.unlock()
        return true
    }

    func setParamExtra(id: String, key: String, value: Any) -> Bool {
        self.lock.lock()
        guard let state = self.params[id] else {
            self.lock.unlock()
            return false
        }
        state.extras[key] = value
        self.lock.unlock()
        return true
    }

    /// Runs the original implementation of a hooked method for a live call.
    /// Partial hooks (`ExteraHook`/`Interceptor`) use it for `chain.proceed()`:
    /// the original runs exactly once, with the arguments the plugin supplied,
    /// and the forwarded implementation is restored afterwards.
    func proceed(id: String, arguments: [Any]?) -> Any? {
        self.lock.lock()
        guard let state = self.params[id] else {
            self.lock.unlock()
            return nil
        }
        state.originalRan = true
        self.lock.unlock()

        if let arguments {
            for (index, value) in arguments.enumerated() {
                _ = self.setParamArgument(id: id, index: index, value: value)
            }
        }
        self.forwardOriginalMethod(entry: state.entry, invocation: state.invocation)
        return self.readResult(invocation: state.invocation)
    }

    /// Marks a live call as handled without running the original implementation.
    /// `proceed()` sets the final result; `skip()` is what a partial hook uses
    /// when the plugin chose not to call `proceed()` at all (Android's "not
    /// calling proceed skips the instruction").
    func skip(id: String) -> Bool {
        self.lock.lock()
        guard let state = self.params[id] else {
            self.lock.unlock()
            return false
        }
        state.skipped = true
        self.lock.unlock()
        return true
    }

    func object(for handle: String) -> AnyObject? {
        return PluginHostAPI.shared.object(for: handle)
    }

    /// Calls an Objective-C selector on a handle with up to two object/number arguments.
    func callObject(handle: String, selector: String, arguments: [Any]) -> Any? {
        guard let object = PluginHostAPI.shared.object(for: handle) as? NSObject else {
            return nil
        }
        let sel: Selector
        if object.responds(to: NSSelectorFromString(selector)) {
            sel = NSSelectorFromString(selector)
        } else if object.responds(to: NSSelectorFromString(Self.mappedSelector(selector))) {
            sel = NSSelectorFromString(Self.mappedSelector(selector))
        } else if object.responds(to: NSSelectorFromString(selector + ":")) {
            sel = NSSelectorFromString(selector + ":")
        } else {
            return nil
        }
        switch arguments.count {
        case 0:
            return object.perform(sel)?.takeUnretainedValue()
        case 1:
            return object.perform(sel, with: PluginObjCRuntime.bridgeObject(arguments[0]))?.takeUnretainedValue()
        case 2:
            return object.perform(sel, with: PluginObjCRuntime.bridgeObject(arguments[0]), with: PluginObjCRuntime.bridgeObject(arguments[1]))?.takeUnretainedValue()
        default:
            return nil
        }
    }

    func getProperty(handle: String, name: String) -> Any? {
        guard let object = PluginHostAPI.shared.object(for: handle) as? NSObject else {
            return nil
        }
        return object.value(forKey: name)
    }

    func setProperty(handle: String, name: String, value: Any) -> Bool {
        guard let object = PluginHostAPI.shared.object(for: handle) as? NSObject else {
            return false
        }
        object.setValue(PluginObjCRuntime.bridgeObject(value), forKey: name)
        return true
    }
}



