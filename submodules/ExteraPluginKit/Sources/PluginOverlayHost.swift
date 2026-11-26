import Foundation
import UIKit

/// Minimal bulletin surface used when the app has not installed a richer one.
///
/// A plugin's `BulletinHelper.show_info("...")` must show something even in a
/// standalone host. The overlay is a rounded label above the safe area, removed
/// after the requested duration; Telegram's own `UndoOverlayController` can
/// replace it by assigning `PluginHostAPI.shared.uiHost`.
public final class PluginOverlayHost: PluginUIHost, @unchecked Sendable {
    public static let shared = PluginOverlayHost()

    private init() {
    }

    public func showBulletin(kind: String, text: String, subtext: String?, duration: Int) {
        self.showBulletin(PluginBulletinSpec(
            kind: kind,
            text: text,
            subtext: subtext,
            duration: duration
        ))
    }

    public func showBulletin(_ spec: PluginBulletinSpec) {
        let message = spec.subtext.map { "\(spec.text)\n\($0)" } ?? spec.text
        DispatchQueue.main.async {
            guard let window = PluginOverlayHost.keyWindow() else {
                return
            }
            let container = UIStackView()
            container.axis = .vertical
            container.spacing = 8
            container.alignment = .center
            container.translatesAutoresizingMaskIntoConstraints = false
            container.backgroundColor = UIColor(white: 0.1, alpha: 0.92)
            container.layer.cornerRadius = 12
            container.layer.masksToBounds = true
            container.isLayoutMarginsRelativeArrangement = true
            container.layoutMargins = UIEdgeInsets(top: 9, left: 14, bottom: 9, right: 14)

            let label = UILabel()
            label.text = message
            label.numberOfLines = 0
            label.textAlignment = .center
            label.font = .systemFont(ofSize: 14, weight: .medium)
            label.textColor = .white
            container.addArrangedSubview(label)

            let dismissed = PluginValueBox(false)
            let didUndo = PluginValueBox(false)
            let dismiss: (Bool) -> Void = { callAction in
                if dismissed.get() {
                    return
                }
                dismissed.set(true)
                UIView.animate(withDuration: 0.2, animations: {
                    container.alpha = 0
                }, completion: { _ in
                    container.removeFromSuperview()
                })
                if callAction, let handle = spec.onAction {
                    _ = try? PythonRuntime.shared.invoke(callback: handle, arguments: [])
                }
            }

            if let undoText = spec.undoText {
                let button = PluginOverlayHost.makeButton(title: undoText, tint: .white)
                button.addAction(UIAction { _ in
                    didUndo.set(true)
                    if let handle = spec.onUndo {
                        _ = try? PythonRuntime.shared.invoke(callback: handle, arguments: [])
                    }
                    dismiss(false)
                }, for: .touchUpInside)
                container.addArrangedSubview(button)
            } else if let buttonText = spec.buttonText {
                let tint: UIColor
                switch spec.kind {
                case "error":
                    tint = .systemRed
                case "success":
                    tint = .systemGreen
                default:
                    tint = .systemBlue
                }
                let button = PluginOverlayHost.makeButton(title: buttonText, tint: tint)
                button.addAction(UIAction { _ in
                    if let handle = spec.onButton {
                        _ = try? PythonRuntime.shared.invoke(callback: handle, arguments: [])
                    }
                    dismiss(false)
                }, for: .touchUpInside)
                container.addArrangedSubview(button)
            }

            window.addSubview(container)

            NSLayoutConstraint.activate([
                container.centerXAnchor.constraint(equalTo: window.centerXAnchor),
                container.bottomAnchor.constraint(equalTo: window.safeAreaLayoutGuide.bottomAnchor, constant: -24),
                container.widthAnchor.constraint(lessThanOrEqualTo: window.widthAnchor, constant: -48)
            ])

            DispatchQueue.main.asyncAfter(deadline: .now() + Double(max(500, spec.duration)) / 1000.0) {
                dismiss(!didUndo.get())
            }
        }
    }

    private static func makeButton(title: String, tint: UIColor) -> UIButton {
        let button = UIButton(type: .system)
        button.setTitle(title, for: .normal)
        button.setTitleColor(tint, for: .normal)
        button.titleLabel?.font = .systemFont(ofSize: 14, weight: .semibold)
        return button
    }

    private static func keyWindow() -> UIWindow? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        return scenes.flatMap { $0.windows }.first { $0.isKeyWindow } ?? scenes.first?.windows.first
    }
}
