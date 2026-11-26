import UIKit

/// Shared UI for the install flows: an encrypted `.elyx` archive asks for its
/// password and retries the same install.
public enum PluginInstallUI {
    public static func isPasswordError(_ message: String?) -> Bool {
        guard let message = message?.lowercased() else {
            return false
        }
        return message.contains("password") || message.contains("encrypted")
    }

    public static func presentPasswordPrompt(
        from presenter: UIViewController,
        title: String = "Archive password",
        onInstall: @escaping (String) -> Void
    ) {
        let alert = UIAlertController(
            title: title,
            message: "This .elyx archive is encrypted. Enter its password.",
            preferredStyle: .alert
        )
        alert.addTextField { field in
            field.isSecureTextEntry = true
            field.placeholder = "Password"
        }
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Decrypt", style: .default) { _ in
            if let text = alert.textFields?.first?.text, !text.isEmpty {
                onInstall(text)
            }
        })
        presenter.present(alert, animated: true)
    }
}
