# exteraGram client parity

This file tracks the client-side `ExteraConfig` surface, separately from the
Python plugin SDK. The plugin SDK has its own coverage in `README.md` and the
test suite. Current status: **45 wired keys of 177**; all remaining keys have
Android-compatible defaults in the Python facade, but not all have iOS UI.

## Implemented and wired

| Android key | iOS implementation |
|---|---|
| `disableNumberRounding` | `NumericFormat.compactNumericCountString` |
| `formatTimeWithSeconds` | `TextFormat.stringForMessageTimestamp` |
| `relativeLastSeen` | `TelegramStringFormatting.stringAndActivityForUserPresence` |
| `filterZalgo` | plain-text message rendering in `ChatMessageTextBubbleContentNode` |
| `inAppVibration` | `Display.HapticFeedback.isEnabled` |
| `downloadSpeedBoost` | `MultipartFetchManager` part size/parallelism |
| `uploadSpeedBoost` | `MultipartUploadManager` part size/parallelism |
| `hidePhoneNumber` | profile header, profile items and settings phone row |
| `showIdAndDc` | personal profile subtitle |
| `defaultProfileTab` | first profile pane (Default/Media/Common groups) |
| `hideArchiveFolder` | archive group removed from chat-list entries |
| `disableUnarchiveSwipe` | unarchive reveal option removed |
| `hideStories` | stories header disabled |
| `hideActionBarStatus` | chat title subtitle blanked |
| `hideDialogsSearchBar` | search field removed and scroll inset set to 0 |
| `avatarCorners` | `AvatarNode` corner factor |
| `tabIcons` | `TabBarComponent` icon/title visibility |
| `hideNavigationBarLabels` | blanks tab-bar titles, keeping only icons |
| `replyBackground` | hides the background block behind a reply/quote preview |
| `replyColors` | disables the author's name color/gradient in replies |
| `replyEmoji` | disables the author's background emoji pattern in replies |
| `tabCounterMode` | all / unmuted (`filteredCounters`) / hidden tab badge |
| `hideShareButton` | hides `ChatMessageShareButton` beside media, stickers and instant video |
| `showCopyPhotoButton` | image copy path in the message menu |
| `showReportButton` | report message/profile actions |
| `showClearButton` | Clear History action (closest iOS analogue of Android's media cache clear) |
| `replaceEditedWithIcon` | pencil glyph instead of the "Edited" label in message timestamps |
| `disableGreetingSticker` | hides the random greeting sticker in an empty chat |
| `hideSendAsPeer` | hides the send-as avatar button; Android's long-press-emoji fallback is not replicated yet |
| `addCommaAfterMention` | inserts `", "` after a selected mention (bots keep a space) |
| `hideKeyboardOnScroll` | dismisses the input when the chat history starts dragging |
| `stickerTimeMode` | `HIDDEN` (2) hides timestamps on sticker messages; `SIDE` (1) is not implemented |
| `stickerSize` | scales static/animated sticker `displaySize` (12 = 1.0x) |
| `stickerShape` | `0` = square, `1`/`2` = 6 pt corner radius (bubble-radius mode is approximated) |
| `doubleTapSeekDuration` | 5/10/15/30 s seek step in the video gallery double-tap |
| `hideReactionsInPrivateChats` | `mergedMessageReactionsAndPeers` returns empty for users/secrets |
| `hideReactionsInChannels` | reaction footer hidden for broadcast channels |
| `hideReactionsInGroups` | reaction footer hidden for groups and supergroups |
| `cameraStabilization` | `preferredVideoStabilizationMode` in `CameraOutput` |
| `cameraMirrorMode` | front-camera mirror flag in `CameraOutput.takePhoto` |
| `extendedFramesPerSecond` | `LegacyCamera.preferredMaxFrameRate` returns 60 fps when enabled |
| `hideCameraTile` | removes the camera rect from the media-picker grid |
| `alwaysSendInHD` | force `isHighQualityPhoto` in `MediaPickerChatMediaSend` |
| `hideFloatingButton` | hides the chat-list compose button |
| `enableAdBlock` | sponsored messages filtered in `AdMessagesHistoryContext` |

The Go/Java/Android values are stored under `extera.client.<Android key>` in
`UserDefaults`, so the Python `ExteraConfig` facade and the native UI read and
write the same value.

## Deliberately storage-only / not portable

| Android key | Reason |
|---|---|
| `centerTitle` | Telegram-iOS already centers the chat title |
| `newLoadingStyle`, `newSliderStyle`, `newSwitchStyle` | Android Material controls, no iOS equivalent |
| `disableNotificationDelay` | iOS has no equivalent pre-display delay |
| `showSaveMessageButton` | Android adds "Save" to Saved Messages; iOS has no direct save-to-self menu action |
| `showOnlineStatus` | Android draws an online dot on message avatars; iOS message avatars have no online indicator |
| `showRepeatMessageButton`, `showHistoryButton`, `showDetailsButton` | iOS has no matching Repeat / Message history / Details message actions |
| `showGenerateButton` | no AI-generate entry point equivalent to exteraGram |
| `groupMessageMenu` | the iOS context menu is already grouped |
| `iconPack`, `editingIconPackId` | iOS alternate icons must be declared in `Info.plist` at build time |
| custom app name / launcher shortcut | SpringBoard does not allow runtime name/icon changes |
| Android-only camera, player, feed, drawer and theme-editor switches | They depend on Android UI/engine structures |

## Not wired yet

The rest of the 177 `ExteraConfig` keys are available to plugins with their
Android defaults, but changing them does not change the iOS client yet. The
largest remaining groups are:

- message-menu button toggles (`showRepeatMessageButton`, `showHistoryButton`,
  `showGenerateButton`, `showDetailsButton`, `groupMessageMenu`, ...);
- camera/video controls (`cameraType`, `zoomSlider`, `preferOriginalQuality`,
  `swipeToPip`, `unmuteWithVolumeButtons`, ...);
- chat-list appearance (`dividerStyle`, `senderMiniAvatars`, `titleText`,
  `squareFab`, `sectionRadius`, ...);
- stickers/replies (`stickerSize`, `stickerShape`, `replyColors`,
  `unlimitedRecentStickers`, ...). In exteraGram these keys are also only read
  by the settings screen, so iOS keeps the same storage-only behaviour;
- reaction *selection* remains available; the three `hideReactionsIn*` keys
  only hide the reaction footer in `mergedMessageReactionsAndPeers`;
- inline tools and AI toggles (`inlineResults`, `inlineMathResult`,
  `telegramAiEditor`, ...).

## Verification

Run from the repository root on a desktop Python host:

```text
test_parity.py   -> ALL PARITY OK
test_sdk.py      -> ALL OK
test_imports.py  -> ALL IMPORTS OK
test_elyx.py     -> ALL ELYX OK
test_pip.py      -> ALL PIP OK
compileall       -> True
```

Static checks:

```text
Android ExteraConfig keys: 177
iOS ExteraConfig defaults: 178 (includes 177 Android keys + pluginsEngine)
Missing defaults: 0
SDK host calls: 98
PluginHostAPI handled cases: 127
Missing host cases: 0
Swift tree-sitter: 46 changed files, 0 parse errors
ExteraSettings.swift typecheck (Swift 5.10.1, -warnings-as-errors): exit 0
ExteraSettings.swift + main.swift compiled/run: Ẕ̷algo / true / false / true / true / true / true / false / false / true / true / 0 / 12.0 / 1 / 1 / true / true / true / false / false / false / false / 0 / false / true / false / true / false / false
tools/check_client_parity.py: CLIENT PARITY ASSERTIONS OK (45 wired keys, 69 guarded call sites)
```

## Blocker

The Swift host/client cannot be compiled or run on the Windows workstation: the
repository needs macOS, Xcode and the iOS SDK. Tree-sitter parsing proves syntax
only. A macOS build plus simulator/device run is required before claiming
"no errors" or runtime parity.
