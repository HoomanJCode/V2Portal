do these todos in priority and mark as down if passed.
> * [x] ~~when i write v2raycli test its show me an error~~ — Fixed: `v2raycli test` without subcommand now shows usage help instead of crashing
> * [x] for testing its better show any loading result for profiles, also show profile id instead.
> * [x] for group, its not accept adding subscription or other group, also i dont want its add profiles of group or sub, its should add them and maybe later subscription updated and profiles changes.
> * [x] i need a command to edit profile of added server
> * [x] accept group as server create, the group has strategy
> * [x] accept sub as alias of subscription
> * [x] accept group as test
> * [x] in adding server if user not define \--profile is it print error? no its should create a server without outbound and outbound is the device, its seems like starting a server on that device.
> * [x] sometimes its not get subscription or test and its show a big error about timeout, i want its show a good timeout message not like that code message error.
> * [x] add auto compelete to this also the v2raycli not have autocompelete with tab button on keyboard.
> * [x] if user type v2raycli server start, its should start all and also for stop, and add restart to servers, also should know sv as server alias.
> * [x] write a full document about using this app and update readme
> * [x] checkout for more beautifull texts over all the app, and if can make better make it better. its menu and text review.
> * [x] tell me how can i do it and write a doc page about this: i want pass epicgames traffic using berlin profile and youtube traffic from group 1, then other from a sub2 (subscription) and about some specific russian websites i want direct traffic not proxy over any profile.
> * [x] for server list should write what profile its redirecting and the path is going
> * [x] don't ask profile or subscription dedicated in commands — IDs are unique so detect automatically (group create / add-member / remove-member now accept mixed profile+subscription IDs)

---

# Refactor — universal ID & resource model

> Plan: `todos/README.md`, phases `todos/01-*.md` … `todos/06-*.md`. Execute in order.

- [x] Phase 01 core: sample of resolution helpers landed earlier (classify_id / classify_ids)
- [x] Phase 01 — `resolve_refs` / `subscription_target` / `resolve_target` v2 (nested groups, cycles, dedup)
- [x] Phase 02 — uniform command shape (`group add`, per-resource `edit`, flags removed)
- [x] Phase 03 — servers accept profile | subscription | group outbound refs
- [x] Phase 04 — referential integrity on every remove path
- [x] Phase 05 — connect / TUI / service accept any ref
- [x] Phase 06 — test sweep, docs, final verification