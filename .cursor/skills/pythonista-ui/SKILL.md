---
name: pythonista-ui
description: >-
  Build or debug Pythonista iOS apps using the ui module (NavigationView,
  TableView, ListDataSource, TextField, flex layout). Use when writing
  Pythonista GUIs, fixing silent crashes on present/push, or shipping
  phone/portrait scripts that must also import cleanly on desktop without ui.
---

# Pythonista `ui` development

Pythonista (omz Software) runs Python on iOS with a UIKit-inspired `ui` module. Desktop/CI usually has **no** `ui` — gate GUI code and keep shared logic importable without it.

## When this skill applies

- Creating or fixing `*_gui.py` / Pythonista scripts
- Crashes on load, present, or `push_view`
- Portrait / phone-width layouts, search-first lists
- Pairing a tap UI with a text/CLI sibling

## Hard rules (crash avoidance)

1. **Prefer plain `ui.View` + `flex`.** Avoid custom `ui.View` subclasses unless you need `draw` / touch. Subclassing is the #1 source of agent-written crashes.

2. **`layout(self)` takes no arguments.** Pythonista calls `view.layout()` with zero args. Never do:
   ```python
   def layout(sender):  # WRONG — missing arg → instant abort on present
       ...
   v.layout = layout
   ```
   If you subclass, override `def layout(self):` and use `self.width` / `self.height`.

3. **Do not `raise SystemExit` after `present()`.** Non-zero exit (or sometimes any `SystemExit`) after showing a view looks like a silent crash. Show errors on a `ui.View` and return normally:
   ```python
   def main():
       try:
           app.present()
       except Exception:
           show_error_view(traceback.format_exc())  # present(); no SystemExit
   if __name__ == "__main__":
       main()  # not raise SystemExit(main())
   ```

4. **UI callbacks run on the main thread.** Long work freezes the app. Use `@ui.in_background` for compute; hop back to the main thread before touching views / `push_view`. Never `push_view` from a background thread (hierarchy inconsistency → abort).

5. **Gate `import ui`.** Shared math/data modules must not import `ui` at top level.
   ```python
   try:
       import ui
   except ImportError:
       ui = None
   ```

## Layout (portrait / phone)

- Set an initial `frame`, then `flex` for resize (`"W"`, `"WH"`, `"LRTB"`, etc.). Flex adjusts margins/size; it does not place the first frame for you.
- Stack: fixed header controls at top, `TableView` / `ScrollView` below with `flex="WH"`.
- Design for ~320pt width; avoid wide multi-column toolbars.
- **Search-first lists:** empty table until the user types; cap matches (e.g. 40). Do not dump hundreds of rows on load.

## Navigation & lists

```python
root = ui.View(name="Species", background_color="white")
# ... add subviews with flex ...
nav = ui.NavigationView(root)
nav.present("fullscreen")  # or "sheet"
# later:
nav.push_view(next_view)
```

- Give screens a `name` (nav bar title).
- `ui.ListDataSource` as both `data_source` and `delegate`:
  ```python
  ds = ui.ListDataSource([])
  ds.action = on_select  # sender is the data source
  tv.data_source = tv.delegate = ds
  ```
- Items: strings or `{"title": "...", "accessory_type": "disclosure_indicator"}`.
- Put rate/detail text in `title` (optionally with `\n`); do not rely on undocumented subtitle keys.

## TextField search pattern

```python
field = ui.TextField(placeholder="Type a species name", ...)
field.delegate = controller  # any object

def textfield_did_change(self, textfield):
    q = (textfield.text or "").strip().lower()
    # filter + ds.items = ...; tv.reload()

def textfield_should_return(self, textfield):
    textfield.end_editing()
    return True
```

## Error surfacing

- Print breadcrumbs: `print("[myapp] loading data")` — user can read the Pythonista console when the UI aborts.
- On missing sidecar files (`encounters.json`, etc.), present a full-screen label with the message; do not `SystemExit`.
- Keep script + data files in the **same folder**; resolve paths via `Path(__file__).resolve().parent`.

## Desktop / CI

- `python3 script_gui.py` without `ui` should print a short message and exit cleanly.
- Put pure logic in a sibling module (e.g. `repel_filter.py`) and import it from the GUI.
- Smoke-test helpers without `ui`; GUI can only be fully verified on device/Pythonista.

## Authoritative references

- Official: https://omz-software.com/pythonista2/docs/ios/ui.html
- Issues: https://github.com/omz/Pythonista-Issues
- Forum archive: https://omz-software.com/forum/archive/
- LLM-oriented synthesis (pyui / flex / anti-patterns): https://github.com/jgwill/llms-txt (llms-ui-pythonista-guide)

## Phone-width toggles

`ui.SegmentedControl` often lays out wider than the visible content on phones, so only the first segment shows. Prefer equal-width `ui.Button` rows sized with `ui.get_screen_size()[0] - 2*pad`, or force the segment control’s frame width to that same content width before present. Keep segment labels short.

## Anti-patterns checklist

- [ ] No one-arg `layout` assigned onto a view
- [ ] No `SystemExit` after `present`
- [ ] No `push_view` from `@ui.in_background` without main-thread hop
- [ ] No full unbounded list on first paint for phone UIs
- [ ] No hard dependency on `ui` inside shared logic modules
- [ ] Actions/delegates attached (`action=`, `delegate=`) for every interactive control
- [ ] Top toggles fit phone width (both options visible; avoid oversized SegmentedControl)
