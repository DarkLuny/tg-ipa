# Integration points in this fork

The kit is self-contained under `submodules/ExteraPluginKit`. These files were
touched outside it so the runtime is reachable from the app:

| File | Change |
|---|---|
| `submodules/ExteraPluginKit/**` | new module: Swift host, CPython bridge, Python SDK, Objective-C hook runtime, analyzer, UI, Bazel target |
| `submodules/TelegramCore/Sources/Plugins/PluginHookPoints.swift` | new: closures for requests, updates and outgoing text, with JSON flattening |
| `submodules/TelegramCore/Sources/Network/Network.swift` | `request`/`requestWithAdditionalInfo` ask `wantsRequest`/`preRequest` and report `postRequest`; a cancelled request becomes `PLUGIN_CANCELLED` |
| `submodules/TelegramCore/Sources/Plugins/PluginRequests.swift` | new: `users.getUsers`, `messages.getHistory`, `messages.readHistory`, `channels.joinChannel` for `send_request` |
| `submodules/TelegramCore/Sources/State/UpdateMessageService.swift` | every update batch is delivered to `receivedUpdate` when a plugin subscribed |
| `submodules/TelegramCore/Sources/PendingMessages/EnqueueMessage.swift` | `enqueueMessages` lets `sendMessage` rewrite text or drop the message |
| `submodules/TelegramUI/Sources/PluginBootstrap.swift` | new: wires hook points, the account registry, `PluginEnvironment`, app events and URL intents |
| `submodules/TelegramUI/Sources/AppDelegate.swift` | calls `PluginBootstrap.start(sharedContext:)`; `handleOpenURL` runs plugin URL handlers before/after the app |
| `submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoSettingsItems.swift` | adds the **Plugins** row to Settings |
| `submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreenSettingsActions.swift` | opens `PluginsViewController` from that row |
| `submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift` | adds the `.plugins` settings section |
| `submodules/TelegramUI/BUILD` | depends on `//submodules/ExteraPluginKit:ExteraPluginKit` |
| `submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/BUILD` | same dependency for the settings row/action module |
| `Telegram/BUILD` | ships `//submodules/ExteraPluginKit:ExteraPluginsBundle` (the Python SDK), `//third-party/python-ios:PythonStdlib{,Simulator}` and the `Python` dynamic framework |
| `third-party/python-ios/**` | vendored CPython 3.11.18 (Python-Apple-support b13), stdlib and device/simulator copies |

## Account identifiers

The plugin-visible account id is `AccountContext.account.peerId.toInt64()`, the
same value for requests, updates and sends of one account. Plugin peer values
are converted between Android dialog ids (positive user id, negative group id,
`-100…` channel id) and Postbox `PeerId` in `PluginBootstrap`.

## Adding a hook point

Do not call the kit from TelegramCore: TelegramCore must not depend on it.
Expose a closure on `PluginHookPoints`, call it at the app's own site, and wire
it in `PluginBootstrap.installHookPoints()`. Values cross as JSON/flattened
dictionaries, never as app objects.
