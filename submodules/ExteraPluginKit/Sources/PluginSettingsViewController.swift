import Foundation
import UIKit

/// One plugin's settings screen.
///
/// Controls are the descriptors returned by `create_settings()`. A control's
/// value is read from and written to the Python settings store, and its
/// callbacks run in the plugin's lifecycle, exactly like the Android screen.
public final class PluginSettingsViewController: UITableViewController {
    private let pluginId: String?
    private let screenTitle: String?
    private var controls: [PluginSettingControl] = []
    private var values: [String: PluginSettingValue] = [:]
    private var loadError: String?
    private var translation: PluginSettingsTranslation?
    private var translateItem: UIBarButtonItem?
    private var reloadItem: UIBarButtonItem?
    private var resetItem: UIBarButtonItem?
    private var targetAlias: String?
    private var didScrollToAlias = false

    public convenience init(pluginId: String, alias: String? = nil) {
        self.init(pluginId: pluginId, controls: nil, title: nil, error: nil, alias: alias)
    }

    public init(pluginId: String?, controls: [PluginSettingControl]?, title: String?, error: String?, alias: String? = nil) {
        self.pluginId = pluginId
        self.screenTitle = title
        self.controls = controls ?? []
        self.loadError = error
        self.targetAlias = alias
        super.init(style: .insetGrouped)
        if let title {
            self.title = title
        }
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        if self.controls.isEmpty, let pluginId {
            let screen = PluginManager.shared.settingsScreen(pluginId: pluginId)
            self.controls = screen?.controls ?? []
            self.loadError = screen?.error
            self.title = screen?.title ?? PluginManager.shared.plugin(id: pluginId)?.name ?? "Plugin"
        }
        if let pluginId {
            self.readValues()
            let reload = UIBarButtonItem(
                title: "Reload", style: .plain, target: self, action: #selector(self.reloadPlugin)
            )
            self.reloadItem = reload
            let reset = UIBarButtonItem(
                image: UIImage(systemName: "trash"),
                style: .plain,
                target: self,
                action: #selector(self.resetSettings)
            )
            self.resetItem = reset
            reset.isEnabled = !self.values.isEmpty
            let translation = PluginSettingsTranslation.of(pluginId)
            translation.resetFailed()
            translation.onChange = { [weak self] failed in
                guard let self else {
                    return
                }
                self.checkTranslation()
                self.tableView.reloadData()
                if failed {
                    let message = translation.failureMessage
                    let alert = UIAlertController(
                        title: "Translation failed",
                        message: message ?? "The settings could not be translated.",
                        preferredStyle: .alert
                    )
                    alert.addAction(UIAlertAction(title: "OK", style: .default))
                    self.present(alert, animated: true)
                }
            }
            self.translation = translation
            self.updateTranslateItem()
            if (PluginManager.shared.plugin(id: pluginId)?.error) != nil {
                self.navigationItem.leftBarButtonItem = UIBarButtonItem(
                    title: "Details", style: .plain, target: self, action: #selector(self.showError)
                )
            }
        }
        self.checkTranslation()
    }

    private func updateTranslateItem() {
        guard let translation else {
            return
        }
        let item = UIBarButtonItem(
            image: UIImage(systemName: translation.enabled ? "character.bubble.fill" : "character.bubble"),
            style: .plain,
            target: self,
            action: #selector(self.toggleTranslation)
        )
        item.accessibilityLabel = translation.enabled ? "Show original" : "Translate"
        item.isEnabled = translation.isTranslatable || translation.enabled
        self.translateItem = item
        var items: [UIBarButtonItem] = []
        if translation.isTranslatable || translation.enabled {
            items.append(item)
        }
        if let reloadItem {
            items.append(reloadItem)
        }
        if let resetItem {
            items.append(resetItem)
        }
        self.navigationItem.rightBarButtonItems = items
    }

    @objc private func toggleTranslation() {
        guard let translation, !translation.isLoading else {
            return
        }
        translation.setEnabled(!translation.enabled)
    }

    private func updateTitle() {
        let original: String?
        if let screenTitle {
            original = screenTitle
        } else if let pluginId {
            original = PluginManager.shared.plugin(id: pluginId)?.name
        } else {
            original = nil
        }
        self.title = self.tr(original)
    }

    private func checkTranslation() {
        guard let translation else {
            return
        }
        var texts: [String] = []
        if let screenTitle {
            texts.append(screenTitle)
        } else if let pluginId, let name = PluginManager.shared.plugin(id: pluginId)?.name {
            texts.append(name)
        }
        for control in self.controls {
            texts.append(control.text)
            if let subtext = control.subtext {
                texts.append(subtext)
            }
            if let hint = control.hint {
                texts.append(hint)
            }
            texts.append(contentsOf: control.items)
            if let title = control.customTitle {
                texts.append(title)
            }
        }
        translation.check(texts)
        self.updateTranslateItem()
        self.updateTitle()
    }

    private func tr(_ text: String?) -> String? {
        return self.translation?.text(text) ?? text
    }

    public override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        self.scrollToTargetAliasIfNeeded()
    }

    private func scrollToTargetAliasIfNeeded() {
        guard !self.didScrollToAlias, let alias = self.targetAlias, !alias.isEmpty else {
            return
        }
        let parts = alias.split(separator: ":", omittingEmptySubsequences: true).map(String.init)
        guard let first = parts.first else {
            return
        }
        guard let index = self.controls.firstIndex(where: { $0.linkAlias == first }) else {
            return
        }
        if parts.count > 1, self.controls[index].callbacks["create_sub_fragment"] != nil {
            self.didScrollToAlias = true
            let remaining = parts.dropFirst().joined(separator: ":")
            self.openSubFragment(self.controls[index], remainingAlias: remaining)
            return
        }
        self.didScrollToAlias = true
        let indexPath = IndexPath(row: index, section: 0)
        self.tableView.scrollToRow(at: indexPath, at: .middle, animated: true)
        self.tableView.selectRow(at: indexPath, animated: true, scrollPosition: .middle)
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.3) { [weak self] in
            self?.tableView.deselectRow(at: indexPath, animated: true)
        }
    }

    private func readValues() {
        guard let pluginId else { return }
        for control in self.controls {
            guard let key = control.key else { continue }
            if let value = PluginManager.shared.settingValue(pluginId: pluginId, key: key) {
                if let parsed = PluginSettingValue(json: value) {
                    self.values[key] = parsed
                }
            }
        }
    }

    @objc private func showError() {
        guard let pluginId, let error = PluginManager.shared.plugin(id: pluginId)?.error else {
            return
        }
        let alert = UIAlertController(title: "Plugin error", message: error, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .default))
        self.present(alert, animated: true)
    }

    @objc private func reloadPlugin() {
        guard let pluginId else { return }
        PluginManager.shared.reload(pluginId: pluginId) { [weak self] _ in
            guard let self else { return }
            let screen = PluginManager.shared.settingsScreen(pluginId: pluginId)
            self.controls = screen?.controls ?? []
            self.readValues()
            self.resetItem?.isEnabled = !self.values.isEmpty
            self.checkTranslation()
            self.tableView.reloadData()
        }
    }

    @objc private func resetSettings() {
        guard let pluginId else {
            return
        }
        let alert = UIAlertController(
            title: "Reset settings?",
            message: "All values for this plugin will be cleared.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Reset", style: .destructive) { [weak self] _ in
            PluginManager.shared.resetSettings(pluginId: pluginId) { [weak self] _ in
                guard let self else {
                    return
                }
                let screen = PluginManager.shared.settingsScreen(pluginId: pluginId)
                self.controls = screen?.controls ?? []
                self.values.removeAll()
                self.readValues()
                self.resetItem?.isEnabled = !self.values.isEmpty
                self.checkTranslation()
                self.tableView.reloadData()
            }
        })
        self.present(alert, animated: true)
    }

    private func value(for control: PluginSettingControl) -> PluginSettingValue {
        if let key = control.key, let value = self.values[key] {
            return value
        }
        switch control.kind {
        case .toggle: return .bool(control.isDefaultOn)
        case .picker: return .int(control.defaultIndex)
        case .input, .editText: return .string(control.defaultText)
        default: return .string("")
        }
    }

    private func store(_ value: Any, for control: PluginSettingControl) {
        guard let pluginId, let key = control.key else { return }
        self.values[key] = PluginSettingValue(json: value) ?? .string("")
        self.resetItem?.isEnabled = true
        PluginManager.shared.setSettingValue(pluginId: pluginId, key: key, value: value)
        if let handle = control.callbacks["on_change"] {
            PluginManager.shared.invokeCallback(handle, arguments: [value])
        }
    }

    /// Reloads the descriptors after a change, the way Android's
    /// `setPluginSettingAndTriggerOnChange` calls `loadPluginSettings`: a
    /// plugin can add, remove or rename rows from its change callback.
    private func reloadSettingsScreen() {
        guard let pluginId, self.targetAlias == nil else {
            self.tableView.reloadData()
            return
        }
        let screen = PluginManager.shared.settingsScreen(pluginId: pluginId)
        self.controls = screen?.controls ?? []
        self.loadError = screen?.error
        if let title = screen?.title, !title.isEmpty {
            self.title = title
        }
        self.readValues()
        self.resetItem?.isEnabled = !self.values.isEmpty
        self.checkTranslation()
        self.tableView.reloadData()
    }

    private func invoke(_ control: PluginSettingControl, callback name: String, arguments: [Any] = []) {
        guard let handle = control.callbacks[name] else {
            return
        }
        PluginManager.shared.invokeCallback(handle, arguments: arguments)
    }

    private func openSubFragment(_ control: PluginSettingControl, remainingAlias: String? = nil) {
        guard let handle = control.callbacks["create_sub_fragment"] else {
            return
        }
        do {
            let value = try PythonRuntime.shared.invoke(callback: handle, arguments: [])
            if let list = value as? [Any] {
                let controls = list.compactMap { PluginSettingControl(json: $0) }
                let controller = PluginSettingsViewController(
                    pluginId: self.pluginId,
                    controls: controls,
                    title: self.tr(control.text),
                    error: nil,
                    alias: remainingAlias
                )
                self.navigationController?.pushViewController(controller, animated: true)
            }
        } catch {
            PluginLog.log("create_sub_fragment failed: \(error)", level: .error)
        }
    }

    // -- Table ---------------------------------------------------------------

    public override func numberOfSections(in tableView: UITableView) -> Int {
        return 1
    }

    public override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        return max(1, self.controls.count)
    }

    public override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        if let loadError, !loadError.isEmpty {
            return "The plugin did not load"
        }
        return self.tr(self.screenTitle)
    }

    public override func tableView(_ tableView: UITableView, titleForFooterInSection section: Int) -> String? {
        if let loadError, !loadError.isEmpty {
            return loadError
        }
        return nil
    }

    public override func tableView(_ tableView: UITableView, heightForRowAt indexPath: IndexPath) -> CGFloat {
        guard !self.controls.isEmpty else { return 44 }
        let control = self.controls[indexPath.row]
        switch control.kind {
        case .header: return 36
        case .divider: return 12
        case .text, .custom: return control.subtext == nil ? 48 : 62
        default: return 50
        }
    }

    public override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        guard !self.controls.isEmpty else {
            let cell = tableView.dequeueReusableCell(withIdentifier: "cell", for: indexPath)
            cell.textLabel?.text = loadError == nil ? "This plugin has no settings" : "Plugin error"
            cell.textLabel?.textColor = .secondaryLabel
            cell.selectionStyle = .none
            return cell
        }

        let control = self.controls[indexPath.row]
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
        cell.accessoryView = nil
        cell.accessoryType = .none
        cell.selectionStyle = .none
        cell.textLabel?.textColor = .label

        switch control.kind {
        case .header:
            cell.textLabel?.text = self.tr(control.text)?.uppercased()
            cell.textLabel?.font = .systemFont(ofSize: 13, weight: .medium)
            cell.textLabel?.textColor = .secondaryLabel

        case .divider:
            cell.backgroundColor = .clear
            cell.contentView.backgroundColor = .clear

        case .toggle:
            cell.textLabel?.text = self.tr(control.text)
            cell.detailTextLabel?.text = self.tr(control.subtext)
            cell.textLabel?.textColor = control.red ? .systemRed : .label
            let toggle = UISwitch()
            toggle.isOn = self.value(for: control).boolValue
            toggle.tag = indexPath.row
            toggle.addTarget(self, action: #selector(self.switchChanged(_:)), for: .valueChanged)
            cell.accessoryView = toggle
            cell.selectionStyle = .none

        case .picker:
            cell.textLabel?.text = self.tr(control.text)
            let index = min(max(self.value(for: control).intValue, 0), max(control.items.count - 1, 0))
            cell.detailTextLabel?.text = control.items.isEmpty ? self.tr(control.subtext) : self.tr(control.items[index])
            cell.accessoryType = .disclosureIndicator
            cell.selectionStyle = .default

        case .input, .editText:
            cell.textLabel?.text = self.tr(control.text.isEmpty ? control.hint : control.text)
            cell.detailTextLabel?.text = self.value(for: control).stringValue
            cell.accessoryType = .disclosureIndicator
            cell.selectionStyle = .default

        case .text:
            cell.textLabel?.text = self.tr(control.text)
            cell.detailTextLabel?.text = self.tr(control.subtext)
            if control.accent || control.red || control.callbacks["on_click"] != nil {
                cell.textLabel?.textColor = control.red ? .systemRed : (control.accent ? .systemBlue : .label)
            }
            cell.accessoryType = control.callbacks["on_click"] != nil || control.callbacks["create_sub_fragment"] != nil ? .disclosureIndicator : .none
            cell.selectionStyle = .default

        case .custom:
            let fallbackTitle: String
            if let factoryType = control.factoryType, !factoryType.isEmpty {
                fallbackTitle = "Custom control (\(factoryType))"
            } else {
                fallbackTitle = "Custom control"
            }
            cell.textLabel?.text = self.tr(control.customTitle ?? (control.text.isEmpty ? fallbackTitle : control.text))
            cell.detailTextLabel?.text = self.tr(control.subtext ?? (control.factoryHandlers.isEmpty ? nil : control.factoryHandlers.joined(separator: ", ")))
            if let viewSpec = control.viewSpec, let data = viewSpec.data(using: .utf8),
               let object = try? JSONSerialization.jsonObject(with: data),
               let spec = object as? [String: Any] {
                cell.accessoryView = self.customView(for: spec, control: control, index: indexPath.row)
            }
            cell.accessoryType = cell.accessoryView == nil && control.callbacks["on_click"] != nil ? .disclosureIndicator : .none
            cell.selectionStyle = .default
        }

        if let icon = control.icon {
            cell.imageView?.image = UIImage(systemName: PluginIcon.systemName(for: icon))
            cell.imageView?.tintColor = .systemBlue
        }
        return cell
    }

    public override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        guard indexPath.row < self.controls.count else { return }
        let control = self.controls[indexPath.row]

        switch control.kind {
        case .picker:
            guard !control.items.isEmpty else { return }
            let sheet = UIAlertController(title: self.tr(control.text), message: nil, preferredStyle: .actionSheet)
            for (index, item) in control.items.enumerated() {
                sheet.addAction(UIAlertAction(title: self.tr(item), style: .default, handler: { [weak self] _ in
                    self?.store(index, for: control)
                    self?.reloadSettingsScreen()
                }))
            }
            sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel))
            if let popover = sheet.popoverPresentationController {
                popover.sourceView = self.view
                popover.sourceRect = self.view.bounds
            }
            self.present(sheet, animated: true)

        case .input:
            let alert = UIAlertController(title: self.tr(control.text), message: self.tr(control.subtext), preferredStyle: .alert)
            alert.addTextField { field in
                field.text = self.value(for: control).stringValue
                field.placeholder = self.tr(control.hint ?? control.text)
            }
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
            alert.addAction(UIAlertAction(title: "Save", style: .default, handler: { [weak self, weak alert] _ in
                let text = alert?.textFields?.first?.text ?? ""
                self?.store(text, for: control)
                self?.reloadSettingsScreen()
            }))
            self.present(alert, animated: true)

        case .editText:
            let controller = PluginTextEditorViewController(
                title: self.tr(control.text) ?? control.text,
                text: self.value(for: control).stringValue,
                placeholder: self.tr(control.hint),
                multiline: control.multiline,
                maxLength: control.maxLength
            ) { [weak self] text in
                self?.store(text, for: control)
                self?.reloadSettingsScreen()
            }
            self.navigationController?.pushViewController(controller, animated: true)

        case .text:
            if control.callbacks["create_sub_fragment"] != nil {
                self.openSubFragment(control)
            } else {
                self.invoke(control, callback: "on_click", arguments: [NSNull()])
            }

        case .custom:
            if control.callbacks["create_sub_fragment"] != nil {
                self.openSubFragment(control)
            } else {
                self.invoke(control, callback: "on_click", arguments: [NSNull()])
            }

        default:
            break
        }
    }

    public override func tableView(_ tableView: UITableView, trailingSwipeActionsConfigurationForRowAt indexPath: IndexPath) -> UISwipeActionsConfiguration? {
        guard indexPath.row < self.controls.count else { return nil }
        let control = self.controls[indexPath.row]
        guard control.callbacks["on_long_click"] != nil else { return nil }
        let action = UIContextualAction(style: .normal, title: "More") { [weak self] _, _, completion in
            self?.invoke(control, callback: "on_long_click", arguments: [NSNull()])
            completion(true)
        }
        return UISwipeActionsConfiguration(actions: [action])
    }

    public override func tableView(_ tableView: UITableView, contextMenuConfigurationForRowAt indexPath: IndexPath, point: CGPoint) -> UIContextMenuConfiguration? {
        guard indexPath.row < self.controls.count else {
            return nil
        }
        let control = self.controls[indexPath.row]
        var actions: [UIAction] = []
        if let alias = control.linkAlias, !alias.isEmpty {
            actions.append(UIAction(
                title: "Copy setting link",
                image: UIImage(systemName: "link")
            ) { _ in
                UIPasteboard.general.string = alias
            })
        }
        if control.callbacks["on_long_click"] != nil {
            actions.append(UIAction(
                title: "More",
                image: UIImage(systemName: "ellipsis.circle")
            ) { [weak self] _ in
                self?.invoke(control, callback: "on_long_click", arguments: [NSNull()])
            })
        }
        guard !actions.isEmpty else {
            return nil
        }
        return UIContextMenuConfiguration(identifier: nil, previewProvider: nil) { _ in
            UIMenu(title: self.tr(control.text) ?? control.text, children: actions)
        }
    }

    @objc private func switchChanged(_ sender: UISwitch) {
        guard sender.tag < self.controls.count else { return }
        self.store(sender.isOn, for: self.controls[sender.tag])
        self.reloadSettingsScreen()
    }

    private func customView(for spec: [String: Any], control: PluginSettingControl, index: Int) -> UIView? {
        switch (spec["type"] as? String) ?? "" {
        case "switch":
            let toggle = UISwitch()
            toggle.isOn = (spec["value"] as? Bool) ?? control.isDefaultOn
            toggle.tag = index
            toggle.addTarget(self, action: #selector(self.customSwitchChanged(_:)), for: .valueChanged)
            return toggle
        case "slider":
            let slider = UISlider()
            slider.minimumValue = (spec["min"] as? NSNumber)?.floatValue ?? 0
            slider.maximumValue = (spec["max"] as? NSNumber)?.floatValue ?? 1
            slider.value = (spec["value"] as? NSNumber)?.floatValue ?? slider.minimumValue
            slider.tag = index
            slider.addTarget(self, action: #selector(self.customSliderChanged(_:)), for: .valueChanged)
            return slider
        case "button":
            let button = UIButton(type: .system)
            button.setTitle((spec["text"] as? String) ?? control.text, for: .normal)
            button.tag = index
            button.addTarget(self, action: #selector(self.customButtonTapped(_:)), for: .touchUpInside)
            return button
        case "textfield":
            let field = UITextField()
            field.text = (spec["value"] as? String) ?? control.defaultText
            field.placeholder = spec["hint"] as? String
            field.tag = index
            field.addTarget(self, action: #selector(self.customTextChanged(_:)), for: .editingChanged)
            field.widthAnchor.constraint(equalToConstant: 160).isActive = true
            return field
        default:
            return nil
        }
    }

    @objc private func customSwitchChanged(_ sender: UISwitch) {
        guard sender.tag < self.controls.count else { return }
        let control = self.controls[sender.tag]
        if control.key != nil {
            self.store(sender.isOn, for: control)
            self.reloadSettingsScreen()
        } else if let handle = control.callbacks["on_change"] {
            PluginManager.shared.invokeCallback(handle, arguments: [sender.isOn])
        }
    }

    @objc private func customSliderChanged(_ sender: UISlider) {
        guard sender.tag < self.controls.count else { return }
        let control = self.controls[sender.tag]
        if let handle = control.callbacks["on_change"] {
            PluginManager.shared.invokeCallback(handle, arguments: [Double(sender.value)])
        }
    }

    @objc private func customButtonTapped(_ sender: UIButton) {
        guard sender.tag < self.controls.count else { return }
        let control = self.controls[sender.tag]
        self.invoke(control, callback: "on_click", arguments: [NSNull()])
    }

    @objc private func customTextChanged(_ sender: UITextField) {
        guard sender.tag < self.controls.count else { return }
        let control = self.controls[sender.tag]
        if let handle = control.callbacks["on_change"] {
            PluginManager.shared.invokeCallback(handle, arguments: [sender.text ?? ""])
        }
    }
}

public final class PluginTextEditorViewController: UIViewController, UITextViewDelegate {
    private let textView = UITextView()
    private let placeholderLabel = UILabel()
    private let initialText: String
    private let placeholder: String?
    private let multiline: Bool
    private let maxLength: Int
    private let onSave: (String) -> Void

    public init(title: String, text: String, placeholder: String?, multiline: Bool, maxLength: Int, onSave: @escaping (String) -> Void) {
        self.initialText = text
        self.placeholder = placeholder
        self.multiline = multiline
        self.maxLength = maxLength
        self.onSave = onSave
        super.init(nibName: nil, bundle: nil)
        self.title = title
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.view.backgroundColor = .systemBackground
        self.textView.translatesAutoresizingMaskIntoConstraints = false
        self.textView.font = .preferredFont(forTextStyle: .body)
        self.textView.text = self.initialText
        self.textView.delegate = self
        self.textView.isScrollEnabled = self.multiline
        self.textView.autocapitalizationType = .sentences
        self.textView.textContainerInset = UIEdgeInsets(top: 12, left: 10, bottom: 12, right: 10)
        self.view.addSubview(self.textView)

        self.placeholderLabel.translatesAutoresizingMaskIntoConstraints = false
        self.placeholderLabel.text = self.placeholder
        self.placeholderLabel.textColor = .placeholderText
        self.placeholderLabel.isHidden = !self.initialText.isEmpty
        self.view.addSubview(self.placeholderLabel)

        NSLayoutConstraint.activate([
            self.textView.leadingAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.leadingAnchor, constant: 12),
            self.textView.trailingAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.trailingAnchor, constant: -12),
            self.textView.topAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.topAnchor, constant: 8),
            self.textView.bottomAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.bottomAnchor, constant: -8),
            self.placeholderLabel.leadingAnchor.constraint(equalTo: self.textView.leadingAnchor, constant: 15),
            self.placeholderLabel.topAnchor.constraint(equalTo: self.textView.topAnchor, constant: 12)
        ])

        self.navigationItem.rightBarButtonItem = UIBarButtonItem(title: "Save", style: .done, target: self, action: #selector(self.save))
        if !self.multiline {
            self.textView.isScrollEnabled = false
        }
    }

    public func textViewDidChange(_ textView: UITextView) {
        self.placeholderLabel.isHidden = !textView.text.isEmpty
        if textView.text.count > self.maxLength {
            textView.text = String(textView.text.prefix(self.maxLength))
        }
    }

    @objc private func save() {
        self.onSave(self.textView.text)
        self.navigationController?.popViewController(animated: true)
    }
}

enum PluginIcon {
    static func systemName(for value: String) -> String {
        let lower = value.lowercased()
        if lower.contains("settings") { return "gearshape" }
        if lower.contains("message") { return "bubble.left" }
        if lower.contains("user") { return "person" }
        if lower.contains("channel") { return "megaphone" }
        if lower.contains("theme") { return "paintpalette" }
        if lower.contains("plug") { return "puzzlepiece" }
        return "puzzlepiece.extension"
    }
}

