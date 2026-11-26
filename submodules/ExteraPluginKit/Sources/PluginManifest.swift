import Foundation

/// Metadata of one `.plugin` file.
///
/// exteraGram reads the top-level `__id__`, `__name__`, ... assignments from the
/// Python source without executing it. The fast path here scans the same
/// assignments from Swift; the embedded interpreter provides the authoritative
/// parse through `_extera_runtime.parse_metadata` when it is available.
public struct PluginManifest: Equatable, Sendable {
    public var id: String
    public var name: String
    public var description: String
    public var author: String
    public var version: String
    public var icon: String?
    public var appVersionRequirement: String?
    public var sdkVersionRequirement: String?
    public var requirements: [String]
    public var category: String?

    public init(
        id: String,
        name: String,
        description: String = "",
        author: String = "",
        version: String = "1.0",
        icon: String? = nil,
        appVersionRequirement: String? = nil,
        sdkVersionRequirement: String? = nil,
        requirements: [String] = [],
        category: String? = nil
    ) {
        self.id = id
        self.name = name
        self.description = description
        self.author = author
        self.version = version
        self.icon = icon
        self.appVersionRequirement = appVersionRequirement
        self.sdkVersionRequirement = sdkVersionRequirement
        self.requirements = requirements
        self.category = category
    }
}

public enum PluginManifestError: Error, CustomStringConvertible, Sendable {
    case notText
    case tooLarge
    case missingIdentifier
    case missingName
    case invalidIdentifier(String)
    case invalidVersion(String)
    case unsupportedAppVersion(required: String, actual: String)
    case unsupportedSDKVersion(required: String, actual: String)

    public var description: String {
        switch self {
        case .notText:
            return "the file is not UTF-8 text, so it cannot be a plugin"
        case .tooLarge:
            return "the file is larger than 64 MB"
        case .missingIdentifier:
            return "__id__ is required"
        case .missingName:
            return "__name__ is required"
        case let .invalidIdentifier(value):
            return "plugin __id__ \"\(value)\" must be 2-32 characters of latin letters, digits, _ or -"
        case let .invalidVersion(value):
            return "invalid version requirement: \(value)"
        case let .unsupportedAppVersion(required, actual):
            return "plugin requires app version \(required), this build is \(actual)"
        case let .unsupportedSDKVersion(required, actual):
            return "plugin requires SDK \(required), this runtime is \(actual)"
        }
    }
}

public enum PluginManifestParser {
    public static let maximumFileSize = 64 * 1024 * 1024

    private static let allowedKeys: Set<String> = [
        "__id__", "__name__", "__description__", "__author__", "__version__",
        "__icon__", "__min_version__", "__requirements__", "__app_version__",
        "__sdk_version__", "__category__"
    ]

    /// Parses the manifest from a file, without executing it.
    public static func parse(fileAt url: URL) throws -> PluginManifest {
        let attributes = try? FileManager.default.attributesOfItem(atPath: url.path)
        if let size = attributes?[.size] as? NSNumber, size.int64Value > Int64(maximumFileSize) {
            throw PluginManifestError.tooLarge
        }
        guard let data = try? Data(contentsOf: url), let source = String(data: data, encoding: .utf8) else {
            throw PluginManifestError.notText
        }
        return try parse(source: source)
    }

    public static func parse(source: String) throws -> PluginManifest {
        let values = topLevelAssignments(in: source)
        guard let identifier = values["id"], !identifier.isEmpty else {
            throw PluginManifestError.missingIdentifier
        }
        guard let name = values["name"], !name.isEmpty else {
            throw PluginManifestError.missingName
        }
        guard isValid(identifier: identifier) else {
            throw PluginManifestError.invalidIdentifier(identifier)
        }

        var appVersion = values["app_version"]
        if appVersion == nil, let minimum = values["min_version"] {
            appVersion = ">=" + minimum
        }

        let requirements = splitRequirements(values["requirements"] ?? "")

        return PluginManifest(
            id: identifier,
            name: name,
            description: values["description"] ?? "",
            author: values["author"] ?? "",
            version: values["version"] ?? "1.0",
            icon: values["icon"].flatMap { $0.isEmpty ? nil : $0 },
            appVersionRequirement: appVersion,
            sdkVersionRequirement: values["sdk_version"],
            requirements: requirements,
            category: values["category"]
        )
    }

    /// Splits `__requirements__` on commas that start a new requirement.
    /// A comma inside a version range (`pkg>=1,<2`) is not a separator.
    private static func splitRequirements(_ value: String) -> [String] {
        var result: [String] = []
        var current = ""
        let characters = Array(value)
        var index = 0
        while index < characters.count {
            let character = characters[index]
            if character == "\n" || character == "," {
                var next = index + 1
                while next < characters.count, characters[next] == " " || characters[next] == "\t" {
                    next += 1
                }
                var nameEnd = next
                while nameEnd < characters.count {
                    let c = characters[nameEnd]
                    if c.isLetter || c.isNumber || c == "_" || c == "." || c == "-" {
                        nameEnd += 1
                    } else {
                        break
                    }
                }
                var after = nameEnd
                while after < characters.count, characters[after] == " " || characters[after] == "\t" {
                    after += 1
                }
                let startsNew = nameEnd > next && (after >= characters.count || "<>=!~".contains(characters[after]))
                if startsNew {
                    let item = current.trimmingCharacters(in: .whitespacesAndNewlines)
                    if !item.isEmpty {
                        result.append(item)
                    }
                    current = ""
                } else {
                    current.append(character)
                }
            } else {
                current.append(character)
            }
            index += 1
        }
        let item = current.trimmingCharacters(in: .whitespacesAndNewlines)
        if !item.isEmpty {
            result.append(item)
        }
        return result
    }

    public static func isValid(identifier: String) -> Bool {
        guard identifier.count >= 2, identifier.count <= 32 else {
            return false
        }
        guard let first = identifier.unicodeScalars.first,
              CharacterSet.letters.contains(first),
              first.isASCII else {
            return false
        }
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        return identifier.unicodeScalars.allSatisfy { allowed.contains($0) }
    }

    /// Scans top-level `__key__ = value` assignments.
    ///
    /// It understands single-line strings, triple-quoted strings, parenthesised
    /// concatenations and lists of strings - the shapes a plugin header uses.
    /// Anything else is skipped, matching the Python metadata reader, which
    /// also ignores statements it cannot evaluate.
    public static func topLevelAssignments(in source: String) -> [String: String] {
        let characters = Array(source)
        var index = 0
        var values: [String: String] = [:]
        let count = characters.count

        func isIdentifierStart(_ character: Character) -> Bool {
            return character == "_" || character.isLetter
        }

        func isIdentifierCharacter(_ character: Character) -> Bool {
            return character == "_" || character.isLetter || character.isNumber
        }

        func skipSpaces(_ position: inout Int) {
            while position < count, characters[position] == " " || characters[position] == "\t" {
                position += 1
            }
        }

        func readIdentifier(_ position: inout Int) -> String? {
            guard position < count, isIdentifierStart(characters[position]) else {
                return nil
            }
            let start = position
            position += 1
            while position < count, isIdentifierCharacter(characters[position]) {
                position += 1
            }
            return String(characters[start ..< position])
        }

        func readString(_ position: inout Int) -> String? {
            guard position < count, characters[position] == "\"" || characters[position] == "'" else {
                return nil
            }
            let quote = characters[position]
            let triple = position + 2 < count && characters[position + 1] == quote && characters[position + 2] == quote
            let delimiter = triple ? String(repeating: String(quote), count: 3) : String(quote)
            position += delimiter.count

            var result = ""
            while position < count {
                if triple {
                    if position + 2 < count,
                       characters[position] == quote,
                       characters[position + 1] == quote,
                       characters[position + 2] == quote {
                        position += 3
                        return result
                    }
                } else if characters[position] == quote {
                    position += 1
                    return result
                }

                let character = characters[position]
                if character == "\\", position + 1 < count {
                    let next = characters[position + 1]
                    switch next {
                    case "n": result.append("\n")
                    case "t": result.append("\t")
                    case "r": result.append("\r")
                    case "\\": result.append("\\")
                    case "\"": result.append("\"")
                    case "'": result.append("'")
                    default: result.append(next)
                    }
                    position += 2
                    continue
                }
                result.append(character)
                position += 1
            }
            return result
        }

        func skipLine(_ position: inout Int) {
            while position < count, characters[position] != "\n" {
                position += 1
            }
            if position < count {
                position += 1
            }
        }

        func skipBracketed(_ position: inout Int, open: Character, close: Character) {
            var depth = 0
            while position < count {
                let character = characters[position]
                if character == "\"" || character == "'" {
                    _ = readString(&position)
                    continue
                }
                if character == open {
                    depth += 1
                } else if character == close {
                    depth -= 1
                    if depth == 0 {
                        position += 1
                        return
                    }
                }
                position += 1
            }
        }

        func readValue(_ position: inout Int) -> String? {
            skipSpaces(&position)
            if position >= count {
                return nil
            }
            if characters[position] == "(" {
                position += 1
                var pieces: [String] = []
                while position < count, characters[position] != ")" {
                    skipSpaces(&position)
                    if position < count, characters[position] == "{" {
                        skipBracketed(&position, open: "{", close: "}")
                        continue
                    }
                    if let piece = readString(&position) {
                        pieces.append(piece)
                    } else {
                        position += 1
                    }
                }
                if position < count { position += 1 }
                return pieces.joined()
            }
            if characters[position] == "[" {
                var items: [String] = []
                position += 1
                while position < count, characters[position] != "]" {
                    skipSpaces(&position)
                    if let item = readString(&position) {
                        items.append(item)
                    } else {
                        position += 1
                    }
                }
                if position < count { position += 1 }
                return items.joined(separator: ",")
            }
            return readString(&position)
        }

        while index < count {
            let lineStart = index
            skipSpaces(&index)
            guard index < count, isIdentifierStart(characters[index]) else {
                index = lineStart
                skipLine(&index)
                continue
            }

            let column = index - lineStart
            guard let identifier = readIdentifier(&index) else {
                skipLine(&index)
                continue
            }
            skipSpaces(&index)
            guard index < count, characters[index] == "=" else {
                skipLine(&index)
                continue
            }
            index += 1
            guard column == 0, allowedKeys.contains(identifier) else {
                skipLine(&index)
                continue
            }
            if let value = readValue(&index) {
                let key = String(identifier.dropFirst(2).dropLast(2))
                values[key] = value
            }
            index = min(max(index, lineStart + 1), count)
            skipLine(&index)
        }

        return values
    }
}

/// Compares version strings the way exteraGram does: missing components are zero.
public func comparePluginVersions(_ lhs: String, _ rhs: String) -> Int {
    let left = lhs.split(separator: ".").map { Int($0) ?? 0 }
    let right = rhs.split(separator: ".").map { Int($0) ?? 0 }
    let length = max(left.count, right.count)
    for index in 0 ..< length {
        let l = index < left.count ? left[index] : 0
        let r = index < right.count ? right[index] : 0
        if l < r { return -1 }
        if l > r { return 1 }
    }
    return 0
}

/// `>=13.0`, `<=1.2`, `==1.0`, `>1`, `<2`; a bare version means `>=`.
public func pluginVersionRequirementIsSatisfied(_ requirement: String, actual: String) throws -> Bool {
    var text = requirement.trimmingCharacters(in: .whitespaces)
    var comparison = ">="
    for candidate in [">=", "<=", "==", ">", "<"] where text.hasPrefix(candidate) {
        comparison = candidate
        text = String(text.dropFirst(candidate.count)).trimmingCharacters(in: .whitespaces)
        break
    }
    guard !text.isEmpty else {
        throw PluginManifestError.invalidVersion(requirement)
    }
    let order = comparePluginVersions(actual, text)
    switch comparison {
    case ">=": return order >= 0
    case "<=": return order <= 0
    case "==": return order == 0
    case ">": return order > 0
    case "<": return order < 0
    default: return false
    }
}
