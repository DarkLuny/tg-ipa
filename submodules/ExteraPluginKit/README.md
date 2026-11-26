# ExteraPluginKit (iOS)

A Python plugin runtime for Telegram-iOS, API-compatible with the
[exteraGram](https://github.com/exteraSquad/exteraGram) plugins SDK.

The Android client runs `.plugin` files, which are Python modules extending
`base_plugin.BasePlugin`, on an embedded CPython interpreter (Chaquopy). This
module ports that host to iOS: the same file format, the same metadata
(`__id__`, `__name__`, `__version__`, ...), the same `BasePlugin` lifecycle, the
same hook names and the same settings descriptors. It embeds CPython the same
way the Android app does and exposes the app through one JSON host API.

```
submodules/ExteraPluginKit
├── BUILD                          Bazel targets + the SDK resource bundle
├── Sources/                       Swift host (manifest, manager, hooks, UI, analyzer)
├── PythonSupport/
│   ├── include/PluginPython.h     the C ABI (start / call / invoke)
│   ├── src/PluginPython.c         CPython embedding + the `_extera_native` module
│   └── sdk/                       the Python SDK copied into the app bundle
└── tests/test_sdk.py              host-side tests (no Xcode, no iOS)
```

## What is ported

| Android / SDK | iOS implementation |
|---|---|
| `.plugin` file, top-level metadata | `PluginManifestParser` + `extera_utils.metadata_parser` |
| `PluginsController` | `PluginManager`, `PluginStore`, `PluginHooks` |
| `PythonPluginsEngine` | `PythonRuntime` + `_extera_runtime.py` |
| `BasePlugin` and lifecycle (`on_plugin_load`, `on_plugin_unload`, `create_settings`, `on_app_event`) | `base_plugin.py`, same names |
| `pre_request_hook`, `post_request_hook`, `on_update_hook`, `on_updates_hook`, `on_send_message_hook` | `PluginHookPoints` in TelegramCore, wired in `PluginBootstrap` |
| `add_hook`, `add_menu_item`, `add_file_hook`, `add_intent_hook` | host registry in `PluginHooks` / `PluginHostAPI` |
| `get_setting`, `set_setting`, `export_settings`, `import_settings` | `plugin_settings.py` (same JSON file format) |
| `client_utils.send_text/send_photo/...`, `AccountClient` | `client_utils.py` + `PluginEnvironment` |
| `ui.alert.AlertDialogBuilder` | `ui/alert.py` → native `UIAlertController` |
| `ui.bulletin.BulletinHelper` | `ui/bulletin.py` → Telegram overlay when the host provides one |
| `ui.settings` descriptors, `SimpleSettingFactory` | `ui/settings.py` + `PluginSettingsViewController`; custom factories keep the Android constructor and registry, and expose a descriptor to the host |
| `hook_utils.get_method/get_field/...`, `_class_for_name`, `_parameter_classes` | `hook_utils.py` → Objective-C selector/property references |
| `intents.IntentsManager` | `intents.py` → host URL/share handlers |
| `file_utils.FilesController` | `file_utils.py` → host document-open routing |
| `extera_utils.lifecycle`, `extera_utils.text_formatting`, `extera_utils.classes` | full API (`PluginScope`, `ManagedCallback`, `HTML`/`Markdown`/`RawEntity`, `JField`/`JHelper`/`Base`/`class_proxy`) |
| `log_utils.get_logger`, `LogLevel`, `dump` | `log_utils.py`, same filtering/handlers/timers; lines go to the host log |
| `dev_server.DevServer` | `dev_server.py` serves the same JSON protocol over TCP loopback (iOS has no abstract sockets/`adb forward`) |
| plugin analyzer (`PluginAnalyzer`, report UI) | `extera_analyzer.py` + `PluginAnalyzer` / `PluginAnalysisViewController`; an update is analyzed against the installed copy and the sheet shows Android's `AnalyzerDiff` ("What changed": new statements and changed findings). |
| Plugins screen, settings screen, install sheet | `PluginsViewController`, `PluginSettingsViewController`, `PluginAnalysisViewController` |
| ElyxCore (`elyxcore`, `.elyx`/`.eaf` archives, `elyx` facade) | `elyxcore/` + `elyx.py`; the iOS engine validates/extracts archives, loads the plugin's `BasePlugin`, exposes assets/strings/settings and routes hooks/menus through the standard registries |
| Plugin catalog (Git `extera-plugins.json` repositories) | `PluginCatalog` parser + `PluginCatalogViewController`; size/SHA-256 verification before the install sheet. Index requests use `If-None-Match`/ETag, a `304` keeps the cached index, and the synced index is stored per repository so the screen opens instantly; the list shows the Android subtitle ("N plugins" / "Not loaded"). |
| Telegram channel catalog repositories | `PluginCatalog.resolveChannel` resolves `@username`/`t.me` links through `contacts.resolveUsername`; `loadChannelIndex` reads the channel history through `messages.getHistory`, lists `.plugin`/`.elyx`/`.eaf` documents, and `downloadChannelPlugin` fetches the bytes through `upload.getFile`. Install then follows the same analysis/Elyx sheet as a local file. |
| Telegram folder catalog repositories | "Add folder" lists `messages.getDialogFilters`; `loadFolderIndex` merges the plugin documents of every channel in the chosen folder into one catalog. |
| Verified catalog folder | Android's trusted folder (`pPhOtEq00KhjYTc6`) is resolved through `chatlists.checkChatlistInvite`, refreshed at most every five minutes, and its channels are listed under "Verified" and opened like a channel repository. |
| Repository share links (`t.me/exteraPluginRepo`) | `PluginCatalog.repositoryLink` builds Android's `?c=<username>` / `?git=<encoded index>` link for Share/Copy; `PluginCatalog.parseRepositoryLink` plus `PluginBootstrap.handleOpenURL` open such a link from a chat or the browser and add the repository. |
| `NotificationCenter` observers (`addObserver`, `didReceivedNotification`) | `telegram_compat.NotificationCenter`; host updates are posted to the same per-account bus, and the plugin events Android broadcasts (`pluginsUpdated`, `pluginMenuItemsUpdated`, `pluginSettingsRegistered`/`Unregistered`, `pluginIsNotResponding`, `pluginCatalogUpdated`, `pluginsPySdkInfoChanged`) keep their names and arguments |
| Plugin watchdog (`PluginsWatchdog`) | every plugin execution (hook, queued callback, menu item, lifecycle method) starts a five-second budget; a plugin still inside one is marked not responding, `pluginIsNotResponding` is posted, and the plugins list offers Wait / Disable plugin |
| `UserConfig.getCurrentUser`, `MessagesController.getUser/getChat/getPeer` | `client.peer`/`client.me` return Android-like fields (`id`, `title`, `username`, `usernames`, `first_name`, `last_name`, `phone`, `premium`, `verified`, `scam`, `fake`, `deleted`, `support`, `bot`, `kind`), so plugin code reads the same keys as on Android |
| Android app classes used by plugins (`UserConfig` incl. `getCurrentUser`, `MessagesController` incl. `putUser`/`putChat`/`getUser`/`getChat`/sub-controller getters, `loadFullUser`/`loadFullChat`/`loadMessages`/`loadPeerSettings`, `sendTyping`/`deleteMessages`/`markDialogAsRead`/`readMentions`/`readReactions`/`joinChannel`/`leaveChannel`, `ChatObject`, `UserObject`, `DialogObject`, `FileLoader` incl. `getAttachFileName`/`loadFile`/`getFileProgress` (documents download through `upload.getFile`), `ImageLocation` incl. `getForPhoto`/`getForDocument`, `MessageObject`, `MessagesStorage` incl. `putUsersAndChats`, `BuildVars`, `SharedConfig`, `Utilities.Callback*`, `MediaController` playback through the host audio bridge) | native shims in `telegram_compat.py`; unknown classes still import as proxies. Common Java/Android utility classes are also native: `Base64`, `Bundle`, `Uri`, `Environment`, `Handler`, `Looper`, `HandlerThread`, `CountDownTimer`, `Pattern`/`Matcher`, `StringBuilder`, `Date`, `SimpleDateFormat`, `Calendar`, `TimeZone`, `Locale`, `Character`, `Integer`/`Long`/`Double`/`Boolean`/`String`, `Math`, `System`, `Random`, `UUID`, `AtomicInteger`/`AtomicLong`/`AtomicBoolean`, `Executors`/`TimeUnit`, `AsyncTask`, `FileInputStream`/`FileOutputStream`/`FileReader`/`FileWriter`/`BufferedReader`, `LruCache`, `SparseArray`, `ArrayMap`/`ArraySet`, `Pair`, `SpannableString`, `TextUtils`, `Html`, `Log`, `SystemClock`, `Intent`, `ClipboardManager`, `PowerManager`, `Vibrator`, `VibrationEffect`, `Settings.Secure`, `ContentResolver`, `ContentValues`, `Process`, `FileProvider`, `BitmapFactory`/`Bitmap` (dimensions and original-byte `compress`), `Resources`/`Configuration`, `DisplayMetrics`, `TypedValue`, `Typeface`, `Build.VERSION_CODES`, `SharedPreferences`, `PluginsConstants`, `ExteraConfig`, `AppUtils`, `PluginsController`, `PythonPluginsEngine`, `PipController`, `IntentsController`, `SvgHelper`, `LaunchActivity`, `LayoutHelper`, `EditTextBoldCursor`, `OutlineTextContainerView`, `RLottieImageView`, `ButtonWithCounterView`, `DialogInterface`, `Dialog`, `ArrayList`/`LinkedList`/`HashMap`/`ConcurrentHashMap`/`Arrays`, `File`, `ByteArrayInputStream`, `Class`, `Method`/`Member`, `com.chaquo.python.PyObject`/`PyException`/`Python`, `DispatchQueue`, `ImageLoader`, `R`, `Plugin`, `RequiredPluginInfo`, `PluginsHooks`, `PyMethodHook`, `PyMethodReplacement`, `ChatMessageCell`. |
| Android views, widgets and graphics used by custom UI code | native stubs in `telegram_compat.py`: `View`/`ViewGroup` with listener interfaces and `MeasureSpec`, `TextView`/`EditText`/`Button`/`ImageView`/`Switch`/`CheckBox`/`RadioButton`/`ProgressBar`/`SeekBar`/`Spinner`/`LinearLayout`/`FrameLayout`/`ScrollView`/`Toolbar`, `Drawable`/`ColorDrawable`/`GradientDrawable`, `Paint`/`Canvas`/`Path`/`Rect`/`RectF`/`Matrix`/`Shader`/`PorterDuff`, `Gravity`/`InputType`/`EditorInfo`/`AttributeSet`, AndroidX `RecyclerView`/`LinearLayoutManager`/`GridLayoutManager`/`ViewCompat`/`DrawableCompat`/`ViewPager`, and Telegram UI `RecyclerListView`/`MediaActionDrawable`/`RLottieDrawable`/`UniversalAdapter`/`BaseFragment`. They keep plugin code running; iOS still renders declarative settings rows, not arbitrary Android views. |
| Settings model aliases (`com.exteragram.messenger.plugins.models.*`) and `UItem` | `CustomSetting`/`DividerSetting`/`EditTextSetting`/`HeaderSetting`/`InputSetting`/`SelectorSetting`/`SwitchSetting`/`TextSetting` map to `ui.settings` rows; `UItem.asHeader/asSwitch/asSwitch2/asSelector/asInput/asEditText/asText/asButton/asDivider/asCustom` build the same dictionaries with Android field aliases (`id`→`key`, `checked`→`default`). |
| MVEL menu/hook conditions | `evaluate_condition` in `_extera_runtime.py` (comparisons, boolean operators, field paths, `context.get`) |
| Plugins list search/sort, per-plugin info, SDK info | `PluginsViewController`, `PluginInfoViewController`, `PluginSDKInfoViewController`; the info screen has source/analyzer/files/share/delete for both `.plugin` and `.elyx` |
| Install from file, URL, Git catalog, or chat attachment (`.plugin`, `.elyx`, `.eaf`) | `PluginsViewController`, `PluginCatalogViewController`, `OpenChatMessage`; an encrypted `.elyx` asks for its password |
| Install source trust (`pluginsUnknownSources`) | a Git catalog entry is a "Trusted source"; a local file, URL or chat attachment is an "Unknown source". The "Unknown sources" switch lives in Plugins engine settings; while it is off the install sheet refuses unknown sources, and while it is on the sheet needs a risk acknowledgement, matching Android's blocked/acknowledged states. |
| Elyx required plugins and validation | `ElyxPlugin` validation errors are stored on the metadata; a plugin with missing requirements is listed but not loaded |
| Dependency collision checks | `pip_controller` refuses packages whose top-level modules would shadow the SDK; a plugin id that shadows an SDK module is rejected |
| Elyx dev-server commands (`elyx_ping`, `elyx_changes`, `get_elyx_plugins`, `elyx_compare_folder`) | `elyxcore/_dev_server.py` patches the same `DevServer._process_command` hook |
| Encrypted `.elyx` archives | the engine accepts an archive password; the install flows prompt for it and retry. |
| Elyx local wheels and pip requirements | pure-Python wheels follow the same `pip_controller` path; binary wheels remain unsupported. |
| Plugin settings translation | `PluginSettingsTranslation` sends the visible descriptors to `messages.translateText` in batches, detects the source language with `NLLanguageRecognizer`, and shows a translate button only when the detected language differs from the app language. |
| Plugins engine switches | `PluginPreferences` + `PluginSDKInfoViewController`: engine on/off, safe mode, developer mode (starts `dev_server.DevServer` over loopback), static analysis, compact view, restore SDK from the app bundle, and reload all plugins. |
| Plugin list pinning | pinned plugin ids in `UserDefaults`; pinned plugins are listed first and can be pinned/unpinned from the row's context menu, swipe actions, or the info screen. |
| Catalog update state, categories and sorting | the repository screen groups updates first, then installed plugins, compares versions, marks entries updated in the last week as New, filters by category, and sorts by last update or name. |
| Sharing an installed Elyx plugin | `elyx_export_archive` packs the plugin directory into a `.elyx` in the cache and the share sheet sends that archive, matching Android's `getPluginPath`. |
| Enable-after-installation choice | `.plugin` and `.elyx` install sheets have the same switch, defaulting to off as on Android. |
| `FileLoader.loadFile` and media downloads | documents and photos download through `upload.getFile` chunks into the plugin cache; `getAttachFileName`/`getPathToAttach`/`getFileProgress`/`isLoadingFile` read the cached file. |
| `SendMessageParams` media fields, inline keyboards and `edit_message` | text, caption, entities, reply, silent, schedule, a local `path` (photo/video/audio/document), an inline keyboard (`replyMarkup` → `reply_markup`) and a shared `user` (sent as a contact card) are honored; `client_utils.edit_message(..., file_path=...)` replaces the media through `messages.editMessage` (the file is uploaded and the edit runs in the background, like Android's asynchronous call); `send_location`/`send_venue`/`send_contact`/`send_dice` build `messages.sendMedia`, and `poll`/`pollSendParams` build `inputMediaPoll` (question, answers, quiz/multiple-choice/public-voter flags, close period/date, countries, solution and correct answers). The remaining Android fields exist so plugin code can set them. |
| Unmapped Android controller/static members | `telegram_compat` answers the Java default for the name shape (predicates read false, getters read null, the rest are no-ops) instead of raising `AttributeError`; a plugin calling a method this port has not modelled yet keeps running. Mapped methods keep their real implementation. |
| Android UI/animation/net extras (`Editable`, `Selection`, `TextPaint`, `Layout`/`StaticLayout`, `ComponentName`, `BroadcastReceiver`, `IntentFilter`, `ContextWrapper`, `Service`, `NetworkInfo`/`NetworkCapabilities`/`ConnectivityManager`, `WebView`/`WebSettings`/`WebViewClient`/`WebChromeClient`/`CookieManager`, `ValueAnimator`/`ObjectAnimator`/`AnimatorSet`/`ViewPropertyAnimator`, the `android.view.animation` interpolators and legacy animations, `ChatActivity`, `ApplicationInfo`, `Context.getDir`) | native facades in `telegram_compat.py`; they keep imports and the common setters/getters working while iOS renders its own UI. |
| Android utility/net/crypto classes used by plugins (`MessageDigest`, `Cipher` with real AES-CTR, `KeyFactory`, `Signature`, `X509EncodedKeySpec`, `URL`/`HttpURLConnection`, `Browser`, `SharedConfig.ProxyInfo`/`proxyList`, `Intent.ACTION_GET_CONTENT`/`CATEGORY_OPENABLE` plus the activity flags, `Bitmap.Config`/`createBitmap`, `PathParser`/`PathMeasure`, `JSONObject`/`JSONArray`, `SQLiteDatabase`/`SQLiteOpenHelper`/`Cursor`, `DecimalFormat`/`MessageFormat`, `java.time.*`, `Icon`/`ShortcutInfo`/`ShortcutManager`/`ActivityManager`, `ApplicationInfo`, `Context.getDir`/`getCodeCacheDir`/`getDatabasePath`, the `android.text.style.*` spans, `ColorStateList`, `StateListDrawable`/`LayerDrawable`/`RippleDrawable`/`InsetDrawable`/`ClipDrawable`/`PaintDrawable`, `ValueAnimator`/`ObjectAnimator`/`AnimatorSet`/`ViewPropertyAnimator`, `ChatActivity`, `MediaController.pauseMessage`/`cleanupPlayer`/`audioVolume`/`VideoPlayer`/`SavedMusicList`, `jarray`/`cast`) | native shims in `telegram_compat.py`, `hook_utils.py`, `java_crypto.py`, `android_sqlite.py` and `java_time.py`; AES is a pure-Python FIPS-197 implementation checked against the FIPS/NIST vectors, HTTP goes through `urllib`, JSON/SQLite use the CPython modules, and proxy/crypto state stays in the SDK. |

## Client-side exteraGram features

The plugin runtime is separate from exteraGram's client settings. The first
client-side batch lives in TelegramCore/TelegramUI and is reachable from
**Settings → ExteraGram**:

| Feature | Behaviour |
|---|---|
| Disable number rounding | `1.23K` becomes the full localized number |
| Time with seconds | Message timestamps render `HH:mm:ss` |
| Relative last seen | Replaces absolute presence times with minutes/hours/relative buckets |
| Filter zalgo | Removes long runs of combining marks from plain message text |
| Ad block | Sponsored messages are removed from chats |
| Download speed boost | Off / Fast (512 KiB, 8 parts) / Ultra (1 MiB, 12 parts) |
| Upload speed boost | Larger parts and at least 8 parallel upload requests |
| Hide stories | Removes the stories row from the chat-list header |
| Hide archive folder | Hides the archive entry from the chat list |
| Hide action bar status | Removes the presence/member subtitle from the chat title |
| Disable unarchive swipe | Removes the unarchive reveal action from archived chats |
| Hide phone number | Masks the number in the profile header and profile settings |
| Show ID and DC | Appends the account id (and datacenter id) to the settings profile subtitle |
| Default profile tab | Default / Media / Common groups on the profile screen |
| In-app vibration | Disables `HapticFeedback` calls globally through a Display-level switch |
| Hide search bar | Removes the chat-list search field and its scroll inset |
| App icon | Picks one of the alternate icons declared in `Info.plist` |
| Avatar corners | Square / Small / Medium / Large / Circle for `AvatarNode` |
| Tab bar | Icons and titles / Titles only / Icons only |
| Tab counter | All / Unmuted / Hidden |
| Hide share button | Hides the side share button beside media, stickers and instant video |
| Show copy photo button | Shows/hides copying an image from the message menu |
| Show report button | Shows/hides report actions |
| Show clear button | Shows/hides Clear History (closest iOS analogue) |
| Replace Edited with icon | Shows a pencil instead of the "Edited" label |
| Disable greeting sticker | Hides the sticker in an empty chat |
| Hide send-as peer | Hides the send-as avatar in the input field |
| Add comma after mention | Inserts ", " after a selected mention |
| Hide keyboard on scroll | Dismisses input when the history is dragged |
| Hide sticker time | Hides timestamps on sticker messages |
| Sticker size | Scales stickers in chat (12 = 1.0x) |
| Sticker shape | Square or rounded sticker corners |
| Double-tap seek | 5/10/15/30 s video seek step |
| Hide reactions in private chats | Hides reaction footers in DMs |
| Hide reactions in channels | Hides reaction footers in channels |
| Hide reactions in groups | Hides reaction footers in groups |
| Camera stabilization | Enables standard video stabilization |
| Mirror front camera | Mirrors front-camera photos |
| Extended frame rate | Prefers 60 fps camera capture when supported |
| Hide camera tile | Removes the camera cell from the media picker |
| Hide tab bar labels | Shows tab icons without titles |
| Reply background | Shows/hides the background behind a reply preview |
| Reply colors | Uses the author's name colors in replies |
| Reply emoji | Uses the author's background emoji in replies |
| Always send in HD | Forces the high-quality photo flag in the media picker |
| Hide floating button | Hides the chat-list compose button |

`ExteraSettings` is the single storage layer for these switches. The Python
`ExteraConfig` facade reads and writes the same keys through the host
`config.get`/`config.set` bridge, so a plugin sees the values the UI shows.

See `CLIENT_PARITY.md` for the per-key status table and the remaining groups.
The remaining `ExteraConfig` switches (theme/icon packs, custom app name,
message-menu toggles, camera controls and the larger appearance set) are not
wired yet. Several of them have no honest iOS counterpart and are deliberately
kept as storage-only values: `centerTitle` (iOS already centers the chat title),
`newLoadingStyle`, `newSliderStyle`, `newSwitchStyle` (Android Material
controls), and `disableNotificationDelay` (iOS has no equivalent pre-display
delay). `hideFloatingButton` hides the iOS chat-list compose button instead of
an Android FAB. On iOS the
launcher icon can only be one of the icons declared at build time, and the
SpringBoard app name cannot be changed at runtime, so exteraGram's custom
icon-pack/shortcut plugin cannot be reproduced 1:1.

## What cannot be identical

iOS has no JVM/ART and no Android UI toolkit. The following Android behaviours
have no honest 1:1 counterpart; each is either mapped to the closest iOS
mechanism or reported to the plugin instead of silently doing nothing:

| Android feature | iOS behaviour |
|---|---|
| Xposed/ART method hooks (`hookMethod`, `hookAllMethods`, partial hooks, field/string/return hooks) | `hook_method` / `hook_all_methods` install a real hook through the Objective-C forwarding runtime (`PluginObjCRuntime`). Only methods visible to Objective-C can be hooked. Partial hooks map Android's bytecode targets onto the closest member-level hooks: `hook_call_site` hooks the callee selector, `hook_field_read`/`hook_field_write` hook the getter/setter, and `hook_return_value` filters the containing method's return. `proceed()` runs the original through `runtime.proceed` (with new arguments when given); not calling it skips the original call/write; `throw_to_caller` raises into the hook. `getCaller()` is always `None` (a method-level hook cannot see its caller) and `hook_string_constant` has no iOS equivalent, so it logs and returns `None` the way an unresolvable Android target does. |
| Rewriting outgoing TL requests (`pre_request_hook` with `MODIFY`) | Cancelling works. A modified JSON cannot be re-serialized into the already-built MTProto buffer, so the change is logged and not applied. |
| Rewriting received updates | Observation works; values are read-only. |
| Rewriting `SendMessageParams` fields | Text rewriting and cancellation work. A changed peer is parsed but not applied (the iOS enqueue path is typed per peer); media fields pass through. |
| `java.lang.reflect`, `ClassProxy`, generated subclasses | `X.class` / `X.getClass()` return a `ClassRef` whose `getDeclaredMethod`/`getDeclaredField` return hookable member handles. `com.exteragram.messenger.plugins.utils.ClassProxy` is a functional facade: `createProxyClass` builds a Python class whose overridden methods call the handler with Android's `"name:java.lang.Type"` signature, constructors use `"<constructor>"`, field specs become getters/setters, and MVEL method specs are evaluated. Generated subclasses still resolve app calls through the host whitelist and otherwise return `None`. |
| Custom settings rows built from `android.view.View` / `UItem.Factory` | A declarative `view` spec (`switch`, `slider`, `button`, `textfield`, `label`) becomes a native control; an arbitrary Android view cannot be translated, so a row without a spec is shown as a descriptor row. |
| Bitmap pixel access, scaling and custom drawing (`Canvas`, `Paint`, `Path`, `BitmapFactory.decodeStream` pixel data) | `BitmapFactory` reads PNG/JPEG/GIF/WebP dimensions and `Bitmap.compress` copies the original bytes to a stream; pixel access, scaling, `Canvas`/`Paint`/`Path` and drawing are not implemented. |
| Launcher icon/name and dynamic shortcuts (`ShortcutManager`, `Icon`, `ActivityManager.TaskDescription`) | The classes, constants and setters resolve and the plugin loads; iOS has no per-app launcher icon/name override or dynamic SpringBoard shortcuts, so calls are accepted and recorded but do not change the home screen. |
| Sending local photos/video/audio from a plugin | `standaloneSendMessage` uploads the bytes; photos use the image pipeline, other files keep their name and MIME type. The upload is asynchronous, so the call reports success when the upload starts. |
| Arbitrary TL requests (`send_request`) | Implemented for `users.getUsers`, `users.getFullUser`, `messages.getHistory`, `messages.getMessages`, `messages.search`, `messages.getFullChat`, `channels.getFullChannel`, `channels.getMessages`, `channels.getParticipants`, `messages.readHistory`, `messages.readMentions`, `messages.readReactions`, `messages.getUnreadMentions`, `messages.getUnreadReactions`, `messages.setTyping`, `messages.deleteMessages`, `messages.sendReaction`, `messages.sendVote`, `messages.getBotCallbackAnswer`, `messages.getPeerDialogs`, `messages.getDialogs`, `messages.forwardMessages`, `messages.sendMessage`, `messages.sendMedia`, `messages.editMessage`, `messages.updatePinnedMessage`, `messages.getPeerSettings`, `messages.getDialogFilters`, `messages.getMessagesViews`, `messages.getPinnedDialogs`, `messages.getCommonChats`, `messages.getStickers`, `messages.getAllStickers`, `messages.getSavedGifs`, `messages.getFavedStickers`, `messages.getStickerSet`, `messages.searchStickers`, `messages.installStickerSet`, `messages.uninstallStickerSet`, `messages.getArchivedStickers`, `messages.getEmojiKeywordsDifference`, `messages.translateText`, `account.updateStatus`, `upload.getFile`, `channels.joinChannel`, `channels.leaveChannel`, `contacts.resolveUsername`, `contacts.block`, `contacts.unblock`, `contacts.addContact`, `contacts.deleteContacts`, `contacts.importContacts`, `photos.getUserPhotos`, `chatlists.checkChatlistInvite`; other names return a typed error. |
| Third-party Python packages (`__requirements__`) | `pip_controller.py` resolves pure-Python wheels from PyPI, verifies SHA-256, extracts them into `plugins/libs` and shares them through a registry; dependency markers and version conflicts are handled. Binary wheels are refused (no Android/desktop binaries on iOS). |
| Xposed filters (`HookFilter`) | Argument filters run before the callback; result filters run after the original method. `ArgumentIsInstanceOf` and `ResultIsInstanceOf` resolve through the Android→iOS class map. |
| Elyx archives containing Android-only assets (custom drawables, Lottie/SVG drawables) | asset bytes and paths are available (`to_drawable` returns a `NativeFile`); Python cannot draw an Android view, so UI rows use the standard plugin icon. |
| Elyx installer bottom sheet | the dev-server commands are implemented, but the install flow is a confirmation/analysis sheet rather than Android's bottom sheet. |
| SDK OTA updates | the SDK ships in the app bundle and is copied into Application Support; no signed over-the-air SDK channel is configured. |
| Exact analyzer rule engine | the report schema, severity and capability names match, but the rules are reimplemented; Android downloads its analyzer engine separately. |

The core protocol (metadata, lifecycle, settings, update/send hooks, analyzer,
unload and import compatibility) is exercised by `tests/test_sdk.py` on a
desktop Python interpreter, including a real `.plugin` file.
`tests/test_parity.py` additionally pins the HTML/Markdown parsers, the managed
class API, lifecycle cancellation, log levels/handlers, `SimpleSettingFactory`,
hook-filter collection, menu registration/invocation, `file_utils.list_dir`,
the notification bus, the Android UI/widget/graphics shims, `UItem` and settings
model builders, `ChatObject`/`UserObject`/`DialogObject`, `ConnectionsManager`,
controller overlays, the plugin watchdog, analyzer diffs, the SDK's own Android
`partial_hooks_demo.plugin`, `FileLoader` document/photo cache paths,
`SendMessageParams` media, the app facades, every Android class the SDK imports
plus the members it calls (`tests/test_parity.py`'s import/member surfaces), the
`com.exteragram.hook` partial-hook API and its `runtime.swizzle` install path,
the runtime services (`DispatchQueue`, `ImageLoader`, `R`, `Plugin`,
`RequiredPluginInfo`, `PluginsHooks`, `PyMethodHook`/`PyMethodReplacement`,
`ChatMessageCell`), `edit_message` media payloads, the
`send_location`/`send_venue`/`send_contact`/`send_dice` media helpers, the
`ClassProxy` facade, `MediaController` playback and playlist traversal, the Java
collection/IO/reflection natives, the controller settings
(`NotificationsController`/`DownloadController`/`LocationController`),
`MessageObject`/hook-payload media classification
(voice/music/video/round-video/GIF/sticker/photo/document plus duration, file
name and size), the contact add/delete/import requests, the `MessagesStorage`
message cache, the sticker load/fave requests, the `UserObject` flags, the
`MediaMetadataRetriever` container parsers (WAV/FLAC/Ogg/MP3/MP4/images),
`getFrameAtTime` through the AVFoundation host bridge, the `Utilities` helpers,
the inline-keyboard normalization, the shared-user contact path, the
sticker/document/photo-by-reference sends, the vote/bot-callback/reaction
requests, the message flag getters (`canForwardMessage`, `canEditMessage`,
`isScheduled`, `isSponsored`, `isSecret`), the full
`ChatObject`/`DialogObject`/`UserObject` id and rights helpers,
`FileLoader.getFileReference`, the topics-controller facade, the
sponsored/recommendation fallbacks, the `UserConfig` config surface, the
`LocaleController`/`AndroidUtilities`/`BuildVars`/`SharedConfig` helpers, the
`Theme` color/drawable factories, the `Utilities` hashing/byte/string/file
helpers, the `ImageLoader` memory-cache and HTTP-name helpers, the
`NotificationsSettings` per-dialog properties, the `MessagesStorage`/`MessagesController`/
`SendMessagesHelper`/`FileLoader`/`ContactsController`/`NotificationsController`/
`DownloadController`/`LocationController`/`SecretChatHelper`/`MediaDataController`/
`MediaController` method surfaces, the `ApplicationLoader` network helpers, the
pure-Python AES/CTR with its FIPS/NIST vectors, the `URL`/`HttpURLConnection`
client, `JSONObject`/`JSONArray`, `SQLiteDatabase`/`SQLiteOpenHelper`/`Cursor`,
`DecimalFormat`/`MessageFormat`, `java.time` values, the launcher/shortcut
stubs and the `MediaController`/`VideoPlayer`/`SavedMusicList` additions.
A corpus of real exteraGram `.plugin` files was imported and its
`on_plugin_load` lifecycle ran against the SDK; the shims were extended until
those loads completed.
`tests/test_elyx.py` covers the Elyx archive engine, required-plugin
download/install, archive analysis, local wheels, the Elyx UI stubs and the
dev-server commands. `tests/test_pip.py` covers the
version/marker/wheel-selection logic and installs `six` from PyPI when the
network is available. Host-side paths that need the app (media upload, request
codec, Objective-C swizzling) compile against TelegramCore but are not covered
by those tests.

`.elyx` archives (the ElyxCore plugin format) run through `elyxcore/` and the
iOS engine in `elyxcore/_ios_engine.py`: the archive is validated and extracted
under `plugins/ElyxPlugins`, its `metainfo.yaml`/`refmap.yaml` are parsed, local
wheels are installed into the plugin's `elyx_local_libs`, and the plugin's
`BasePlugin` is loaded and dispatched through the same hooks, menus, settings and
lifecycle registries as a `.plugin`. Both formats appear in one list.

## Recent parity additions

The following Android surfaces were added after the original matrix and are
covered by `tests/test_parity.py`:

- `android.net.nsd` (`NsdManager`, `NsdServiceInfo`, registration/discovery/resolve listeners) and `android.net.wifi` (`WifiManager`, `WifiInfo`, `ScanResult`, `WifiConfiguration`, Wi-Fi locks); `getSystemService` now returns the NSD, Wi-Fi, telephony, battery, connectivity, sensor, location, notification and window managers.
- `android.os.BatteryManager`, `android.os.Message`, and the full `Handler` message queue surface (`sendMessage*`, `hasMessages`, `removeCallbacksAndMessages`, `obtainMessage`).
- `android.view.ViewTreeObserver` and its listener interfaces, `View.getViewTreeObserver`/`post`/`postDelayed`, plus the common `View` focus/scroll/system-UI constants.
- `java.nio.ByteBuffer`, `org.telegram.ui.Components.ItemOptions`, `LocaleController.LocaleInfo`, and the Android `Build`/`Context`/`Intent`/`Environment` constants used by system-info plugins.
- `TLRPC.MessageEntity`, `TLRPC.Message` and other plain TLRPC nested names are constructible (not just `TL_*` constructors).
- `client_utils.run_on_queue` and `DispatchQueue` now execute on background threads and return cancellable managed callbacks, like Android; `run_on_ui_thread` keeps its managed callback contract.
- `intents.IntentsManager` accepts both the Android `HandlerInfo` form and the documented callback-plus-keyword form.
- The vendored `requests` shim now provides `Session`, `session()`, `exceptions`, `codes` and `options`, so Elyx dependencies such as `KangelPluginsManager` run unchanged.
- `get_last_fragment()` and `LaunchActivity.getSafeLastFragment()` return a `ChatActivity` facade with the current `dialog_id`/`topic_id`; `ChatController` reports the open chat to the plugin manager.
- `plugins.show_install` opens the plugin install document picker from a plugin.
- Local Elyx wheels now live under `PluginsController.pluginsDir`, matching Android and the SDK's own Elyx wheel tests.
- `java.net` and `java.io` additions used by real plugins: `Thread` (with persistent `currentThread()`), `Socket`/`ServerSocket`, `InetAddress`/`InetSocketAddress`, `URL`/`URI`/`URLConnection`/`HttpURLConnection`/`HttpsURLConnection` with response headers/content length, `ByteArrayOutputStream`, `RandomAccessFile`, `DataInputStream`/`DataOutputStream`, `Scanner`, and `NativeSet` for `java.util.HashSet`.
- `java.security.SecureRandom` and `javax.crypto.Mac` (HMAC-SHA1/256/384/512/MD5) are native, alongside the existing AES/CTR `Cipher`, `MessageDigest`, `KeyFactory` and `Signature` facades.
- Telegram UI/custom-view facades used by real plugins: `BottomSheet`, `StarParticlesView`, `NestedScrollView`, `BackupImageView`, `GiftSheet`, `ProxyListActivity.TextDetailProxyCell`, `RequestTimeDelegate`, and the Android `StatFs` filesystem counters.
- `hook_utils.find_class`, `java.jclass`, `get_method`, `get_field` and `get_constructor` resolve the native iOS facades (for example `SoundPool`, `UserObject`, `BottomSheet`, `ProxyListActivity$TextDetailProxyCell`) instead of returning an opaque `ClassRef`.
- `HeaderSetting`/`UItem` and the other settings-model aliases keep working through the lazy native mapping.

## Verification

Run on 2026-11-26 on the Windows host (desktop CPython only; Xcode/Bazel
cannot run here):

| Check | Result |
|---|---|
| `tests/test_parity.py` | `ALL PARITY OK` |
| `tests/test_sdk.py` | `ALL OK` |
| `tests/test_imports.py` | `ALL IMPORTS OK` |
| `tests/test_elyx.py` | `ALL ELYX OK` |
| Real Elyx quick-start archive (`.elyx` and `.eaf`; YAML `refmap`/`metainfo`, `src.greeting`, SVG asset, `en`/`ru` strings, `Header`/`Input`/`Text` settings) | install → inspect → enable → settings → app event → delete all pass |
| Encrypted `.elyx` archive (ZipCrypto) | correct password reads metadata and `main.py`; wrong password raises `ArchiveEncryptionError` |
| Dev-server JSON protocol over loopback TCP | `ping`/`pong` and `get_plugins` responses pass |
| `tests/test_pip.py` | `ALL PIP OK` |
| `ExteraConfig` bridge | property, `get*`/`set*` accessors and in-memory fallback pass in `test_parity.py` |
| Client parity assertions | `tools/check_client_parity.py` → `CLIENT PARITY ASSERTIONS OK` |
| Swift syntax of the changed host/client files | tree-sitter: 46 files, 0 parse errors |
| `ExteraSettings.swift` typecheck (Swift 5.10.1, Windows SDK 10.0.18362, `-warnings-as-errors`) | exit 0 |
| `ExteraSettings` compiled and executed | `Ẕ̷algo`, then defaults for the 28 checked keys |
| Android SDK `tests/test_metadata_parser.py` against the iOS SDK | 5/5 pass |
| Android SDK `tests/test_elyx_wheels.py` against the iOS SDK | 6/6 pass |
| Android SDK `tests/test_dev_server.py` peer checks | 3/4 pass (the fourth constructs `os.getuid()`, which does not exist on Windows; on iOS it does) |
| Real `.plugin` corpus, `on_plugin_load` | 34/34 load (15 original + 19 downloaded; `kangel_plugins_manager.plugin` needs its PyPI dependency) |
| Real `.plugin` deep lifecycle (`load` → `create_settings` → serialize → app events → unload) | 33/34 pass; `direct.plugin` fails on its own `rremove_on_send_message_hook` typo, and `kangel_plugins_manager.plugin` needs its `KangelPluginsManager` PyPI dependency |
| Real `.plugin` hook calls (`pre_request_hook`, `post_request_hook`, `on_update_hook`, `on_updates_hook`, `on_send_message_hook`) | 23 hook calls pass; only the same `direct.plugin` unload typo fails |
| Dynamic import audit of the corpus | all remaining names are helper callables, lazy settings aliases, or mapped collections; no missing Java/Android module |
| `KangelPluginsManager==1.4.3` through `pip_controller` | installed with `requests`/`charset-normalizer`/`idna`/`urllib3`/`certifi`; plugin load/settings/unload pass |
| Kangel through the real runtime path (`parse_metadata` → `install_requirements` → `load_plugin` → `plugin_info` → `unload_plugin` → `uninstall_requirements`) | every step returns `ok` |
| Host method audit | 96 SDK host calls, 128 handled `PluginHostAPI` cases, 0 missing |
| `compileall` of the SDK | `True` |
| tree-sitter Swift parse | 35 files, only the known `PluginPythonBridge.swift` `@_silgen_name` false positive |

## macOS verification

On a macOS host with Xcode, run:

```bash
bash submodules/ExteraPluginKit/tools/verify_macos.sh
```

It runs the Python suites, the `debug_sim_arm64` build and the signing-helper
dry run. Follow it with the simulator/device checklist in `README.md` and the
device `lib-dynload` signing command from the build section.

## Host API

Every SDK call ends in `extera_ios.host(method, json)`; the Swift switch in
`PluginHostAPI.swift` is the complete capability list. The important methods:

| Method | Purpose |
|---|---|
| `app.info`, `device.info`, `account.current`, `account.list` | environment |
| `config.get`, `config.set`, `config.all` | `com.exteragram.messenger.ExteraConfig` bridge |
| `paths.dir` | plugins / sdk / cache / documents |
| `ui.run`, `ui.cancel`, `ui.toast`, `ui.bulletin`, `ui.copy`, `ui.clipboard`, `ui.open_url`, `ui.notify`, `ui.present`, `ui.pick_file` | UI primitives |
| `alert.create`, `alert.show`, `alert.update`, `alert.dismiss` | `AlertDialogBuilder` |
| `client.send`, `client.send_text`, `client.send_media`, `client.edit_message`, `client.delete_messages`, `client.request`, `client.peer`, `client.chats`, `client.contacts`, `client.me` | Telegram data and sending |
| `http.request`, `http.download` | plugin HTTP and binary downloads |
| `hooks.add`, `hooks.remove`, `hooks.add_xposed`, `menu.add`, `menu.update`, `menu.remove`, `menu.list`, `menu.invoke` | registry and menu surface |
| `file.register`, `file.unregister`, `intent.register`, `intent.unregister`, `intent.send` | file/intent handlers |
| `settings.get`, `settings.set`, `settings.reload`, `settings.open` | settings |
| `runtime.swizzle`, `runtime.unswizzle`, `runtime.class_exists`, `runtime.selector_exists`, `runtime.responds_to`, `runtime.call`, `runtime.get_property`, `runtime.set_property`, `runtime.resolve` | Objective-C reflection and hooks |
| `runtime.object.call/get/set`, `java.*`, `telegram.call` | proxy objects |

`PluginBootstrap` is the only place that converts an app object into one of
these calls; a method that is not in that switch cannot be reached from Python.

## Adding CPython to the app

The release tarball is vendored under `third-party/python-ios`:
`Python-3.11-iOS-support.b13.tar.gz` (sha256
`e1f55eef2b8c4812f63ee02f8284c8db067ef1a26e75b9a470934376ac197ea0`), its
`Python.xcframework`, and three standard-library trees (device, arm64 simulator,
x86_64 simulator; Python 3.11.18, minimum iOS 13). The Windows extraction
materialised the archive's `lib` symlink as a directory and stores
`libpython3.11.dylib` as a copy of `Python.framework/Python`; the archive
checksum is unchanged.

`BUILD` already declares:

- `//third-party/python-ios:Python` — the dynamic xcframework;
- `//third-party/python-ios:PythonHeaders` — the framework headers, listed as a
  compile input of `PluginPython`;
- `//third-party/python-ios:PythonStdlib`, `:PythonStdlibSimulator`,
  `:PythonStdlibSimulatorX86_64` — `apple_resource_group` targets with
  `structured_resources`, selected by `TARGET_CPU` in `Telegram/BUILD`;
- `//submodules/ExteraPluginKit:PluginPython` — depends on the xcframework and
  includes its headers.

`PluginPython.c` uses `__has_include(<Python.h>)`, and `PythonRuntime` passes
the stdlib directory from `PluginStore.bundledStdlibDirectory()` to
`pl_python_start`. Both `PluginStore` lookups validate a marker file
(`_extera_runtime.py`, `encodings/__init__.py`) and fall back to a recursive
search, so a resource layout that keeps a package prefix still resolves. Without
the framework the same file compiles to a stub and `PythonRuntime.isAvailable`
is `false`.

On a **device**, the `.so` files under `stdlib*/python3.11/lib-dynload` are
executable code and must be signed with the app's identity; signing only the
app binary and embedded frameworks is not enough. The simulator does not
enforce this. If the build does not sign resource files, add a signing step for
`lib-dynload` (or link a static CPython with the extension modules built in).

## Using it

The Settings tab gets a **Plugins** row (`PeerInfoSettingsItems.swift`,
`PeerInfoScreenSettingsActions.swift`). The screen lists installed plugins,
toggles them, accepts a `.plugin` file through the document picker, shows the
analysis before installing, and opens each plugin's generated settings screen.

A plugin is installed from Files, from a `.plugin` document opened in a chat
(the document path is analysed before the install sheet), or from the Plugins
screen's document picker. Installation is refused when the manifest is invalid
or requires a newer app/SDK; the analysis report is advisory and a critical
report needs an extra confirmation. `__app_version__` is checked against the
exteraGram compatibility version (`13.2.1`), not the Telegram-iOS marketing
version, so a plugin's version gate keeps the meaning it has on Android.

Menu items are surfaced where the iOS UI has the corresponding place:
`message_context_menu` in a message's long-press menu, `profile_action_menu` in
the profile's action list, `chat_action_menu` in a chat's long-press menu and
`main_menu` / `drawer_menu` in the Plugins screen (iOS has no Android drawer).

Pure-Python dependencies can be placed in `plugins/.deps/<plugin id>/`; the
runtime adds that directory to `sys.path` while the plugin is loaded. The
`__requirements__` declaration is reported by the analyzer but is not installed
automatically (there is no pip on the device).

The app wires everything in `submodules/TelegramUI/Sources/PluginBootstrap.swift`:

```swift
PluginBootstrap.start(sharedContext: sharedContext)
```

It sets `PluginHookPoints`, installs the `PluginEnvironment` (send, peer, HTTP,
clipboard, settings navigation) and starts `PluginManager`.

## Android → iOS mapping

The SDK keeps the Android names; underneath each one is the iOS mechanism that
plays the same role. This is the table a plugin author needs when a script uses
an app class directly.

| Android name | iOS surface |
|---|---|
| `UserConfig.selectedAccount` (int index) | account peer id (`context.account.peerId.toInt64()`); the account list comes from `activeAccountContexts` |
| `AccountInstance.getInstance(n)` | `AccountContext` for that id |
| `SendMessagesHelper.sendMessage(params)` / `client_utils.send_text` | `enqueueMessages(account:peerId:messages:)` |
| `MessagesController` / `ContactsController` / `MessagesStorage` | `TelegramEngine` (`context.engine.*`), exposed through the controller getters |
| `ConnectionsManager.sendRequest` / `send_request` | a typed set of raw requests through `client.request`/`send_request` (`users.getUsers/getFullUser`, `messages.getHistory/getMessages/search/getFullChat/readHistory/readMentions/readReactions/getUnreadMentions/getUnreadReactions/setTyping/deleteMessages/sendReaction/getPeerDialogs/getDialogs/forwardMessages/sendMessage/editMessage/getPeerSettings/getDialogFilters/getMessagesViews/getPinnedDialogs/getCommonChats/getStickers/getAllStickers/getSavedGifs/getFavedStickers/getStickerSet/searchStickers/installStickerSet/uninstallStickerSet/getArchivedStickers/getEmojiKeywordsDifference/translateText`, `account.updateStatus`, `upload.getFile`, `channels.getFullChannel/getMessages/getParticipants/joinChannel/leaveChannel`, `contacts.resolveUsername`, `chatlists.checkChatlistInvite`); other names return a typed error |
| `AlertDialog.Builder` | `UIAlertController` with the same builder methods (`set_title`, `set_message`, buttons, items, listeners) |
| `AndroidUtilities.runOnUIThread` | `DispatchQueue.main.async` (`extera_ios.run_on_ui_thread`) |
| `NotificationCenter` notifications | host events / `on_update_hook`; no global observer object |
| `BulletinFactory` | Telegram overlay when the host provides one, otherwise a short toast |
| `java.io.File` | `URL` / Foundation file APIs (`NativeFile` proxy in `extera_utils.classes`) |
| `android.view.View` | `UIView`; a Python plugin cannot construct one, so custom settings rows are descriptors |
| `XposedBridge.hookMethod` / `hook_method` | Objective-C method swizzling (`runtime.swizzle`); no bytecode hooks |
| `de.robv.android.xposed.XC_MethodHook.MethodHookParam` | `MethodHookParam` proxy with `args`, `thisObject`, `getResult`/`setResult` for Objective-C hooks |
| `Intent` / `IntentsManager` | URL opens and share items routed by the host |
| `SharedPreferences` | `plugin_settings.json` |
| `R.drawable.*` / `R.raw.*` | SF Symbols / host assets; resource ids are accepted and mapped where possible |

The account identifier is the one observable difference a script may notice:
Android uses a 0-based account index, iOS uses the account's peer id. The SDK
passes the same identifier to every hook of one account, and `get_client()` /
`account_scope` keep working; a script that hardcodes `account=0` should use
`get_selected_account()` or the value it receives in a hook instead.

## Security analyzer

`extera_analyzer.py` inspects the source before it is imported and produces the
same report schema as the Android analyzer:

```json
{"analyzer":{"version":"ios-1.0"},
 "max_severity":"danger",
 "statements":[{"id":"java_hooks","severity":"danger","title":"Hooks app code",
                "values":[],"rules":["hooks.java"],"capabilities":["java_hooks"]}],
 "findings":[{"rule":"hooks.java","severity":"danger","title":"Hooks app code",
              "capabilities":["java_hooks"],"values":["hook_method"],
              "evidence":[{"symbol":"hook_method","location":{"artifact":"0","line":41}}]}],
 "limits":[],"artifacts":[{"id":"0","name":"x.plugin","kind":"python"}],
 "stats":{"elapsed_ms":3}}
```

Rules cover dynamic code (`exec`, `eval`, `compile`), encoded payloads, native
code and subprocesses, file writes/deletes, session/key material, account and
message access, wallet symbols, method hooks, network endpoints and raw IPs,
request interception, and third-party packages. Statements combine findings into
the capabilities the install sheet shows; a critical statement requires an
explicit confirmation.

The Android analyzer runs in an isolated native process and its rule engine is
not part of the exteraGram source tree (the app downloads and verifies it). The
iOS port therefore implements the same report schema, severity model and
capability names with rules written here; it does not claim byte-for-byte
identical findings. A report that cannot be produced is shown as `unavailable`
rather than as a clean result.

## Python SDK layout

```
sdk/
  base_plugin.py            BasePlugin, HookResult, HookStrategy, menu items
  client_utils.py           send helpers, AccountClient, controller getters
  plugin_settings.py        JSON setting store (same file format as Android)
  hook_utils.py             get_method/get_field, private fields
  intents.py                IntentsManager, HandlerInfo, URL/share handlers
  file_utils.py             FilesController, file helpers
  log_utils.py              Logger, per-plugin log
  android_utils.py          log, run_on_ui_thread, Runnable, click listeners
  markdown_utils.py         markdown parsing to plain entities
  extera_analyzer.py        security analyzer
  extera_utils/
    classes.py              Java class/object proxies + Objective-C helpers
    lifecycle.py            scopes, cleanup, managed callbacks
    metadata_parser.py      top-level `__id__`/... parsing (ast)
    text_formatting.py      HTML/Markdown to entities
  ui/
    alert.py                AlertDialogBuilder
    bulletin.py             BulletinHelper
    settings.py             Switch, Selector, Input, Text, Header, Divider, EditText, Custom
  compat.py                 import hooks for java/android/org.telegram/de.robv
  telegram_compat.py        native shims for common Android app classes
  elyx.py                   public `elyx` facade for `.elyx` plugins
  elyxcore/                 Elyx engine: archives, assets, strings, settings, hooks
  pip_controller.py         pure-Python wheel installer and dependency registry
  _vendor/                  PyYAML, packaging and the requests shim used by the SDK
  extera_ios.py             friendly wrapper over `_extera_native`
  _extera_runtime.py        load/unload, hooks, settings, analyzer, Elyx entry points
  _extera_native.py         desktop fallback for the C module
  _sdk_version.py           version guard (same `Z.c()` convention)
```

## Tests

```sh
python3 submodules/ExteraPluginKit/tests/test_sdk.py
python3 submodules/ExteraPluginKit/tests/test_imports.py
python3 submodules/ExteraPluginKit/tests/test_parity.py
python3 submodules/ExteraPluginKit/tests/test_elyx.py
python3 submodules/ExteraPluginKit/tests/test_pip.py
```

The first creates a real `.plugin`, loads it through `_extera_runtime`, checks
metadata, lifecycle, settings serialization, update and send-message hooks,
analysis, unloading, and the Java/Android import compatibility layer. The
second imports every SDK module, exercises the Java collection/class proxies,
settings/custom-view serialization, text entities, analyzer rules and the
MethodHookParam shim. `test_parity.py` pins the HTML/Markdown parsers, managed
classes, lifecycle cancellation, log levels/handlers, `SimpleSettingFactory`,
hook-filter collection, menu registration/invocation, file and intent handlers,
the notification bus, MVEL conditions, TL objects, `file_utils.list_dir` and the
Android UI shims. `test_elyx.py` builds a synthetic `.elyx` directory and
archive, checks metadata/strings/assets and local imports, installs, enables,
reads settings, dispatches updates and app events, checks required-plugin gating,
downloads and installs a required plugin from a local HTTP server, analyzes a
malicious archive, exercises the Elyx dev-server commands, exports the installed
plugin back to a `.elyx`, and deletes the plugin. `test_pip.py` covers the
version/marker/wheel-selection logic and installs `six` from PyPI.

## Next steps

- Build on macOS with the vendored CPython using the repository's
  `build-system/Make/Make.py` (for example the `debug_sim_arm64`
  configuration), then run the simulator build. Xcode/Bazel cannot run on this
  Windows host, so the Swift app itself was syntax-checked with tree-sitter but
  not compiled here.
- For a device build, sign `stdlib*/python3.11/lib-dynload/*.so` with the app
  identity (the simulator does not require it); verify that CPython starts and
  imports the standard library. The helper
  `submodules/ExteraPluginKit/tools/sign_python_libs.py` finds every
  `lib-dynload/*.so` in an app bundle and signs it with Xcode's
  `EXPANDED_CODE_SIGN_IDENTITY` (use `--dry-run` to inspect the list and
  `--verify` to verify each signature).
- Device/simulator checks: install `.plugin`/`.elyx`/`.eaf` from Files, a chat
  attachment, a URL, a Git catalog and a Telegram channel/folder repository;
  then exercise engine/safe mode, settings translation, hooks/menus, alerts,
  NotificationCenter, intents, analyzer diff, dev-server commands, encrypted
  archives, required plugins, downloads, repository links, inline keyboards,
  partial hooks, controller actions and polls/albums.
- Recheck `kangel_plugins_manager.plugin` through the real installer with its
  `KangelPluginsManager==1.4.3` requirement, and ignore `direct.plugin`'s own
  `rremove_on_send_message_hook` typo unless that plugin is fixed upstream.
- Signed SDK OTA updates, if the fork chooses an update channel.
- Additional raw requests and Android class shims as scripts need them.
- Request rewriting and instruction-level hooks remain limited by the platform
  (see above).

## Licence and attribution

This is an independent reimplementation for iOS of the exteraGram plugins SDK
interface. The API names and behaviour are kept for source compatibility; the
Swift, C and Python sources here were written for this port. It is licensed
under the GNU GPL v2 or later, matching Telegram-iOS.

The plugin format and the SDK interface originate from
[exteraGram](https://github.com/exteraSquad/exteraGram), Copyright @exteraGram,
GPL v3 with additional terms (`ADDITIONAL_TERMS.md` in that repository). A fork
that ships this port must keep the attribution required by those terms and must
not present itself as exteraGram.
