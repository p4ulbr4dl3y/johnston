# Changelog

## Unreleased

### Breaking Changes

* **permissions:** remove permission groups (read/write/net/exec) and project-level permissions. Only global per-tool permissions (`~/.johnston/config.json` → `permissions.tools`) plus `default`, and session overrides remain. `update_permission("group", ...)` and `project_dir`/project scope arguments are gone; project `.johnston/permissions.json` files are no longer read. Default for all tools without an explicit entry is now `ask` (previously `read`/`write` group tools defaulted to `allow`).
* **shell:** remove Shell Guard (shell-command safety guard) entirely. The `analyze_shell_command()` guard, `permissions.shell_guard` config key, Shell Guard UI toggle, and related overrides are gone. The `shell` tool now runs through the normal per-tool permission flow only.

## [0.28.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.27.1...johnston-v0.28.0) (2026-08-31)


### Features

* **checkpoint:** scope rollback diffs and restore to session files ([69dcdec](https://github.com/p4ulbr4dl3y/johnston/commit/69dcdec28ca7e28a62947859c3e31dd2ddcc2553))
* **commands:** scope /diff command to session modified files ([ff0a66e](https://github.com/p4ulbr4dl3y/johnston/commit/ff0a66e781bfc81dd9066de5b0ee2928e7ef9ff9))
* **config:** centralize typed settings with sectioned json schema ([5c9dbe5](https://github.com/p4ulbr4dl3y/johnston/commit/5c9dbe58825cec858422724697c49cc1a0b8aa77))
* **config:** make compaction summarize ratio configurable ([b3dc492](https://github.com/p4ulbr4dl3y/johnston/commit/b3dc4927601f1994e308acc410074947056b9f1c))
* **config:** make max_concurrent_subagents user configurable ([ea10eab](https://github.com/p4ulbr4dl3y/johnston/commit/ea10eabb803f80da324bbdb38be299b9bc6080fd))
* **config:** simplify model selection and auto title configuration ([d4b03d3](https://github.com/p4ulbr4dl3y/johnston/commit/d4b03d3da45070b71554de179bf411c6643b1b5c))
* **converter:** implement pure lightweight document converter ([ecabf55](https://github.com/p4ulbr4dl3y/johnston/commit/ecabf556902bfaf84a21df62d26ce3dcc0e3e315))
* **infra:** add temp images cleanup by age on startup ([67ca91a](https://github.com/p4ulbr4dl3y/johnston/commit/67ca91a896c89c7f6be1dc05d20a3240377e3d15))
* **mcp:** support sse transport, roots, resources, and prompts ([745229a](https://github.com/p4ulbr4dl3y/johnston/commit/745229a93489ee31772ac337664305e31f25f7d3))
* **read:** support archive inspection and clean doc converter ([8e925b7](https://github.com/p4ulbr4dl3y/johnston/commit/8e925b7e63d062f701174ec85a352a59d3e46eef))
* **roles:** support wildcard glob patterns in tool policies ([27847ea](https://github.com/p4ulbr4dl3y/johnston/commit/27847ea76d48092f6abd03c2dc7bd2865b00531d))
* **rules:** support .clinerules, copilot-instructions, and cursor mdc ([7e4a260](https://github.com/p4ulbr4dl3y/johnston/commit/7e4a26055129e6a5eaf1fc8eec562013c9d4019f))
* **session:** add background session auto-titling ([c40c01c](https://github.com/p4ulbr4dl3y/johnston/commit/c40c01c3ec8a7d7948b454e38c542cd3790f7c14))
* **session:** add lazy fork, tree depth in resume, and safe rewind ([48d9e1a](https://github.com/p4ulbr4dl3y/johnston/commit/48d9e1a48e4fb51039f4427ec3cfd66edd1f5b87))
* **session:** add multi-tier json-first auto-title parsing ([d39b391](https://github.com/p4ulbr4dl3y/johnston/commit/d39b391e01babe044527d961dc3f72ea20905ae0))
* **session:** enable auto-titling for forked sessions ([0c1f9ce](https://github.com/p4ulbr4dl3y/johnston/commit/0c1f9ce83c1bbb69a3be57ffed1d52f09107df49))
* **skills:** expand johnston-guide references and documentation ([13a484b](https://github.com/p4ulbr4dl3y/johnston/commit/13a484be0388aed1b6fab3218c540df7145a9a8b))
* **theme:** add native adaptive theme and improve UI styling ([05cc687](https://github.com/p4ulbr4dl3y/johnston/commit/05cc6871eb89bd472cd5760f3f6165c82387594d))
* **theme:** decouple core manager and add cross-platform osc queries ([e617722](https://github.com/p4ulbr4dl3y/johnston/commit/e6177223c4c032995086c041d07a2eaec143ab47))
* **theme:** make native theme fully adaptive across terminals and OS ([436c51f](https://github.com/p4ulbr4dl3y/johnston/commit/436c51ffa6583662268c3e8af5c0858d602b1c84))
* **theme:** make zinc soft dark and add zinc-oled theme ([4edc497](https://github.com/p4ulbr4dl3y/johnston/commit/4edc497e58b354b08777722324fb70399676529b))
* **theme:** refactor theme manager and add trending themes ([b81fc08](https://github.com/p4ulbr4dl3y/johnston/commit/b81fc08c1c5097ae679f27cea0221b41a2652faa))
* **theme:** sort dark themes first followed by light themes in /themes ([b10520d](https://github.com/p4ulbr4dl3y/johnston/commit/b10520d5cf6c5bd3723fa1dce09453eb571b9641))
* **theme:** support tcss variable interpolation in markdown styles ([46b5e67](https://github.com/p4ulbr4dl3y/johnston/commit/46b5e67986858bdd4bc229d054363f505d39c71d))
* **tools:** add whitespace-agnostic matching and auto-indent to edit ([d42f81e](https://github.com/p4ulbr4dl3y/johnston/commit/d42f81e115d012af237a126f36d9e7d0eb143adb))
* **tools:** support concurrent execution for read-only tools ([070c7f8](https://github.com/p4ulbr4dl3y/johnston/commit/070c7f8789f08ef938a23c8d817a4e73ad6d95d7))
* **ui:** add 2-step flow with stdin and live log to /shell modal ([dad26e3](https://github.com/p4ulbr4dl3y/johnston/commit/dad26e35921a12b69d720f0a1e7490c11977a00a))
* **ui:** add ctrl+h to hide plan notch and skip restoring completed plans ([a400633](https://github.com/p4ulbr4dl3y/johnston/commit/a4006330555da8d418f6267a156396797bbd4902))
* **ui:** add duration to subagents modal and clean task badges ([f2c7a96](https://github.com/p4ulbr4dl3y/johnston/commit/f2c7a96f754fe0e4edd137ccabb0d73af4e03a54))
* **ui:** add floating top notch toast and fix chat scroll spacing ([206abf6](https://github.com/p4ulbr4dl3y/johnston/commit/206abf6afd0af2025c18f8bb95f58bc7e0fbba4f))
* **ui:** add multi-language layout normalization and key aliases ([05665b8](https://github.com/p4ulbr4dl3y/johnston/commit/05665b8f4c0aee7c6b215e9daa275b90bb952688))
* **ui:** implement live plan notch update and auto-clear logic ([6abd75d](https://github.com/p4ulbr4dl3y/johnston/commit/6abd75dfc9d70637e2b00168ec7d5fa9ffae820c))
* **ui:** implement monochrome plan notch with sliding window ([7d61b94](https://github.com/p4ulbr4dl3y/johnston/commit/7d61b947f75a9b3757148054f6f524334bf54344))
* **ui:** soften status dot and accent colors for zinc palette ([bfaa361](https://github.com/p4ulbr4dl3y/johnston/commit/bfaa36140b9d298213473e5d6796ade56d26facd))
* **ui:** style modal hotkey hints matching status footer theme ([b7bdfa4](https://github.com/p4ulbr4dl3y/johnston/commit/b7bdfa47a75dc4aca71f3c846b48f01f1f022d35))
* **ui:** unify markdown table cell and inline code backgrounds ([2831258](https://github.com/p4ulbr4dl3y/johnston/commit/28312586d2509344822f5bb162c8999fd20de715))
* **ui:** unify subagent hud layout and format footer hotkeys ([2ab2342](https://github.com/p4ulbr4dl3y/johnston/commit/2ab2342605a00bd4ac0be0b60e580ee592c8c710))


### Bug Fixes

* **config:** handle null/invalid json, env 0 values and per-file cache ([eec03a1](https://github.com/p4ulbr4dl3y/johnston/commit/eec03a177a41b04acbc7b5c67e7df3687b3af7cd))
* **config:** honor configured limits instead of hardcoded values ([ee8ff8d](https://github.com/p4ulbr4dl3y/johnston/commit/ee8ff8d3459f6b061f557f5f2140d026744e9224))
* **config:** honor dead UI and storage settings ([0d220ee](https://github.com/p4ulbr4dl3y/johnston/commit/0d220ee7184df9a200cb325f2ac2a5f3f5fdc357))
* **config:** resolve reviewer findings for edge cases and path normalization ([224499c](https://github.com/p4ulbr4dl3y/johnston/commit/224499ceb97a46879e270ce3fa2794953b516c31))
* **converter:** handle errors, anchors, scripts and formula cells ([ad55fa6](https://github.com/p4ulbr4dl3y/johnston/commit/ad55fa63ec1b07efbb1ce88ecfc0651d6c08267b))
* **converter:** improve docx, html, xlsx and ipynb parsing ([775e282](https://github.com/p4ulbr4dl3y/johnston/commit/775e282af336e26caa075a1cd3d23308a0d0f9db))
* **converter:** improve edge case handling, encoding and tag parsing ([edf4ccb](https://github.com/p4ulbr4dl3y/johnston/commit/edf4ccb62550c6d3d9e1701ef69debc4c04b3dfa))
* **converter:** repair layout-mode pdf, data-loss and robustness issues ([de3d7d9](https://github.com/p4ulbr4dl3y/johnston/commit/de3d7d92af79d0854e40975bf9657c86bf56fbe2))
* **converter:** resolve crashes, leaks and formatting in doc parsers ([3272ad7](https://github.com/p4ulbr4dl3y/johnston/commit/3272ad788e74cb167f18b070b92f4a0facf3bdfa))
* **converter:** resolve edge cases and expand doc converter tests ([d74b4aa](https://github.com/p4ulbr4dl3y/johnston/commit/d74b4aafedf58c8c55f109ee40a07aeebf5a06a2))
* **converter:** stop content loss and mangling in md conversions ([eb434eb](https://github.com/p4ulbr4dl3y/johnston/commit/eb434ebe04416317e1591cc9484af1c2cf7810e5))
* **core:** wrap rule content in CDATA section ([0904786](https://github.com/p4ulbr4dl3y/johnston/commit/09047867d930390dfaecbdafe54f143e0989f912))
* **diff:** balance green and red OKLab luminosity for diff view ([d7823c1](https://github.com/p4ulbr4dl3y/johnston/commit/d7823c1e6c78dec01bd0c8205ba6e30fcc58fefa))
* **diff:** use theme-adaptive colors for diff lines and stats markup ([3bf1d64](https://github.com/p4ulbr4dl3y/johnston/commit/3bf1d646bdbc8933bb7aed249ce3fe387bec0619))
* **plan:** robust app binding and notify on empty plan toggle ([ca94d31](https://github.com/p4ulbr4dl3y/johnston/commit/ca94d317ceeecd595b8b4fa876c705619508e5a2))
* **session:** avoid baking ellipsis into stored auto-titles ([ccea211](https://github.com/p4ulbr4dl3y/johnston/commit/ccea211038f3bb1e70d796aa21b18f8d7350d234))
* **session:** avoid evaluating client property in auto title ([39f43e6](https://github.com/p4ulbr4dl3y/johnston/commit/39f43e600d988073de34ff69e7b8b21b4247733a))
* **session:** skip save and touch when session state unchanged ([ddae547](https://github.com/p4ulbr4dl3y/johnston/commit/ddae547f5531f5db2e53d3981f0aa4b146935936))
* **sessions:** preserve auto-generated titles on save and reload ([b617749](https://github.com/p4ulbr4dl3y/johnston/commit/b617749b3b9717db32dc79cc670cf2034d7ef10f))
* **streaming:** handle reasoning token limits and add sparse config ([59367b3](https://github.com/p4ulbr4dl3y/johnston/commit/59367b370f9eef8fa2d58d144859bfb887d62afb))
* **theme:** improve markdown syntax styling and runtime switching ([e9037d1](https://github.com/p4ulbr4dl3y/johnston/commit/e9037d148d834a06aff14d56cda2a800ad886a3c))
* **theme:** lighten tool header and boost charcoal hover fg-primary ([a249a01](https://github.com/p4ulbr4dl3y/johnston/commit/a249a018140c726bc1b337e2fa33e16cfb0a21b1))
* **theme:** make charcoal subtle color monochrome for clean footer ([a9bba5c](https://github.com/p4ulbr4dl3y/johnston/commit/a9bba5c00bf1d8f9721c10641d2b098bf63a2284))
* **themes:** harmonize color palettes and contrast across all themes ([76d3c4a](https://github.com/p4ulbr4dl3y/johnston/commit/76d3c4ac974742c6e02b11356b151bf56f8c8e26))
* **theme:** support python 3.10 cbrt and skip posix tests on windows ([40ec0bc](https://github.com/p4ulbr4dl3y/johnston/commit/40ec0bcc0a376e45a6384144320b119b1e9804d2))
* **theme:** use dynamic theme colors and fix light theme contrast ([632b2f7](https://github.com/p4ulbr4dl3y/johnston/commit/632b2f704a9dfdf6af9a420a034e54ed99fd061c))
* **tools:** restore dynamic tool registry fallback and agent tool wiring ([0e9b29f](https://github.com/p4ulbr4dl3y/johnston/commit/0e9b29f90eea924baa7b4923398eb97456795b35))
* **tools:** route xlsm and ppsx reads through document converter ([34f35ee](https://github.com/p4ulbr4dl3y/johnston/commit/34f35eef58a32f7eca7a8b108e32d508118b4382))
* **tools:** track concurrent tool widgets correctly ([373cac9](https://github.com/p4ulbr4dl3y/johnston/commit/373cac9a5a5da26639fb818dd888a5ed6b1b9ba6))
* **ui:** defer plan notch display until session loading completes ([af3156d](https://github.com/p4ulbr4dl3y/johnston/commit/af3156d0133a4026ac9607405f77bc75300a3433))
* **ui:** expand command suggestions description to full row budget ([e5a79f3](https://github.com/p4ulbr4dl3y/johnston/commit/e5a79f3ba867fd2cbc6dd0f323a62e0c00d0ad5b))
* **ui:** fix tool hover visibility and use semantic markup colors ([e4f0e37](https://github.com/p4ulbr4dl3y/johnston/commit/e4f0e37b4e67eb20069d52497a1ea3604ff00485))
* **ui:** flush modal option badges right with zero option padding ([3df8d9b](https://github.com/p4ulbr4dl3y/johnston/commit/3df8d9b169bf505632aeeefb5231717ecc50d123))
* **ui:** format sub-tenth durations and sub-cent costs properly ([c4d4931](https://github.com/p4ulbr4dl3y/johnston/commit/c4d4931fe3266c1042f951660719d6b8195578b7))
* **ui:** handle markup escaping and edge cases in plan notch ([7653cd9](https://github.com/p4ulbr4dl3y/johnston/commit/7653cd9721a99f8001be10808b29a378f6393f0f))
* **ui:** include esc hint in help, mcp and skills refresh views ([a061de5](https://github.com/p4ulbr4dl3y/johnston/commit/a061de5c8a64554b8648b352275bd078a7f899a9))
* **ui:** prevent black loading dots in transparent native theme ([9a1210d](https://github.com/p4ulbr4dl3y/johnston/commit/9a1210da04766fb77220ca10758f511e16372796))
* **ui:** scroll to bottom and enable auto follow on rewind ([d4b26af](https://github.com/p4ulbr4dl3y/johnston/commit/d4b26afc983431e1ff06086e435e8a236e9edc45))
* **ui:** use clean text color hover for expandable tool headers ([6eb0f73](https://github.com/p4ulbr4dl3y/johnston/commit/6eb0f734d3b66da7506ec7d352c937aea1f6e77a))
* **ui:** use transparent modal overlay for native and ansi themes ([73441c3](https://github.com/p4ulbr4dl3y/johnston/commit/73441c37b3ccd1e7d5512c945456f789478da606))


### Documentation

* **guide:** update config reference schema and environment variables ([ad4b7bd](https://github.com/p4ulbr4dl3y/johnston/commit/ad4b7bd18dcffacdf84c6b75ae979bd94e8696c3))
* **tools:** update read and web_fetch schemas for new formats ([4dc27c6](https://github.com/p4ulbr4dl3y/johnston/commit/4dc27c6a063c20332cbf68ea6c9965950e1bdc8d))

## [0.27.1](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.27.0...johnston-v0.27.1) (2026-08-28)


### Bug Fixes

* **commands:** sync full history for rewind, fork and checkpoints ([f08381c](https://github.com/p4ulbr4dl3y/johnston/commit/f08381cad9a3c01a458efd54edfe28587839c79a))
* **core:** remove pointer-based message key caching in agent ([54ecc5c](https://github.com/p4ulbr4dl3y/johnston/commit/54ecc5ca02df6872c859365327f10f6090e327d8))
* **core:** resolve config helpers paths at call time ([7dd99d8](https://github.com/p4ulbr4dl3y/johnston/commit/7dd99d8ac9bb5dd977aab6b9dc86c74f6cda117e))
* **ui:** fix autoscroll race and infinite pagination trigger on scroll ([fb9aa28](https://github.com/p4ulbr4dl3y/johnston/commit/fb9aa2811508ad91c9635eb674591821ef5fd0e8))
* **ui:** use height compensation on scroll up instead of reactive watch ([3315caa](https://github.com/p4ulbr4dl3y/johnston/commit/3315caa56b336c5651d1c56417ab514a64731dfd))


### Performance Improvements

* **screens:** optimize modal load times, catalog lookups and git diffs ([76cfe5f](https://github.com/p4ulbr4dl3y/johnston/commit/76cfe5f30815478776652596e226ef3eccf0cd96))
* **ui:** add lazy pagination and scroll autoloading to chat view ([aff6133](https://github.com/p4ulbr4dl3y/johnston/commit/aff6133221681416845c5bfdac454a62adf9c60a))

## [0.27.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.26.0...johnston-v0.27.0) (2026-08-27)


### Features

* **core:** migrate tool results and prompts to xml format ([e28a294](https://github.com/p4ulbr4dl3y/johnston/commit/e28a294fed53c6fec3bce5ffb5b3be365f4e7b81))
* **permissions:** introduce execution modes and cycle toggle ([38e7bcc](https://github.com/p4ulbr4dl3y/johnston/commit/38e7bcc8b4aab6619477f68b6d0cf87851d8b3e3))
* **security:** add xml escaping for prompt injection protection ([4c4bf12](https://github.com/p4ulbr4dl3y/johnston/commit/4c4bf12a024afb5e56413809a5a361097c7c1dfe))
* **selection:** budget OptionList max_height across all selection dialogs ([d37d220](https://github.com/p4ulbr4dl3y/johnston/commit/d37d220dbdd548dc53e058c05745c01b7bda4720))
* **session:** add /rename command and modal to rename active session ([71e7f6e](https://github.com/p4ulbr4dl3y/johnston/commit/71e7f6e96bae6c41348f9fd7f845ff5795914a51))
* **session:** add copy-on-write auto-fork for read-only sessions ([96395d8](https://github.com/p4ulbr4dl3y/johnston/commit/96395d811e5d7e91fc470f4df62bce04ff34af01))
* **session:** add session locking and conflict resolution ([2c858be](https://github.com/p4ulbr4dl3y/johnston/commit/2c858be0fa961767c717a8686d932de8c4f6e52b))
* **session:** add unified /fork command and session branching ([d1ead54](https://github.com/p4ulbr4dl3y/johnston/commit/d1ead54dbbeec102a9512bed31ee9701fe9c5c4e))
* **session:** derive smart fork title from selected branch message ([46c4a02](https://github.com/p4ulbr4dl3y/johnston/commit/46c4a02dd83d9806c1350637accc171975dc5d85))
* **subagent:** inherit sandbox and enforce UI permission prompts ([d920a64](https://github.com/p4ulbr4dl3y/johnston/commit/d920a647f81324d691ba74f1304b13180181da36))
* **subagents:** add worktree guidelines and auto-commit prompts ([16e4a84](https://github.com/p4ulbr4dl3y/johnston/commit/16e4a84ff38a90683058c3b9f22ca9ae754687af))
* **subagents:** prefix subagent rows with role name in tasks modal ([9c6163c](https://github.com/p4ulbr4dl3y/johnston/commit/9c6163cca115ca6bac7740124b529281636e4f97))
* **tasks:** handle silent commands without output in console view ([6f5785e](https://github.com/p4ulbr4dl3y/johnston/commit/6f5785e120195a6c326e74f54f9c9304d326f232))
* **tools:** inherit host sandbox mode for subagents ([3fab65e](https://github.com/p4ulbr4dl3y/johnston/commit/3fab65e732a4d01cb94d889693fb934460635d7d))
* **tools:** require noun phrase for invoke_subagent title ([18003f1](https://github.com/p4ulbr4dl3y/johnston/commit/18003f1d4e99922fe9834889c2865a7694658d08))
* **ui:** adapt permission confirm dialog width to content ([8d6c0df](https://github.com/p4ulbr4dl3y/johnston/commit/8d6c0dff642eed4d2cd5c997fc5463de2c2ac505))
* **ui:** add ctrl+r keybinding to refetch models in model modal ([ced9129](https://github.com/p4ulbr4dl3y/johnston/commit/ced9129ff6fd9bf17f1029282d02167af66e8f48))
* **ui:** add inline expand and click actions for manage tools ([23afb57](https://github.com/p4ulbr4dl3y/johnston/commit/23afb57955f314039d53f632c59a808dce910ee9))
* **ui:** add responsive single/dual-pane layout to diff viewer ([ab0822d](https://github.com/p4ulbr4dl3y/johnston/commit/ab0822ddefdb889ff5b666cdc165500e0cd0bb48))
* **ui:** add search to modals, interactive help tabs and fix heights ([77972fa](https://github.com/p4ulbr4dl3y/johnston/commit/77972fa11c966df506715f75c685338d71054c03))
* **ui:** consolidate responsive design onto shared breakpoints and debounced resize ([e25afd4](https://github.com/p4ulbr4dl3y/johnston/commit/e25afd4bc7b0f32e4fe5e85ed9186bca2b2241a0))
* **ui:** display line ranges and byte offset in read tool chip ([9fd898b](https://github.com/p4ulbr4dl3y/johnston/commit/9fd898bd65fcbaefeb5e0d65beaa8674cb07e6d3))
* **ui:** format subagent worktree paths in status footer ([9fe74db](https://github.com/p4ulbr4dl3y/johnston/commit/9fe74dbec04afd78268184382ab40bf068f50ff8))
* **ui:** format update_plan chip with active step or done status ([1181388](https://github.com/p4ulbr4dl3y/johnston/commit/11813885f693cc17fbfcaa78b0f17ca210f0f73a))
* **ui:** include role prefix in invoke_subagent tool chip ([04044a1](https://github.com/p4ulbr4dl3y/johnston/commit/04044a1d251d859dd5edf35700a1976cdfe93ae9))
* **ui:** multi-step providers screen and current state session fork ([8e5071a](https://github.com/p4ulbr4dl3y/johnston/commit/8e5071a0b981756f1bf979e8a28bd331c0274d5e))
* **ui:** reflect execution mode and sandbox-off in status footer ([9288602](https://github.com/p4ulbr4dl3y/johnston/commit/9288602f0a8ef5ded9e5005174ab94744b8418ea))
* **ui:** size small modals to content instead of stretching to terminal width ([49a2f51](https://github.com/p4ulbr4dl3y/johnston/commit/49a2f512f44037be38d345cf206702db32b6c34d))
* **wizard:** enable scrolling in answers summary step via arrows and pgup/pgdn ([9384860](https://github.com/p4ulbr4dl3y/johnston/commit/938486021448578a83a24e9c312091192307adb9))


### Bug Fixes

* **compaction:** stop clobbering API context with heuristic estimate ([f15abed](https://github.com/p4ulbr4dl3y/johnston/commit/f15abedb3ed98aa400dcd0c53f282a49be8557c4))
* **core:** improve logging setup and background notification tests ([11283dd](https://github.com/p4ulbr4dl3y/johnston/commit/11283dd534a8d7e69457ef5c7b721f046e2f14bc))
* **core:** invalidate permission snapshot when config path changes ([130e04b](https://github.com/p4ulbr4dl3y/johnston/commit/130e04b8e5053644ffc852e35efbef03895c31a0))
* **core:** portable session lock metadata and checkpoint purge ([f2b4636](https://github.com/p4ulbr4dl3y/johnston/commit/f2b4636682938c786012394c12a89ee4866d2991))
* **core:** scope skill manager cache to global skills dir ([cbf3d81](https://github.com/p4ulbr4dl3y/johnston/commit/cbf3d81a5d9ec7b90fa4f3780d539d8604ba049a))
* **diff:** fix keyboard navigation and pgup/down after tab toggle ([e956d91](https://github.com/p4ulbr4dl3y/johnston/commit/e956d91377c4b80d899e2336ba4f6bfd3f6e325a))
* **footer:** dynamically scale model name budget in compact mode ([bd65788](https://github.com/p4ulbr4dl3y/johnston/commit/bd6578840c7a0b775bc210d3a864fb53e398c801))
* **permissions:** adapt layout dynamically when reject feedback input opens ([0add9fb](https://github.com/p4ulbr4dl3y/johnston/commit/0add9fb587d84a3ef304a5d183404e7ab6a1c548))
* **permissions:** compute exact scrollbox budget guaranteeing hint visibility ([521ed9f](https://github.com/p4ulbr4dl3y/johnston/commit/521ed9f751e10e1a8425e2d85a9480f5202279e6))
* **permissions:** forward pageup/pagedown to code box and lock outer layout ([87e1fed](https://github.com/p4ulbr4dl3y/johnston/commit/87e1feded46b0a03fe10ecf88695409804778be3))
* **permissions:** guarantee hint visibility across all terminal heights ([88da0fa](https://github.com/p4ulbr4dl3y/johnston/commit/88da0fab1c8ad20187786ad2ab4b65a047136827))
* **permissions:** lock outer dialog and scroll only tool content box ([b34dcae](https://github.com/p4ulbr4dl3y/johnston/commit/b34dcae51299368f3e1ddaa2e5268c917124ef37))
* **permissions:** restore default hint when navigating back to options list ([89ffad2](https://github.com/p4ulbr4dl3y/johnston/commit/89ffad249ccdec04bb845a22ee85b68d3aa41eaa))
* **permissions:** scale modal dialog and option list on low height terminals ([92ef914](https://github.com/p4ulbr4dl3y/johnston/commit/92ef91445b0c38ff926b56368a2569f831bc8003))
* **prompt:** include skill file path in prompt xml ([948defd](https://github.com/p4ulbr4dl3y/johnston/commit/948defdf220b6a9d7a4a4753f6f4dede2941c72e))
* **resume:** eliminate modal width jumping on session conflict step ([1a42653](https://github.com/p4ulbr4dl3y/johnston/commit/1a426536ceb8129221359a1541168b44898a3fde))
* **resume:** implement in-place conflict resolution matching rewind UX ([4b392b2](https://github.com/p4ulbr4dl3y/johnston/commit/4b392b2fda99bbd416d9797b40febbd606140752))
* **resume:** prevent event bubbling during step 2 conflict transition ([9774d2e](https://github.com/p4ulbr4dl3y/johnston/commit/9774d2ebaae41ba889ac807cfae894739defb2d3))
* **sandbox:** allow common package manager and build cache roots ([9b278fe](https://github.com/p4ulbr4dl3y/johnston/commit/9b278fec37c3a3e52640f06c8712c0aef8db8b3d))
* **session:** fix step counting fallback for disk and in-memory sessions ([bbddf5f](https://github.com/p4ulbr4dl3y/johnston/commit/bbddf5f436238d044ed97a530c1c3eacf9540d6f))
* **session:** lazily instantiate session on rename if not yet in sm ([fc4cae1](https://github.com/p4ulbr4dl3y/johnston/commit/fc4cae1b9a06b577de196deae953632dfd7c5ecf))
* **session:** prevent duplicate event dividers in session messages ([af68771](https://github.com/p4ulbr4dl3y/johnston/commit/af6877123132bb7c332602357f53444212b955be))
* **tasks:** compute dialog width from filtered tasks before rendering rows ([f361268](https://github.com/p4ulbr4dl3y/johnston/commit/f3612684f6b8e310198919b68362b25ec67aa3c4))
* **tools:** harden shell, web_fetch, and git diff edge cases ([2204ef5](https://github.com/p4ulbr4dl3y/johnston/commit/2204ef55ac9fb87d0dd213b11a15362c0af76267))
* **tools:** make new_str optional in edit schema ([b303557](https://github.com/p4ulbr4dl3y/johnston/commit/b30355761430b1c71c599eed4e4ad82412498c90))
* **tools:** propagate task log path on background shell completion ([1daac1a](https://github.com/p4ulbr4dl3y/johnston/commit/1daac1a3fc04812ee1686ffde19bbec35ad193c5))
* **ui:** adapt modal option badge widths on mount and resize ([17370e9](https://github.com/p4ulbr4dl3y/johnston/commit/17370e9518f683dc89bc83f9940a51445ed94cdf))
* **ui:** add top and bottom spacing and background to docked modal hint ([fe79146](https://github.com/p4ulbr4dl3y/johnston/commit/fe791464a12f4fef810885e5156b558473cf02e5))
* **ui:** adjust fork title truncation to match exact ellipsis column ([bc8fb47](https://github.com/p4ulbr4dl3y/johnston/commit/bc8fb47ba0ad47f776fe306dd1779433d4152926))
* **ui:** align ellipsis boundary for forked session titles in resume modal ([8dcd130](https://github.com/p4ulbr4dl3y/johnston/commit/8dcd1300c9d2bb9658d6de290134aa65f1a0d716))
* **ui:** apply adaptive content-fitting across all modal screens ([be98326](https://github.com/p4ulbr4dl3y/johnston/commit/be98326f990a2e33dc68ce79224f44c55c456872))
* **ui:** cap natural text width in permission confirm dialog ([85ca1ce](https://github.com/p4ulbr4dl3y/johnston/commit/85ca1ce4b00e960b5cb95524fe29480029055bda))
* **ui:** disable footer select and require drag to copy selection ([b2d9d7b](https://github.com/p4ulbr4dl3y/johnston/commit/b2d9d7bef8de18a9e15fade140fb2edd8b448ce3))
* **ui:** dock modal hints to bottom across all modal screens ([9102fda](https://github.com/p4ulbr4dl3y/johnston/commit/9102fda4280b70097f9315d14af7ce7fe138e765))
* **ui:** dynamic footer row 2 scaling and full fork title preservation ([afeba2c](https://github.com/p4ulbr4dl3y/johnston/commit/afeba2c54a3a4f9b789cf1a1aa4052f15ac7b8e4))
* **ui:** dynamically fit RewindScreen per step to eliminate dead space ([d6202dc](https://github.com/p4ulbr4dl3y/johnston/commit/d6202dcc7bf1e00393ada373592cf64c2948d360))
* **ui:** enable responsive content-hugging in ForkScreen ([c586088](https://github.com/p4ulbr4dl3y/johnston/commit/c586088de8917a45f784ef5711ed79edf03c5cc7))
* **ui:** enhance responsive layout, low-height scaling and footer ([fc567c0](https://github.com/p4ulbr4dl3y/johnston/commit/fc567c08564e83ba3df28f2865cf8ddb7bb937ea))
* **ui:** expand help modal dialog width and table layout ([fdb732e](https://github.com/p4ulbr4dl3y/johnston/commit/fdb732e02bd9779dabe5cf55a72fc29692232487))
* **ui:** expand text-heavy modals to wide responsive layout ([e604aab](https://github.com/p4ulbr4dl3y/johnston/commit/e604aab2d79daf881ba016827238b074be5bdee7))
* **ui:** fix content width measurement in MCPScreen and tasks ([cffc28e](https://github.com/p4ulbr4dl3y/johnston/commit/cffc28ec917f7a190aaaabae8d67a24aa7600103))
* **ui:** fix right-badge alignment with markup prefix in resume modal ([0989467](https://github.com/p4ulbr4dl3y/johnston/commit/09894677281e9effb8eee81e1c287551ae4dd324))
* **ui:** handle task cancellation and clean empty shell output ([3ef112f](https://github.com/p4ulbr4dl3y/johnston/commit/3ef112f787dedc5cc9b95bca3df59064a25bac80))
* **ui:** improve modals layout, key input and summary scrolling ([f2156b6](https://github.com/p4ulbr4dl3y/johnston/commit/f2156b604f18a050b273eedcfa71a101eca1bb07))
* **ui:** improve responsive title truncation and modal adaptivity ([36b4a1f](https://github.com/p4ulbr4dl3y/johnston/commit/36b4a1ff8c0f8ed074afb2ec8547bb43d2833a82))
* **ui:** improve responsiveness and hints across modal screens ([821e8a7](https://github.com/p4ulbr4dl3y/johnston/commit/821e8a755471834efb39af10437a8eabcf94420d))
* **ui:** initialize log_path on ToolCallWidget to prevent toast error ([a5a8791](https://github.com/p4ulbr4dl3y/johnston/commit/a5a87911b0e20f6c5d94f7601e4f023f449caf84))
* **ui:** isolate keybindings in subagent screen via ModalScreen ([1f8804e](https://github.com/p4ulbr4dl3y/johnston/commit/1f8804e2954c2b1fb666921cabd5d703a3c0348f))
* **ui:** lock outer modal dialog frame to prevent container scrolling ([97ab897](https://github.com/p4ulbr4dl3y/johnston/commit/97ab897f60756d22a0ffc4a41cf315ea40d1362c))
* **ui:** match modal width between ResumeScreen and SessionConflictScreen ([579167b](https://github.com/p4ulbr4dl3y/johnston/commit/579167b7e88c12057f9d8d736429e6cb935dd81f))
* **ui:** preserve cursor selection on back navigation from conflict screen ([839ac4a](https://github.com/p4ulbr4dl3y/johnston/commit/839ac4a76f879a20b4d44389de063e60cb8cb15f))
* **ui:** preserve full-width sidebar options across diff view toggles ([e92d539](https://github.com/p4ulbr4dl3y/johnston/commit/e92d53931a971a32cb28a9c07fbae507fe70c01b))
* **ui:** remove dock from modal hint to prevent overlapping content ([319e247](https://github.com/p4ulbr4dl3y/johnston/commit/319e247c3ebe7e5c4508242733efd9e26e5eca72))
* **ui:** reset subagent tool aggregation on step boundaries ([dfa75bf](https://github.com/p4ulbr4dl3y/johnston/commit/dfa75bfb7665c00f807a1a52ec86b132d4bcbeaf))
* **ui:** resolve mouse click selection and badge alignment in modals ([aef02f9](https://github.com/p4ulbr4dl3y/johnston/commit/aef02f9268f6331d4668adadc113fcc13e10e894))
* **ui:** restore git branch in status footer ([325668f](https://github.com/p4ulbr4dl3y/johnston/commit/325668fd36b8e8c383760062938063dafd875366))
* **ui:** return to resume screen on esc in SessionConflictScreen ([f15ce2d](https://github.com/p4ulbr4dl3y/johnston/commit/f15ce2d3f4a13e61a21d7325ba5142c3ab58ed99))
* **ui:** streamline tool expansion and subagent click behavior ([4bc30cd](https://github.com/p4ulbr4dl3y/johnston/commit/4bc30cd8b0e53849110248f7273edf5abff240c6))
* **ui:** wrap help table in scrollbox to prevent hint overlap ([099d7a6](https://github.com/p4ulbr4dl3y/johnston/commit/099d7a66c7e7339b71255229bb6451b90c93f698))
* **wizard:** budget option list height ensuring hint visibility on small screens ([9262230](https://github.com/p4ulbr4dl3y/johnston/commit/9262230a734ccdaa6821d0121cece384aa01e995))
* **wizard:** normalize margin below summary title to standard single gap ([33a1d0d](https://github.com/p4ulbr4dl3y/johnston/commit/33a1d0d8871d6dffca421d1efafa9e012602a457))
* **wizard:** stabilize ask_user dialog width across all question steps ([7f82440](https://github.com/p4ulbr4dl3y/johnston/commit/7f82440d20ff006ea7b7dc685cc3da6d13ce9967))


### Performance Improvements

* **core:** resolve UI, async loop, tool and git storage bottlenecks ([c170bdf](https://github.com/p4ulbr4dl3y/johnston/commit/c170bdfd0d2efb10407977afbf7f273b8809a31e))

## [0.26.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.25.0...johnston-v0.26.0) (2026-08-25)


### Features

* **checkpoints:** archive purged states with ttl and harden snapshot pipeline ([ffa92e3](https://github.com/p4ulbr4dl3y/johnston/commit/ffa92e3ec2c93ce404200ae374f66526750dd560))
* **core:** update tool display, task screens and shell hint ([81c4b45](https://github.com/p4ulbr4dl3y/johnston/commit/81c4b452b8d0183c403903f51ed97bda287343eb))
* **diff:** add full-screen diff viewer and rewind integration ([69dbb02](https://github.com/p4ulbr4dl3y/johnston/commit/69dbb02c286d2d2bda5228485ce13923cd7d4d31))
* **diff:** add live search filter to sidebar files list ([0abc5b3](https://github.com/p4ulbr4dl3y/johnston/commit/0abc5b3785e5ae5d870d2a5e800e5757ecd7e737))
* **permissions:** add pattern-level rules for tools and shell commands ([d2400f9](https://github.com/p4ulbr4dl3y/johnston/commit/d2400f91cf2709d0208535c2021a0674d7ea2b40))
* **provider:** harden config handling, env keys, base_url templates ([699d5bc](https://github.com/p4ulbr4dl3y/johnston/commit/699d5bcefa73d16e40681b5c60a631e26766cdcd))
* **provider:** support native api cost and granular cache pricing ([86b3c71](https://github.com/p4ulbr4dl3y/johnston/commit/86b3c71dce26cb5189175837d6cd8a62cf225034))
* **runtime:** keep strong refs on fire-and-forget background tasks ([06cd70d](https://github.com/p4ulbr4dl3y/johnston/commit/06cd70db2253e0efd0385047aa070e5cd0f5d76d))
* **sandbox:** add comprehensive cross-platform credential deny paths ([734fd40](https://github.com/p4ulbr4dl3y/johnston/commit/734fd40c3ca50051ebc7fd8e10ddb7de7825f8e4))
* **sandbox:** add read-only role policy and sandbox restrictions ([037edb5](https://github.com/p4ulbr4dl3y/johnston/commit/037edb501dd0be3605fd075d694a6bf225694160))
* **sandbox:** add shell sandbox toggle and os-level isolation ([0acfca0](https://github.com/p4ulbr4dl3y/johnston/commit/0acfca090c2162556573646ed5b3889eb5acd51d))
* **sandbox:** add windows safer restricted token sandbox backend ([70afb66](https://github.com/p4ulbr4dl3y/johnston/commit/70afb668cd036f293045d21b47e2db8003477712))
* **secrets:** centralize api keys in secrets.json with interpolation ([d1074fe](https://github.com/p4ulbr4dl3y/johnston/commit/d1074fe21c3cc03f7cd34a91c1d9cee9db6de818))
* **session:** add session scratchpad space with sandbox integration ([8b01800](https://github.com/p4ulbr4dl3y/johnston/commit/8b01800ca8661f5c89e9c0a11b43b41441a03475))
* **session:** persist and restore agent role in session data ([38648a1](https://github.com/p4ulbr4dl3y/johnston/commit/38648a1756605496d65a4faf537a1608b1996df1))
* **shell:** surface unsandboxed fallback when backend unusable ([a454663](https://github.com/p4ulbr4dl3y/johnston/commit/a454663645cc9ff79cc7ac27f714016a1b6ec863))
* **subagents:** enforce sandbox and autonomous allow execution ([8939f1c](https://github.com/p4ulbr4dl3y/johnston/commit/8939f1c249b7698f90e7c6f21ec0ee91d033d731))
* **tools:** clarify subagent reuse, branch merge, and shell schemas ([814049c](https://github.com/p4ulbr4dl3y/johnston/commit/814049c33376fe817e143ba78f940d826e17b97c))
* **ui:** add 2-step rewind flow for code vs conversation rollback ([1359f52](https://github.com/p4ulbr4dl3y/johnston/commit/1359f52d275a922e96e13b38fb862f0a1121f9c8))
* **ui:** add chat keyboard scroll, /copy command and pill help modal ([f2eaf21](https://github.com/p4ulbr4dl3y/johnston/commit/f2eaf2133a959b15cafb77b48dabd009a2e74711))
* **ui:** add placeholder support for ChatInput ([518eb8e](https://github.com/p4ulbr4dl3y/johnston/commit/518eb8ef23499ccd6aac33bd0df2fedb9debfc29))
* **ui:** add token count formatting for completed subagents ([2cef5a2](https://github.com/p4ulbr4dl3y/johnston/commit/2cef5a2df844912c8ff3ca1d3f3a348f82fc3367))
* **ui:** display changed files list in rewind step 2 ([7ae088a](https://github.com/p4ulbr4dl3y/johnston/commit/7ae088add9d8fb53ada003436e214bf091ca6582))
* **ui:** display live progress and status badge for shell tasks ([9be75e5](https://github.com/p4ulbr4dl3y/johnston/commit/9be75e5f6c82036689b5ba26af75b7613c1e6576))
* **ui:** display live progress badge for running subagents ([e1c058b](https://github.com/p4ulbr4dl3y/johnston/commit/e1c058bc9bc4e7aa86c2a36c378fc420adfb5a1d))
* **ui:** notify on copy and auto-copy ChatInput mouse selection ([d3f46ee](https://github.com/p4ulbr4dl3y/johnston/commit/d3f46ee7b1b0aa6404b9c874595347ea465cf1e5))
* **ui:** pop last attachment on ctrl+d and format as Image #N ([2f7adcd](https://github.com/p4ulbr4dl3y/johnston/commit/2f7adcdd385037b46c8f92dc77c5a88dcca0abae))
* **ui:** remove unused tab focus binding from diff screen ([9252a9d](https://github.com/p4ulbr4dl3y/johnston/commit/9252a9dfc881b5d7244766a26682f0fb73bdf256))
* **ui:** simplify sandbox toggle notifications ([ea8a1f8](https://github.com/p4ulbr4dl3y/johnston/commit/ea8a1f80e03e4357e6eb6a2074ec705c98a45018))
* **ui:** skip rewind confirmation step if no file changes exist ([9abf4b9](https://github.com/p4ulbr4dl3y/johnston/commit/9abf4b90ad6bbf20ef4939d8d8b89e85a8607daf))
* **ui:** strip git headers and add hunk separators in diff viewer ([7fb83d1](https://github.com/p4ulbr4dl3y/johnston/commit/7fb83d153921568d5c2b472d8fcade94169f46d1))
* **ui:** support subagent context and scroll keys in confirm modal ([1bafc75](https://github.com/p4ulbr4dl3y/johnston/commit/1bafc750126164f4dd4e73bc215192798876cb5b))
* **ui:** unify and add dynamic hotkey hints across modals and screens ([5488d3e](https://github.com/p4ulbr4dl3y/johnston/commit/5488d3e2d209e870cd0549355b0ff20db1ae144c))
* **ui:** unify ask_user summary answer format with checkmark ([3d2227e](https://github.com/p4ulbr4dl3y/johnston/commit/3d2227e5a678beee25e8adc9fc569daeaf99d784))
* **ui:** unify modal layouts and add rejection reason input ([e9f2ebb](https://github.com/p4ulbr4dl3y/johnston/commit/e9f2ebb8e5b3a3debc0fc0fb23bc6fe0ae24b6da))
* **ui:** use unicode status indicators and align list gutters ([b7db0c5](https://github.com/p4ulbr4dl3y/johnston/commit/b7db0c552bac61a13ca4f6ee37522266b4b18067))


### Bug Fixes

* **agent:** treat error finish reasons as retryable stream failures ([c32560d](https://github.com/p4ulbr4dl3y/johnston/commit/c32560db5e6ca8961db2b3d92c0f4fd83715d864))
* **core:** resolve concurrency, timeout and edge cases in git rewind ([881c4ad](https://github.com/p4ulbr4dl3y/johnston/commit/881c4adbe3f64cf844ddfa1857a1527eb5d455a7))
* **mcp:** tear down stale warmup client by identity, not by key ([d4347e8](https://github.com/p4ulbr4dl3y/johnston/commit/d4347e874ffd9820c36df50c1dfedf4bc5d58472))
* **mcp:** warm enabled server immediately and surface start errors in modal ([8c3a549](https://github.com/p4ulbr4dl3y/johnston/commit/8c3a549df5eae6df797c0cf029086ca594088f63))
* **mcp:** warn clearly on unsupported url-only servers ([42f20e1](https://github.com/p4ulbr4dl3y/johnston/commit/42f20e1564da0901485df3ac848befac845e5922))
* **permissions:** fail-closed pattern priority and strict action validation ([d9c4d79](https://github.com/p4ulbr4dl3y/johnston/commit/d9c4d79e6c940dc7278000bd1cdbcc8bbb4f9ec2))
* **sandbox:** add sensitive path masking to linux bubblewrap backend ([fa9e7d9](https://github.com/p4ulbr4dl3y/johnston/commit/fa9e7d9fe9dd614481aa587837903d98e5ae2969))
* **sandbox:** allow git worktrees and cache paths in sandbox ([d3eb32d](https://github.com/p4ulbr4dl3y/johnston/commit/d3eb32dc4d7c4873b16282b056fcfeea78c988a8))
* **sandbox:** fs-root extras grant nothing; probe bwrap usability ([0091894](https://github.com/p4ulbr4dl3y/johnston/commit/00918944bca68d69b351e301c62c6fc23d41fc2d))
* **sandbox:** harden path normalization, sbpl escaping, and win32 handles ([a93ee2a](https://github.com/p4ulbr4dl3y/johnston/commit/a93ee2a2fb5bcbebbdb2ce8bf57c6fded98ea7c8))
* **sandbox:** protect credentials, api keys and keychains from read ([b0fcf94](https://github.com/p4ulbr4dl3y/johnston/commit/b0fcf946fe456a5eaee6ad448374b2e6127a6cec))
* **sandbox:** scope protected read paths to johnston-guide configs ([1e5d4a8](https://github.com/p4ulbr4dl3y/johnston/commit/1e5d4a8199a96d0aa34b8939c6aa384af1bfa110))
* **session:** serialize rewind git restore against next turn snapshot ([757a969](https://github.com/p4ulbr4dl3y/johnston/commit/757a9697330f6afe3018c043ceeff8a843c5cb15))
* **tools:** enforce sandbox path checks on file operations ([f2b4a64](https://github.com/p4ulbr4dl3y/johnston/commit/f2b4a64b204979f0632cc6b63697ca092c4f0281))
* **tools:** harden argument coercion, validation and cancel handling ([4f40839](https://github.com/p4ulbr4dl3y/johnston/commit/4f40839f5211cda9f292a59928e3c32779d5caa6))
* **tools:** preserve process returncode in shell tool execution results ([29ed1e8](https://github.com/p4ulbr4dl3y/johnston/commit/29ed1e8ad533ff929b63b187c80a39eebf6cdc3c))
* **ui:** align right-side badges via shared cell-aware row formatter ([6c0e6e5](https://github.com/p4ulbr4dl3y/johnston/commit/6c0e6e5304806ec97aa3810fb62e70dcbdd3c4dc))
* **ui:** compact hotkey hint in ask_user wizard to avoid overflow ([7dedba8](https://github.com/p4ulbr4dl3y/johnston/commit/7dedba8517e5e92d27efbcaf2a0ac25b2775d971))
* **ui:** disable click and hover on invoke_subagent error ([e51c150](https://github.com/p4ulbr4dl3y/johnston/commit/e51c150543536290f909e8533b29dbb931d54ef4))
* **ui:** enable copying and cutting selected text in ChatInput ([aec63ca](https://github.com/p4ulbr4dl3y/johnston/commit/aec63ca62af9e415273b2215531e4e73d4844e8a))
* **ui:** enable subagent selection and fix auto-scroll on drag ([152b557](https://github.com/p4ulbr4dl3y/johnston/commit/152b557ef0d085b2a513e25cd8c3b41a57e35b5d))
* **ui:** enforce fence-header height to fix code selection ([86ac4bd](https://github.com/p4ulbr4dl3y/johnston/commit/86ac4bd2e6a8e9432530a9a8e59aba74d0c489f9))
* **ui:** ensure autoscroll completes after layout reflow ([4e3e1de](https://github.com/p4ulbr4dl3y/johnston/commit/4e3e1de9b91df97785c8ceceaafd152afcd0a865))
* **ui:** ensure Ctrl+C always exits and remove copy interceptor ([0f7ff87](https://github.com/p4ulbr4dl3y/johnston/commit/0f7ff87dd7c4fb94727d718fd95c0184123bceab))
* **ui:** fix markdown bullet line breaks for changed files in rewind ([3b8aea7](https://github.com/p4ulbr4dl3y/johnston/commit/3b8aea770c8b4a003d3c99b59b1ec03580f5c8ad))
* **ui:** fix markdown title formatting in rewind step 2 ([3996964](https://github.com/p4ulbr4dl3y/johnston/commit/399696492c42c45d5e08e22f860da6653ed4ec72))
* **ui:** force scroll on toolcard expansion and result update ([802c92b](https://github.com/p4ulbr4dl3y/johnston/commit/802c92b76d7c4fb0b4732e866c09f585961598ef))
* **ui:** keep shell expansion open when foreground task backgrounded ([7a4d82c](https://github.com/p4ulbr4dl3y/johnston/commit/7a4d82cd4fe20d145160b189111f9ab331f56a5e))
* **ui:** make chat autoscroll respect user intent and layout races ([9338dfe](https://github.com/p4ulbr4dl3y/johnston/commit/9338dfefdff04d6d6358955cd6afd2320bfbed12))
* **ui:** preserve active tool badge across tool results ([5f96c01](https://github.com/p4ulbr4dl3y/johnston/commit/5f96c011b4554f33f8ef624c6b77abc61d40e251))
* **ui:** prevent BaseSelectionScreen handler conflict in RewindScreen ([2b9628e](https://github.com/p4ulbr4dl3y/johnston/commit/2b9628eef219ed43eda9f0d786dc9993229adcef))
* **ui:** remove redundant cancel option from rewind step 2 ([902fbee](https://github.com/p4ulbr4dl3y/johnston/commit/902fbee27c94c59ec18065c607d27f2bdc7fc629))
* **ui:** remove stats info from rewind step 2 title ([f59c2aa](https://github.com/p4ulbr4dl3y/johnston/commit/f59c2aaa5202c899b9d80b20ec6fc07e8b77aef2))
* **ui:** render toolcall badge red on non-zero returncode ([6031179](https://github.com/p4ulbr4dl3y/johnston/commit/60311791de3dd4c163f3010401852c13b12125d6))
* **ui:** render untagged markdown code blocks as plain text ([163a574](https://github.com/p4ulbr4dl3y/johnston/commit/163a5741cb8f894e2e632cadd754dd7118834f2e))
* **ui:** resolve session save races, status blocking and duplicate code ([0ae48f3](https://github.com/p4ulbr4dl3y/johnston/commit/0ae48f37f25f6e92476e61d733cdbab7e606a640))
* **ui:** restore quit bindings and key expansion in modal screens ([d86a02b](https://github.com/p4ulbr4dl3y/johnston/commit/d86a02b99d4d3693703061fe84c82f9749c0cc9e))
* **ui:** scroll to widget top on manual card expansion ([7273f86](https://github.com/p4ulbr4dl3y/johnston/commit/7273f86e16e473bf33cff6e39a295a0db41c278c))
* **ui:** shorten modal hotkey hints to prevent wrap on 80col terminals ([080d15e](https://github.com/p4ulbr4dl3y/johnston/commit/080d15eaceb4b812715561d1d1972f31adc4c461))
* **ui:** smooth tool expand and ctrl+o scrolling without jitter ([19b3b4b](https://github.com/p4ulbr4dl3y/johnston/commit/19b3b4b7b8a8e73c772b202079b1617e83315399))
* **ui:** subtract OptionList option padding from badge row widths ([ccf5491](https://github.com/p4ulbr4dl3y/johnston/commit/ccf54917b82db1a891a175f151ab254c61849a1e))
* **ui:** unify cost estimation, stop subagent footer pricing free models ([42fc50a](https://github.com/p4ulbr4dl3y/johnston/commit/42fc50a3da836f3069f020809cd0e678da7f5134))
* **ui:** use Content in CustomMarkdownFence for precise mouse selection ([21fd0ef](https://github.com/p4ulbr4dl3y/johnston/commit/21fd0ef10e0e5c50f93dd2bdb6a1d861f3ef296d))
* **ui:** use modal-dialog-medium for subagents screen ([9504f45](https://github.com/p4ulbr4dl3y/johnston/commit/9504f45db9fa5103c0c8447304f0e786b42c11b4))
* **win-sandbox:** restricted-token runner without Safer privilege traps ([7046549](https://github.com/p4ulbr4dl3y/johnston/commit/7046549ae99ff83899261f5007caf65275b6d784))


### Performance Improvements

* resolve performance bottlenecks across ui, core, and tools ([4eb9395](https://github.com/p4ulbr4dl3y/johnston/commit/4eb9395c05a2c2f23f26c7995cdb4f0d854ca986))


### Documentation

* **skills:** align module docstring with SKILL.md-only scan ([6e7967a](https://github.com/p4ulbr4dl3y/johnston/commit/6e7967a3c153363cd1cc5717392b80b64aa304e8))
* **tools:** mention unbuffered output for live shell logs ([1b27206](https://github.com/p4ulbr4dl3y/johnston/commit/1b27206946e1471100f9c2fc4740c4ca2376c881))

## [0.25.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.24.0...johnston-v0.25.0) (2026-08-23)


### Features

* **core:** track prompt cache read tokens and extend anthropic rolling cache ([4c24920](https://github.com/p4ulbr4dl3y/johnston/commit/4c24920d72faad7adbb8bd9a0481509ae9b03839))
* **ui:** add autoscroll support for expanded thinking and streaming shell output ([3b570ba](https://github.com/p4ulbr4dl3y/johnston/commit/3b570babb9490edfde72f85168a8e99a10719d47))
* **ui:** add subagent header and isolate modal keybindings ([f3c24e9](https://github.com/p4ulbr4dl3y/johnston/commit/f3c24e9567d68b289dc028ed827f2599284d43e4))
* **ui:** auto-expand new tool and thinking widgets when expand all is active ([09e6ef4](https://github.com/p4ulbr4dl3y/johnston/commit/09e6ef469b317892ddff9cdb57269a2cf8bb80ce))
* **ui:** display background shell log contents when expanding tool card ([be90e3e](https://github.com/p4ulbr4dl3y/johnston/commit/be90e3ecd4df2efe3ac8cc384d960223cc34ef1c))
* **ui:** redesign status footer to 2-line layout and add monochrome attachment bar ([307798f](https://github.com/p4ulbr4dl3y/johnston/commit/307798f700e6b9d449f654f1424e10841fb08be0))
* **ui:** simplify tool truncation boilerplate and preserve log path ([1bc028b](https://github.com/p4ulbr4dl3y/johnston/commit/1bc028b6bad04b7a5777f99c2a0615bd7a3b06af))


### Bug Fixes

* **generation:** preserve skill display_text for mid-generation queue items ([245d68a](https://github.com/p4ulbr4dl3y/johnston/commit/245d68a43d02d1ca22149738e644205e4082cbc0))
* **lifecycle:** safely handle mock objects in _kill_all_tasks_sync ([2c76020](https://github.com/p4ulbr4dl3y/johnston/commit/2c760205a3c0ef031d6d5e658305b9a97d65c13b))
* **prompt:** resolve identity ambiguity and clarify path boundary rule ([dc8c137](https://github.com/p4ulbr4dl3y/johnston/commit/dc8c137936a2741535693327ee620a242efd3ea9))
* **providers:** honor enable/disable in agent selection ([22937bf](https://github.com/p4ulbr4dl3y/johnston/commit/22937bf164b1a6eb9a653628025d13ec1f983552))
* **shell:** preserve partial output on interruption and fix stale running state on session restore ([3c040fa](https://github.com/p4ulbr4dl3y/johnston/commit/3c040fa0b9338fd77b29a858951abf9b0e5776ae))
* **subagent:** cleanly cancel in-flight tools in subagent session on interruption ([d9355ea](https://github.com/p4ulbr4dl3y/johnston/commit/d9355ea2b742c2393723a5c33d8801f7862da61d))
* **tools:** streamline tool schemas, self-healing hints, and subagent title parameter ([8b7778c](https://github.com/p4ulbr4dl3y/johnston/commit/8b7778cd3b1c4f61200da98782645da80a07d50d))
* **ui:** handle cancellation and status state in ask_user tool and modal interruption ([889ad5e](https://github.com/p4ulbr4dl3y/johnston/commit/889ad5e730a392d4dc30a2c3ce7dcc16c2b81508))
* **ui:** manage role lifecycle across sessions and polish selection screens ([d6899f9](https://github.com/p4ulbr4dl3y/johnston/commit/d6899f9169995fce7145fa1fc14483cad926f9ab))
* **ui:** preserve autoscroll position on async tool render and expand ([d7110ec](https://github.com/p4ulbr4dl3y/johnston/commit/d7110ec4cec4311d86a3b24b94121c98980f8902))
* **ui:** sanitize and shorten event divider titles ([66e33a0](https://github.com/p4ulbr4dl3y/johnston/commit/66e33a0cf86d07ea997f04546000533927c7e5f7))
* **ui:** toggle inline expansion on running shell toolcard and update ask_user description ([edad2a7](https://github.com/p4ulbr4dl3y/johnston/commit/edad2a7ba6b955ae926fad75e236a1dabfa8ebdb))
* **ui:** unify modal layout, paddings, and status footer ([bc2682f](https://github.com/p4ulbr4dl3y/johnston/commit/bc2682f407db8bd85a03aaf4f5b8e8de33695909))


### Documentation

* **skills:** fix johnston-guide reference links and example role config ([19f0128](https://github.com/p4ulbr4dl3y/johnston/commit/19f0128324283a89e088e55ea8f1210754411700))

## [0.24.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.23.0...johnston-v0.24.0) (2026-08-22)


### Features

* **ui:** add cross-layout keybinding aliases and centralize key helpers ([f8c2147](https://github.com/p4ulbr4dl3y/johnston/commit/f8c21475fb2b620d142756985ba6aec492798be1))
* **ui:** add hanging indent line wrapping for diffs and remove horizontal scroll ([70036f1](https://github.com/p4ulbr4dl3y/johnston/commit/70036f172a2dd6eca80675cdccef473702ab3991))
* **ui:** remove horizontal scroll and enable word wrapping for markdown fences and tool outputs ([ba2d8a8](https://github.com/p4ulbr4dl3y/johnston/commit/ba2d8a8e1fc56346eba25d39ecf9990461da9215))


### Bug Fixes

* **tools:** allow fake-ip range 198.18.0.0/15 in web_fetch SSRF guard ([4bc8a54](https://github.com/p4ulbr4dl3y/johnston/commit/4bc8a54b3f3fd978eaebf5e5ab327377b96dc15a))
* **tools:** make branch optional in invoke_subagent and handle non-git repos ([3f8761d](https://github.com/p4ulbr4dl3y/johnston/commit/3f8761d610e0815eaab1c97ea6f15d447943dd25))
* **ui:** dismiss empty task modals and update active option on mouse hover ([6f05bcb](https://github.com/p4ulbr4dl3y/johnston/commit/6f05bcbc1c4731d53774eb0d928e9302d7d5488f))
* **ui:** dynamic sequential toolcall spacing on expand/collapse ([6f257a7](https://github.com/p4ulbr4dl3y/johnston/commit/6f257a71540fc81b962701d8e9ad1f65e8d4fa5d))
* **ui:** improve modal sizing, diff scrolling, and title truncation ([8bdba1a](https://github.com/p4ulbr4dl3y/johnston/commit/8bdba1a9ea73b2e12b4a89cd91f315dd2f4418d8))

## [0.23.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.22.1...johnston-v0.23.0) (2026-08-21)


### Features

* **providers:** update default providers, models source, and skills screens ([ccd0c18](https://github.com/p4ulbr4dl3y/johnston/commit/ccd0c189a7c9f7e61b038c8221553fc2b1c2bf0f))


### Bug Fixes

* **mcp:** surface tool failures with ERR prefix ([460a991](https://github.com/p4ulbr4dl3y/johnston/commit/460a991297b7eb12de5bf76f04d7d1e2b95c6f2d))
* **storage:** isolate shadow repos and support JOHNSTON_CONFIG_DIR override ([e505844](https://github.com/p4ulbr4dl3y/johnston/commit/e50584496ca20eafaa0bf933e6fc334057a1e184))
* **tools:** refine truncation line counts and inspection hints ([1db54f4](https://github.com/p4ulbr4dl3y/johnston/commit/1db54f4b7e8b552e2c3e3d34c2b6b3804886a857))
* **widgets:** skip non-numbered lines in chat diff ([190dcee](https://github.com/p4ulbr4dl3y/johnston/commit/190dcee44b71747cb29eee94a96af3d731633c0a))

## [0.22.1](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.22.0...johnston-v0.22.1) (2026-08-20)


### Bug Fixes

* atomic prompt history persistence and json cache invalidation ([b90640c](https://github.com/p4ulbr4dl3y/johnston/commit/b90640c5b8abbe037b9f0c892ca2c63a5a54233c))
* **generation:** finalize thinking widget on stream error or disconnection ([18a176e](https://github.com/p4ulbr4dl3y/johnston/commit/18a176e566165efd74aa9a599b9864a1da9f9786))
* **skills:** preserve and restore skill command messages in chat history ([e7851e1](https://github.com/p4ulbr4dl3y/johnston/commit/e7851e1e3531b2d1f8bab1dd5c93a8009d88b210))
* windows test hangs, shell process execution and unicode encoding ([e992242](https://github.com/p4ulbr4dl3y/johnston/commit/e992242f387db09b340a761ebcb2bbd7cb46c17d))

## [0.22.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.21.0...johnston-v0.22.0) (2026-08-19)


### Features

* **commands:** notify warning toast when no MCP servers found on /mcp ([d28bd13](https://github.com/p4ulbr4dl3y/johnston/commit/d28bd13da3d0a885be7320f37a5f1ac9f41f0a53))
* **compaction:** align with codex turn-based compaction and subagent prompt retention ([28d4a17](https://github.com/p4ulbr4dl3y/johnston/commit/28d4a170415cafafc556ffb7f1a4897c671672ca))
* **linters:** disable presets by default (opt-in) ([683d076](https://github.com/p4ulbr4dl3y/johnston/commit/683d076bb9b9660479006e25befd40c23c5fc03b))
* **logging:** use content-appropriate extensions for tool snapshots and add markitdown dumps in read ([850c09e](https://github.com/p4ulbr4dl3y/johnston/commit/850c09ed893d5a76fa0923753bcb118476f66812))
* **prompt:** allow continuing independent work while background tasks run ([0690719](https://github.com/p4ulbr4dl3y/johnston/commit/0690719795fc2b7e98ffa3a85680298bd6cf4b67))
* **prompts:** adopt evidence-first verification and disciplined role prompts ([434add1](https://github.com/p4ulbr4dl3y/johnston/commit/434add1abaffbfbc3640bc6145b9c25e726b9e79))
* **prompts:** disallow conversational commentary before tool calls ([3f4a76b](https://github.com/p4ulbr4dl3y/johnston/commit/3f4a76bc14b74982e705908193222cb9464e093b))
* **providers:** handle retry-after header and notify user on provider retry ([d45b867](https://github.com/p4ulbr4dl3y/johnston/commit/d45b8675b41b8a5696633423ea411fe021fb9029))
* **roles:** add batch subagent role definition guideline to orchestrator ([1527e9c](https://github.com/p4ulbr4dl3y/johnston/commit/1527e9ca7fc9951e5973a082ae7096ab877b7280))
* **roles:** support per-role provider override for subagents ([147b38c](https://github.com/p4ulbr4dl3y/johnston/commit/147b38cf620fa2c85d01317fd155ee25a5db937f))
* **screens:** group mcp and skills modals by scope ([5aa62ed](https://github.com/p4ulbr4dl3y/johnston/commit/5aa62edf4426290e0b568fb5899fde21c4f599fa))
* **screens:** group tasks by running/completed status ([7b6ed2d](https://github.com/p4ulbr4dl3y/johnston/commit/7b6ed2d7e5f4b1b222c704e32001a3550d1b8bfc))
* **screens:** keep group headers visible on option wrap ([751be7f](https://github.com/p4ulbr4dl3y/johnston/commit/751be7fff68d3bdb390464453ac7cbc589fa4fd6))
* **shell:** mention user backgrounding and elapsed time on ctrl+b ([2e97aa2](https://github.com/p4ulbr4dl3y/johnston/commit/2e97aa27665bf0f221bcd6ae57f99d9f03e1b626))
* **subagent:** add status footer and info bar to subagent screen ([b3e2788](https://github.com/p4ulbr4dl3y/johnston/commit/b3e2788e784c2ea11ba6f90cb37103efd6ae0a4a))
* **subagent:** compact footer with effort and dot separators ([cd21963](https://github.com/p4ulbr4dl3y/johnston/commit/cd2196311099c01406e98a767e38fe2084c54b6e))
* **subagent:** show agent info in input slot with footer ([86d8cbc](https://github.com/p4ulbr4dl3y/johnston/commit/86d8cbc2a940439639845c1bedfe42ebdeefa2f5))
* **subagents:** queue follow-up messages like main agent ([c6a3c5f](https://github.com/p4ulbr4dl3y/johnston/commit/c6a3c5fddb43604542981b9fc21a1ad863159497))
* **suggest:** include directories in file suggestions ([e84f45a](https://github.com/p4ulbr4dl3y/johnston/commit/e84f45a9253ee7995dfa6cfff6b7de58c5c43a9b))
* **tools:** log background shell output to file, tail in responses ([9c1d2e4](https://github.com/p4ulbr4dl3y/johnston/commit/9c1d2e428de32e97d02d38dfc35a286b48723a9d))
* **tools:** tailor shell tool schema for subagents to enforce synchronous execution ([360272b](https://github.com/p4ulbr4dl3y/johnston/commit/360272bbcf3a7cc42cd9592d6d9a8541bf7ee621))
* **ui:** add /shell command for background shell tasks ([b060814](https://github.com/p4ulbr4dl3y/johnston/commit/b060814aa3b34cb31016f0f96ad09dd0387fc142))
* **ui:** allow down arrow in write-in input to jump to first option in ask user modal ([d9b6b7f](https://github.com/p4ulbr4dl3y/johnston/commit/d9b6b7f60c0775c549aea84eab3fd4f666834eab))
* **ui:** expand Rich Markdown tables to full width with preserved column alignment ([856ef1e](https://github.com/p4ulbr4dl3y/johnston/commit/856ef1e2f29356113a7acb8a7aa1d09fbcd5912c))
* **ui:** fullscreen subagent screen and richer footers ([613d5b2](https://github.com/p4ulbr4dl3y/johnston/commit/613d5b2f3c2b58e054ee8f656702f376fbb4c422))
* **ui:** human-like confirm messages for manage_subagent, update_plan, ask_user ([40c9e21](https://github.com/p4ulbr4dl3y/johnston/commit/40c9e215dc67e14f1c3f222292210b06d653c025))
* **ui:** human-like labels for manage_shell/subagent send actions ([d811db4](https://github.com/p4ulbr4dl3y/johnston/commit/d811db4fa25d31715e7c802738f7f6580f041e51))
* **ui:** open console modal on running bg shell click and auto-collapse on backgrounding ([03f6942](https://github.com/p4ulbr4dl3y/johnston/commit/03f694255bb8ea906e874d5eef0f9c5d75323c20))
* **ui:** predefined tool chip labels, compact dict for non-builtin ([f5cd0f8](https://github.com/p4ulbr4dl3y/johnston/commit/f5cd0f8818e9db11e1fe2ab8c3048231eba80696))
* **ui:** replace /tasks with /subagents, subagent-only modal ([1902d37](https://github.com/p4ulbr4dl3y/johnston/commit/1902d37eb3e82c97779d47b2fe2bdd99265dca31))


### Bug Fixes

* **agent:** drop retry partial text, run duplicate tool calls, surface adapter thinking ([afefa0d](https://github.com/p4ulbr4dl3y/johnston/commit/afefa0d8b8caf4478cdfa83cc34b6c83374a01b3))
* **chat:** treat empty bot message as continuity for sequential tool calls ([ddc7490](https://github.com/p4ulbr4dl3y/johnston/commit/ddc74901427d2e26d723d3d871c25adaec203906))
* **ci:** restore green test matrix across Linux/macOS/Windows ([7ccf46b](https://github.com/p4ulbr4dl3y/johnston/commit/7ccf46b3c491df75b3e9b1d860805c1affdcd421))
* **ci:** retry temp dir cleanup on Windows; raise job timeout ([83dd83a](https://github.com/p4ulbr4dl3y/johnston/commit/83dd83ad45abe7044e44e24224a6abb73ea6396f))
* **ci:** run windows tests serially to prevent pipe deadlocks ([608027f](https://github.com/p4ulbr4dl3y/johnston/commit/608027fc58be07a13b10e27b24c852a1f90fcd7f))
* **ci:** stabilise provider key test; give Windows job more time ([193de7e](https://github.com/p4ulbr4dl3y/johnston/commit/193de7e4b6ca8cedde4d6e351bba887ddb74245e))
* context limit type, pagination bounds, read DoS, MCP process leak/stop crash ([8336566](https://github.com/p4ulbr4dl3y/johnston/commit/8336566923e17027aa8773fe42bacb90a68a60dd))
* **core:** align role_tool_error with allowed_tools, drop dead output_limits ([602dd88](https://github.com/p4ulbr4dl3y/johnston/commit/602dd883b0f421d8a2e2c42eb6a81bf86f89d264))
* **core:** handle frontmatter comment/None, empty subagent step, cleanup_fn safety ([dd09da3](https://github.com/p4ulbr4dl3y/johnston/commit/dd09da396a2d5720d2bcdde99d89d35201cd3cf5))
* **core:** role scope whitespace, prompt None/schema types, linter path/exit safety ([badad46](https://github.com/p4ulbr4dl3y/johnston/commit/badad46e7c07cf3afebf8712a6be65dd1cee8ad4))
* **core:** surface session save errors, re-raise cancel ([45ea268](https://github.com/p4ulbr4dl3y/johnston/commit/45ea268f121caa3772c7a4355a633a6f256ef260))
* **core:** upgrade context compaction with native history and prompt caching ([92f7828](https://github.com/p4ulbr4dl3y/johnston/commit/92f7828a333c5295e4d7398260a7d51524083786))
* **flow:** release is_generating when interrupt lands before stream loop ([a67c5df](https://github.com/p4ulbr4dl3y/johnston/commit/a67c5df11c3b1ce41c4a086b321766f554436884))
* **markdown:** patch table_open block to disable cell tooltips ([74b0a8e](https://github.com/p4ulbr4dl3y/johnston/commit/74b0a8e10e7af2d0fcfa936259370a86e88f5928))
* **markdown:** suppress cell tooltips during streaming rows ([25b7ec5](https://github.com/p4ulbr4dl3y/johnston/commit/25b7ec5fc35db6fcc392ba0b6ffef36d4011e70e))
* **markdown:** use live BLOCKS mapping so table tooltips stay suppressed ([d56a398](https://github.com/p4ulbr4dl3y/johnston/commit/d56a398a36929ff4844337541f5ce9064d394a36))
* **mcp:** drop pending future on cancelled write; mark UI tests slow ([9595904](https://github.com/p4ulbr4dl3y/johnston/commit/9595904fa40f8e45a742543f1f37fb8873826b41))
* **mcp:** guard tool call races, join reader thread, reset clients on project change, group prompt snippet by server ([811db59](https://github.com/p4ulbr4dl3y/johnston/commit/811db59d7803ddaa75e6584d275c67e215dac48f))
* **mcp:** harden manager concurrency and UI status rendering ([3a11fc1](https://github.com/p4ulbr4dl3y/johnston/commit/3a11fc1f58313df3496db88d16e6108bb93de8f5))
* **mcp:** resolve async deadlocks, process leaks, routing latency, and UI rendering ([4e7a7ce](https://github.com/p4ulbr4dl3y/johnston/commit/4e7a7ce3491bc10f4b57198d19b39318339aca7d))
* **mcp:** start background warmup on app mount and fix footer status polling ([5c0e4d2](https://github.com/p4ulbr4dl3y/johnston/commit/5c0e4d22b3d3a2f181b275e1b80c9113e838ed39))
* **mcp:** truncate MCP tool output when exceeding limit ([0fa2791](https://github.com/p4ulbr4dl3y/johnston/commit/0fa2791f758b6b4b733c0dde5d92b6e1cc3e9902))
* None-safe shell/manage args, alias chain resolution, adapter NaN keys ([890695a](https://github.com/p4ulbr4dl3y/johnston/commit/890695aa1fbec4c9222ae211d591cec4895b0288))
* **openai:** always emit reasoning_content for compatible providers ([a5cb7f3](https://github.com/p4ulbr4dl3y/johnston/commit/a5cb7f38dc43d26a213483a43294fbf007428c1f))
* permission fail-closed, session path traversal, symlink/readonly write safety ([522b281](https://github.com/p4ulbr4dl3y/johnston/commit/522b281cfc51db3446fcd5ac65a7379e9f914bcf))
* **provider:** log provider-config save errors, dedupe parsers ([7c6afdc](https://github.com/p4ulbr4dl3y/johnston/commit/7c6afdc16c5d84035e03e776cf5301d1e705da37))
* **rewind:** kill bg tasks, truncate transcript, reset tokens ([786d7b6](https://github.com/p4ulbr4dl3y/johnston/commit/786d7b625a28fac107256233a29b1d09640d0fe4))
* **roles:** clarify branch is required on invoke_subagent ([9316aea](https://github.com/p4ulbr4dl3y/johnston/commit/9316aea8682962a24ab9fc3ee57b31e2a889734c))
* **security:** web_fetch SSRF/XSS, tool_display secret leak, session role/null/typed fields ([90dbd61](https://github.com/p4ulbr4dl3y/johnston/commit/90dbd6147b7c314ea9c7dd8cab1f488d438e0ea4))
* **shell:** restore ctrl+b backgrounding with recent output and timeout truncation ([a574706](https://github.com/p4ulbr4dl3y/johnston/commit/a574706f995a23aeaa79f93661c1122dd87b3730))
* **shell:** restore ctrl+b by registering sync tasks; keep shells manageable ([ca9824d](https://github.com/p4ulbr4dl3y/johnston/commit/ca9824d2f9671ad088136b3f366d38a3d2894ac4))
* **skills:** include skill file path in invoked skill block ([5ccc7bd](https://github.com/p4ulbr4dl3y/johnston/commit/5ccc7bd849e01c8d069f45bfdbfa248dbdb25801))
* **subagents:** mark invoke_subagent card running on send_message ([bc570e1](https://github.com/p4ulbr4dl3y/johnston/commit/bc570e185523ed26447412b53ea45fd988e746b6))
* **subagents:** unify message queue draining and handle API error status ([0e1fa29](https://github.com/p4ulbr4dl3y/johnston/commit/0e1fa297a81024f17725a2cb46694838eda2c413))
* **tasks:** backfill buffered output when background log opens late ([65f1553](https://github.com/p4ulbr4dl3y/johnston/commit/65f15534eaf110f32324cb12ae87989fc843cb8d))
* **tasks:** notify background shell completion only when in background and hide system messages in ui restore ([7bd4f64](https://github.com/p4ulbr4dl3y/johnston/commit/7bd4f64241d020bd2fc5a01bc3f0487ce34a4e97))
* **tests:** adapt to dead-code removal and markdown_scanner ([750428f](https://github.com/p4ulbr4dl3y/johnston/commit/750428f730b30fc6593cd8ad59b8cceb589c0e0e))
* **tests:** import truncate from application.display in plan display test ([b574bc9](https://github.com/p4ulbr4dl3y/johnston/commit/b574bc97a9a3f7814daf14dfc63c749e08fa6751))
* **tests:** update run_git patch paths for moved subagent_worktree ([6822130](https://github.com/p4ulbr4dl3y/johnston/commit/6822130c704791cb8a46904a89c266de9cfd8a85))
* **tools:** cooperative cancellation for blocking to_thread tool work ([666af54](https://github.com/p4ulbr4dl3y/johnston/commit/666af5417d8a9e504c136a06156f84fceb905f7d))
* **tools:** decode Windows console output and fix cross-platform tests ([c451eda](https://github.com/p4ulbr4dl3y/johnston/commit/c451edaa5d680f9b87a1f073304225c9da8eba78))
* **tools:** preserve CRLF line endings on file edits ([3e421f9](https://github.com/p4ulbr4dl3y/johnston/commit/3e421f985204776bddc7ae89c5b7fc3a59901c82))
* **tools:** support fallback to raw_text for syntax highlighting in create tool widget ([50dd506](https://github.com/p4ulbr4dl3y/johnston/commit/50dd506325199ec3f2834a38b77bdbc8dbf2684e))
* **tools:** tighten update_plan description and refine UI style ([65898e3](https://github.com/p4ulbr4dl3y/johnston/commit/65898e3382afd467737d1e006e4bbf2e0b14128a))
* **tools:** unify snapshot logs, cap size, purge stale ([93865ea](https://github.com/p4ulbr4dl3y/johnston/commit/93865ea6aa14231909f74b6e9972772c25a7b894))
* **ui:** await prompt history save task in tests to avoid race condition ([8a7a176](https://github.com/p4ulbr4dl3y/johnston/commit/8a7a1761092bf436bd169c92baf4ea41167149ed))
* **ui:** center markdown headers in modal dialogs while keeping chat headers left-aligned ([7264e98](https://github.com/p4ulbr4dl3y/johnston/commit/7264e9845a50e6fc06798721bc937e5b02a8f177))
* **ui:** count disabled servers in mcp_total to show 0/N when servers are disabled ([8f4e04f](https://github.com/p4ulbr4dl3y/johnston/commit/8f4e04fe8a97485716d036785d9f90bc2b231779))
* **ui:** don't expand error/cancelled tool cards except shell ([b5539fb](https://github.com/p4ulbr4dl3y/johnston/commit/b5539fbf108227daf65f00ce0874af95f4ce3eed))
* **ui:** dynamically update tool counts in MCPScreen when server warmup finishes ([4bbfa50](https://github.com/p4ulbr4dl3y/johnston/commit/4bbfa50f0b5345839eed8d23b4d7c90e5740a767))
* **ui:** ensure uniform 1-line margin after all headings in Textual Markdown ([25ec67d](https://github.com/p4ulbr4dl3y/johnston/commit/25ec67db76d28155b966f981a92a57133c74aafe))
* **ui:** fix list items baseline and paragraph margin inside lists ([0264fcd](https://github.com/p4ulbr4dl3y/johnston/commit/0264fcdb42d448304096b633b73780b35ce9e04e))
* **ui:** flush pending stream before tool call so last char isn't dropped ([cf5df1d](https://github.com/p4ulbr4dl3y/johnston/commit/cf5df1d3d2bf90b9eee7fcc6759a4856c2a1be5c))
* **ui:** format MCP screen empty state placeholder cleanly ([f7493af](https://github.com/p4ulbr4dl3y/johnston/commit/f7493afaa2a1860ca0de857e1e1ce8b854783fb5))
* **ui:** format status footer directory paths with real home expansion ([86cbcd2](https://github.com/p4ulbr4dl3y/johnston/commit/86cbcd2e0abe245f82ef594a70d2ecfa4e7e01bb))
* **ui:** guard initial setup against app teardown; skip slow on Windows ([d9c9a9d](https://github.com/p4ulbr4dl3y/johnston/commit/d9c9a9d606f4e3836b40d866b89fecdf605352ea))
* **ui:** harden widget/screen edge cases; fix markdown table, tool-call rendering, input sanitization ([432fd57](https://github.com/p4ulbr4dl3y/johnston/commit/432fd57b5ddfcab5e6a20913ae82f32d24277088))
* **ui:** harmonize Textual Markdown and Rich Markdown alignment and spacing ([9490de7](https://github.com/p4ulbr4dl3y/johnston/commit/9490de7d48a039006383086a99cbeded851264a3))
* **ui:** keep MCP footer count live after warmup ([998689f](https://github.com/p4ulbr4dl3y/johnston/commit/998689f90c51140ac6431358ebb8ee9c7ab9289e))
* **ui:** keep MCP indicator in status footer showing 0 when no servers enabled ([25654eb](https://github.com/p4ulbr4dl3y/johnston/commit/25654ebbb57af233bc99d6f0be403a847989f32d))
* **ui:** load cached MCP servers synchronously on modal init ([12e605b](https://github.com/p4ulbr4dl3y/johnston/commit/12e605be87d044c3d332fdcd39fb6786c5c02bd3))
* **ui:** mark interrupted tool call as cancelled instead of stuck running ([aad978d](https://github.com/p4ulbr4dl3y/johnston/commit/aad978d87bc6d2e81ed2fc8c109f0841d6084316))
* **ui:** patch Screen.get_widget_and_offset_at and RichVisual.render_strips for mouse drag selection on Rich renderables ([5c3afe5](https://github.com/p4ulbr4dl3y/johnston/commit/5c3afe5c723b0c3fca4eb0690897f4eaf42dedc6))
* **ui:** preserve bot message before tool call and flush stream content ([2321725](https://github.com/p4ulbr4dl3y/johnston/commit/2321725de2e2a1a388e5a53ff6c82a619b47a671))
* **ui:** preserve git branch and diff metrics in status footer ([e81f1b5](https://github.com/p4ulbr4dl3y/johnston/commit/e81f1b5d0a159ab72c9f7db655aa5c2f87c2c894))
* **ui:** properly push Johnston monochrome theme to Textual App console and left-align headings ([4a68f23](https://github.com/p4ulbr4dl3y/johnston/commit/4a68f2353d61033861d4984bc1bbd2757f10e272))
* **ui:** remove empty leading separator in permissions modal ([e49124d](https://github.com/p4ulbr4dl3y/johnston/commit/e49124d947d980c715f163497a8f9e4279042d8f))
* **ui:** repaint invoke_subagent tool card on completion ([cda8412](https://github.com/p4ulbr4dl3y/johnston/commit/cda841275cde383cfc02c0b364f154127fffa421))
* **ui:** repaint shell tool widget on background completion ([edb928d](https://github.com/p4ulbr4dl3y/johnston/commit/edb928dacdc92766f35480568be5a44f0b38f8c3))
* **ui:** reset is_generating and handle message queue on rewind, resume, and compact ([559bb89](https://github.com/p4ulbr4dl3y/johnston/commit/559bb89f55f2b91b850bfd4c5c9e435c906463db))
* **ui:** restore attachment indicators in footer and messages, preserve user prompts without vision ([124e12c](https://github.com/p4ulbr4dl3y/johnston/commit/124e12c04da25c8a2495cd0c75a8af205a6a78b0))
* **ui:** restore compact original margins (margin 0 for paragraphs and lists) ([54c4f99](https://github.com/p4ulbr4dl3y/johnston/commit/54c4f999479330a9387cf737defeb18a83ede3fe))
* **ui:** restore MCP server highlight on modal reopen ([5f2bad1](https://github.com/p4ulbr4dl3y/johnston/commit/5f2bad14d589582428f5496bff8c9c08cf59f9e0))
* **ui:** show MCP: 0 instead of 0/0 when no MCP servers configured ([f8e289e](https://github.com/p4ulbr4dl3y/johnston/commit/f8e289eacbbe2d75c5b5663b45144d8618b855a2))
* **ui:** show subagent's own data in subagent status footer ([3fdbc5a](https://github.com/p4ulbr4dl3y/johnston/commit/3fdbc5a94e7129e86915c52245ec4ad9c9e3cea2))
* **ui:** support text selection and clipboard copying on Static with Rich renderables ([ab85561](https://github.com/p4ulbr4dl3y/johnston/commit/ab85561b4d697f971b6dcdac0ffd0a5e32977705))
* **ui:** truncate background shell output via truncate_output, backfill test ([f7a7258](https://github.com/p4ulbr4dl3y/johnston/commit/f7a7258f40fd75e82ceb02e7add7f95f0773ce0d))
* **ui:** unify all heading styles (h1..h6) across Textual Markdown and Rich Markdown ([2802553](https://github.com/p4ulbr4dl3y/johnston/commit/2802553ce5821ed0784248bb591c7fc8b1424d59))
* **ui:** unify code block background to dark zinc [#18181](https://github.com/p4ulbr4dl3y/johnston/issues/18181)b in Rich Markdown ([0bb57f1](https://github.com/p4ulbr4dl3y/johnston/commit/0bb57f17c06c8482006dc631c40542e200660d46))
* **ui:** unify subagent status footer and fix stream metrics ([60c7fdd](https://github.com/p4ulbr4dl3y/johnston/commit/60c7fdd84c95300f4879cbf0315dd3afc46be61e))
* **ui:** update session tool messages on background shell and subagent completion ([ded2030](https://github.com/p4ulbr4dl3y/johnston/commit/ded2030732671798da2edd43903cbdbddfce6094))
* **ui:** use error color for cancelled tool call ([424de05](https://github.com/p4ulbr4dl3y/johnston/commit/424de05abe1cf42e4bbe53b9d63d37534619c2ad))
* **ui:** use old line number for removed lines in diff viewer ([9fcf7d6](https://github.com/p4ulbr4dl3y/johnston/commit/9fcf7d647521a0b1b332ff8d636b98e70a1497b4))
* **ui:** use Textual Markdown for interactive selection in BotMessage with Rich fallback ([6a4cad9](https://github.com/p4ulbr4dl3y/johnston/commit/6a4cad9b40def55a949ce74659cf8cef85661927))


### Performance Improvements

* comprehensive core, tools, storage and UI performance overhaul ([d628811](https://github.com/p4ulbr4dl3y/johnston/commit/d628811fcbe9535ab10e8e3e08bb102cc583b93e))
* **core,ui:** optimize startup, compaction async io, scroll coalescing and memory cleanup ([dc3bd57](https://github.com/p4ulbr4dl3y/johnston/commit/dc3bd5709e1682b7881f7781bfd072414d74a92b))
* **core:** move blocking io off event loop; share http clients ([989920a](https://github.com/p4ulbr4dl3y/johnston/commit/989920a09632696a5b02371d35c7a9a4377f995c))
* eliminate O(n^2) stream build and cache hot paths ([4bfe060](https://github.com/p4ulbr4dl3y/johnston/commit/4bfe06040c8372f9a087bd67b21a33174870e30f))
* **ui:** eliminate tool call and markdown event loop freezes ([9465c53](https://github.com/p4ulbr4dl3y/johnston/commit/9465c53a858127da6463a03feec9fcdd8c0ba792))
* **ui:** migrate BotMessage to direct RichMarkdown rendering with synchronized theme ([8c729ca](https://github.com/p4ulbr4dl3y/johnston/commit/8c729ca60b7b7daf978874f08a5df9eff3a63f72))
* unblock UI event loop by offloading blocking I/O ([0c3e3fd](https://github.com/p4ulbr4dl3y/johnston/commit/0c3e3fd87438db03d7c97d254e8552eca01d553e))


### Documentation

* **agents:** remove scripts/ mention and ignore rule ([4551a1e](https://github.com/p4ulbr4dl3y/johnston/commit/4551a1eca6a3eb1ad24bf50fa4906bce371c7b44))
* correct stale session module docstring ([351f1ae](https://github.com/p4ulbr4dl3y/johnston/commit/351f1aedaa58edf513794129a05e126d25f20876))
* **roles:** trim redundant applicability clause from builtin role descriptions ([aa01d68](https://github.com/p4ulbr4dl3y/johnston/commit/aa01d683628b15260358245b0abb955eb3f66e67))
* **skills:** fix johnston-guide references; filter dotfiles in skill loader ([55db8a1](https://github.com/p4ulbr4dl3y/johnston/commit/55db8a158a82c3a82a83d153c425a49632eba6f2))
* **skills:** fix johnston-guide roles worktree and providers key refs ([ed7a306](https://github.com/p4ulbr4dl3y/johnston/commit/ed7a3060968d1854f19aec5cca143b190f061169))

## [0.21.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.20.0...johnston-v0.21.0) (2026-08-10)


### Features

* **modes:** add Orchestrator execution mode ([6d6610d](https://github.com/p4ulbr4dl3y/johnston/commit/6d6610d549fe6f4152bfcaef3ec5487a4969fd77))
* refine Orchestrate mode delegation guidance ([28ba59c](https://github.com/p4ulbr4dl3y/johnston/commit/28ba59cb14e245c730c5e7e22f9b298dbd64a9a0))
* **tools:** expand argument aliases and accept single-question asks ([f6ba818](https://github.com/p4ulbr4dl3y/johnston/commit/f6ba8186f9cc968e9b0ac54cfbbbda3129528909))
* **tools:** format subagent truncation hint with read tool start_line ([d43f3aa](https://github.com/p4ulbr4dl3y/johnston/commit/d43f3aae82666fe0fda6cf58d83ca035ef7fbbc1))
* **tools:** include full log file path in subagent truncation notice ([c16298c](https://github.com/p4ulbr4dl3y/johnston/commit/c16298cea7f0f4c445c1516af87c0e2d2acfd242))
* **ui:** add modal questions minimize with Tab and resume via /questions ([b664222](https://github.com/p4ulbr4dl3y/johnston/commit/b664222e880d8256ac2b7f71d8832a4023aaed57))
* **ui:** implement inline question bar for /demo command ([ecc7bb7](https://github.com/p4ulbr4dl3y/johnston/commit/ecc7bb7ea1945c99f1befc9c36ac74fc6c6a0705))
* **ui:** make ask_user tool expandable inline and resumable via modal ([d40a118](https://github.com/p4ulbr4dl3y/johnston/commit/d40a118e014ab909ea5965e6eacca23ca22ec218))
* **ui:** unify background tasks and subagents into single TasksListScreen ([0afae3e](https://github.com/p4ulbr4dl3y/johnston/commit/0afae3e529f902a8eaa25e9931ab6c7445c9b2e5))


### Bug Fixes

* **adapters:** reuse AsyncOpenAI client and close on exit ([c326b6c](https://github.com/p4ulbr4dl3y/johnston/commit/c326b6cb96be872d32172f6872cd300101a7b8bb))
* **agent:** coerce reasoning to str before join in streaming loop ([878b747](https://github.com/p4ulbr4dl3y/johnston/commit/878b74729cf5aa93c5e6850cde1067fd016e5de2))
* **agent:** emit compaction divider on in-loop compaction ([255af8f](https://github.com/p4ulbr4dl3y/johnston/commit/255af8f72c0d8be8ebb520aee28ee1a8bfbdd481))
* **ci:** make tests pass on Python 3.10 and Windows ([e0632cd](https://github.com/p4ulbr4dl3y/johnston/commit/e0632cdcc786adf951e03f455eeea41d1f720a5c))
* **cli:** patch cli.tomllib in tests for Python 3.10 compat ([1950a29](https://github.com/p4ulbr4dl3y/johnston/commit/1950a2971f827b228ccb488d7701c35f369a7349))
* **compaction:** drop empty tool output that serializes to empty user message ([aee2e44](https://github.com/p4ulbr4dl3y/johnston/commit/aee2e44105b88c171186d8f194386f72a5bb8797))
* **compaction:** drop empty user messages to fix 400 user message must have content ([208b6d6](https://github.com/p4ulbr4dl3y/johnston/commit/208b6d6bf3b6f5c55ea9c297aab23613f3254c31))
* **core:** count agent loop steps in session message_count ([5663a15](https://github.com/p4ulbr4dl3y/johnston/commit/5663a1557b1c7e0de5f5f123010bbda3e33d148b))
* **core:** use tail truncation for background shell task output ([4542b4e](https://github.com/p4ulbr4dl3y/johnston/commit/4542b4ebf777174fc7daaa57c67cf4d5df6b0b85))
* **git_utils:** handle backslash paths and inner quotes in Windows diff headers ([89324c2](https://github.com/p4ulbr4dl3y/johnston/commit/89324c2e3161754d000c4eec18e2fecf08961124))
* **mcp:** revert to to_thread readline to avoid event-loop deadlock on cancel ([fd4758e](https://github.com/p4ulbr4dl3y/johnston/commit/fd4758e7d3de02a72f42e8c4ee53201fc2970af4))
* **mcp:** use single reader thread to avoid per-line thread spawn ([87d2fa3](https://github.com/p4ulbr4dl3y/johnston/commit/87d2fa3eae240aefba978aab97f660d16d609e17))
* **permissions:** map multi_edit to write group ([47f8910](https://github.com/p4ulbr4dl3y/johnston/commit/47f89101448bcc535f0c20815ad9cb8e89f33d31))
* **queue:** consume own-session messages via snapshot drain to avoid infinite loop ([0f469e0](https://github.com/p4ulbr4dl3y/johnston/commit/0f469e030bc581c59c29af281673e454ab2ec8b4))
* **queue:** drain queued messages between agent steps and guard end-of-turn race ([8417415](https://github.com/p4ulbr4dl3y/johnston/commit/8417415a81937c7ff8784c2c30e93dc32283edb5))
* **skills:** restrict skill discovery to SKILL.md and root markdown files ([b9f5fcd](https://github.com/p4ulbr4dl3y/johnston/commit/b9f5fcdbce324bcdb3eaefc5ae4e5a446f9da319))
* **tests:** ruff lint errors in UI tests ([71ed976](https://github.com/p4ulbr4dl3y/johnston/commit/71ed9767caca453526662128a4e1ed062849097b))
* **tools:** alias read offset to start_line and ignore tracebacks in file contents ([b273a96](https://github.com/p4ulbr4dl3y/johnston/commit/b273a968486ca8a6e1b76869a06618d94c48b88b))
* **tools:** clarify read tool description for targeted line ranges ([eb4a5f5](https://github.com/p4ulbr4dl3y/johnston/commit/eb4a5f5c3e9ddc17698add2fd39a0a656b55e963))
* **tools:** detect trailing newline changes in git diff ([8f7c1dd](https://github.com/p4ulbr4dl3y/johnston/commit/8f7c1ddcd57cc1de02b5e4d5f5ce67591ba30a20))
* **tools:** expand tool aliases and restore multi_edit routing ([ce5a15b](https://github.com/p4ulbr4dl3y/johnston/commit/ce5a15b584ff6113da2cdf26d0df82b2f8f35b64))
* **ui:** disable tool header hover effect and clicks in subagent screen ([1bca132](https://github.com/p4ulbr4dl3y/johnston/commit/1bca1327c0362c016a768fe5e3b815177801f2a9))
* **ui:** filter status footer subagents strictly by session_id ([50050ca](https://github.com/p4ulbr4dl3y/johnston/commit/50050ca867b30ee747d05284e58cfddf8867b1b4))
* **ui:** handle diff context lines without leading space ([817d99b](https://github.com/p4ulbr4dl3y/johnston/commit/817d99b82413be4507268eea70f9cf3e95b4dc56))
* **ui:** improve subagent type detection and prevent duplicate cancellation events ([239da78](https://github.com/p4ulbr4dl3y/johnston/commit/239da78d976211c94e80ef43a85eb128bd8cff89))
* **ui:** preserve leading blank lines and monotonic line numbers in diffs ([3bc2b26](https://github.com/p4ulbr4dl3y/johnston/commit/3bc2b26f49e0f0cc3ba0884f75625fabfdab8998))
* **ui:** process queued messages sequentially and enable OS clipboard copy on text selection ([29238ab](https://github.com/p4ulbr4dl3y/johnston/commit/29238abcc766b8a010fa54e00636e2a71f98228e))
* **ui:** refine task details routing for mock subagent tasks ([02de02c](https://github.com/p4ulbr4dl3y/johnston/commit/02de02c11398a51e8910dbe6bec927b0d0f07903))
* **ui:** robust ask_user answer parsing for edge cases ([e56a5bb](https://github.com/p4ulbr4dl3y/johnston/commit/e56a5bb08d97187648c4296b07a83c72b417cd9f))
* **ui:** unify subagent chat modal event rendering and code block styling ([4481c17](https://github.com/p4ulbr4dl3y/johnston/commit/4481c17025b9794f9acd251dfb8fd28ee042e7a1))


### Performance Improvements

* **agent:** optimize streaming loop, join-buffers, single watchdog task ([d883a84](https://github.com/p4ulbr4dl3y/johnston/commit/d883a847421dbb0b2d91c7fe35bc722f98a86e77))
* **agent:** switch stream to delta-yield contract, blocking queue wait ([d8226a0](https://github.com/p4ulbr4dl3y/johnston/commit/d8226a09141d1607ae2a28b55ad4a8d39f983fc6))
* **background_task:** use deque for output buffer truncation ([75a7900](https://github.com/p4ulbr4dl3y/johnston/commit/75a7900c879268e93a9ccfb385112c575d64537f))
* **base_provider:** hoist prompt/tool build out of stream loop ([3ff6354](https://github.com/p4ulbr4dl3y/johnston/commit/3ff6354173b9362d18981ae20a115333446f91c2))
* cache tool sort, skip empty listener copies, cache provider-cache reads ([dc0883e](https://github.com/p4ulbr4dl3y/johnston/commit/dc0883e3561831225f0679e7834e5778b76d459d))
* **chat_toolcall:** cache _try_parse_json results per text ([ca07f63](https://github.com/p4ulbr4dl3y/johnston/commit/ca07f638d9bcc92fdb392997c7675a2cf11ea208))
* **core:** add disk-aware caching to hot read paths ([ef3d606](https://github.com/p4ulbr4dl3y/johnston/commit/ef3d606d8968956a533f407db3ce187ab0928dad))
* **core:** cache baseline shadow env in git_checkpoint ([775b4ce](https://github.com/p4ulbr4dl3y/johnston/commit/775b4ceb475056773254653cde94b3a2d797bf16))
* **core:** single os.walk for skill scan and signature on cache miss ([9a7b371](https://github.com/p4ulbr4dl3y/johnston/commit/9a7b3717864402fd378a969462128b28824ba50e))
* **mcp:** bound pending responses cache and add write/config caching ([554842b](https://github.com/p4ulbr4dl3y/johnston/commit/554842b820906a2ff33705b45b685c3831c2b147))
* **mcp:** read async stdout directly instead of to_thread per line ([7d0c78e](https://github.com/p4ulbr4dl3y/johnston/commit/7d0c78e521ca65d115e56ac8d501e28b7bd0d2e2))
* **roles:** cache role loading with mtime/size signature ([6b5384a](https://github.com/p4ulbr4dl3y/johnston/commit/6b5384a456fcdf0763c910d8c95cc6eeb6b302c7))
* **rules:** TTL-cache rules signature computation ([af0e838](https://github.com/p4ulbr4dl3y/johnston/commit/af0e83872b9175f57f1c43df11371d12105d24fe))
* **shell:** cap unbounded shell output buffers ([7479290](https://github.com/p4ulbr4dl3y/johnston/commit/747929041f4844c41deee3a129f9fa96ad1ec3c5))
* **tasks:** cache filtered tasks within tick and invalidate on mutations ([84bac02](https://github.com/p4ulbr4dl3y/johnston/commit/84bac022ffba8cef1bd8d4bc5752b1ea9b9d77a8))
* **tools:** avoid sync I/O on event loop and eliminate full-file copies ([92f4a5f](https://github.com/p4ulbr4dl3y/johnston/commit/92f4a5f3124b3b354d40571251e52b0ddfc4131e))
* **ui:** reduce render-path regex & I/O overhead in widgets ([922316d](https://github.com/p4ulbr4dl3y/johnston/commit/922316d6bbefd4f3d65eeec1bf3df8fa7d3fdda1))


### Reverts

* **rules:** drop signature TTL-gate that broke rule-change detection ([90977e4](https://github.com/p4ulbr4dl3y/johnston/commit/90977e4f68079630525939fd041d96d9c6aebcfc))

## [0.20.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.19.0...johnston-v0.20.0) (2026-08-07)


### Features

* **ui:** display relative file paths in tool call cards and clarify shell tool CWD ([e156e70](https://github.com/p4ulbr4dl3y/johnston/commit/e156e707b59cd9800238ed7925b1b95b549f03d3))


### Bug Fixes

* **ci:** normalize path display slashes and patch checkpoint in test_app ([dc224f0](https://github.com/p4ulbr4dl3y/johnston/commit/dc224f05e57d2e2b87ac950738c26233c56240a6))
* **subagents:** track session lifecycle status in message flow ([447bab7](https://github.com/p4ulbr4dl3y/johnston/commit/447bab7a5e5b50f07be76e9f5f9fe2629c630e9f))
* **tests:** isolate permissions screen test from global user config ([a058fd0](https://github.com/p4ulbr4dl3y/johnston/commit/a058fd01e523c4117b0f146718bdcdb555bc0364))

## [0.19.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.18.0...johnston-v0.19.0) (2026-08-07)


### Features

* **permissions:** add tool permission manager and confirmation UI ([47adbd6](https://github.com/p4ulbr4dl3y/johnston/commit/47adbd6e7a1481dae8179a538e980a599dac7bc1))
* **permissions:** support session overrides for shell guard aliases ([33be325](https://github.com/p4ulbr4dl3y/johnston/commit/33be32563acbf6999dfabb2e2e1a11b74716a75b))
* **scripts:** add dump_system_prompt.py to inspect main agent prompt ([ad653ed](https://github.com/p4ulbr4dl3y/johnston/commit/ad653ed0b6fceca72c3bdbb9654bd700618dffc4))
* **scripts:** add mock visual inspection scripts for subagents, tasks, and shell_confirm modals ([3a39c23](https://github.com/p4ulbr4dl3y/johnston/commit/3a39c238a6775b365858f4fa93abda6f33d3f47c))
* **scripts:** update dump_system_prompt.py to dynamic live execution ([fcd2a68](https://github.com/p4ulbr4dl3y/johnston/commit/fcd2a68749fb993ca48f29916929323f973fa3b5))
* **subagents:** ask user about branch deletion after merge ([6390def](https://github.com/p4ulbr4dl3y/johnston/commit/6390def451819c6421b9236fce8027062c0aa45b))
* **subagents:** save final subagent Markdown response to ~/.johnston/subagents/logs/&lt;task_id&gt;.md and include in manage_subagent status ([e429adf](https://github.com/p4ulbr4dl3y/johnston/commit/e429adf94957e479aa782647f7b9c16d03c5f689))
* **subagents:** update explore and general system prompts ([e4484c5](https://github.com/p4ulbr4dl3y/johnston/commit/e4484c58198630a4d2a79337150b7bb73d6c71fe))
* **ui:** add /permissions command and interactive modal screen ([c2a69f9](https://github.com/p4ulbr4dl3y/johnston/commit/c2a69f98b0facb3a3cb99d8453b2b5e64a839ff1))
* **ui:** add PermissionConfirmScreen with human-friendly action descriptions and diff view ([8dc64a2](https://github.com/p4ulbr4dl3y/johnston/commit/8dc64a2c03f96008c157fa5286320bcf31649698))
* **ui:** add search and normalize keybindings in modal screens ([fca3063](https://github.com/p4ulbr4dl3y/johnston/commit/fca30633f9efd0e68d090626d7539990f3b672da))
* **ui:** dynamically set shell syntax language (powershell vs bash) based on OS ([e28d525](https://github.com/p4ulbr4dl3y/johnston/commit/e28d525dfac0ce2583e550f18eec7a6c4385a095))
* **ui:** support lazy creation of project permissions and clean up header title ([fde24c3](https://github.com/p4ulbr4dl3y/johnston/commit/fde24c312ec982e206b2f9f09729c65508b950a4))
* **worktree:** preserve git branch when subagent makes changes in worktree ([c048c74](https://github.com/p4ulbr4dl3y/johnston/commit/c048c74ee8810d40cb9e35beb36177a560e0dd92))


### Bug Fixes

* **app:** defer queued message execution to prevent Textual exclusive worker collision ([f4acbd7](https://github.com/p4ulbr4dl3y/johnston/commit/f4acbd7b8bed5e061e52bba0adbd4840bad09ee4))
* **app:** reset is_generating flag before scheduling queued message processing ([2df4dd9](https://github.com/p4ulbr4dl3y/johnston/commit/2df4dd90a08482bc3d9e2ca28228d0195ee5bb32))
* **permissions:** harden permission system against bypasses and fail-open paths ([35efd71](https://github.com/p4ulbr4dl3y/johnston/commit/35efd71f86c5e114d85bea006d6c262b472ebeb8))
* **subagents:** clean up subagent worktree management and background queue processing ([d0c1e5a](https://github.com/p4ulbr4dl3y/johnston/commit/d0c1e5a90c03eb2cc56a5ef86893e588b39333e2))
* **subagents:** cleanup follow-up worktree and commit changes to branch ([7f484b1](https://github.com/p4ulbr4dl3y/johnston/commit/7f484b1ac71c9ad3b415d7e50c6ed119a17296fc))
* **subagents:** dynamic is_running calculation for BackgroundSubagent and completion toast notify ([89e3e53](https://github.com/p4ulbr4dl3y/johnston/commit/89e3e5304a0eda2dbf7d95ebace4b0874857ae55))
* **subagents:** isolate project rules and persist follow-up worktree context ([3191ed0](https://github.com/p4ulbr4dl3y/johnston/commit/3191ed042829d83a4b8fbfe46804b1e87c8e5a6e))
* **subagents:** propagate cwd for isolated subagent worktrees ([142ce5e](https://github.com/p4ulbr4dl3y/johnston/commit/142ce5e94f8e98048df80a3a14b35cfe35d4ea77))
* **subagents:** unify subagent result output log extension to .log ([9a5a318](https://github.com/p4ulbr4dl3y/johnston/commit/9a5a3187e2c900a6b0886756053ca52e60e9776c))
* **tcss:** replace invalid display flex with display block ([b168fad](https://github.com/p4ulbr4dl3y/johnston/commit/b168fad982edd03f863600563145fa8a5a781a81))
* **tools:** increase MAX_SUBAGENT_RESULT_CHARS limit to 15000 ([401e6fc](https://github.com/p4ulbr4dl3y/johnston/commit/401e6fcde706ec62cd0324d853b8ff478a77e4e4))
* **tools:** resolve send_message cwd fallback and background error accumulation ([b0ae62c](https://github.com/p4ulbr4dl3y/johnston/commit/b0ae62c7e472dfe178657306ed6e9c4d2843e34c))
* **ui:** apply CustomMarkdownFence globally so modal code blocks use dark background ([b278070](https://github.com/p4ulbr4dl3y/johnston/commit/b27807080368e1bcd3f7fe20b0f372f3e65d0b59))
* **ui:** fix import order in chat_view.py ([2015d39](https://github.com/p4ulbr4dl3y/johnston/commit/2015d396d468d2ad1beb30f6064c13bf58e91166))
* **ui:** fix project scope resolution and activation in /permissions modal ([b3128a4](https://github.com/p4ulbr4dl3y/johnston/commit/b3128a45594f5af7ccb96a2d1af0e3a5a6beaec5))
* **ui:** highlight first item in Groups/Tools tabs and active scope item in Scope tab ([9dc25f0](https://github.com/p4ulbr4dl3y/johnston/commit/9dc25f0c2b4889d73541523bc073ae4211a47417))
* **ui:** move format_edit_diff helper before ToolCallWidget class ([e48c177](https://github.com/p4ulbr4dl3y/johnston/commit/e48c177a05692594b2f746b0973ed940d21916eb))
* **ui:** pass target_highlight to update_step when toggling selection ([d326bdb](https://github.com/p4ulbr4dl3y/johnston/commit/d326bdbfa9ee42d393fd39db712b3a434347fd11))
* **ui:** preserve highlight on deselect and submit summary on enter in ask_user wizard ([0c2d54f](https://github.com/p4ulbr4dl3y/johnston/commit/0c2d54fad036c9b48135faace24ecbf9b542d96a))
* **ui:** remove dock top from search input so it stays below title ([24307dd](https://github.com/p4ulbr4dl3y/johnston/commit/24307dd3e05f07fbeab2aac4da182bd623b3c250))
* **ui:** remove redundant top margin on modal inputs to match help screen spacing ([26372fd](https://github.com/p4ulbr4dl3y/johnston/commit/26372fdd9ca989ffca544bcc5b7cdc4574a5d717))
* **ui:** remove trailing dash from scope items in permissions modal ([3c165f9](https://github.com/p4ulbr4dl3y/johnston/commit/3c165f95c68a7d20dc12236af715828e92cb0db5))
* **worktree:** detect manual subagent commits when diffing against parent base commit ([860fa80](https://github.com/p4ulbr4dl3y/johnston/commit/860fa80e508e4d64a0b975e5ccdc4acd1b082183))
* **worktree:** ensure keep_branch preserves subagent branch on changes ([d58daef](https://github.com/p4ulbr4dl3y/johnston/commit/d58daef85fc253961bb91c0ffd9877d8ad74ad84))
* **worktree:** prevent duplicate subagent- prefix in branch names ([3c02d0e](https://github.com/p4ulbr4dl3y/johnston/commit/3c02d0ee0c67ce692fa41fa0172c2a604d1548ce))

## [0.18.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.17.0...johnston-v0.18.0) (2026-08-06)


### Features

* **commands:** inject full skill content into prompt for slash commands ([16a6bb6](https://github.com/p4ulbr4dl3y/johnston/commit/16a6bb65bc58b2c32c13a3491f1a1fd5dd6716cd))
* **tools:** include line count and start_line hint in truncate_output footer ([a3a6af1](https://github.com/p4ulbr4dl3y/johnston/commit/a3a6af1e89817c288105415ef1b1134f929cf3c4))
* **tools:** optimize prompt caching and add tool parameter normalization ([7b0eb5f](https://github.com/p4ulbr4dl3y/johnston/commit/7b0eb5fdad86922943d398b9ecf46af1cd476cc6))

## [0.17.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.16.0...johnston-v0.17.0) (2026-08-05)


### Features

* **skills:** convert /init and /handoff commands to global skills ([f5f6fcf](https://github.com/p4ulbr4dl3y/johnston/commit/f5f6fcfd8b47afdb5d2d69d3d8c389598bb748ca))
* **tools:** enforce file read verification before create and edit ([872b3b5](https://github.com/p4ulbr4dl3y/johnston/commit/872b3b516bab214410812bd4663f686805dd8090))
* **ui:** persist global prompt history across sessions ([0067319](https://github.com/p4ulbr4dl3y/johnston/commit/006731958e2db21be25bb3f5ce8c2a3a88563bc0))


### Bug Fixes

* **cli:** prevent headless hang on shutdown and non-tty stdin ([296425b](https://github.com/p4ulbr4dl3y/johnston/commit/296425b034a0d350c2f75b86f1c0507b58e373b5))
* **providers:** handle data-wrapped responses from clinepass ([4583a7c](https://github.com/p4ulbr4dl3y/johnston/commit/4583a7ce645d887bb5ac4ebdce6dbc3c80f17a45))
* **skills:** support multiline YAML block scalars in frontmatter parsing ([27f0eb0](https://github.com/p4ulbr4dl3y/johnston/commit/27f0eb02b492f03de11341caa040ee16e478c50b))
* **tools:** auto-expand end_line for multi-line targets in edit tool ([1c034bd](https://github.com/p4ulbr4dl3y/johnston/commit/1c034bda15e308af330756ee624b293fb27b897b))
* **ui:** display only background tasks in task manager ([fdded33](https://github.com/p4ulbr4dl3y/johnston/commit/fdded33be14ecaf6e46263f5314a4231469cb94a))
* **ui:** filter non-background tasks before opening tasks screen ([3aaabf4](https://github.com/p4ulbr4dl3y/johnston/commit/3aaabf4660945d9175851214050c313da0107fc8))
* **ui:** strip OK status headers and system noise from tool diff views ([8fc8fcc](https://github.com/p4ulbr4dl3y/johnston/commit/8fc8fccdd476a8d8fc3c713813dbacb404b597cd))

## [0.16.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.15.0...johnston-v0.16.0) (2026-08-05)


### Features

* **cli:** add --system-prompt flag to print rendered system prompt ([a9c56e6](https://github.com/p4ulbr4dl3y/johnston/commit/a9c56e6aba853e029b63faf2135027bde4d6eee8))
* **prompt:** group skills and subagents by path templates in system prompt ([09e18f7](https://github.com/p4ulbr4dl3y/johnston/commit/09e18f75140f9db52d656fda9f66e882592abff6))
* **prompt:** increase project instructions truncation limit to 20000 chars ([5df8cc1](https://github.com/p4ulbr4dl3y/johnston/commit/5df8cc12147aa576c9ef3f30c5f3cac49a4a6549))
* **skills:** add session-debugger project skill ([3652e8a](https://github.com/p4ulbr4dl3y/johnston/commit/3652e8a2cd32a3fa7527f38c9d1fc281fa287f09))
* **tools:** add diff on create update, quote normalization and trailing newline deletion in edit ([70ceae7](https://github.com/p4ulbr4dl3y/johnston/commit/70ceae75dd5f0f957560817c48ca74b587655997))
* **tools:** expand tool aliases in ALIAS_MAP ([ffbb1f5](https://github.com/p4ulbr4dl3y/johnston/commit/ffbb1f5ce70b89f5fe86a854b3790589a8b3cb87))
* **tools:** pretty print JSON dumps and improve truncation hints ([09b6841](https://github.com/p4ulbr4dl3y/johnston/commit/09b6841a0867316035a449e3675d677f4654996e))
* **ui:** dynamic Queued Messages divider tracking exact unstarted queue boundary ([0f960f2](https://github.com/p4ulbr4dl3y/johnston/commit/0f960f28ce58b2cdc00848ad9bf58cee422b803f))
* **ui:** implement sticky Queued Messages divider with smart widget insertion above divider ([4279389](https://github.com/p4ulbr4dl3y/johnston/commit/42793896ef39f43ea1c5235dfa438f0c982e69c5))
* **ui:** make message queue production-grade with session drift protection and checkpointing ([0e3d8a9](https://github.com/p4ulbr4dl3y/johnston/commit/0e3d8a9db18856d1f7ff9987814564f5b5cdf805))
* **ui:** render Queued Messages divider above queued message execution block ([21f1c50](https://github.com/p4ulbr4dl3y/johnston/commit/21f1c5098cf898e8930911b0ccf4c6f10a982730))
* **ui:** simplify message queue to batch-process all queued inputs in a single clean turn ([8d2f6b4](https://github.com/p4ulbr4dl3y/johnston/commit/8d2f6b4fdda1f958230f10a120dee7cf1cdcb7c7))
* **ui:** unify code block syntax theme to one-dark ([31acbb8](https://github.com/p4ulbr4dl3y/johnston/commit/31acbb82af6c736f675b8d89f1d83c3815fdab9f))


### Bug Fixes

* **app:** respect show_in_ui flag when processing queued messages ([1171282](https://github.com/p4ulbr4dl3y/johnston/commit/1171282444f8c767019fd1b68b13dff387b1ef59))
* **ask_user:** clear write-in input value between wizard questions ([d0053d3](https://github.com/p4ulbr4dl3y/johnston/commit/d0053d319977308c74d1449fcbc272948038af4a))
* **ci:** fix ruff lint error and pytest test runner in release-please ([dde209b](https://github.com/p4ulbr4dl3y/johnston/commit/dde209b77f4d1190c480a06caece405955b8af4b))
* **cli:** exit process cleanly after TUI shutdown ([61fc366](https://github.com/p4ulbr4dl3y/johnston/commit/61fc366a3c087c000f9ac86b124e6c1a6c10f020))
* **cli:** exit process cleanly on exit and support RU hotkeys ([79fcc47](https://github.com/p4ulbr4dl3y/johnston/commit/79fcc47379e243a14cea7622e3304a3c5d1f7431))
* **cli:** use clean sys.exit instead of os._exit to restore terminal TTY state ([658db2c](https://github.com/p4ulbr4dl3y/johnston/commit/658db2c97465158de309c0c750002c3d41c53c1e))
* **prompt:** fix duplicate wording in DEFAULT_SYSTEM_PROMPT ([90c9ef9](https://github.com/p4ulbr4dl3y/johnston/commit/90c9ef9fc855204ed74f6064f29282508717a319))
* **provider:** sanitize interrupted tool calls with synthetic responses to prevent API 400 errors ([120b2ad](https://github.com/p4ulbr4dl3y/johnston/commit/120b2ad6b48f2b020470437f647a63c941516975))
* **tests:** resolve Windows CI race condition in test_exception_clears_queue ([4bb801a](https://github.com/p4ulbr4dl3y/johnston/commit/4bb801a41f6c03dc90cecf4c2ab5d8dc3b4471fc))
* **tests:** wait for is_generating reset in test_exception_clears_queue ([9b5a983](https://github.com/p4ulbr4dl3y/johnston/commit/9b5a983147856ebc909a9f374609ef8932e4a72d))
* **ui:** change divider title to Queued Message ([4e6bbba](https://github.com/p4ulbr4dl3y/johnston/commit/4e6bbba233ae946058ece01989bc2111c10f8768))
* **ui:** defer queued user message rendering to guarantee strict chronological chat order ([0fbc7ba](https://github.com/p4ulbr4dl3y/johnston/commit/0fbc7ba4e2208039e30f762fb3b5180378a78128))
* **ui:** defer rendering queued messages to guarantee strict chronological chat order ([dd3fbc4](https://github.com/p4ulbr4dl3y/johnston/commit/dd3fbc4f2cdc184d1ead0738a2bebbb8c2100025))
* **ui:** disable Rich markup parsing in Static widgets to prevent text formatting glitches ([c268368](https://github.com/p4ulbr4dl3y/johnston/commit/c2683682b3f895bfb9bb748024dbf60994fd237f))
* **ui:** eliminate async queue rendering race condition by awaiting _queue_message_ui directly ([159b549](https://github.com/p4ulbr4dl3y/johnston/commit/159b5492fe784be5d7dd8addaca029b2536d24ec))
* **ui:** extend diff line background colors to full widget width ([86e10d0](https://github.com/p4ulbr4dl3y/johnston/commit/86e10d002bdeeb0b7c06c9e098fd1f3772ff8637))
* **ui:** guarantee diff widget rendering when Create tool updates existing file ([da1ac4f](https://github.com/p4ulbr4dl3y/johnston/commit/da1ac4f0e92a44c429fc10b898e1a5983842a9ec))
* **ui:** handle missing theme attribute on CustomMarkdownFence ([0165f15](https://github.com/p4ulbr4dl3y/johnston/commit/0165f1546757bbbe3471a000139d417dee56e166))
* **ui:** keep only standard ctrl+c and ctrl+q bindings in chat_input ([defc6b9](https://github.com/p4ulbr4dl3y/johnston/commit/defc6b981d3aeb6c785ae37d6ec9a5f466d1be47))
* **ui:** match background color of CustomMarkdownFence Syntax to [#18181](https://github.com/p4ulbr4dl3y/johnston/issues/18181)b ([d1973a3](https://github.com/p4ulbr4dl3y/johnston/commit/d1973a389f2a3b6c640c8bc18af5801389ea56fa))
* **ui:** mount Queued Messages divider immediately when user queues input ([0496e28](https://github.com/p4ulbr4dl3y/johnston/commit/0496e2808e2a8edf1a7534e9b81364303ded1305))
* **ui:** position Queued Messages divider before first unstarted queued message ([d255044](https://github.com/p4ulbr4dl3y/johnston/commit/d255044c5595e7b6065429d17bef4a66d567c412))
* **ui:** preserve pre-mounted bot_msg reference during thinking stream ([027b070](https://github.com/p4ulbr4dl3y/johnston/commit/027b0701641ada4d3aac1bbe85f2492397674d14))
* **ui:** remove Queued Messages divider when queue is empty ([9a48c2f](https://github.com/p4ulbr4dl3y/johnston/commit/9a48c2f6b4a940b18a2ffa40166e096f86e14dfa))
* **ui:** render queued user message bubble immediately under Queued Messages divider ([05d0395](https://github.com/p4ulbr4dl3y/johnston/commit/05d03953cd631b6464baae1c421213f626689d08))
* **ui:** scope background tasks by session and sort running items first ([14a9e87](https://github.com/p4ulbr4dl3y/johnston/commit/14a9e878b0b5995151f3f63ff9d89be0d4cec012))
* **ui:** strip Success status text from diff view display ([7355d7c](https://github.com/p4ulbr4dl3y/johnston/commit/7355d7ce27e92a3365f0e25d1681eb19810b22f0))
* **ui:** strip system hints from UI tool expansion blocks ([33d2a75](https://github.com/p4ulbr4dl3y/johnston/commit/33d2a754afc24a82b8b6dddb165ea8a15074a59d))
* **ui:** use plain text lexer for non-code fence blocks to prevent false syntax highlighting ([483954d](https://github.com/p4ulbr4dl3y/johnston/commit/483954dfc38d6404e6c635014a371319119a3c96))


### Reverts

* **cli:** remove temporary --system-prompt debug flag ([209c18b](https://github.com/p4ulbr4dl3y/johnston/commit/209c18b05fcd52a50f6f0c5d828f0e36b969df58))


### Documentation

* **architect:** document .json format support for subagents in johnston-architect skill ([f072ceb](https://github.com/p4ulbr4dl3y/johnston/commit/f072ceb491048200719cdfd206ea6f6fc6dd1050))

## [0.15.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.14.0...johnston-v0.15.0) (2026-08-03)


### Features

* **subagent:** update completion hint to include send_message action and log file path ([2f46a06](https://github.com/p4ulbr4dl3y/johnston/commit/2f46a069b63055ff51f28612aebf3c691acf2398))
* **tools:** add run_in_background parameter to shell tool ([4ee3d18](https://github.com/p4ulbr4dl3y/johnston/commit/4ee3d18e8dfb84291e21f53d465a3fcda496454c))
* **tools:** update default shell timeout to 120s and max timeout to 600s ([44067c6](https://github.com/p4ulbr4dl3y/johnston/commit/44067c6ae240557e071f429d550404a0c682097f))
* **ui:** add ctrl+b keybinding to move all active foreground shell tasks to background ([784c618](https://github.com/p4ulbr4dl3y/johnston/commit/784c618ef131f72cec6e48eb6a7ff57917acb562))
* **ui:** render queued messages immediately with divider ([a773c54](https://github.com/p4ulbr4dl3y/johnston/commit/a773c54d27a83624ef77e98c1e025a56a75e9e34))


### Bug Fixes

* **ci:** fix ruff lint errors ([8414cd5](https://github.com/p4ulbr4dl3y/johnston/commit/8414cd56a0c6666e3227a72c85103db45bc1a0c1))
* **core:** remove queued messages divider ([bfb0926](https://github.com/p4ulbr4dl3y/johnston/commit/bfb09265d13f8155491a36d2b7e182ed532d350f))
* **test:** fix Windows process mocking and increase UI test pause delays ([7b9ee88](https://github.com/p4ulbr4dl3y/johnston/commit/7b9ee883724568f5c04b09a88a4bfe88cf9f9364))
* **test:** mock GitCheckpointManager in test_esc_key_cancellation_real_flow to avoid git delays on Windows ([9fc14f7](https://github.com/p4ulbr4dl3y/johnston/commit/9fc14f7a51f54a2c65fd2193b3c37acbe701f21e))
* **test:** mock GitCheckpointManager in test_generate_ai_response_queue_draining_and_attachments ([9d2412b](https://github.com/p4ulbr4dl3y/johnston/commit/9d2412b81872383a42c5f1ee49386d50b58f1ef1))
* **tools:** truncate shell output from tail and fix option highlight styling ([764155e](https://github.com/p4ulbr4dl3y/johnston/commit/764155e0cf301ada39a945a6b4f39b0c588043a1))
* **ui:** absorb vertical scroll events in ToolScrollBox to prevent chat from scrolling vertically ([e1d2946](https://github.com/p4ulbr4dl3y/johnston/commit/e1d294632f06a9068eacdc37cc80afbc53f9b5d3))
* **ui:** add text-wrap: nowrap; to tool content widgets to prevent Textual line wrapping ([5bfc49f](https://github.com/p4ulbr4dl3y/johnston/commit/5bfc49f151e52afe69e86e95f4f0cb7ed8ac60fc))
* **ui:** allow child width auto and min-width 100% with parent overflow-x auto to enable horizontal scroll ([6d8cd58](https://github.com/p4ulbr4dl3y/johnston/commit/6d8cd58a63b720b487348907ef16358fad3a35f0))
* **ui:** disable expand capability for read and web_fetch tools ([9a8365b](https://github.com/p4ulbr4dl3y/johnston/commit/9a8365b6d53775a44e0ce06a0ac1375ef8aefc87))
* **ui:** remove manual line wrapping in diff view to enable true horizontal scrolling ([bbe8329](https://github.com/p4ulbr4dl3y/johnston/commit/bbe832908757a6b57cc8426fd51962c3bf445f9e))
* **ui:** remove redundant newline in DiffRenderable to fix blank line gaps ([7485672](https://github.com/p4ulbr4dl3y/johnston/commit/74856728177fd301acf916ff4c08d820030c8d65))
* **ui:** restore normal vertical scrolling over code blocks ([95bbe92](https://github.com/p4ulbr4dl3y/johnston/commit/95bbe92a46b112368a7352264c24570b2cebc703))
* **ui:** use custom DiffRenderable to prevent Rich Text paragraph line wrapping ([64e11af](https://github.com/p4ulbr4dl3y/johnston/commit/64e11af21f60b6938e017b180c86bc4b8ec20067))
* **ui:** wrap tool content in inner scroll box so header stays fixed while content scrolls horizontally ([b59ea9f](https://github.com/p4ulbr4dl3y/johnston/commit/b59ea9fb46d88eed66eebe975b5cd7895505484d))


### Performance Improvements

* **ui:** use word_wrap=False and overflow-x auto for invisible horizontal scrolling ([a72bfd3](https://github.com/p4ulbr4dl3y/johnston/commit/a72bfd35d73882b6ac7304e7545001224bb51f31))


### Documentation

* **help:** add ctrl+b to keybindings list in help modal ([5a5e78f](https://github.com/p4ulbr4dl3y/johnston/commit/5a5e78f16c2baa9c2c76c36d885664ef9f7e86ba))

## [0.14.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.13.0...johnston-v0.14.0) (2026-08-03)


### Features

* **core:** auto-notify agent when background command requests interactive input ([131c97a](https://github.com/p4ulbr4dl3y/johnston/commit/131c97aef7ec9c906d7b4af9089779e2376ca0c8))
* **core:** process queued messages after each step in generation loop ([dc9bb5d](https://github.com/p4ulbr4dl3y/johnston/commit/dc9bb5dafb67dd702de5a739a77fddba912c0686))
* **tools:** add intuitive tool aliases (edit_file, spawn_subagent, mcp, fetch, etc.) ([cf43232](https://github.com/p4ulbr4dl3y/johnston/commit/cf43232df46df54c2073082338e2a6abf96722cb))
* **tools:** guide agent to use send_input when interactive prompt is detected ([d41aeda](https://github.com/p4ulbr4dl3y/johnston/commit/d41aedaf23457cb92ac787788a6baf4f814099e4))
* **tools:** include recent output tail on background task timeout ([4988dce](https://github.com/p4ulbr4dl3y/johnston/commit/4988dcedb2e051da6e0bb0c987a00f4244637234))
* **tools:** separate shell tool descriptions and enforce synchronous execution for subagents ([a2520db](https://github.com/p4ulbr4dl3y/johnston/commit/a2520dbbda782d612d408eb8cdb264490b4014d8))
* **ui:** add visual divider for queued messages injected mid-generation ([126f0ab](https://github.com/p4ulbr4dl3y/johnston/commit/126f0ab39b90a19b6e93fe1a12880179b5b61fb2))
* **ui:** right-align user message bubble with left-aligned text ([8c50340](https://github.com/p4ulbr4dl3y/johnston/commit/8c50340fb451d37500bc41043bde08f29d542536))


### Bug Fixes

* **core:** prevent test hangs in retry logic and MCP server init ([8e3ae03](https://github.com/p4ulbr4dl3y/johnston/commit/8e3ae036e53645080308debd2971f6e68c51b95d))
* **core:** rebuild prompt and tools per step for dynamic MCP registration ([46c0abe](https://github.com/p4ulbr4dl3y/johnston/commit/46c0abe967fd02123a1b6297f84d27931a6b5def))
* **core:** record tokens and update context on response interrupt ([afcb5c2](https://github.com/p4ulbr4dl3y/johnston/commit/afcb5c2fd09bda3730d48e3fc088bb1ca878966f))
* **core:** reset prompt_notified on send_input to support multi-prompt interactive commands ([e3ca1dd](https://github.com/p4ulbr4dl3y/johnston/commit/e3ca1ddf7b2e5d121f02378dc3a4dc71d130c307))
* **core:** set PAGER=cat and GIT_PAGER=cat in shell_env to prevent interactive terminal hangs ([e9c6008](https://github.com/p4ulbr4dl3y/johnston/commit/e9c6008905fff913489a30e06f4a8a59597baf5c))
* **mcp,core,tools:** implement async multiplexed MCP transport and fix TUI deadlocks on cancellation ([1a2ffd4](https://github.com/p4ulbr4dl3y/johnston/commit/1a2ffd42bc2dc04a74d19084eaf20bf9bcf00402))
* **mcp:** handle win32 pipe reading in MCPProcessClient ([804aa16](https://github.com/p4ulbr4dl3y/johnston/commit/804aa167e258a79586e2f873e0d9403e1b72aa25))
* **mcp:** restore blocking stdout and resolve sync-async event loop deadlocks ([10ecded](https://github.com/p4ulbr4dl3y/johnston/commit/10ecded894daeea40a9185262077d84a2f4a3b07))
* **shell:** read background stdout chunks instead of readline to capture interactive prompts without trailing newlines ([f946b2a](https://github.com/p4ulbr4dl3y/johnston/commit/f946b2a4d3ac8690faecd5db6b94a61d5c1760e0))
* **shell:** remove no_background parameter to prevent sync process hanging ([7a76167](https://github.com/p4ulbr4dl3y/johnston/commit/7a76167f0aa8344743a70e755d3a837c366d52f6))
* **shell:** standardize execution on standard pipes and hide system notification queued dividers ([e8da9da](https://github.com/p4ulbr4dl3y/johnston/commit/e8da9daca12d22306882cdc2e575f4eab03ed4d9))
* **subagent:** force asynchronous background execution for subagents to prevent main agent blocking ([d5cd965](https://github.com/p4ulbr4dl3y/johnston/commit/d5cd965de45af2957b9a4674b0d8ce6f5544761b))
* **ui:** address reviewer feedback for clipboard pasting ([a61aca8](https://github.com/p4ulbr4dl3y/johnston/commit/a61aca804aeb337642f1b1c20dfc286ff0e41db5))
* **ui:** collapse carriage returns and suppress terminal spinner animation spam ([63ef175](https://github.com/p4ulbr4dl3y/johnston/commit/63ef175f421ca1bd7480b43d2df077e65dee6124))
* **ui:** enable soft wrapping and line count height in ChatInput ([9b5d5f9](https://github.com/p4ulbr4dl3y/johnston/commit/9b5d5f9fe242e062c83b25c9bcc0384680c31d32))
* **ui:** handle file drag-and-drop and paste formatting into [@path](https://github.com/path) ([1dce5c2](https://github.com/p4ulbr4dl3y/johnston/commit/1dce5c22c1014421e0ea05a66b5fbb910f6a2073))
* **ui:** improve subagent modal layout, session loading, and streaming text handling ([f22f392](https://github.com/p4ulbr4dl3y/johnston/commit/f22f3920b54e5cfdd50b5e644d443e68e0a343e6))
* **ui:** render error text when update_plan fails ([f24de3d](https://github.com/p4ulbr4dl3y/johnston/commit/f24de3d84ff4044eb42e24ad19db4718456b8524))
* **ui:** smart Markdown vs Syntax rendering for web_fetch tool ([324a9bd](https://github.com/p4ulbr4dl3y/johnston/commit/324a9bdf79b3664915d1049250ac0dbbe996cf88))
* **ui:** update fallback MCP tool name to call_mcp in UI header extractor ([b795d9f](https://github.com/p4ulbr4dl3y/johnston/commit/b795d9f62430b691bd719f5082eb74ea444e4f08))


### Performance Improvements

* **ui:** make clipboard access asynchronous to prevent freezes ([6d48dd6](https://github.com/p4ulbr4dl3y/johnston/commit/6d48dd6d277f7e0a3e340b001062c3f67f732cda))


### Reverts

* **core:** remove experimental interactive prompt auto-detection ([a4ddc9d](https://github.com/p4ulbr4dl3y/johnston/commit/a4ddc9d1b072a3cf8b2ed27a7567e432c538037f))

## [0.13.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.12.0...johnston-v0.13.0) (2026-08-01)


### Features

* **ui:** add status colors for tool call headers ([b819705](https://github.com/p4ulbr4dl3y/johnston/commit/b819705faaa5bc9dd78e652458a8bffe4781289c))
* **ui:** format JSON tool output with multi-line indentation and syntax highlighting ([00965a9](https://github.com/p4ulbr4dl3y/johnston/commit/00965a9f58d08f96dbe6a4ae9677729fa7cd46cc))
* **ui:** format truncated JSON tool outputs with partial JSON parser ([51c7593](https://github.com/p4ulbr4dl3y/johnston/commit/51c7593ee09e173d24db4c43881d4c1a2716c45d))
* **ui:** make call_mcp_tool and custom MCP tools expandable ([0f7efa6](https://github.com/p4ulbr4dl3y/johnston/commit/0f7efa625d41d3dc6967bdb056de80d2cbcf0f50))
* **ui:** render output truncation notice as plain text below JSON syntax block ([5a7f84c](https://github.com/p4ulbr4dl3y/johnston/commit/5a7f84c23b8f7314a355356bcf17df09fb3f7e6c))


### Bug Fixes

* **prompt:** enforce strict non-polling rule for async actions ([6aebd0a](https://github.com/p4ulbr4dl3y/johnston/commit/6aebd0afaa2167c0df6db7011eefe2cdc1d1d6bf))
* **ui:** clean up MCP tool result formatting in UI ([4004f65](https://github.com/p4ulbr4dl3y/johnston/commit/4004f65ef553db475c8c551d582840451cf17ad2))
* **ui:** disable markup parsing on ToolCallWidget content to prevent Textual MarkupError ([0ecd0d2](https://github.com/p4ulbr4dl3y/johnston/commit/0ecd0d271aa801b3821a92be19146ab97459d5cd))
* **ui:** prevent MarkupError by disabling markup on tool content and using Text.from_ansi ([59a700a](https://github.com/p4ulbr4dl3y/johnston/commit/59a700abfa59c6bafa37d30b903384c044da2110))
* **ui:** prevent TUI freeze on message submission ([a98177e](https://github.com/p4ulbr4dl3y/johnston/commit/a98177e5e1d6c35628410920468361755f55b434))
* **ui:** sanitize ANSI escape codes prior to Rich markup escaping ([bcbe711](https://github.com/p4ulbr4dl3y/johnston/commit/bcbe71151cfd27e7a0dc166efe65ce9139c31883))

## [0.12.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.11.0...johnston-v0.12.0) (2026-08-01)


### Features

* **ui:** add immediate loading state and token metrics to /compact divider ([0f4b7b5](https://github.com/p4ulbr4dl3y/johnston/commit/0f4b7b5f326cc0289d7d1279244f7574f11cf2ed))
* **ui:** queue user input during manual /compact and drain queue on finish ([08baac2](https://github.com/p4ulbr4dl3y/johnston/commit/08baac238770e59da1664a7b82d86153fc30f930))
* **ui:** route all provider API errors to full-width event divider line ([87956c8](https://github.com/p4ulbr4dl3y/johnston/commit/87956c8bab056d317a13153acd00f56b76a8b55a))
* **ui:** update compaction divider to 'Compaction Cancelled' when cancelled via Esc ([2d07482](https://github.com/p4ulbr4dl3y/johnston/commit/2d07482c5fa221cdce7a8b6f2a164c4c14d971d7))


### Bug Fixes

* **compaction:** merge consecutive roles in compact_messages and report actual API errors ([22a9003](https://github.com/p4ulbr4dl3y/johnston/commit/22a90039d75089b7201db157659d3a6a92e3cfa4))
* **compaction:** move save_current_session to finally block in CompactCommand so failure/cancel divider states persist ([f3b26bb](https://github.com/p4ulbr4dl3y/johnston/commit/f3b26bb8f2f05e18fec3b8df91fd4f47d1d62690))
* **compaction:** pass base_url, api_key, model to adapter.stream_chat and handle adapter_text tags ([c0fa58a](https://github.com/p4ulbr4dl3y/johnston/commit/c0fa58a375a72842cc8daea5bce5880ba9a20664))
* **ui:** add Ctrl+C and Ctrl+Q keybindings to HelpScreen ([cf202a7](https://github.com/p4ulbr4dl3y/johnston/commit/cf202a7511fd810b297ea352597a65f7e30ba6bd))
* **ui:** ensure Ctrl+Q exit keybinding works across all modal screens ([72806bb](https://github.com/p4ulbr4dl3y/johnston/commit/72806bb245a84a415142fbcff7b1639ed717a83a))
* **ui:** handle task cancellation in _handle_markdown_task_done to suppress exit traceback ([e0bd414](https://github.com/p4ulbr4dl3y/johnston/commit/e0bd41427a18d853279d7172ea253ce191871ac7))


### Performance Improvements

* **ui:** replace Markdown with Static in ThinkingWidget for fast rendering ([a27c6fb](https://github.com/p4ulbr4dl3y/johnston/commit/a27c6fbd6133740df8088bc88f5e533efeee6d79))

## [0.11.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.10.0...johnston-v0.11.0) (2026-08-01)


### Features

* **tools:** truncate long MCP tool outputs at 8000 chars ([15bbd67](https://github.com/p4ulbr4dl3y/johnston/commit/15bbd67c29a7500d9c6cd4b668753475fa41f907))


### Bug Fixes

* **core:** resolve concurrency, adapter, and provider edge-case issues from audit ([6200267](https://github.com/p4ulbr4dl3y/johnston/commit/6200267c477a9c98b6ca19f2cfecedd353c42d5a))
* **tools:** avoid false line 1 match hint when target content is not found ([add43b7](https://github.com/p4ulbr4dl3y/johnston/commit/add43b7d5736b939e8ae126214b3cc643d0f2403))
* **tools:** resolve edge case bugs found during codebase audit ([78e55d7](https://github.com/p4ulbr4dl3y/johnston/commit/78e55d71c3984e8884bbe27c28141d333c393af3))
* **ui:** robust extraction and display for MCP tool calls ([fcf2cfd](https://github.com/p4ulbr4dl3y/johnston/commit/fcf2cfda7e968629fc36f070eb48ba64c2030889))

## [0.10.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.9.0...johnston-v0.10.0) (2026-07-31)


### Features

* **prompt:** insert active model display name into system prompt ([aef22b1](https://github.com/p4ulbr4dl3y/johnston/commit/aef22b17c096ebe91ec3d1121b7d99a1fb330cb4))
* **providers:** sync providers with opencode and add tab toggle ([5f52a78](https://github.com/p4ulbr4dl3y/johnston/commit/5f52a78c2906b198b84e61d471c42a94e9a45224))
* **ui:** add cross-platform clipboard image paste support ([b4d65fb](https://github.com/p4ulbr4dl3y/johnston/commit/b4d65fb2b916d7c52e6af9fb755837042f4c7469))


### Bug Fixes

* **providers:** make Tab key toggle reliable in ProvidersScreen ([4fc7ab8](https://github.com/p4ulbr4dl3y/johnston/commit/4fc7ab86a0432a0ab12dfad6b49647c41ada6d72))
* **providers:** treat disabled providers as disconnected and block prompt generation ([661f214](https://github.com/p4ulbr4dl3y/johnston/commit/661f214d9e97650df553aadd6e84357018b8f8e3))
* **tests:** skip PTY shell tests on Windows ([95e0c0f](https://github.com/p4ulbr4dl3y/johnston/commit/95e0c0f86785414edee31c824d1503c0bbc03d29))

## [0.9.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.8.2...johnston-v0.9.0) (2026-07-31)


### Features

* **commands:** add /detach command and update HelpScreen documentation ([ba0f904](https://github.com/p4ulbr4dl3y/johnston/commit/ba0f904b1a629212fd07660dbe233e1e3f24bb48))
* **core:** add Image Handling rule to DEFAULT_SYSTEM_PROMPT ([44dc58e](https://github.com/p4ulbr4dl3y/johnston/commit/44dc58eddca954d4208d4c05e29bc2c783349200))
* **tools:** add image viewing support to read tool with multi-provider vision adapters ([face64e](https://github.com/p4ulbr4dl3y/johnston/commit/face64ee5e893a066f12154b3a3b46893a2d723e))
* **ui:** add dedicated AttachmentBar and ClipboardAttachment system for clipboard images ([1eb9d15](https://github.com/p4ulbr4dl3y/johnston/commit/1eb9d15794b0e8ea3eb82d6a55de6a41da44d01d))
* **ui:** display box branch attachment indicator under UserMessage in ChatView ([54e6fd1](https://github.com/p4ulbr4dl3y/johnston/commit/54e6fd1e06dabec0ad5447275120af1322259278))


### Bug Fixes

* **commands:** include exact skill file location in prompt ([a1a8a6f](https://github.com/p4ulbr4dl3y/johnston/commit/a1a8a6f5a5dd0e53fa78684e13b0f2ab9f1401f3))
* **commands:** prevent ModelScreen from opening when no connected models exist ([aad14e4](https://github.com/p4ulbr4dl3y/johnston/commit/aad14e4a3fdaa78006fe9b6b4af1f4ab84bf373a))
* **commands:** show info notification when no connected providers exist on /models ([b670162](https://github.com/p4ulbr4dl3y/johnston/commit/b670162c384190f6eee7c4e1899b36b0f0ae4e47))
* **core:** fallback image tool result to text hint on non-vision provider error ([7f3a7bb](https://github.com/p4ulbr4dl3y/johnston/commit/7f3a7bb59fbca2fa113c48e3eaec5322fb5ef566))
* **core:** format openai image messages in direct base_provider client calls ([231b737](https://github.com/p4ulbr4dl3y/johnston/commit/231b73704c6a6e6f9d55b545a17942cbea5ddf95))
* **core:** inject hint when reading images with non-vision models ([e0d06a6](https://github.com/p4ulbr4dl3y/johnston/commit/e0d06a60365c4b62fd0ed3be5e4d6b4fd22ec029))
* **core:** pre-inject attachment images directly into turn history to prevent extra tool calls ([107fc82](https://github.com/p4ulbr4dl3y/johnston/commit/107fc8224ec730a2deaf790281a4ce7ee37bdc47))
* **core:** update vision error hint to concise token-efficient text ([1a59fc6](https://github.com/p4ulbr4dl3y/johnston/commit/1a59fc6d3c1219b66f85b819cad570d7409a78bf))
* **notifications:** restrict toast notifications and notify background subagent completion ([4ab1fea](https://github.com/p4ulbr4dl3y/johnston/commit/4ab1fea3dc99d55b7e30b9a252092d6a1ea4c2ba))
* **provider:** pass image attachments natively in user content array to fix vision model recognition ([5e58881](https://github.com/p4ulbr4dl3y/johnston/commit/5e5888112e04277e654cd14e26bf54de5aece360))
* **providers:** filter out unconfigured providers in fetch_models_grouped ([73fdc50](https://github.com/p4ulbr4dl3y/johnston/commit/73fdc507e5180697a5ed863af0a380b858f2723e))
* **providers:** prevent fallback to first provider on empty provider key and render select provider prompt ([db300d6](https://github.com/p4ulbr4dl3y/johnston/commit/db300d6e0f0d7d7e19bd1510b5998a7f36a1e722))
* **providers:** remove Ollama from default providers ([8361846](https://github.com/p4ulbr4dl3y/johnston/commit/8361846485e88e59373e96ea6a7ef826d57de196))
* **ui:** define ClipboardAttachment in chat_input and update compact StatusFooter rendering ([215195d](https://github.com/p4ulbr4dl3y/johnston/commit/215195d59274f7d9df690f269d2c0810d1e6e4a3))
* **ui:** define TEMP_IMAGES_DIR and refine image paste handling ([9d6115f](https://github.com/p4ulbr4dl3y/johnston/commit/9d6115f672fa28a2c2f2d7ae0b6732b52833aa43))
* **ui:** disable expansion for read tool on image files ([eb46814](https://github.com/p4ulbr4dl3y/johnston/commit/eb46814260f6277da138eb8d3b2b303b0cbfa3bc))
* **ui:** fix Textual markup parsing error in AttachmentBar ([998190a](https://github.com/p4ulbr4dl3y/johnston/commit/998190a1629c4458348d7a056f8e3d96dcf2b33c))
* **ui:** improve clipboard image paste using JXA AppKit reader for PNG and TIFF ([f73a0be](https://github.com/p4ulbr4dl3y/johnston/commit/f73a0beac817f5468f47d8e5d8c4e597496dbaba))
* **ui:** open ModelScreen with clear status message when no providers/models are connected ([7df2ae9](https://github.com/p4ulbr4dl3y/johnston/commit/7df2ae9358eea5d437fb6c9d4dd68a2675536466))
* **ui:** prevent duplicate skill loading on SkillsScreen mount ([e867ac8](https://github.com/p4ulbr4dl3y/johnston/commit/e867ac8a82023b68fafe5261fe74a8943c341560))
* **ui:** prevent header layout distortion on long code blocks ([a81865a](https://github.com/p4ulbr4dl3y/johnston/commit/a81865aca12efb1e61d327c34e9edc2ff6501514))
* **ui:** remove duplicate user message rendering in generate_ai_response ([0a49485](https://github.com/p4ulbr4dl3y/johnston/commit/0a494852c8ff1977a7ad9d5e9f60c1af1b19b136))
* **ux:** refine provider/model onboarding, status footer, and model catalog formatting ([67cac3a](https://github.com/p4ulbr4dl3y/johnston/commit/67cac3ab8ef3ffd91c5eee8aa5369d07317545df))


### Performance Improvements

* **app:** offload save_current_session during response streaming ([435496d](https://github.com/p4ulbr4dl3y/johnston/commit/435496d823f77ce3ba64dec2ba52da926d3074e9))
* **commands:** make /models command open instantly by non-blocking catalog refresh ([2818d24](https://github.com/p4ulbr4dl3y/johnston/commit/2818d24806a7ef1e63d658f5ad3ff0f7ab28df16))
* **providers:** strictly eliminate blocking HTTP requests in fetch_models_for_provider when force_refresh is False ([870bf9d](https://github.com/p4ulbr4dl3y/johnston/commit/870bf9df21678cad51a8a66b8a21a4dc3412d72b))
* **skills:** optimize system prompt snippet for token efficiency ([04ccaa2](https://github.com/p4ulbr4dl3y/johnston/commit/04ccaa2916a552cd869096b77e90c22ac7ecf24a))
* **tools:** cache shutil.which in linter and use zero-allocation finditer in token_util ([8f5cea7](https://github.com/p4ulbr4dl3y/johnston/commit/8f5cea7b0ebae961a5410be32a232747bdc7f125))
* **ui:** make MCPScreen open instantly by offloading MCP server process queries ([916d79a](https://github.com/p4ulbr4dl3y/johnston/commit/916d79a7d52412612a0df577efef1b61414f1c9b))
* **ui:** offload blocking I/O and optimize token estimation and suggestions ([b1c8e7b](https://github.com/p4ulbr4dl3y/johnston/commit/b1c8e7bd95292e3e1784b94ad28e797ec62a917a))
* **ui:** optimize markdown preprocessing loop, status footer timer, and skills screen loading ([5b55cd5](https://github.com/p4ulbr4dl3y/johnston/commit/5b55cd5c22f1707e59292f6831e56b25a65b41f1))
* **ui:** optimize ModelScreen rendering and catalog resolution to O(1) slug lookup ([b28f80a](https://github.com/p4ulbr4dl3y/johnston/commit/b28f80ab50debd85c4ecfe3ce28d7aa2bd967338))
* **ui:** pre-warm secondary tab cache in ModelScreen for 0ms tab switching ([6d17792](https://github.com/p4ulbr4dl3y/johnston/commit/6d177929d5f8a537acc77346b55257213013fca1))

## [0.8.2](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.8.1...johnston-v0.8.2) (2026-07-31)


### Bug Fixes

* **provider:** add deepseek-v4-flash to default models for search filter test ([ea7d65c](https://github.com/p4ulbr4dl3y/johnston/commit/ea7d65cfa9442583cdf52e34b09a53e1ff2262c6))
* **provider:** fallback to configured models list when offline or uninitialized ([8650fdc](https://github.com/p4ulbr4dl3y/johnston/commit/8650fdcc0b3a4bdc1fa1d067efca29713a4780e1))
* **provider:** include default model lists for built-in providers ([7eed28f](https://github.com/p4ulbr4dl3y/johnston/commit/7eed28f5ea216bb8ffb2e3abb0174725b3a862bf))
* **provider:** return configured models list when API key is not configured ([caf3339](https://github.com/p4ulbr4dl3y/johnston/commit/caf3339de82e51d3e6f1b218bdd4d0a8c92d6894))
* **provider:** set cheapest default model for each built-in provider ([29ed0ed](https://github.com/p4ulbr4dl3y/johnston/commit/29ed0ed215fc7962a45268c6c4a9a6e69b3f8390))


### Documentation

* add configuration guide and remove legacy config options ([a65fa1d](https://github.com/p4ulbr4dl3y/johnston/commit/a65fa1df3c79a33a3a2ec6c12dc5a769f2864a5b))
* standardize subagent system prompt format in configuration guide ([9aad9c8](https://github.com/p4ulbr4dl3y/johnston/commit/9aad9c8108cdddd13b2b7af09c9a200a85daf6e3))

## [0.8.1](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.8.0...johnston-v0.8.1) (2026-07-30)


### Bug Fixes

* **core:** prevent global path duplication when cwd is home directory ([e8d5e6e](https://github.com/p4ulbr4dl3y/johnston/commit/e8d5e6e623344e709d761c8f29c3c7580dfd633d))
* **thinking:** default effort resolution to auto when un-set for UI consistency ([ba678a4](https://github.com/p4ulbr4dl3y/johnston/commit/ba678a4eb947595510dea37a445c18019d089fc9))
* **ui:** highlight active item initially in ThinkingEffortScreen ([944c245](https://github.com/p4ulbr4dl3y/johnston/commit/944c2459ce745d94adfbea3e878b408448f271b9))
* **ui:** prevent crash when text selection container is None ([4c38f7b](https://github.com/p4ulbr4dl3y/johnston/commit/4c38f7b82be290923986611a10509c82fdbb5322))
* **ui:** refactor StatusFooter refresh logic and display skills as N/M ([048a2c0](https://github.com/p4ulbr4dl3y/johnston/commit/048a2c045ba7b1c14dd512677ac38ac36095dec9))

## [0.8.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.7.0...johnston-v0.8.0) (2026-07-30)


### Features

* **skills:** add hidden skill status toggle in UI and prompt filtering ([9bbf2cd](https://github.com/p4ulbr4dl3y/johnston/commit/9bbf2cd3a91e740aeeafe71a4aeb7be1a39e93d6))
* **ui:** show tool count in MCP modal and support dynamic tools update ([4e843b7](https://github.com/p4ulbr4dl3y/johnston/commit/4e843b7f7401b42c58ae3a3fc01620df7cfffdc1))

## [0.7.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.6.0...johnston-v0.7.0) (2026-07-30)


### Features

* **auto-healing:** add out-of-bounds start_line Auto-Fix Hint for read and edit ([2995775](https://github.com/p4ulbr4dl3y/johnston/commit/2995775fe19b9d5c885e859654d81034a978cbb4))
* **auto-healing:** add self-correction hints for edit, 404 read, unknown tools, and task ids ([b253aae](https://github.com/p4ulbr4dl3y/johnston/commit/b253aae54a39270ae5edfb4ab5aa48803312b119))
* **core:** add circuit breaker and production-ready retry resilience ([3656813](https://github.com/p4ulbr4dl3y/johnston/commit/3656813e8e71bda3147a90a531034f3a1fe61ca7))
* **mcp:** add get_mcp_schema tool and streamline lazy mcp prompt snippet ([765524c](https://github.com/p4ulbr4dl3y/johnston/commit/765524c8d2b18f6951ab5dba2d63ce078108d146))
* **mcp:** add parameter signatures to lazy prompt snippet and auto-hint schema on error ([b4ab52f](https://github.com/p4ulbr4dl3y/johnston/commit/b4ab52fca27a4b2ed13ae1e417b61342e83c0bbb))
* **ui:** add Ctrl+O keybinding and /expand command for chat blocks ([93ce44b](https://github.com/p4ulbr4dl3y/johnston/commit/93ce44bdeec5d46f46c9c935896bf0e38911a627))


### Bug Fixes

* **git-checkpoint:** enforce default exclude rules in shadow repos ([4e7adda](https://github.com/p4ulbr4dl3y/johnston/commit/4e7addad01ad54b90c9101e4c4a0872f8fd21863))
* **mcp:** add thread safety and pending response buffering to MCPProcessClient ([ac70616](https://github.com/p4ulbr4dl3y/johnston/commit/ac7061615a1170eae02e037cfc22df126f3f28ba))
* **perf:** fix prompt caching timestamp and optimize read directory listing ([159616c](https://github.com/p4ulbr4dl3y/johnston/commit/159616c46f5c64e2813d0a438ebdaad58b5acc0d))
* **skills:** stop auto-creating project .johnston/skills directory ([200c4e6](https://github.com/p4ulbr4dl3y/johnston/commit/200c4e66525f3455bb4f45189ee4515d0333bcd6))
* **test:** include Hint string in read directory output for test compatibility ([866368d](https://github.com/p4ulbr4dl3y/johnston/commit/866368d67dada080546085b2454824a5c15d5880))
* **test:** remove dot in registry Unknown tool output string for test compatibility ([e38253b](https://github.com/p4ulbr4dl3y/johnston/commit/e38253b4df195df6fcce96cf6a7e06445e861959))
* **tools:** increase shell background task timeout to 60 seconds ([d246068](https://github.com/p4ulbr4dl3y/johnston/commit/d2460689283bee25bdd91db434b2ee55aaf719f1))
* **ui:** format GetMCPSchema header with tool name in PascalCase ([aacde7c](https://github.com/p4ulbr4dl3y/johnston/commit/aacde7c2652f22fc4073181f8b46ca640550b4a5))
* **ui:** improve edit tool diff formatting, lexing and wrapping ([63e8f7c](https://github.com/p4ulbr4dl3y/johnston/commit/63e8f7ce9855cc5fd391e31aadd026a52e3e4714))
* **ui:** improve shell confirm modal layout and code block styling ([45e7a6b](https://github.com/p4ulbr4dl3y/johnston/commit/45e7a6b2a17d1592a3b75acbbe725f3d2ed55b8f))
* **ui:** restore tool display labels and syntax highlighting for file edits ([554faa1](https://github.com/p4ulbr4dl3y/johnston/commit/554faa1fd1c66d4d37cbf3b42e9c2e1178a29bbe))

## [0.6.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.5.0...johnston-v0.6.0) (2026-07-29)


### Features

* **core:** add rule 14 for skill slash commands to system prompt core principles ([e302780](https://github.com/p4ulbr4dl3y/johnston/commit/e3027807334fad505409de29859f913d2597db72))
* **core:** support skills anywhere in user prompt (start, middle, or end) ([425f8ba](https://github.com/p4ulbr4dl3y/johnston/commit/425f8baef1559b5d324751283381000d2b98fd01))
* **tools:** add hint when read tool is used on directories ([1ad3c98](https://github.com/p4ulbr4dl3y/johnston/commit/1ad3c98f63dbe3c0e085734a066e71de083d16b1))
* **tools:** auto-list directory contents in ReadTool ([0432523](https://github.com/p4ulbr4dl3y/johnston/commit/04325237b1e0ad80897656e0fd833571835503bf))
* **tools:** return clean error hint on directory read without dumping contents ([17a4797](https://github.com/p4ulbr4dl3y/johnston/commit/17a47975f0ab48fdf8093018b2812dd49ec05d06))
* **ui:** support slash suggestions anywhere in prompt and multi-skill execution ([596f027](https://github.com/p4ulbr4dl3y/johnston/commit/596f02745e86f5aa8f94ec4b88fbc728452680ac))


### Bug Fixes

* **app:** restore generate_ai_response method structure ([52771d1](https://github.com/p4ulbr4dl3y/johnston/commit/52771d1f8d21bc8b2b737a5bc92fe67e5be9a85b))
* **core:** invalidate ProviderManager cache on config writes and path changes ([02dcc34](https://github.com/p4ulbr4dl3y/johnston/commit/02dcc34e8f8fd54fc2c560ebd0437416d974dec1))
* **core:** isolate vision config in test_core_extra to prevent overwriting user config and format vision model exceptions ([fa3112e](https://github.com/p4ulbr4dl3y/johnston/commit/fa3112e773b0bf3c405ba4cd2b4a86d074408660))
* **core:** kill background processes synchronously on app exit ([ee83d70](https://github.com/p4ulbr4dl3y/johnston/commit/ee83d707927831e345dd8747884b2a154a8c3e99))
* **core:** prevent prompt file expansion for system notifications ([c981845](https://github.com/p4ulbr4dl3y/johnston/commit/c981845c5b8e0e2aa526144fb806bdd76fa6ded3))
* **lint:** remove unused imports and organize import blocks ([6619b9d](https://github.com/p4ulbr4dl3y/johnston/commit/6619b9d8f15af773413b4eecf8c2d461a4766a24))
* **prompt:** strictly forbid models from guessing image contents without calling view_image ([3ba20dc](https://github.com/p4ulbr4dl3y/johnston/commit/3ba20dcc2882713483e02cd96f027e29d53203a8))
* **session:** restore session ui messages sequentially in single async worker to prevent tool widget race condition ([b7dc060](https://github.com/p4ulbr4dl3y/johnston/commit/b7dc060866e02f3a838a3e60e2244d7a421c294d))
* **tests:** update analyze_image assertions after header removal ([c7ec5be](https://github.com/p4ulbr4dl3y/johnston/commit/c7ec5be42e4aadb36c36fec49ea7ba15407d6f1a))
* **tools:** add schema required fields, dir guards for edit/create, and filter explore tools ([ee9f95d](https://github.com/p4ulbr4dl3y/johnston/commit/ee9f95dc3fb72e1719e2d5a116a1cb76320c3c79))
* **tools:** enforce 800-line cap on format_line_pagination when end_line is specified ([1c036d1](https://github.com/p4ulbr4dl3y/johnston/commit/1c036d13e73e6ef07ddcb7a0ff00bbd566275352))
* **tools:** remove silent fallback to random providers in analyze_image to prevent unintended token usage ([7576c36](https://github.com/p4ulbr4dl3y/johnston/commit/7576c36592313a794e7547e4aa89498b54399e5a))
* **tools:** remove strict workspace path restriction ([e8eb779](https://github.com/p4ulbr4dl3y/johnston/commit/e8eb77956ae7459308a5dfadcb587a1d3743c41b))
* **tools:** require explicit Vision model setting if active model lacks vision support ([40bc187](https://github.com/p4ulbr4dl3y/johnston/commit/40bc18733fa5e2c4a14d6af0499b287c30b54bd5))
* **tools:** stop line pagination at complete line boundaries before max_chars limit ([4d4a714](https://github.com/p4ulbr4dl3y/johnston/commit/4d4a714bbf8a50adfb18e89e2a3438e3d49c3c92))
* **ui:** add clean_markdown_for_rendering preprocessor for nested markdown and edge-cases ([59eba55](https://github.com/p4ulbr4dl3y/johnston/commit/59eba55b4f27ca48089c146479802e1eb811cc8a))
* **ui:** add view_image to EXPANDABLE_TOOLS and tcss styling for full tool widget rendering ([869c94d](https://github.com/p4ulbr4dl3y/johnston/commit/869c94d9a330ca091274a43cdf52525b3dd95fc9))
* **ui:** append trailing space after file path insertion and paste ([29efbb0](https://github.com/p4ulbr4dl3y/johnston/commit/29efbb0c4a4201e3956627afa71ee35c605ded23))
* **ui:** call self.header_label.update in render_header for view_image tool widgets ([92afb3c](https://github.com/p4ulbr4dl3y/johnston/commit/92afb3caa57b8f4d56c3f86b6a351656a214a418))
* **ui:** check background task status before showing running command text ([567dd54](https://github.com/p4ulbr4dl3y/johnston/commit/567dd54c5594ad87793fe21849676df8d4ff2763))
* **ui:** colorize diff line numbers for added, deleted, and unchanged lines ([91e08ae](https://github.com/p4ulbr4dl3y/johnston/commit/91e08ae81e8a36ee08af8da9fe7b640e02e47c1f))
* **ui:** disable linkify autolinking for filenames like AGENTS.md ([da0a423](https://github.com/p4ulbr4dl3y/johnston/commit/da0a4236cf26c94e6c158e4e1876f054c3183e9d))
* **ui:** disable Textual tooltips globally at app level ([d8a0972](https://github.com/p4ulbr4dl3y/johnston/commit/d8a0972e4c907076b320c9645f240a491971a4b9))
* **ui:** enable shallow file suggestions in home directory ([e630a50](https://github.com/p4ulbr4dl3y/johnston/commit/e630a50d93441d703ca8bc34ac8f7e159b6f5802))
* **ui:** enhance diff code highlighting and syntax brightness in tool expansion ([0cd3652](https://github.com/p4ulbr4dl3y/johnston/commit/0cd3652c73ad24b494141bd4f92889d1898f9c34))
* **ui:** extend diff background color bar across full line width including line numbers ([9f5cab8](https://github.com/p4ulbr4dl3y/johnston/commit/9f5cab8360027120b4293cbdee599b16f578b3e5))
* **ui:** fallback to javascript lexer for non-html snippets in html files to prevent monochrome rendering ([9bf3912](https://github.com/p4ulbr4dl3y/johnston/commit/9bf39127cb75f293465c8b2629cf3d5f2c6a2944))
* **ui:** hide all scrollbars and scrollbar corners globally ([f0cf4c1](https://github.com/p4ulbr4dl3y/johnston/commit/f0cf4c15705112acaf96f5d351a9a5d435bb3111))
* **ui:** improve JS lexer detection in HTML diffs for string literal highlighting ([7d59552](https://github.com/p4ulbr4dl3y/johnston/commit/7d5955226d4b3d124eda7d89d7b3c5ed9783c433))
* **ui:** normalize double list markers in markdown tools ([06312ce](https://github.com/p4ulbr4dl3y/johnston/commit/06312ce2ef3c64d8086b1e1d597219e0cfbb26b1))
* **ui:** remove black scrollbar track overlays and enable clean seamless layout ([a1fa646](https://github.com/p4ulbr4dl3y/johnston/commit/a1fa646af4a5abba67b93ff03f28e0c5e941bdc6))
* **ui:** remove expansion support for ViewImage tool ([d8ee534](https://github.com/p4ulbr4dl3y/johnston/commit/d8ee534e2be35e63db5ae8f93d17764d5d2f5d20))
* **ui:** remove tooltip hover text on markdown table cells ([da0385e](https://github.com/p4ulbr4dl3y/johnston/commit/da0385e59c90fb119ec2cfb8237e7f104cb8228d))
* **ui:** rename ambiguous variable l in chat_view.py to fix ruff lint error E741 ([9819f56](https://github.com/p4ulbr4dl3y/johnston/commit/9819f561758ff1c7c860dddb6f464a43daa22a8d))
* **ui:** render clean slash command in UI when invoking skills ([db2a49b](https://github.com/p4ulbr4dl3y/johnston/commit/db2a49bce35d3f4044f8751ef1021c619f97f601))
* **ui:** render image reads as ViewImage widgets and enforce direct view_image in system prompt ([33383a4](https://github.com/p4ulbr4dl3y/johnston/commit/33383a45d6cc0297ec446caf16374711e5a95b9a))
* **ui:** suppress tooltips globally and strip table cell tooltips ([521a2ea](https://github.com/p4ulbr4dl3y/johnston/commit/521a2ea441e7b37f9a4bee64d9f8aab442ef2705))
* **ui:** unify scrollbars and disable task console output formatting ([a02cae1](https://github.com/p4ulbr4dl3y/johnston/commit/a02cae191bb106e45da577bdad8ae1421aa288a7))
* **ui:** use apply_suggestion for command autocompletion on Enter/Tab instead of load_text ([f3d69fd](https://github.com/p4ulbr4dl3y/johnston/commit/f3d69fdfa0c284adf790b198d3608597f69fb30a))
* **ui:** use monochrome white style for tool read errors ([dd8dcce](https://github.com/p4ulbr4dl3y/johnston/commit/dd8dcce887d3866902d71f4e9a7bb76242de4c69))
* **ui:** use regex for html tag detection to prevent js comparison operators from resetting lexer ([b437c5b](https://github.com/p4ulbr4dl3y/johnston/commit/b437c5b2b8402773f17bc9f2838dac401cb7724c))
* **vision:** filter usable providers by configured API key before resolving fallback vision model ([0e3c2ec](https://github.com/p4ulbr4dl3y/johnston/commit/0e3c2ec09efcb12feedb0b45aebc84ddc3075cd7))
* **vision:** refactor fallback vision persistence, provider compatibility and catalog caching ([b62116f](https://github.com/p4ulbr4dl3y/johnston/commit/b62116fd96e46cefaefd87b9019c4446af84aebd))


### Performance Improvements

* **models:** cache /models modal and simplify vision model selection ([74ce1ac](https://github.com/p4ulbr4dl3y/johnston/commit/74ce1ac3ba89cfaa581e9dc58aeccfa012743ef6))
* optimize UI threading and disk caching ([c9a64e1](https://github.com/p4ulbr4dl3y/johnston/commit/c9a64e1452cbbbc5cfa2f276ac4fdc47e0069e49))

## [0.5.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.4.0...johnston-v0.5.0) (2026-07-28)


### Features

* **core:** add Git Worktree workspace isolation for subagents ([83da834](https://github.com/p4ulbr4dl3y/johnston/commit/83da834116fdd2dfa83a885fa45058a3569c76d0))
* **shell:** add cross-platform ShellGuard and ShellConfirmScreen for destructive commands ([2ac51a7](https://github.com/p4ulbr4dl3y/johnston/commit/2ac51a7249ef0bc1d1c3b5450f005bfcf4a9ca5b))
* **tools:** add 800-line pagination windowing and doc caching to ReadTool ([c7ffd23](https://github.com/p4ulbr4dl3y/johnston/commit/c7ffd23fd639132d5f28430313f10dc22456f095))
* **tools:** add in-memory caching to web_fetch tool ([c8dbdbe](https://github.com/p4ulbr4dl3y/johnston/commit/c8dbdbe6ab2a9883b5641dede7828d730888c566))
* **tools:** add ReplaceFileContentTool and MultiReplaceFileContentTool with range matching ([d42cb8a](https://github.com/p4ulbr4dl3y/johnston/commit/d42cb8acdc97286fbea2066328cbb91352b3a890))
* **tools:** add update_plan tool and live plan widget based on OpenAI Codex spec ([eea4d33](https://github.com/p4ulbr4dl3y/johnston/commit/eea4d3328dd973ba1d317f3d19ced6839433b059))


### Bug Fixes

* **ask_user:** prevent down arrow in write-in input from advancing wizard step ([1f7b8fd](https://github.com/p4ulbr4dl3y/johnston/commit/1f7b8fdd1acaf8e3d8fee37b8f7eabf1df72387f))
* **catalog:** add background refresh on app mount and provider cache fallback ([f5c3e33](https://github.com/p4ulbr4dl3y/johnston/commit/f5c3e330fc88797f25d1a7d19c2d066db6e8ad06))
* **commands:** await both model list and catalog metadata before pushing ModelScreen ([22aab07](https://github.com/p4ulbr4dl3y/johnston/commit/22aab073c85471cf49561842c86d7a7c26a00aa2))
* **core:** update system prompt and mode rules for chunk editing, update_plan, and worktree isolation ([31d0a4f](https://github.com/p4ulbr4dl3y/johnston/commit/31d0a4f058455fae44d5cd1b97316f5d0597a1ff))
* **explore:** prohibit ask_user tool calls for mode switching in Explore mode prompt ([470e907](https://github.com/p4ulbr4dl3y/johnston/commit/470e907771fd438b1dbaf48be5f0c5d505912b31))
* **prompt:** remove edit tool names from base system prompt ([25813a9](https://github.com/p4ulbr4dl3y/johnston/commit/25813a93e5dbec399447e819e98864e2da9f8caa))
* **tools:** address edge cases, resource leaks, and argument validation ([ea3bd94](https://github.com/p4ulbr4dl3y/johnston/commit/ea3bd94340cabd8990240629157542368197560e))
* **tools:** update truncate_output hint to suggest shell grep/head/tail filtering ([ac11772](https://github.com/p4ulbr4dl3y/johnston/commit/ac117723e2d54205fa3e178325124071b402da58))
* **ui:** do not display line numbers for tool error messages ([f591c74](https://github.com/p4ulbr4dl3y/johnston/commit/f591c74289f65f80a7c70b5b17bc17a42381d5d1))
* **ui:** ensure text paste events do not query OS clipboard image when text is provided ([66d0ee7](https://github.com/p4ulbr4dl3y/johnston/commit/66d0ee7c06e90f32c9fcfccc1c906f5cca80ae3b))
* **ui:** format update_plan header with step progress and make plan widget expandable ([574706d](https://github.com/p4ulbr4dl3y/johnston/commit/574706d7541083097fdd0862cd997244bb90cc65))
* **ui:** handle CancelledError in markdown updates and throttle streaming ([a09f862](https://github.com/p4ulbr4dl3y/johnston/commit/a09f862d615f9689a9491cb44add0c62a8e82c1d))
* **ui:** strip hint lines from tool expansion view while preserving them for model context ([a64eaac](https://github.com/p4ulbr4dl3y/johnston/commit/a64eaac782a24ede495761dfa1376c3b8d0eee88))


### Performance Improvements

* **core,ui,tools:** fix event loop disk I/O, regex caching, queue exception safety, and file thread offloading ([a450cfe](https://github.com/p4ulbr4dl3y/johnston/commit/a450cfe3c7410ca8318b4876962181abcf678778))
* **ui:** prebuild tab options and optimize catalog key lookup for instant tab switching ([b989e95](https://github.com/p4ulbr4dl3y/johnston/commit/b989e95a8ce8476e9088e8e0d64301bf890c3e2b))

## [0.4.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.3.0...johnston-v0.4.0) (2026-07-27)


### Features

* add /demo slash command for instant AskUser modal preview ([6f910ae](https://github.com/p4ulbr4dl3y/johnston/commit/6f910ae86026700c3039baa00e8353f6aa5ce1c3))
* add /policy slash command and modal screen for security rule configuration ([08c3ad0](https://github.com/p4ulbr4dl3y/johnston/commit/08c3ad054fb4a7c49343eb3b5f41e359f9347cdb))
* add harness budgets and trace evals ([77636e4](https://github.com/p4ulbr4dl3y/johnston/commit/77636e4f5291104b0886beb3a3609548cb34f0b6))
* add tabbed UI in PolicyScreen with dedicated Resource Budgets tab ([3783e30](https://github.com/p4ulbr4dl3y/johnston/commit/3783e3008719dd7770f2b1a4f1d2de597b6ee806))
* add transactional harness controls ([ab52666](https://github.com/p4ulbr4dl3y/johnston/commit/ab5266654e734b18cadb5b4c2c8f0833ba6b6c8a))
* **ask_user:** allow toggling/deselecting options with Space key ([237845c](https://github.com/p4ulbr4dl3y/johnston/commit/237845c2603d22be5ad6a072c66e81ebe517337d))
* **commands:** add /demo command for 0-token interactive fake agent session ([cc1f25b](https://github.com/p4ulbr4dl3y/johnston/commit/cc1f25b8405665a4940e4b43da8925eb083f62ab))
* **commands:** add 2-minute background shell task loop to /demo for testing background tasks ([fe5369e](https://github.com/p4ulbr4dl3y/johnston/commit/fe5369ef6af130c37b8fba48c2b26f5c7df9a1b2))
* **commands:** add ask_user tool call and interactive QuestionScreen modal popup to /demo ([261f188](https://github.com/p4ulbr4dl3y/johnston/commit/261f1881764d8d202d303d8bd741045a702891f0))
* **demo:** run real AskUserTool with 3 multi-option questions in /demo ([cd1d307](https://github.com/p4ulbr4dl3y/johnston/commit/cd1d3076eaf1f43143269215aa4c21c25483e92e))
* harden agent harness policy ([bfa8de1](https://github.com/p4ulbr4dl3y/johnston/commit/bfa8de18fcb3c9461279ea2981aea98aa29dec3b))
* make budget limits optional and unlimited by default ([ec5c943](https://github.com/p4ulbr4dl3y/johnston/commit/ec5c94322b40efdba3c02b72c2bdd633b6633ff4))
* remove /rollback and /trace commands ([efd1025](https://github.com/p4ulbr4dl3y/johnston/commit/efd1025a4c403d01f57176f2b96f55eebf38274b))


### Bug Fixes

* **app:** execute slash commands via asyncio.create_task to avoid blocking Textual event pump ([842eb19](https://github.com/p4ulbr4dl3y/johnston/commit/842eb190b5f5fac59712a76f88fa792b899ec094))
* **ask_user:** automatically focus write-in input field when navigating to Write-in option ([0bbde9b](https://github.com/p4ulbr4dl3y/johnston/commit/0bbde9b6233d665ebf855e7857a50c791ebc36e5))
* **ask_user:** do not insert 'No response' text into input field state ([9321fae](https://github.com/p4ulbr4dl3y/johnston/commit/9321faeadbbeddd5af97796632cd1a575268b7e4))
* **ask_user:** eliminate modal flicker with single AskUserWizardScreen ([a6ee728](https://github.com/p4ulbr4dl3y/johnston/commit/a6ee728041ff0ea1df5b11bb5a648e8c9a6b5908))
* **ask_user:** enable full arrow key navigation (left/right/up/down) inside WriteInInput ([fbbc97c](https://github.com/p4ulbr4dl3y/johnston/commit/fbbc97cec420fd8bb2cd13b251024cb7a1e181b6))
* **ask_user:** preserve current option highlight index when deselecting an answer ([5902a5a](https://github.com/p4ulbr4dl3y/johnston/commit/5902a5a1357aa257021d1f55694df31fbaae6475))
* **ask_user:** prevent Enter key bleed across multi-question wizard screens ([c0259c1](https://github.com/p4ulbr4dl3y/johnston/commit/c0259c14694a785ab2b076580f53676e5c8f7470))
* **ask_user:** prevent focus escape via Tab/Shift+Tab keys in AskUserWizardScreen ([f2827b4](https://github.com/p4ulbr4dl3y/johnston/commit/f2827b4096eabc6e23c9b372798ba043e299dd35))
* **ask_user:** record 'No response' in Answer output without pre-filling the input field ([161a081](https://github.com/p4ulbr4dl3y/johnston/commit/161a08138cd60ad261bc36087803cd4ec281d401))
* **ask_user:** render escaped [✓] and [ ] status badges for options in OptionList ([ca2b2ab](https://github.com/p4ulbr4dl3y/johnston/commit/ca2b2ab837fec2a9fe45238f3b09498133b7da8a))
* escape bracket markup tags in PolicyScreen options ([86f59f7](https://github.com/p4ulbr4dl3y/johnston/commit/86f59f75947616e9b943ea36c8a1b186c0dd282e))
* handle OptionSelected event in PolicyScreen for Enter key selection ([6d1a27a](https://github.com/p4ulbr4dl3y/johnston/commit/6d1a27aa938cc54e71c17a1522ad4403a6b5116d))
* harden shell policy enforcement ([9cbb52a](https://github.com/p4ulbr4dl3y/johnston/commit/9cbb52aad6944007edb121bb8445a6e1063937ee))
* pass active thinking effort to status footer ([356d277](https://github.com/p4ulbr4dl3y/johnston/commit/356d277dd53bef683229689fba69c839e7af82de))
* prevent background polling and improve ask_user schema ([fc5c3f5](https://github.com/p4ulbr4dl3y/johnston/commit/fc5c3f5e864d83bf4c000fbaf97c6d5d8aa6dc81))
* prevent root directory freezes and fix MCP scope resolution ([219c9eb](https://github.com/p4ulbr4dl3y/johnston/commit/219c9eb29b0ab26f7e308952a0eebce676009ade))
* **provider:** deduplicate duplicate tool calls streamed in single response step ([c072f9a](https://github.com/p4ulbr4dl3y/johnston/commit/c072f9a7d74e016ea2e541161611768f67560300))
* **provider:** fix indentation error in tool execution loop inside BaseAgent.stream_steps ([b5da41a](https://github.com/p4ulbr4dl3y/johnston/commit/b5da41af329af0679f7bb4627d9839348a533849))
* remove /rules alias from PolicyCommand ([7c64868](https://github.com/p4ulbr4dl3y/johnston/commit/7c6486869199fee56dc369cc4d43f97b665734b4))
* remove trace rollback logic ([07c35d6](https://github.com/p4ulbr4dl3y/johnston/commit/07c35d69ae5169a8b8d3312b22178d0f7a0f1137))
* **subagent:** add 3-stage fallback lookup (session candidates -&gt; all sessions -> disk reload) ([0b6a81c](https://github.com/p4ulbr4dl3y/johnston/commit/0b6a81cb332e07c72c731fff078260328696738f))
* **subagent:** add substring and prefix matching fallback for subagent session lookups ([b1bd676](https://github.com/p4ulbr4dl3y/johnston/commit/b1bd67642e1728f28206bc2219f0818830205476))
* **subagents:** add disk reload and session fallback to /subagents screen ([22634d5](https://github.com/p4ulbr4dl3y/johnston/commit/22634d5802d5e08600fd004588015fed064c191c))
* **tcss:** clean up MarkdownFence and nested MarkdownBlockQuote borders ([47af2a1](https://github.com/p4ulbr4dl3y/johnston/commit/47af2a12993676e5b56ebf3c802daee006ca17b0))
* **tcss:** override text-style to none !important to prevent double-inversion in Input component selection ([c1f000e](https://github.com/p4ulbr4dl3y/johnston/commit/c1f000e70be4e1f814e953f3ac3c0f34c7b259c8))
* **tcss:** remove trailing duplicate closing brace in app.tcss ([47fba03](https://github.com/p4ulbr4dl3y/johnston/commit/47fba0333d7e080141002460398ebac08ca8e55c))
* **tools:** fix AskUserTool execution when agent.app is missing or not a UI instance ([4d4dcf7](https://github.com/p4ulbr4dl3y/johnston/commit/4d4dcf74379b174500559a18af4232518a1f1eae))
* **ui:** add _wait_until_attached check to ChatView mount methods to prevent MountError ([1901411](https://github.com/p4ulbr4dl3y/johnston/commit/19014113d62865829484dfe02869d219d6e95a1a))
* **ui:** add 250ms mount debounce to QuestionScreen to prevent accidental trailing Enter key auto-submit ([4be26fd](https://github.com/p4ulbr4dl3y/johnston/commit/4be26fd4ea5ccbb678127a1b699da86cc5126d83))
* **ui:** clear text selection and set cursor position to end on WriteInInput focus ([53474ef](https://github.com/p4ulbr4dl3y/johnston/commit/53474efa6b8030a5cab1604f48523176a620a899))
* **ui:** enable Up arrow navigation from write-in input back to OptionList ([4d9e05b](https://github.com/p4ulbr4dl3y/johnston/commit/4d9e05b1a697c18dfe5cb3af538c8e5725457e15))
* **ui:** ensure reliable modal focus and resolve test hanging in DemoCommand ([5540ed8](https://github.com/p4ulbr4dl3y/johnston/commit/5540ed89203f91308606ac87bb19730339027136))
* **ui:** handle awaitable and mock objects safely in TasksListScreen kill action ([1597f5e](https://github.com/p4ulbr4dl3y/johnston/commit/1597f5e371e4bf002d3e4ab76da35dd7c256a14a))
* **ui:** instantiate CustomMarkdownFence properly in Markdown initialization ([fcccfc7](https://github.com/p4ulbr4dl3y/johnston/commit/fcccfc77d7b3f65b877e5b4315086031c0906611))
* **ui:** override select_all and add call_after_refresh to prevent blue text selection on WriteInInput focus ([585c4d2](https://github.com/p4ulbr4dl3y/johnston/commit/585c4d28e0d092c7f9285a3c6ed320bf135e32c8))
* **ui:** refine markdown blockquote nesting and header spacing in TCSS ([0155c15](https://github.com/p4ulbr4dl3y/johnston/commit/0155c1509ad542fba0c9568914102652329ef1cb))
* **ui:** resolve subagent screen lookup by handling truncated description labels and task_id fallback ([f576278](https://github.com/p4ulbr4dl3y/johnston/commit/f57627819eba400ed6dbe87bb9e24957842c3afd))
* **ui:** restore click handler to open SubagentViewScreen for subagent and task tools ([d754c0d](https://github.com/p4ulbr4dl3y/johnston/commit/d754c0d13cea4e584623cb77beae408d57b10983))
* **ui:** truncate option list item text to prevent multi-line wrapping in rewind and resume screens ([56ddeef](https://github.com/p4ulbr4dl3y/johnston/commit/56ddeefe8083de4263bdb50b5d24946ad5636848))
* **ui:** use WriteInInput subclass to intercept Up arrow and return focus to OptionList ([27d30e2](https://github.com/p4ulbr4dl3y/johnston/commit/27d30e275c723251af8a4cfaeb0a3ad888a1660b))


### Documentation

* **ask_user:** instruct LLMs to list recommended options first with (Recommended) prefix ([cef02e2](https://github.com/p4ulbr4dl3y/johnston/commit/cef02e2c811e4b569be73f40bc0dac21eeac48ff))
* update AGENTS.md repository guidelines ([dad9ff0](https://github.com/p4ulbr4dl3y/johnston/commit/dad9ff076b829f16f62c6215f8478759955c061c))

## [0.3.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.2.2...johnston-v0.3.0) (2026-07-27)


### Features

* add shadow git checkpoint system for /rewind ([e47b7ae](https://github.com/p4ulbr4dl3y/johnston/commit/e47b7ae2a1ae71cecddeb8705ffa3dd59041acb5))
* auto init git and display fallback checkpoint status labels in rewind modal ([878431c](https://github.com/p4ulbr4dl3y/johnston/commit/878431c39b60b3b908113ab253f360c3734ce5d0))
* format API error messages cleanly across all provider adapters ([2ca9761](https://github.com/p4ulbr4dl3y/johnston/commit/2ca97612e4d0d11c105e19cf60d1d73fd6455ee1))
* show git diff stats in rewind modal ([97a2279](https://github.com/p4ulbr4dl3y/johnston/commit/97a22792c530e09e1794d7e444c6e8daf5c0ae3d))


### Bug Fixes

* adjust rewind modal option width truncation so diff stat labels fit on screen ([9fe2e26](https://github.com/p4ulbr4dl3y/johnston/commit/9fe2e26afd288391e25f0f6a55c6ba82b3d74251))
* cap supported python version to &lt;3.14 for onnxruntime compatibility ([d6854e8](https://github.com/p4ulbr4dl3y/johnston/commit/d6854e8fe52a6db6552cd0f04723b196cc5561c4))
* pass explicit project_path to GitCheckpointManager ([2ee6428](https://github.com/p4ulbr4dl3y/johnston/commit/2ee6428876f7c7caca42bec1dac99c3d4157e737))
* set max_text_len to 45 for rewind screen ([afad92b](https://github.com/p4ulbr4dl3y/johnston/commit/afad92b4ada63a686e509988fc081e23f9e780ac))
* use parentheses formatting for diff stat labels to prevent Rich markup stripping ([3335de0](https://github.com/p4ulbr4dl3y/johnston/commit/3335de0db098911051783f58167c1192f5968384))
* use sequential message index for git checkpoint lookup in /rewind ([4eb724a](https://github.com/p4ulbr4dl3y/johnston/commit/4eb724af579a5134a31981d5f96c31c7897c4c1a))

## [0.2.2](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.2.1...johnston-v0.2.2) (2026-07-27)


### Bug Fixes

* await read_task before closing pty transport in ShellTool ([b00c955](https://github.com/p4ulbr4dl3y/johnston/commit/b00c95593d44ba55b322221fce404150aaa96dd8))
* ignore SIGHUP signal on PTY to prevent runner shutdown on Linux ([ffa5534](https://github.com/p4ulbr4dl3y/johnston/commit/ffa5534bc693ed48d582422f7bcd330098951c29))
* remove secondary raw os.read on PTY EIO to fix Linux asyncio transport cleanup ([05120e8](https://github.com/p4ulbr4dl3y/johnston/commit/05120e8aee5a22d516ac86719c89be62c1b7337b))
* remove start_new_session in PTY branch to prevent Linux TTY driver SIGHUP signal to runner ([5503476](https://github.com/p4ulbr4dl3y/johnston/commit/55034766e44e95890880e68922d58f190618756e))
* resolve PTY transport file descriptor leak ([3fa1457](https://github.com/p4ulbr4dl3y/johnston/commit/3fa1457dcbb19eb32d84d0cd4851c7855ecd648c))
* validate pid in terminate_process to prevent os.killpg(0) self-termination on Linux ([6d390fc](https://github.com/p4ulbr4dl3y/johnston/commit/6d390fcf7d8a4b31c87a8318d2ffa543a10c7e95))

## [0.2.1](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.2.0...johnston-v0.2.1) (2026-07-26)


### Bug Fixes

* avoid model catalog refresh during tests ([beb36ec](https://github.com/p4ulbr4dl3y/johnston/commit/beb36ec55dd8ca6f59551e264d39363f483a8f9c))
* eliminate race condition in test_list_sessions ([92c5d05](https://github.com/p4ulbr4dl3y/johnston/commit/92c5d05df374958709a02692bd71072818d31e04))
* reset usage metrics on rewind ([28f3aa7](https://github.com/p4ulbr4dl3y/johnston/commit/28f3aa7179e08dc4089c36f56b1c772942afde46))
* stabilize session ordering test ([6d21803](https://github.com/p4ulbr4dl3y/johnston/commit/6d218039eaa82ba4d0ff59d95a0759af87a22263))
* strip trailing newlines in create tool ([4c261b8](https://github.com/p4ulbr4dl3y/johnston/commit/4c261b85470ad4e86795f15984923f67fcc22a58))

## [0.2.0](https://github.com/p4ulbr4dl3y/johnston/compare/johnston-v0.1.4...johnston-v0.2.0) (2026-07-26)


### Features

* activate skill directly and insert slash command into input on enter ([3788fd5](https://github.com/p4ulbr4dl3y/johnston/commit/3788fd59228ddc511aee2cad95544b3084617391))
* add --subagents flag to CLI argument parser ([c03880a](https://github.com/p4ulbr4dl3y/johnston/commit/c03880a047a68390331d1a1aed6485c4eb23f735))
* add @ file suggestions, drag-and-drop image tags, and clinepass provider ([7e98802](https://github.com/p4ulbr4dl3y/johnston/commit/7e988023a6d3e4d966621760b7e511a8548bb60f))
* add /copy slash command to copy last assistant message to clipboard ([6a7f3c2](https://github.com/p4ulbr4dl3y/johnston/commit/6a7f3c2da9c69c72e3868ca760e48b30a8163ec6))
* add /paste command and expand hotkeys for pasting clipboard images ([6f5b8e3](https://github.com/p4ulbr4dl3y/johnston/commit/6f5b8e37777d425f256c0c39fc1bf70046f8edfd))
* add /rules slash command and RulesScreen modal by analogy with /mcp ([cdc1a54](https://github.com/p4ulbr4dl3y/johnston/commit/cdc1a54cfecad710bb03f3f79b64b0bf533554cc))
* add /skills slash command and SkillsScreen modal dialog ([8a3700d](https://github.com/p4ulbr4dl3y/johnston/commit/8a3700daa03e241b78242976df3f2d40ec9938db))
* add 3-line status footer with subagents counter and /subagents command ([5a8cad0](https://github.com/p4ulbr4dl3y/johnston/commit/5a8cad0f41dd03009d01cfeb73e17c9414ef95c6))
* add automatic line numbering to Read tool output for easy precise editing ([47cc43b](https://github.com/p4ulbr4dl3y/johnston/commit/47cc43bde83ff9db6bae2854567721174b0e69a5))
* add Bash mode toggle via Shift+! and /bash command, render tool widget only ([00c69ce](https://github.com/p4ulbr4dl3y/johnston/commit/00c69ced4279b52ea4150dfff79025894952ded6))
* add centered johnston welcome banner on empty chat screen ([8345b93](https://github.com/p4ulbr4dl3y/johnston/commit/8345b93dc4720fcc5e688b93c948ab4c90e388e6))
* add click-to-copy functionality for messages and tool results ([15ea01b](https://github.com/p4ulbr4dl3y/johnston/commit/15ea01b275972c1b18afe8e91be25933b83532e9))
* add clinepass provider to project providers ([869fb5f](https://github.com/p4ulbr4dl3y/johnston/commit/869fb5fdd1872c45582580117e17a6e28bf3e6a1))
* add clipboard image pasting support with automatic [Image #N] formatting ([b957403](https://github.com/p4ulbr4dl3y/johnston/commit/b957403a5bc1e7272257e0ec267530f3fe4a9e64))
* add cross-platform shell support ([983f1b1](https://github.com/p4ulbr4dl3y/johnston/commit/983f1b1ca137f67bee487d9e8f272ad915b9f13a))
* add direct shell execution via !cmd prefix without LLM call ([7779ce7](https://github.com/p4ulbr4dl3y/johnston/commit/7779ce7e3a511265d79c765cab4205f20ef60393))
* add global (~/.tui/skills) and project (.tui/skills) Skill support ([cbd58fa](https://github.com/p4ulbr4dl3y/johnston/commit/cbd58fac779cff062d3672b3667801986a265818))
* add global and project MCP support with /mcp modal toggle command ([5a61180](https://github.com/p4ulbr4dl3y/johnston/commit/5a6118011399d9ed776d9f21e1b34b2a6f9ec108))
* add globs field formatting in RuleDetailScreen ([1b665e5](https://github.com/p4ulbr4dl3y/johnston/commit/1b665e562947a704ad8489065acdefc9be45fcf7))
* add handoff slash command ([f30c700](https://github.com/p4ulbr4dl3y/johnston/commit/f30c700504e454c1549afa1497d88a9375c4d4ed))
* add install.sh script ([babdd3e](https://github.com/p4ulbr4dl3y/johnston/commit/babdd3e4f6af1cccc49f2c5e4123278487717865))
* add johnston-architect meta-skill for system self-configuration ([61650cb](https://github.com/p4ulbr4dl3y/johnston/commit/61650cb47dd6c1f7ba033599d4fcd206479b1623))
* add ManageTask tool for AI agent to inspect and kill background tasks ([7bb0980](https://github.com/p4ulbr4dl3y/johnston/commit/7bb0980e3ad4f46f03fedd763199d9ad120d218d))
* add markdown rules engine with frontmatter mode and globs filtering ([d8f8945](https://github.com/p4ulbr4dl3y/johnston/commit/d8f894575bfc3c0bad9ba52da405e360243a6c2d))
* add multi-format API adapters for OpenAI, Anthropic, Gemini, and Ollama ([dbfd9b0](https://github.com/p4ulbr4dl3y/johnston/commit/dbfd9b0432990bf1fa80b15df0e52d290192ec13))
* add NVIDIA NIM provider ([f123551](https://github.com/p4ulbr4dl3y/johnston/commit/f123551dc2c16d101e82ec45448178e08e13396e))
* add Plan and Build modes with Tab key toggle and PlanExit tool ([634f011](https://github.com/p4ulbr4dl3y/johnston/commit/634f011b76f41baeca48a16fea558144f38b109d))
* add PTY and interactive stdin for Bash, fix file paste and single-line tool headers ([5b75afc](https://github.com/p4ulbr4dl3y/johnston/commit/5b75afc121078bb69b9434ac9b7754b5347cae72))
* add ruff linter configuration and fix lint errors ([a009338](https://github.com/p4ulbr4dl3y/johnston/commit/a0093388b61fbdce056d8e6f405be69b95bd7822))
* add search input to ProviderScreen and ConnectProviderScreen ([9f6d28d](https://github.com/p4ulbr4dl3y/johnston/commit/9f6d28d1c2554e4b6415eb0509e7388dc25c67ff))
* add smart retry system with exponential backoff for stream timeouts and transient errors ([3910e8e](https://github.com/p4ulbr4dl3y/johnston/commit/3910e8e0831299e33329fe9f2f2d8d64ce1855e8))
* add stdin piping, clean stdout output, and -q/--quiet/--verbose flags for CLI headless mode ([1337ff6](https://github.com/p4ulbr4dl3y/johnston/commit/1337ff64a4aff0913c9d7b20ca18f9dbbf05d29c))
* add Subagent TaskTool with foreground and background execution ([61805c0](https://github.com/p4ulbr4dl3y/johnston/commit/61805c071fa08f04346650bb03a1c479538707b7))
* add support for .johnston/rules and .windsurfrules ([206a323](https://github.com/p4ulbr4dl3y/johnston/commit/206a3239f335fec819685157594b5d8e99f76489))
* add support for global and project user rules in system prompt ([905c6fa](https://github.com/p4ulbr4dl3y/johnston/commit/905c6fa6b20183ed2cc48a280233096f95bcdaae))
* add thinking effort controls ([555d2aa](https://github.com/p4ulbr4dl3y/johnston/commit/555d2aaeb5b3126849f9522a0d63211a7f90db5b))
* add token cost tracking from OpenRouter catalog ([3d070bd](https://github.com/p4ulbr4dl3y/johnston/commit/3d070bd8c1389c50897d9e64acde5ae9c0909e90))
* add token counting, models.dev context limits, and 2-line status bar ([59a90e1](https://github.com/p4ulbr4dl3y/johnston/commit/59a90e1c691aca1d86522c286ac109fa510f8383))
* add top 15 popular 2026 provider presets to DEFAULT_JSON_PROVIDERS ([63e69ff](https://github.com/p4ulbr4dl3y/johnston/commit/63e69ffbeb27e6e0ebac02281e6246b549b1f450))
* add ViewImageTool and update ReadTool to support reading images ([e76b7b9](https://github.com/p4ulbr4dl3y/johnston/commit/e76b7b9540001283b191d01311ed9a4848a2c7d6))
* add vision capability detection and fallback sub-agent vision analysis ([c252ddc](https://github.com/p4ulbr4dl3y/johnston/commit/c252ddca62f0e8942cae228ae7bc886d5b487fa8))
* **agent:** implement automatic context compaction when history exceeds 75% threshold ([0bd6b1c](https://github.com/p4ulbr4dl3y/johnston/commit/0bd6b1c3ce4be8a3f700751ad7515d445dc387f8))
* **app:** append interruption marker to agent history so LLM is aware it was interrupted ([4bc4d3b](https://github.com/p4ulbr4dl3y/johnston/commit/4bc4d3b14e8a8fd4a5776d7416f0f1cd3c355121))
* append trailing space and hide suggestions on Tab completion ([a767fe3](https://github.com/p4ulbr4dl3y/johnston/commit/a767fe39fcc816d7cf111b0c9da638e3edddd37b))
* auto-save truncated tool outputs to ~/.johnston/logs/last_tool.log ([065e3eb](https://github.com/p4ulbr4dl3y/johnston/commit/065e3ebccd06e463249aebb86013aced966cc5c6))
* **bash:** add production bash command permission guard and confirmation modal ([333c4bf](https://github.com/p4ulbr4dl3y/johnston/commit/333c4bf6d066587a38bef000c69b0dd795d770ed))
* **build:** align build mode prompt principles with Kilo (no unsolicited commits, minimal comments, lint/test verification, concise outputs) ([30840df](https://github.com/p4ulbr4dl3y/johnston/commit/30840df116125b56d1a6a4e15b6019ffbb369245))
* bypass confirmation popups for user-initiated direct Bash mode commands ([99ed8fc](https://github.com/p4ulbr4dl3y/johnston/commit/99ed8fc24b96af721bb3d27908aec648b672cc10))
* change Plan/Build mode toggle hotkey to Shift+Tab ([78be775](https://github.com/p4ulbr4dl3y/johnston/commit/78be7751e6d617784640cb9f5ad67b46146aa509))
* check architecture.input_modalities array from API/cache to determine vision support ([c007a9e](https://github.com/p4ulbr4dl3y/johnston/commit/c007a9e7cb8352550f1d9885fc5afd62d64eb268))
* clean up slash command alias descriptions and add standard aliases ([672f53d](https://github.com/p4ulbr4dl3y/johnston/commit/672f53d2d51f3c4d509151c82d715e873d060c79))
* **cli:** add CLI flags for prompt, mode, provider, model, resume, models, skills, mcp, rules, and version ([6ff9d96](https://github.com/p4ulbr4dl3y/johnston/commit/6ff9d96919d8e8abafad61c8027876ddbc29e43f))
* color code edits with red and green striping like git diff ([f6242f0](https://github.com/p4ulbr4dl3y/johnston/commit/f6242f0309e805455ed9366a29a39efae604a2c7))
* **compaction:** OpenCode-grade context compaction, incremental summary & footer UI metric fixes ([471e927](https://github.com/p4ulbr4dl3y/johnston/commit/471e927ec00855e28fca8a13980df104ab0d3171))
* complete integration of sequential AskUser questionnaire modal screens with TCSS styles and label mapping ([93d1b8f](https://github.com/p4ulbr4dl3y/johnston/commit/93d1b8fa1ac327d373a88046f882e373acdac567))
* copy text selection on mouse up and immediately clear the selection ([45b22d8](https://github.com/p4ulbr4dl3y/johnston/commit/45b22d82e91dce3ce34b1dc65abda5a1d4b744c6))
* **core:** extract reasoning/thinking tokens from delta and model_extra for OpenRouter models ([624ec2c](https://github.com/p4ulbr4dl3y/johnston/commit/624ec2c282ba2ee5a6f2eb996298658fb05bc286))
* default ListDir target path to . ([54eca9a](https://github.com/p4ulbr4dl3y/johnston/commit/54eca9a001c17eb1ac2bd7e0e4664b6b58fa73fd))
* disable background timeout for user direct Bash mode commands ([706127a](https://github.com/p4ulbr4dl3y/johnston/commit/706127ac7d225e306946c17efd4b3e7000fbca72))
* display directory, provider, model, context limit, token count, and cost in StatusFooter ([514e510](https://github.com/p4ulbr4dl3y/johnston/commit/514e510c580b27a9d8b304cc31f2f90e8806850c))
* display human-readable provider name in status bar ([44cc9a6](https://github.com/p4ulbr4dl3y/johnston/commit/44cc9a68d4f498c1a4c46609195c60817b613aa9))
* display Skills and active MCP servers count in status bar ([70eb477](https://github.com/p4ulbr4dl3y/johnston/commit/70eb477ebc3784dcf177b6e6fda55866d82ad1d6))
* dynamic skill autocompletion and direct slash execution ([9b43a8e](https://github.com/p4ulbr4dl3y/johnston/commit/9b43a8e17311428c7f9b28cea1693c8d38abce35))
* dynamically adapt ViewImage tool schema based on model vision support ([b0270ae](https://github.com/p4ulbr4dl3y/johnston/commit/b0270ae89421ad2bc5d57c235fa7de3470eae2f6))
* dynamically bind active MCP server tools to agent and registry ([c3f991d](https://github.com/p4ulbr4dl3y/johnston/commit/c3f991ddc66e3d1fe0760b8f513e0bd2051cde06))
* enable fuzzy search by provider name and model tokens in /models ([7cab611](https://github.com/p4ulbr4dl3y/johnston/commit/7cab6113d412d64efabb790845959094ce8af925))
* fetch model catalog & context limits from OpenRouter API, remove models.dev ([47f1437](https://github.com/p4ulbr4dl3y/johnston/commit/47f143751d1a987ecfedc50ab8fd5ac808e0c8b0))
* format AskUser tool target header with quoted question list ([083f34e](https://github.com/p4ulbr4dl3y/johnston/commit/083f34e3a8185e7dca30d86f67dd41b156abe6c3))
* format Grep and Glob tool targets as pattern in path ([73ba482](https://github.com/p4ulbr4dl3y/johnston/commit/73ba482692fa7acf3b9d48c937196b1956e51c62))
* format ManageTask target with action and task_id ([dfde099](https://github.com/p4ulbr4dl3y/johnston/commit/dfde099bbcb849a43deeabbd2907ceaa20c6a9ac))
* format tool expand views (Create shows file content, Edit shows git diff, Read has no expand) ([f03d5a9](https://github.com/p4ulbr4dl3y/johnston/commit/f03d5a92d887f75bf933d3f34a8f4f10d590dd47))
* format ViewImage tool target with prompt and path ([5e5f965](https://github.com/p4ulbr4dl3y/johnston/commit/5e5f965fd5eaf9ea36de1de37b89ef1d3a7cd985))
* group models under disabled section headers in /models screen ([e6f9a88](https://github.com/p4ulbr4dl3y/johnston/commit/e6f9a88f2933846de71124f3dbe2e0150d208b64))
* hide system notification from UI when background bash command completes ([60cf1fd](https://github.com/p4ulbr4dl3y/johnston/commit/60cf1fd6a5415d0de7814b4aac1bf80f308bb6ba))
* highlight active model and select it by default in /models screen ([2ee3d66](https://github.com/p4ulbr4dl3y/johnston/commit/2ee3d665e1f4560144d6a1c3a9fa3ac0053b1612))
* highlight last option by default and remove index prefixes in RewindScreen ([ef880c7](https://github.com/p4ulbr4dl3y/johnston/commit/ef880c7daba359fe66d2823687d1afa1dd0c2744))
* hybrid models catalog (models.dev + openrouter) with fuzzy matching ([2952891](https://github.com/p4ulbr4dl3y/johnston/commit/2952891b47af2366bf8e71a0e5266f2624916313))
* implement 2-tab SubagentsScreen modal with left/right tab switching for tasks and templates ([2345481](https://github.com/p4ulbr4dl3y/johnston/commit/23454810a497e4df8e731e08bb882bb1fd4ee51f))
* implement custom modes system with global and project override support ([1eac65e](https://github.com/p4ulbr4dl3y/johnston/commit/1eac65e4538bed08130b245e5a0d0f90ce312655))
* implement message queuing and refine monochrome markdown UI styles ([5134a13](https://github.com/p4ulbr4dl3y/johnston/commit/5134a13c1fe131ae65fd9a48959c9a554ee15250))
* implement OpenCode-grade provider features (reasoning_effort, headers, extra_body, SSE chunk timeout, fallback provider routing) ([26a1707](https://github.com/p4ulbr4dl3y/johnston/commit/26a17076384bb55fcf28b64922a642f288148326))
* implement prompt caching parsing and separate active context usage from cumulative total tokens ([0716bb2](https://github.com/p4ulbr4dl3y/johnston/commit/0716bb2d6fbc6feca76d343eaa9c50347afa53c1))
* inject available MCP tools description into agent system prompt ([b1c0d70](https://github.com/p4ulbr4dl3y/johnston/commit/b1c0d707c423719a89a7380a93acd622b148faac))
* integrate /init and /compact commands with AI context compaction ([3238359](https://github.com/p4ulbr4dl3y/johnston/commit/32383594650741ad1fa784da24b5c8d0b9680b0b))
* integrate background tasks manager modal and /tasks slash command ([ee787c0](https://github.com/p4ulbr4dl3y/johnston/commit/ee787c07aeb6bed21db8ebd2d309012f7ba324ef))
* integrate RTK CLI proxy and remove obsolete list_dir, grep, glob tools ([55e4705](https://github.com/p4ulbr4dl3y/johnston/commit/55e470548a7bc98c6db75eefcb199a57bf4fe184))
* integrate sequential questionnaire wizard with autofocus and key-navigation into AskUser tool ([e98617b](https://github.com/p4ulbr4dl3y/johnston/commit/e98617b439a6da79b16bbf5c381381a1fc080d97))
* intercept sleep commands in BashTool using Python asyncio.sleep ([18896c4](https://github.com/p4ulbr4dl3y/johnston/commit/18896c407b3054c128861e8ede8d882fa4842194))
* keep provider section headers in search results if models match ([8c80088](https://github.com/p4ulbr4dl3y/johnston/commit/8c8008861337abd7ca4e591827744ed6405fb789))
* **linter:** use uv run ruff for Python linting ([3e8da99](https://github.com/p4ulbr4dl3y/johnston/commit/3e8da992e93611a9a1596aebf2cfb10bfdd91825))
* load clicked message text directly into input field instead of clipboard ([69aaa47](https://github.com/p4ulbr4dl3y/johnston/commit/69aaa47a266fd7670cdadf2e41c1c09f725937ab))
* make /paste command universal for both text and image clipboard content ([951644d](https://github.com/p4ulbr4dl3y/johnston/commit/951644d629909264a5f50c82cd92b99576690774))
* make ToolCallWidget expandable on click to show execution output ([f508690](https://github.com/p4ulbr4dl3y/johnston/commit/f50869005c67879a3ed323be9c959fcb4f3a9fe2))
* map OpenRouter model IDs to clean display names in UI and status bar ([f6284bb](https://github.com/p4ulbr4dl3y/johnston/commit/f6284bb5c7d15d5f3b639d42e8eafd8993502ec8))
* **mcp:** add support for eager and lazy MCP servers with CallMCPTool ([5d922cc](https://github.com/p4ulbr4dl3y/johnston/commit/5d922cc93b66fa3d944052b6173f88d6c6882c8f))
* middle truncation for long tool target headers ([c82e3a9](https://github.com/p4ulbr4dl3y/johnston/commit/c82e3a9a9f4215fe4a59160eb5efae916bbdcfe7))
* migrate to JSON provider schema and dynamic subagent registry ([213e9c9](https://github.com/p4ulbr4dl3y/johnston/commit/213e9c94af14b4a9aa42e4a9a6133707821748a0))
* **models:** extract and cache real-time model context_length from provider API ([d7e8661](https://github.com/p4ulbr4dl3y/johnston/commit/d7e86611a48565e92fd01f7406031d5125c9e358))
* **models:** trigger vision warning modal every time a non-native vision model is selected ([8261bae](https://github.com/p4ulbr4dl3y/johnston/commit/8261baee995325c805fdaec69cabe237c109a842))
* **modes:** add specialized modes (ask, debug, orchestrator, plan, build/code) with targeted prompts, read-only guards, and slash commands ([32784a2](https://github.com/p4ulbr4dl3y/johnston/commit/32784a2ea98f12dd5efd65bb5a8431642009177b))
* modify rewind logic to load selected message into input field and remove it from chat ([70ca31f](https://github.com/p4ulbr4dl3y/johnston/commit/70ca31f232cd159f48d85eb2cc9721e020896f42))
* move providers to project dir, add /connect command and grouped /models ([6d330e6](https://github.com/p4ulbr4dl3y/johnston/commit/6d330e6114136615d3c5f14b049bf2b6af9b2a9e))
* non-interactive CLI --prompt mode, MCP singleton & FastMCP parser fixes ([8fbe275](https://github.com/p4ulbr4dl3y/johnston/commit/8fbe275ee291d80c1ee3b5aa4a536b1969d27a13))
* **plan:** instruct model to call PlanExit after user confirms the plan ([d9d77d6](https://github.com/p4ulbr4dl3y/johnston/commit/d9d77d60ac0264290207dbe1751ceac5e61c8562))
* **plan:** update Plan mode to be read-only in chat without creating disk files ([e127884](https://github.com/p4ulbr4dl3y/johnston/commit/e127884ec53e5be6169d1cc88f6cc64d8de04c4d))
* **prompt:** auto-inject AGENTS.md / CLAUDE.md / .cursorrules project instructions into system prompt ([9cfd501](https://github.com/p4ulbr4dl3y/johnston/commit/9cfd501544ab45d4876a0dc17f84056b114e3db8))
* **prompt:** dynamic environment metadata (CWD, Local Time, OS, Git context) in system prompt ([da077e8](https://github.com/p4ulbr4dl3y/johnston/commit/da077e8054dfbc6d6e407f087a738515cf3e599b))
* **prompts:** upgrade SYSTEM_PROMPT to professional agent coding principles ([a836d7c](https://github.com/p4ulbr4dl3y/johnston/commit/a836d7cd7fcc519653944e0d025942897d772527))
* **providers:** add OpenRouter provider template ([f9ad727](https://github.com/p4ulbr4dl3y/johnston/commit/f9ad727cd77ef902f95c07789c830854e15de058))
* **providers:** convert clinepass to custom python plugin provider ([ac81741](https://github.com/p4ulbr4dl3y/johnston/commit/ac81741f319b0daf8f444acda8028599da12258f))
* redesign HelpScreen into 2 tabs for Commands and Keybindings ([6856a98](https://github.com/p4ulbr4dl3y/johnston/commit/6856a984e6fbab4ac80360f7bdbd91ef875a4505))
* redesign status footer to compact 2-row layout with bullets and Unix dir style ([e3dfbe1](https://github.com/p4ulbr4dl3y/johnston/commit/e3dfbe17cabdc204b3777dc78bd543c00bee2320))
* rename /connect to /providers with provider management and enable/disable toggling ([4ee52b2](https://github.com/p4ulbr4dl3y/johnston/commit/4ee52b271f1c37442523970d1796758d406ecdc1))
* render empty parentheses for PlanExit tool header ([f40c614](https://github.com/p4ulbr4dl3y/johnston/commit/f40c614a9b826b16323d7bde5b459bdcf2980c73))
* restore /demo command ([6827d84](https://github.com/p4ulbr4dl3y/johnston/commit/6827d84aa59d64976aff53a05dcc26c72a460af6))
* restrict text selection to only user and AI messages in TUI ([ce73a9f](https://github.com/p4ulbr4dl3y/johnston/commit/ce73a9fb24f1b238f57c8ab27b98fb238add9339))
* run bash commands in background if they take longer than 5 seconds ([5ae8308](https://github.com/p4ulbr4dl3y/johnston/commit/5ae830814022f2f75a8205ef269907d99aa7b222))
* sanitize history and preserve context across model/provider switching ([28464ad](https://github.com/p4ulbr4dl3y/johnston/commit/28464ad69874f2067b88ff0b1eafb6ed304b572b))
* set cline-pass/mimo-v2.5 as preferred vision fallback model ([a47deff](https://github.com/p4ulbr4dl3y/johnston/commit/a47deff69b7e86f02a57aaf538d96aafae4c65b1))
* set cost-efficient default models with tool calling for providers ([1c692b9](https://github.com/p4ulbr4dl3y/johnston/commit/1c692b917b81f16c9a509f6dc4f7a5fedbf2ed59))
* setup release-please workflow ([c676288](https://github.com/p4ulbr4dl3y/johnston/commit/c676288b4a71694b283422b71fe8b4e72f88cf04))
* show interactive [Select model: /models] prompt in status bar when model is unselected ([bd60883](https://github.com/p4ulbr4dl3y/johnston/commit/bd6088397c86301bb05873d4308af6f9f6f4ea71))
* simplify agent modes to Action and Explore with SwitchToAction tool ([db8292f](https://github.com/p4ulbr4dl3y/johnston/commit/db8292f2757a4f4cd2052a82a8534942f9effb21))
* **subagent:** add /subagents command and interactive SubagentsListScreen modal screen ([8963912](https://github.com/p4ulbr4dl3y/johnston/commit/89639124a5be959c3cbedd7664975a09d931ff33))
* **subagent:** add JSON disk persistence for subagent sessions ([c96a549](https://github.com/p4ulbr4dl3y/johnston/commit/c96a549f0b67fa0f6fdcaca390f3a8c96b17005a))
* **subagent:** add live subagent watch modal screen with real-time streaming ([cadaed5](https://github.com/p4ulbr4dl3y/johnston/commit/cadaed5b21fbd80109ca9cc79b1dbd1ec9f00426))
* **subagent:** add manage_subagent tool for list, status, kill, and send_message ([931f420](https://github.com/p4ulbr4dl3y/johnston/commit/931f4204b7b04a96fe875f8b7886475e7edd1dd9))
* **subagent:** add optional background flag for send_message in manage_subagent ([7cb286c](https://github.com/p4ulbr4dl3y/johnston/commit/7cb286caa2711dd953e9d2361299be05eb5e56f6))
* **subagent:** aggregate subagent token usage and cost into main agent metrics ([19a953d](https://github.com/p4ulbr4dl3y/johnston/commit/19a953d800aa66101b40cfed7d6a3d0fb133d654))
* **subagent:** bind subagents to current chat session_id to isolate subagents per session ([efefc00](https://github.com/p4ulbr4dl3y/johnston/commit/efefc00a872654be5bd29992b577b8753c6d4e47))
* **subagents:** add full log file path to manage_subagent status output ([1194c56](https://github.com/p4ulbr4dl3y/johnston/commit/1194c565a040ed54a1b81bd6997709b47a8a38b8))
* **subagents:** add MAX_CONCURRENT_SUBAGENTS limit check ([c3b1621](https://github.com/p4ulbr4dl3y/johnston/commit/c3b1621b3fe3cd06a558be233536ec8307d53d9c))
* **subagents:** enforce read-only tools and update system prompt for explore subagent ([c630b8e](https://github.com/p4ulbr4dl3y/johnston/commit/c630b8eb328bd09fa374e4c047cce3b6b05f70f5))
* suppress CLI progress bars using TERM=dumb and collapse carriage return lines ([f046d6b](https://github.com/p4ulbr4dl3y/johnston/commit/f046d6b05aa51971af2be1bf5fda443ecc12c726))
* **tools:** add ListDirTool for fast 1-level directory listing ([1957040](https://github.com/p4ulbr4dl3y/johnston/commit/195704072f26038c66e99e5dfa995f23a2dfd55f))
* **tools:** centralize truncate_output helper with actionable LLM hints across all tools ([7e998eb](https://github.com/p4ulbr4dl3y/johnston/commit/7e998eb96834a23b6a0affea32e1c8baf6c88b54))
* **tools:** expand ignore filters for Glob and Grep tools ([4c6d195](https://github.com/p4ulbr4dl3y/johnston/commit/4c6d1956321fcc0fd7632752e0aeab4981d7a217))
* **tools:** format line numbers in ReadTool and add ambiguity check to EditTool ([b566c08](https://github.com/p4ulbr4dl3y/johnston/commit/b566c080a35ae46b4361d6028f9f73143e5c7710))
* **tools:** increase bash background timeout to 60 seconds ([db981a6](https://github.com/p4ulbr4dl3y/johnston/commit/db981a6f0b46a2d58813dedd28a12afb303c1815))
* **tools:** integrate markitdown into read and add production web_fetch tool ([ae71b12](https://github.com/p4ulbr4dl3y/johnston/commit/ae71b12f780d6a2b8e18f0251dafe9bc1ff69a13))
* truncate long tool header targets in base_provider ([834f4e1](https://github.com/p4ulbr4dl3y/johnston/commit/834f4e1bfd35ece878ff294d1c8ab686a1a96f2e))
* **ui:** add All Models and Vision Models tab filtering in ModelScreen ([915d28b](https://github.com/p4ulbr4dl3y/johnston/commit/915d28bbc98333448066f0b09f591a87548077d5))
* **ui:** add animated model generation spinner to status footer ([b1c466d](https://github.com/p4ulbr4dl3y/johnston/commit/b1c466d3c74371ffdfaf1fb7841ecc46fe1206fe))
* **ui:** add click expansion and collapse support for ThinkingWidget ([bf5efb3](https://github.com/p4ulbr4dl3y/johnston/commit/bf5efb3a9ee910794e3e81f19f24b3505925bcce))
* **ui:** add copy button for markdown code blocks and remove function name underline ([6eed113](https://github.com/p4ulbr4dl3y/johnston/commit/6eed113fd1ff29e06fa9e3bbe769f32536afa26e))
* **ui:** add expandable tool widgets with line numbers and syntax highlighting ([96779a0](https://github.com/p4ulbr4dl3y/johnston/commit/96779a0058e6fe3d85a0ee5e02110183a9eaf573))
* **ui:** add expansion support for web_fetch tool in chat ([007a8e1](https://github.com/p4ulbr4dl3y/johnston/commit/007a8e1f705bf8dd55a7f7ab77335716d62b16b7))
* **ui:** add Links section to /demo command showcase ([d76338d](https://github.com/p4ulbr4dl3y/johnston/commit/d76338ddc635202dd2dd30c9d1755f2b0eacc824))
* **ui:** add live search input to ModelScreen modal ([1af2ff9](https://github.com/p4ulbr4dl3y/johnston/commit/1af2ff979ff43da05f8a7098e0bf137c0961c844))
* **ui:** add live streaming for Bash tool and clean background task system output ([89a100d](https://github.com/p4ulbr4dl3y/johnston/commit/89a100d6757956e55f0ea4d0489d6e59ce903a3e))
* **ui:** add syntax-highlighted diff rendering for Edit tool and fix linter build noise ([884abfb](https://github.com/p4ulbr4dl3y/johnston/commit/884abfb3eff1414eeec5e8aad2a3446294f1c43a))
* **ui:** add vision warning modal screen with interactive actions and clean layout ([c8a1baa](https://github.com/p4ulbr4dl3y/johnston/commit/c8a1baab80f8251ea6ab86f5a717faf044875d5b))
* **ui:** apply compact dict args formatting to all multi-parameter tools ([d355238](https://github.com/p4ulbr4dl3y/johnston/commit/d355238e7a4539bcc512c92a0bef5ea44c3a180b))
* **ui:** atomic deletion of [Pasted text #N +X lines] blocks on Backspace/Delete ([e562cf7](https://github.com/p4ulbr4dl3y/johnston/commit/e562cf7dc07c0345a1c57b11cff104c92aaec920))
* **ui:** automatically open TasksListScreen on application startup ([7363392](https://github.com/p4ulbr4dl3y/johnston/commit/736339267ffebed7aee9b3b823e8f67560f39929))
* **ui:** clean up Read tool output formatting by stripping redundant headers and line prefixes ([3032b10](https://github.com/p4ulbr4dl3y/johnston/commit/3032b10544c9b5a8e03b056bf3c15ea6ee8d549a))
* **ui:** collapse long pastes into [Pasted text #N +X lines] placeholder in ChatInput ([72ad448](https://github.com/p4ulbr4dl3y/johnston/commit/72ad4487cd66ea04689adefcbc5dfaa864ce69e8))
* **ui:** display EAGER/LAZY badge and add toggle mode hotkey in MCP modal ([df28a65](https://github.com/p4ulbr4dl3y/johnston/commit/df28a65d83c46a2fa2d62d137b92729d398e49ed))
* **ui:** format CallMCPTool header as tool_name({compact_args}) with expandable JSON card ([1b54f4a](https://github.com/p4ulbr4dl3y/johnston/commit/1b54f4a57244a2ab9a67e97a578c6bd0b1cae09a))
* **ui:** implement multi-word token search & relevance scoring in BaseSelectionScreen ([46abf98](https://github.com/p4ulbr4dl3y/johnston/commit/46abf98981ce4dd7146a98876eb9ecf0eac36af6))
* **ui:** refine model selection screen and vision warning modal layout ([c8c641a](https://github.com/p4ulbr4dl3y/johnston/commit/c8c641aebc008c7583ada72cea59b0efcec3a3bb))
* **ui:** render Bash tool output as plain text without syntax highlighting ([0e2f72e](https://github.com/p4ulbr4dl3y/johnston/commit/0e2f72ede8eff9cf0b835fd50592a954257ddb85))
* **ui:** render response interrupted state using centered divider and clean history note ([28fb824](https://github.com/p4ulbr4dl3y/johnston/commit/28fb8244083db03d1013b4aeea853b601bbc483d))
* **ui:** restrict tool expansion exclusively to Create, Edit, Bash, and Read ([fd47881](https://github.com/p4ulbr4dl3y/johnston/commit/fd478816ac1d592d94153c5c65a430e219e1f12a))
* **ui:** support live streaming reasoning output in ThinkingWidget when expanded ([d4002a0](https://github.com/p4ulbr4dl3y/johnston/commit/d4002a01df689a34a978beb6a316c201be1f6d81))
* unify all providers under JSON configuration system ([eecada6](https://github.com/p4ulbr4dl3y/johnston/commit/eecada66d4616265053a44da13654553643728c2))
* update --help description to Johnston Coding Agent and bump to v0.1.2 ([9339fdf](https://github.com/p4ulbr4dl3y/johnston/commit/9339fdf6cc1323d9bb005e5ce94e706248aec2d9))
* update skills modal to single-liners with detail view ([c8f3551](https://github.com/p4ulbr4dl3y/johnston/commit/c8f35515edb471a92e8ca188c1cc50765b38bea9))
* **vision:** add image auto-resizing and history token optimization for vision models ([3196316](https://github.com/p4ulbr4dl3y/johnston/commit/3196316bf8b2aa9ab49907ab3cecfff5ab52bfcc))
* **vision:** scope Select Vision Model action strictly to view_image fallback without altering main agent model ([af74d32](https://github.com/p4ulbr4dl3y/johnston/commit/af74d322b177ac002f3f7551deb4f753a0889def))


### Bug Fixes

* add core_dir to sys.path for backward compatibility with external provider configs ([fa4b37b](https://github.com/p4ulbr4dl3y/johnston/commit/fa4b37bb5c322bf19c0f7bfa075d004d7d9e0e55))
* add fallback priority for provider active model selection ([6722e3b](https://github.com/p4ulbr4dl3y/johnston/commit/6722e3b26808e5fd82720d6962b66a902a21a2ce))
* add Language Matching rule to DEFAULT_SYSTEM_PROMPT ([a31bcd9](https://github.com/p4ulbr4dl3y/johnston/commit/a31bcd98b2ec3a3d86e22b4151bf7dc304cf648e))
* add missing import os in base_provider.py ([95393cb](https://github.com/p4ulbr4dl3y/johnston/commit/95393cbedf3bd0b64dc185455a6a90eb878bacfd))
* **agent-loop:** enforce subagent recursion guard, safe turn-boundary compaction, and json syntax error reporting ([9b8fe46](https://github.com/p4ulbr4dl3y/johnston/commit/9b8fe46e53edc1e736693e0ef047914e1c9015ed))
* **agent:** dynamically refresh MCP tools after calls and rebuild tools list on each step ([f5cf89e](https://github.com/p4ulbr4dl3y/johnston/commit/f5cf89edb8054b429c15da88d06c3785b6a1a8f3))
* **agent:** enable tool-calling in native adapters and harden agent loop ([87cf2dc](https://github.com/p4ulbr4dl3y/johnston/commit/87cf2dcd7c4be341ab938a5ea2a76e1263b65342))
* **app:** add stop_all and on_unmount handlers for clean MCP subprocess termination on Ctrl+C / quit ([8c5c848](https://github.com/p4ulbr4dl3y/johnston/commit/8c5c848f06162cff721d5d31f5e4ca9764ae9fdb))
* **app:** calculate real elapsed duration and preserve accumulated thinking text on cancellation ([f5aa477](https://github.com/p4ulbr4dl3y/johnston/commit/f5aa47724b6145bdef64cfae2793306b4af559e8))
* **app:** gracefully terminate background tasks and suppress unmount RuntimeError on exit ([58bc0a6](https://github.com/p4ulbr4dl3y/johnston/commit/58bc0a6bf19f710affa06dcacbd32d69f90bdcef))
* apply Monochrome Slate styling to modal Input fields ([d5f66a2](https://github.com/p4ulbr4dl3y/johnston/commit/d5f66a27889d991c6454f51af45d7ba429ab8c8d))
* **app:** rename read-only property override to is_app_active ([e57dcc3](https://github.com/p4ulbr4dl3y/johnston/commit/e57dcc33ad41257291a4b25cb813ea73f9acc114))
* auto-format image paths on input change and preserve pasted_texts in load_text ([cea0844](https://github.com/p4ulbr4dl3y/johnston/commit/cea0844097f2f83f3444a08781d975d8cafd2afa))
* avoid auto-prefixing plain words with @ on paste ([e7d4737](https://github.com/p4ulbr4dl3y/johnston/commit/e7d47379d93b506ee097373e7cb3939f0bca5a25))
* balance status footer with left and right columns ([199fb88](https://github.com/p4ulbr4dl3y/johnston/commit/199fb885039bd37c5401156695f5d272d8af1e9c))
* **catalog:** normalize model IDs to ignore tag suffixes during matching ([edbc33a](https://github.com/p4ulbr4dl3y/johnston/commit/edbc33a46e456f8cbd9d3937711e59ce03c36484))
* **catalog:** persist add_vision_override to cache including base model id ([62a5d1d](https://github.com/p4ulbr4dl3y/johnston/commit/62a5d1d01df86362cb33d3707415a2c132ba9ee6))
* **catalog:** persist user_vision_overrides across cache TTL background refreshes ([c100402](https://github.com/p4ulbr4dl3y/johnston/commit/c100402d02d841e78c83765e45b0c7c2993700f8))
* **catalog:** rely exclusively on OpenRouter catalog with background auto-refresh ([c086660](https://github.com/p4ulbr4dl3y/johnston/commit/c08666081d1311fee8e216fce48977798fca0c93))
* **catalog:** resolve dynamic context limits via provider configs and model patterns ([f031671](https://github.com/p4ulbr4dl3y/johnston/commit/f0316711e00f6ad28ae2742c3ff14ccf3e935b92))
* **catalog:** unify model display name formatting across all models (slug to Title Case) ([7c39e9e](https://github.com/p4ulbr4dl3y/johnston/commit/7c39e9ecc6465fc562e20410fc6e584039a1e8fd))
* change default agent mode to Action across base provider, prompt builder, status footer, and context ([f6d16eb](https://github.com/p4ulbr4dl3y/johnston/commit/f6d16ebad480b1fd6c83897fbe56810aeb8bf5e5))
* change OpenCode Go provider name to clean 'OpenCode Go' ([0767341](https://github.com/p4ulbr4dl3y/johnston/commit/0767341de669599795d2b86318b23ebc8cdc7fd2))
* change provider disable/enable shortcut to Ctrl+D ([1cdc3ac](https://github.com/p4ulbr4dl3y/johnston/commit/1cdc3acc0f9d5abe761e7f4e8a33c305de8e89e9))
* change provider disable/enable shortcut to Ctrl+T ([e7cee23](https://github.com/p4ulbr4dl3y/johnston/commit/e7cee2397655287a4cde6a3639b219d7b7ac37a3))
* clarify empty handoff behavior ([26531bc](https://github.com/p4ulbr4dl3y/johnston/commit/26531bc10f9f04a0f0f2d4138f405a0c15f17c7b))
* clear stale disk cache for unauthenticated providers in fetch_models_for_provider ([ef7debc](https://github.com/p4ulbr4dl3y/johnston/commit/ef7debcfbec85360f0c1db4100edacb4e65fe316))
* collapse carriage return progress bar lines across full output buffer ([6095e1a](https://github.com/p4ulbr4dl3y/johnston/commit/6095e1a077e1c182a458a9d5ef47e255f3f13d39))
* combine original SubagentsListScreen formatting on Active Tasks tab with Subagent Templates tab ([ded5ceb](https://github.com/p4ulbr4dl3y/johnston/commit/ded5ceb066073d8c9bb3c0104bc074dda7d70d53))
* **commands:** fix syntax error in COMMAND_CLASSES list ([0546c10](https://github.com/p4ulbr4dl3y/johnston/commit/0546c108ff927e6d38c0afeb713a03dc8f3dd54a))
* **core:** dynamically compute context_limit and context_window on model change ([be878a9](https://github.com/p4ulbr4dl3y/johnston/commit/be878a9c7e41ec6f25bc6c63828aa9c2a5ea199f))
* **core:** fallback to estimate_tokens(history) when last_context_tokens is zero ([14714e5](https://github.com/p4ulbr4dl3y/johnston/commit/14714e5fd44ee924c7017da354ec025ed6d1cbd8))
* **core:** remove hardcoded OpenCode prefix from API Error messages ([21d7fa4](https://github.com/p4ulbr4dl3y/johnston/commit/21d7fa497d6ce3c72339013cce344b7c23ab3f57))
* direct render in StatusFooter on_mount to guarantee status bar is never blank ([622022f](https://github.com/p4ulbr4dl3y/johnston/commit/622022ffce42d391dfe01742fb7c2d0e94827c49))
* display $0 instead of $0.0000 when cost is zero ([ebc008d](https://github.com/p4ulbr4dl3y/johnston/commit/ebc008d0e151dd4684e938cd7e05f06d28b5cb83))
* display 0% instead of 0.0% when context usage is zero ([5f1bf2a](https://github.com/p4ulbr4dl3y/johnston/commit/5f1bf2ad1a768fbadda7a43340e7ddb9f480c2ce))
* display clean model names without provider/org prefixes in /models ([bca9153](https://github.com/p4ulbr4dl3y/johnston/commit/bca91536948246d1022f6850b8b51984fcd11e4f))
* eliminate double margin gap between ThinkingWidget and ToolCallWidget ([f4c12a0](https://github.com/p4ulbr4dl3y/johnston/commit/f4c12a0ce9f50dff65c7725b881b974e40b73f16))
* ensure command suggestions items are strictly single-line truncated ([82b0314](https://github.com/p4ulbr4dl3y/johnston/commit/82b0314856f0a4a5c8a5cd6679d4adab28650eb4))
* ensure Enter key selects first matching valid model instead of fallback default_value ([e52cbc5](https://github.com/p4ulbr4dl3y/johnston/commit/e52cbc57935bac19c67cfd2e20ea143fb13694a4))
* escape Rich markup brackets in MCP and Skills screens and isolate test data ([9ab3c87](https://github.com/p4ulbr4dl3y/johnston/commit/9ab3c870b6b418ccd1189fd3aff6155c6ca5c37e))
* exclude disabled providers from /models list ([2c86dc8](https://github.com/p4ulbr4dl3y/johnston/commit/2c86dc86d4f3e2d026b0c5bf274f0488b84a7f53))
* fallback context limit lookup across all provider caches and model basenames ([a1e94fe](https://github.com/p4ulbr4dl3y/johnston/commit/a1e94fe32544bbfebf7f6fe14a8255572a3b17c2))
* filter /models and johnston --models to display connected providers only ([7cf079f](https://github.com/p4ulbr4dl3y/johnston/commit/7cf079f127d1a98b425c30488ef5003736ce2b7b))
* highlight default_value strictly when present without forcing selection on unmatched tabs ([967e9ec](https://github.com/p4ulbr4dl3y/johnston/commit/967e9ec2d9ded04635a78b23a495a8417b6de9cc))
* **input:** enable Shift+Tab binding in app and cycle through all 5 modes with toast notifications ([4dbae49](https://github.com/p4ulbr4dl3y/johnston/commit/4dbae496d6d9c3d101b778067bb0d9652219abaa))
* keep only johnston executable ([bde2e9c](https://github.com/p4ulbr4dl3y/johnston/commit/bde2e9c5ed2b4beb8526c0fc49f5b4100afe022a))
* mark active thinking effort ([6853934](https://github.com/p4ulbr4dl3y/johnston/commit/68539341590f95f1171d690468a40e610f39d250))
* mark deepseek-v4 models as text-only so ViewImage triggers mimo-v2.5 vision fallback ([5d2087a](https://github.com/p4ulbr4dl3y/johnston/commit/5d2087a771452093c44a3c7c85e99f3349f36c96))
* **markdown:** support file:// link parsing in Markdown parser factory ([1535262](https://github.com/p4ulbr4dl3y/johnston/commit/15352624ee81c790b5c3476b9fc20274d54ace46))
* **mcp:** filter jsonrpc notifications and match request id in _read_response ([cb5995b](https://github.com/p4ulbr4dl3y/johnston/commit/cb5995b3f3eaf930962c350e1949fbcb258b68ae))
* **mcp:** include parameter signatures in lazy MCP prompt snippet ([a58bbb1](https://github.com/p4ulbr4dl3y/johnston/commit/a58bbb1e0f6f297ad38359d82232a5c1bc8ee4e0))
* **mcp:** increase default mcp tool execution timeout to 10 minutes (600s) ([b6f47a5](https://github.com/p4ulbr4dl3y/johnston/commit/b6f47a5e0fa7093483a299db3779c4a8d959c8a2))
* **mcp:** increase process initialization and tool list timeouts for slow node/npx spawns ([8e6ce17](https://github.com/p4ulbr4dl3y/johnston/commit/8e6ce17d84c3ebd431358da1a419712736f6a7bd))
* **mcp:** remove execution timeout for MCP tool calls (timeout=None) to support long-running tasks ([c3fea2e](https://github.com/p4ulbr4dl3y/johnston/commit/c3fea2ec5b0fb7049e32642fc6b0f11e420ee3e6))
* **mcp:** return explicit tool execution message when mcp tool output is empty ([1b60d60](https://github.com/p4ulbr4dl3y/johnston/commit/1b60d60103ca5c0835326c7b81a43d3bf95e518c))
* **models:** update model context limit defaults for Kimi/Moonshot, Nemotron, Grok ([72357e4](https://github.com/p4ulbr4dl3y/johnston/commit/72357e43899953344f5b4477dabd8dcabcdb8327))
* **mode:** remove toast notifications on mode switches per user request ([d0cc344](https://github.com/p4ulbr4dl3y/johnston/commit/d0cc34421b437b63fce84e8f94fc97e9f2df7cd3))
* pass image attachments in OpenAI multimodal image_url format ([10af624](https://github.com/p4ulbr4dl3y/johnston/commit/10af6241ab01e025bf2c5a7d66cd4faec3d33d5b))
* pass ViewImage tool results as OpenAI multimodal image_url blocks ([29d4e63](https://github.com/p4ulbr4dl3y/johnston/commit/29d4e6386a208fef6a012efeafaef8056c85fbf5))
* preserve mode across agent switches ([ab816ac](https://github.com/p4ulbr4dl3y/johnston/commit/ab816ac7dfb730c158ede667edd2956c04110454))
* prevent duplicate copy notifications by checking selection_copy_active in Click handlers ([706edb0](https://github.com/p4ulbr4dl3y/johnston/commit/706edb0050cec5ec994d33cee7acba7b03ba4d76))
* prevent Shift+Tab focus switching in search modals ([9398d1d](https://github.com/p4ulbr4dl3y/johnston/commit/9398d1ddcc3e30577753962852197c949d5f49b8))
* **prompt:** add rule 9 for dynamic & MCP tool awareness in system prompt ([07f145f](https://github.com/p4ulbr4dl3y/johnston/commit/07f145fa1e7079831d1b3b761bf155da6c25b0a5))
* **providers:** persist selected model to config.json and provider file ([376a41a](https://github.com/p4ulbr4dl3y/johnston/commit/376a41a800a83ae2a8e48c18caadc29a2d8fcebb))
* remove /demo from help screen ([5d16048](https://github.com/p4ulbr4dl3y/johnston/commit/5d160485274b8217e4fa5e6272d3d5c84b3723ee))
* remove active provider default selection in ProviderScreen ([c94c073](https://github.com/p4ulbr4dl3y/johnston/commit/c94c073dd1d94347c9a2bc01a931e51311589783))
* remove dot prefix fallback for custom tools in chat view ([d247233](https://github.com/p4ulbr4dl3y/johnston/commit/d24723360a699afc8faf64b4f96b60f3d32578ad))
* remove duplicate notify in PasteCommand ([e65f1e8](https://github.com/p4ulbr4dl3y/johnston/commit/e65f1e8fcc492d6d6abc958c06c6928b088d3396))
* remove hardcoded default model strings for 3rd party providers, rely on dynamic fetching ([ff95323](https://github.com/p4ulbr4dl3y/johnston/commit/ff95323c571b373071f55921296b16e51b749258))
* remove hardcoded model defaults from OpenAI, Anthropic, Gemini, Ollama ([b4840e9](https://github.com/p4ulbr4dl3y/johnston/commit/b4840e9a6dbc7c9ba0516c6b9da85a04946a87d7))
* remove initial option highlight in SkillsScreen and MCPScreen ([6b2c2c5](https://github.com/p4ulbr4dl3y/johnston/commit/6b2c2c50311b558430247c956b89217649334a53))
* remove initial option highlight when search is active ([f1d2a6e](https://github.com/p4ulbr4dl3y/johnston/commit/f1d2a6e129e436967fe2bcfe884d27b591a398a5))
* remove phantom empty BotMessage creation causing double margin after first Thought ([9fa0e69](https://github.com/p4ulbr4dl3y/johnston/commit/9fa0e69c93ed4fd192d44657febf39b1cb0ae534))
* remove prompt text line from ApiKeyInputScreen ([c24fa59](https://github.com/p4ulbr4dl3y/johnston/commit/c24fa5937aeebe573450dc99dddb4a2cf19c4567))
* remove provider descriptions from selection screens ([90f1245](https://github.com/p4ulbr4dl3y/johnston/commit/90f12450ce3324333f484581c9b32cca666c8c23))
* remove unused imports, fix /skills modal trigger, fix subagent killing in ManageTask ([81dff1b](https://github.com/p4ulbr4dl3y/johnston/commit/81dff1bf99f186ab4f140531d62d81e9b3335fa4))
* render StatusFooter on_mount to prevent blank footer on startup ([968d5c3](https://github.com/p4ulbr4dl3y/johnston/commit/968d5c3d24814ee7f891b407f51b2498793ce0a2))
* resolve 22 audit bugs and update test suite ([8e2afd5](https://github.com/p4ulbr4dl3y/johnston/commit/8e2afd5b951d10c9202acf86a48a3a31c57012d2))
* resolve background task reading loop crash by starting stdout reader early, and update HelpScreen ([5225fe6](https://github.com/p4ulbr4dl3y/johnston/commit/5225fe6198d3c8a6e691d7aea66fc16fd7f0c7c1))
* resolve file creation paths relative to project cwd to prevent writing to root / ([b21c181](https://github.com/p4ulbr4dl3y/johnston/commit/b21c1810a1062f7216c45dec02cb07ea5ca118e8))
* resolve logic bugs in agent loop, tools, and session handling ([fb54f20](https://github.com/p4ulbr4dl3y/johnston/commit/fb54f20eade76a314b9c6be53c9d00f3c024b40d))
* resolve project_dir dynamically and auto-refresh real stats in status footer on_mount ([d1b02bc](https://github.com/p4ulbr4dl3y/johnston/commit/d1b02bc006856641575e0da012ce28fd791ccdbc))
* resolve Rich markup error in Option header string ([1267038](https://github.com/p4ulbr4dl3y/johnston/commit/1267038c7bebfe166361001c31ce8cbea9f7af2c))
* restore 1-line margin after ThinkingWidget ([ff68f59](https://github.com/p4ulbr4dl3y/johnston/commit/ff68f59ba570d4b4f026f9115d1429c9c287e46e))
* restore 2-tab SubagentsScreen modal with session fallback logic ([8ad7f88](https://github.com/p4ulbr4dl3y/johnston/commit/8ad7f882a1d922833f55c9fe84bbc0885c08af96))
* restore default model for built-in clinepass while supporting optional model field in custom user providers ([096ae46](https://github.com/p4ulbr4dl3y/johnston/commit/096ae46948b448a0840bddcfcc109a1baefb480e))
* restore initial option highlight for SkillsScreen and MCPScreen ([d1e2d85](https://github.com/p4ulbr4dl3y/johnston/commit/d1e2d8522ab667280efeb25d823606d8bbff27ce))
* restore instruction for agent to wait for background task completion ([464afec](https://github.com/p4ulbr4dl3y/johnston/commit/464afecd401528e7a26bf7ccf41b4a9c23efeee6))
* restrict paste hotkeys strictly to Ctrl+V / Cmd+V (including Russian layout) ([118a777](https://github.com/p4ulbr4dl3y/johnston/commit/118a777b659bc9575b33dc19a82a30d91774a64f))
* sanitize API keys in templates, fix Glob/Grep path params, and align bot_delta streaming events ([6de5f8a](https://github.com/p4ulbr4dl3y/johnston/commit/6de5f8a0f1d5ef6106a5fb3e78a25d5b88898e07))
* sanitize multiline messages to single line in rewind and resume screens ([0951e44](https://github.com/p4ulbr4dl3y/johnston/commit/0951e443514806d988c82cbd0b259216e37769a8))
* **screens:** enable Ctrl+C / Ctrl+Q exit bindings across all modal screens ([437b2c7](https://github.com/p4ulbr4dl3y/johnston/commit/437b2c7b2655e0f46ef34b6783c198ae203cead2))
* strip org/provider prefix from model_name in status footer ([108d422](https://github.com/p4ulbr4dl3y/johnston/commit/108d42229c68767aaae114ad433c2d953d0d15af))
* style command suggestions and status footer with Monochrome Slate theme ([5359b73](https://github.com/p4ulbr4dl3y/johnston/commit/5359b73e538d34c8223db2f7fd461babbcaadf23))
* **subagent:** enforce strict session_id equality in SubagentTracker ([e4f0ca7](https://github.com/p4ulbr4dl3y/johnston/commit/e4f0ca7479fe02ef1baf66b690b6a93d4cc95132))
* **subagent:** isolate test subagent sessions and fix manage_subagent target string ([e888025](https://github.com/p4ulbr4dl3y/johnston/commit/e8880255dd2e5f71c29ba19ec4548afaca7455bf))
* **thinking:** calculate thinking block duration from block start instead of cumulative turn time ([331e30b](https://github.com/p4ulbr4dl3y/johnston/commit/331e30bb9d24f91a971c3acaa9d7ed057fdd4111))
* **tools:** add case insensitivity and aliases for tool names ([fd1fd8a](https://github.com/p4ulbr4dl3y/johnston/commit/fd1fd8a55e443e65e13a223214614d9f884ccffb))
* **tools:** include hint alongside save_log message in truncate_output ([d8e6baa](https://github.com/p4ulbr4dl3y/johnston/commit/d8e6baaf21ce564b4442c7805e6d756655764143))
* **tools:** keep prompt as an optional parameter in view_image schema for targeted questions ([37a6e64](https://github.com/p4ulbr4dl3y/johnston/commit/37a6e64835edba4ab098dfa20666f74c4f705795))
* **tools:** prioritize query/prompt and string values for target display string ([e26c80e](https://github.com/p4ulbr4dl3y/johnston/commit/e26c80e2ab573ebd85d687074e0047d3086e4a50))
* **tools:** remove 'Do not poll for status' from subagent background message ([195abca](https://github.com/p4ulbr4dl3y/johnston/commit/195abca8d3271bf6d11118c1a1ea5778225c0039))
* **tools:** remove manage_task prompt from background bash message ([5807fdd](https://github.com/p4ulbr4dl3y/johnston/commit/5807fdd99bec8f3a2ff02a9888b3be4987f61504))
* **tools:** remove redundant prompt parameter from native view_image tool schema ([ee0e321](https://github.com/p4ulbr4dl3y/johnston/commit/ee0e321e9fe0017682d5be79ff0f939b8f61beff))
* **tools:** strict schema separation for native vision and non-vision models ([0055fc8](https://github.com/p4ulbr4dl3y/johnston/commit/0055fc88d6f2d4f8f51457b2489115c527743879))
* **ui:** add mock tasks/subagents when lists are empty to allow offline UI testing without model tokens ([ee75f07](https://github.com/p4ulbr4dl3y/johnston/commit/ee75f072c6ce77bff0d97b1dc2c0bdea39d69f8d))
* **ui:** add right margin to MarkdownFence for scrollbar spacing ([43c37dd](https://github.com/p4ulbr4dl3y/johnston/commit/43c37dd641a06a03179e8c324e1d7d2560dff440))
* **ui:** align code block language label with content padding ([5cad515](https://github.com/p4ulbr4dl3y/johnston/commit/5cad51562a8f22c449bbf4fdec474a7479de261e))
* **ui:** apply link hover properties directly to MarkdownParagraph ([e2433a2](https://github.com/p4ulbr4dl3y/johnston/commit/e2433a238998bde526815a32770241842a9b0640))
* **ui:** auto-expand ChatInput on multiline paste and text changes ([63e3578](https://github.com/p4ulbr4dl3y/johnston/commit/63e357899aa94c2f686e1bf52af0056e8bdc1061))
* **ui:** auto-scroll to bottom on session load and safely handle click event target ([455f098](https://github.com/p4ulbr4dl3y/johnston/commit/455f09871190844d3fdf8b28e7652fcb07575b76))
* **ui:** clear selection on welcome screen click in ChatView ([d63ab1d](https://github.com/p4ulbr4dl3y/johnston/commit/d63ab1d18750e46d9032c548ea6395d64f50f82c))
* **ui:** comprehensive UI/UX fixes for contrast, focus, autoscroll, and performance ([eb405a4](https://github.com/p4ulbr4dl3y/johnston/commit/eb405a4d03cf2d1ce894703a0f0f80800a72ba88))
* **ui:** disable expansion for ManageSubagent tool widget ([aa29de8](https://github.com/p4ulbr4dl3y/johnston/commit/aa29de8aaaacf40b985ef89cbf7569b5e2d54fb7))
* **ui:** disable keyboard focus for code block Copy button ([10c6597](https://github.com/p4ulbr4dl3y/johnston/commit/10c659745945d5806f3c2cde36d212d89a36fc2e))
* **ui:** disable text selection on main screen logo ([acf145a](https://github.com/p4ulbr4dl3y/johnston/commit/acf145ac54fd655c32b5d1f91158a05523253a60))
* **ui:** dismiss None on Escape cancel in BaseSelectionScreen ([9ceb834](https://github.com/p4ulbr4dl3y/johnston/commit/9ceb8340300453978acddc7331c5cb493cd76398))
* **ui:** display exact provider model IDs in status footer and model selection screen ([54c00a4](https://github.com/p4ulbr4dl3y/johnston/commit/54c00a4fc0f23ab5e0881527bf837a0a3af309c6))
* **ui:** do not auto-highlight first model if current model is not present in filtered tab list ([6c9dbb2](https://github.com/p4ulbr4dl3y/johnston/commit/6c9dbb2c6532daa676606e88f84d2fe8c7b6b960))
* **ui:** eliminate black bottom strip on markdown code blocks ([ba08a6b](https://github.com/p4ulbr4dl3y/johnston/commit/ba08a6b1cd838927aeb876ed11c74080713e5442))
* **ui:** escape Rich markup characters in command and description strings for OptionList ([81d322f](https://github.com/p4ulbr4dl3y/johnston/commit/81d322fb4fbb7ce692f0bb899331a0b87b688468))
* **ui:** escape rich markup in tool execution widgets and patch catalog test persistence ([ff4578e](https://github.com/p4ulbr4dl3y/johnston/commit/ff4578edf33340b0eec834ec417b89d95a0b76e4))
* **ui:** fix code block header alignment and heading underline styling ([f35cd7a](https://github.com/p4ulbr4dl3y/johnston/commit/f35cd7a61c17904f3fa6d80fd87a74050c6ec7ec))
* **ui:** format AGENTS.md as code block in help menu to prevent autolink parsing ([7f6953e](https://github.com/p4ulbr4dl3y/johnston/commit/7f6953e63518c9c12129b748a2e07e3ad5d1519b))
* **ui:** hide fence header in modal dialogs ([e79c9f9](https://github.com/p4ulbr4dl3y/johnston/commit/e79c9f9f6840b1dc77fa4c17c0a59cf4c8540a2e))
* **ui:** ignore clicks on empty ChatView background and whitespace selections ([3eeb6fc](https://github.com/p4ulbr4dl3y/johnston/commit/3eeb6fc930bc06e43c9e03e788e9418aee6ed549))
* **ui:** improve TUI responsiveness and layout styles ([66e51cf](https://github.com/p4ulbr4dl3y/johnston/commit/66e51cf4b07790b4ba32a566eee78c261ed2ddda))
* **ui:** list only native vision models in Vision Models tab and auto-highlight valid selection ([f0f7da3](https://github.com/p4ulbr4dl3y/johnston/commit/f0f7da399cc19bea163ce7646eded8996ae84073))
* **ui:** monochrome link hover styling without blue highlight ([36c5df9](https://github.com/p4ulbr4dl3y/johnston/commit/36c5df95afffaa9282fbc008f694000f4d4ba507))
* **ui:** order string truncation before rich.markup.escape to prevent breaking escaped brackets ([d7d4808](https://github.com/p4ulbr4dl3y/johnston/commit/d7d4808cd6af54312fd7ce86c7d8b33045b27efc))
* **ui:** override ID selector specificity for MarkdownFence in bash confirm modal ([554cb1d](https://github.com/p4ulbr4dl3y/johnston/commit/554cb1d193163f59ebc0a717b84fce8c130f375d))
* **ui:** preserve all streaming lines when Bash task transitions to background ([e7ecd8c](https://github.com/p4ulbr4dl3y/johnston/commit/e7ecd8cf50cb92fe3358291fe9c2314b2f2feebc))
* **ui:** prevent default 'Thinking...' fallback string from rendering into ThinkingWidget markdown ([3394676](https://github.com/p4ulbr4dl3y/johnston/commit/3394676cee1f99376d3a3010e1b9c84bf7a38ca1))
* **ui:** refresh status footer when toggling MCP servers in MCPScreen ([906d90b](https://github.com/p4ulbr4dl3y/johnston/commit/906d90bbf5435565d5aab5db9974ea7a33bf556b))
* **ui:** remove black scrollbar track under Markdown code blocks ([f54795c](https://github.com/p4ulbr4dl3y/johnston/commit/f54795c2cb781a20ef38ce49080c70080103a9d4))
* **ui:** remove bold style from inline code ([1385b64](https://github.com/p4ulbr4dl3y/johnston/commit/1385b644da4ca075e3ff4340b130f56f32bddf48))
* **ui:** remove bottom margin for tool call content ([3b3e275](https://github.com/p4ulbr4dl3y/johnston/commit/3b3e275b9500f5a1feb67aaea56202276153f5ee))
* **ui:** remove expansion support for call_mcp_tool, subagent, and task in chat ([9dedb5e](https://github.com/p4ulbr4dl3y/johnston/commit/9dedb5efec7398110f3a4df41c82ef2ecf618abe))
* **ui:** remove fallback default_val assignment so unselected tabs have no pre-selected option ([b7ac911](https://github.com/p4ulbr4dl3y/johnston/commit/b7ac91167e732f60c3bdb077e2e0c23ca1bc58d2))
* **ui:** remove horizontal scrollbar track reservation in MarkdownFence ([e858369](https://github.com/p4ulbr4dl3y/johnston/commit/e8583697e0351e052b8c46b5fd587bb7d5511a4f))
* **ui:** remove left border, padding and margin for code block in BashConfirmScreen ([57b4a70](https://github.com/p4ulbr4dl3y/johnston/commit/57b4a702b5cabde88cb810214f4517fefd9754e8))
* **ui:** replace invalid Rich color closing tags with standard [/] syntax ([b779180](https://github.com/p4ulbr4dl3y/johnston/commit/b7791807abcef2cc5a5a4f6a69222a5d1dd3e28c))
* **ui:** require mouse drag for text copying; prevent copy on simple click ([14f4b9b](https://github.com/p4ulbr4dl3y/johnston/commit/14f4b9bdd0781271938319da1938a2e15ec975f9))
* **ui:** scope compact dict formatting exclusively to MCP tools, preserving system tool target strings ([32c5c14](https://github.com/p4ulbr4dl3y/johnston/commit/32c5c148e2f792ba272109eda004400ba93da796))
* **ui:** set zero padding for code block in BashConfirmScreen ([1fa3711](https://github.com/p4ulbr4dl3y/johnston/commit/1fa3711cafc267a6a0469b58792edbe8943138dd))
* **ui:** strip line number prefixes in web_fetch expand view ([2aae8f2](https://github.com/p4ulbr4dl3y/johnston/commit/2aae8f24f364ee3692d3c2be01b77fa0365f59b2))
* **ui:** style inline code background and add JS block to demo ([1dac142](https://github.com/p4ulbr4dl3y/johnston/commit/1dac142e8e8c40b2f6e58191e5580535db2efb56))
* **ui:** unify modal option list styling, keep search input focus, disable command palette ([f69eb9e](https://github.com/p4ulbr4dl3y/johnston/commit/f69eb9efac3e920bc52d5392dcaa008f942cfcbb))
* **ui:** use clean uniform white background inversion for text selection ([9839577](https://github.com/p4ulbr4dl3y/johnston/commit/98395779fb7f0aeb0cb623dbb40507ea571382a4))
* **ui:** use dynamic true color inversion (text-style: reverse) for selection ([074d580](https://github.com/p4ulbr4dl3y/johnston/commit/074d580d94f33ca49fb35311a948ea19159ab26c))
* **ui:** use rich.text.Text objects in OptionList to bypass markup parsing completely and add mock tasks for testing ([3f81e30](https://github.com/p4ulbr4dl3y/johnston/commit/3f81e304cb3beefa4a8b7de5db15f29c9703ecbf))
* **ui:** use uniform high-contrast monochrome selection style ([4c44d69](https://github.com/p4ulbr4dl3y/johnston/commit/4c44d69c45294d4baba093a21386baf29c824fcb))
* unwrap ClinePass data.choices format in analyze_image_with_fallback ([889e937](https://github.com/p4ulbr4dl3y/johnston/commit/889e9371e2aa67ef2704960861fc4e8060170891))
* unwrap ToolContext in ViewImageTool to properly detect agent model and trigger vision fallback ([3b3b1f2](https://github.com/p4ulbr4dl3y/johnston/commit/3b3b1f214aebe6340365300741885b43266ad974))
* update DeepSeek v4 models context limit to 1M in catalog and tests ([018c795](https://github.com/p4ulbr4dl3y/johnston/commit/018c795d09d6680f68ad771b8a96e28ebb0a1fd4))
* update DEFAULT_SYSTEM_PROMPT to reference Subagent tool ([5a7b0d1](https://github.com/p4ulbr4dl3y/johnston/commit/5a7b0d1de40b2fa2d2d85ae58e9c041e716c3356))
* use .tool-sequential CSS class to avoid TCSS + combinator syntax error ([c5a18a6](https://github.com/p4ulbr4dl3y/johnston/commit/c5a18a6d4d1972329cca52c7469395cb74e8632b))
* use component class selector MarkdownBlock &gt; .code_inline for inline code background ([5fbe045](https://github.com/p4ulbr4dl3y/johnston/commit/5fbe04579c4beb857420648caf37b24f801ef76b))
* use copy_to_clipboard method instead of read-only clipboard property ([63ed73a](https://github.com/p4ulbr4dl3y/johnston/commit/63ed73a81dada5244cb5f6bbdec624b5181c725e))
* use lstrip() in command suggestions to respect trailing space after Tab ([aa45c9e](https://github.com/p4ulbr4dl3y/johnston/commit/aa45c9e1715af5ff679a1ff4a20e818ba2be31f4))
* use rich markup [bold] instead of markdown ** in tool label header ([24d587e](https://github.com/p4ulbr4dl3y/johnston/commit/24d587eab92be2689a38fd1e952c7c9589c2f8d9))
* use Rich Table grid for true left-right alignment in StatusFooter ([bd8aba1](https://github.com/p4ulbr4dl3y/johnston/commit/bd8aba11f764ece015acbff38e7ec62ef1d4ed43))
* **vision:** enforce detail: high mode for accurate image OCR and vision resolution ([1bd578f](https://github.com/p4ulbr4dl3y/johnston/commit/1bd578f74569c0cb3703db6eccce0fc04580dce2))
* **vision:** refine fallback vision logic, UI selection tabs and history sanitization ([01d0b9a](https://github.com/p4ulbr4dl3y/johnston/commit/01d0b9af90781eb54912050968015fb37912ec53))
* **widgets:** safe Markdown update to prevent unawaited coroutines ([0779a38](https://github.com/p4ulbr4dl3y/johnston/commit/0779a38e4f784f3cd6cb8c20cdf137f931eb15ba))


### Performance Improvements

* improve token efficiency with prompt caching and accurate estimation ([f3ef190](https://github.com/p4ulbr4dl3y/johnston/commit/f3ef19066c6958faff16823cba9a6152a80d0321))
* increase Bash background timeout from 5s to 10s ([f9994ab](https://github.com/p4ulbr4dl3y/johnston/commit/f9994abec1efeec0dd061af23e7a34af30caafe1))
* optimize Edit tool and history compaction for maximum token efficiency ([20f08cd](https://github.com/p4ulbr4dl3y/johnston/commit/20f08cda6e0efd55f2ac820ac9c26a76b9e2cfa6))
* **subagent:** eliminate blocking sync disk I/O on high frequency streaming deltas ([bd4500b](https://github.com/p4ulbr4dl3y/johnston/commit/bd4500b2925cbbfeec224fdbbe67144fa2a6eb08))


### Reverts

* remove [ACTIVE] tag and dimming styles from /models ([fbcff2e](https://github.com/p4ulbr4dl3y/johnston/commit/fbcff2e65a37770e8e9c02315a0fdf81ea9734ad))
* restore original orange text style for inline code ([14be958](https://github.com/p4ulbr4dl3y/johnston/commit/14be9583db8f443cbc6e227ccbb704d9831e36bd))


### Documentation

* add deployment & publishing section to AGENTS.md ([2e8d0e6](https://github.com/p4ulbr4dl3y/johnston/commit/2e8d0e6916e6af28196870fe6907096e93258ac2))
* add README.md ([4fb1c8a](https://github.com/p4ulbr4dl3y/johnston/commit/4fb1c8a42adabe149aa5bdea23b1598b7d0edaea))
* add Shift+Tab hotkey to help screen ([40b640d](https://github.com/p4ulbr4dl3y/johnston/commit/40b640d9e27dafc2018aa093c587135e6d5a61d2))
* **agents:** update AGENTS.md with context compaction, dynamic prompt metadata, and full slash commands ([9018b2f](https://github.com/p4ulbr4dl3y/johnston/commit/9018b2f457999f04fde429f8eb015f9fdd9fb260))
* center logo and intro in README.md ([9ed1940](https://github.com/p4ulbr4dl3y/johnston/commit/9ed1940fc66e246ed873879437133440fe3a5aa1))
* center logo and update description in README ([a0da9e7](https://github.com/p4ulbr4dl3y/johnston/commit/a0da9e7a9e54449d955614d9642ba5ac6c829ef9))
* clarify ManageTaskTool schema description for CLI background commands ([a444bc3](https://github.com/p4ulbr4dl3y/johnston/commit/a444bc35070b9c6431158a5e6f7ba5fde3e88d48))
* fix subtitle alignment in pre block ([915fd91](https://github.com/p4ulbr4dl3y/johnston/commit/915fd91f5c4b88ec89cf8270eb425467ba2c3927))
* format subtitle as code block in README ([f9f731a](https://github.com/p4ulbr4dl3y/johnston/commit/f9f731a3a21f3c2e0a5e82ab60706b91b07684e0))
* **help:** add Ctrl+V paste keybinding to Keybindings list ([70e4d09](https://github.com/p4ulbr4dl3y/johnston/commit/70e4d09c70aace0c831b94f4a1d7db1fdb59109e))
* **help:** update HelpScreen with all active slash commands and keybindings ([2e8e6ee](https://github.com/p4ulbr4dl3y/johnston/commit/2e8e6ee24beee87379fe668a4ebbc118872b73e6))
* move subtitle inside pre block under ASCII logo ([7a88d98](https://github.com/p4ulbr4dl3y/johnston/commit/7a88d98f4ed0ab00ad1b92b01e7587ac37320fdd))
* remove header title from README.md ([1af3c53](https://github.com/p4ulbr4dl3y/johnston/commit/1af3c532e22461664ecf5538d47d5dc796c908bb))
* remove license section from README.md ([5db2444](https://github.com/p4ulbr4dl3y/johnston/commit/5db24446e65362da8cee9809bfa6d175cac68c95))
* **subagent:** clarify in tool schema and AGENTS.md that send_message resumes COMPLETED subagents ([72db8b4](https://github.com/p4ulbr4dl3y/johnston/commit/72db8b4fcafe28d34ad4f5b838236e232ea2d39b))
* update AGENTS.md to reflect core package, ToolContext, and tests setup ([83c142b](https://github.com/p4ulbr4dl3y/johnston/commit/83c142b97d490448fb5ba0265015794336bbda83))
* update AGENTS.md with /rules command and accurate tools list ([49cb7bf](https://github.com/p4ulbr4dl3y/johnston/commit/49cb7bfd17214c7d546bb51db60f90acad05ec27))
* update AGENTS.md with UI design system and latest changes ([8ae90e8](https://github.com/p4ulbr4dl3y/johnston/commit/8ae90e88fcbe79ebeaca153efc78674b419ee402))
* update deployment instructions in AGENTS.md ([3ea487c](https://github.com/p4ulbr4dl3y/johnston/commit/3ea487c073a1c3c16f7a19613305946b39fc1ac9))
* update johnston-architect skill with custom modes instructions ([4e413a9](https://github.com/p4ulbr4dl3y/johnston/commit/4e413a9f6a33fbe3801463a2b2b373d5659ce102))
