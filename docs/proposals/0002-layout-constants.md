# Implementation Proposal: Move Layout Constants into `theme.py` (Issue #20)

| | |
|---|---|
| **Status** | Accepted — approved by the owner on 2026-11-08 |
| **Author** | Gemini 2.5 Flash |
| **Date** | 2026-11-08 |
| **Base** | main `9912263` (post-split, v1.0.0) |
| **Related Issue** | #20 (Move remaining layout constants into theme.py) |

---

## 1. Background and Goal

`theme.py` centralizes all colors and font definitions for the application, and `tests/test_theme.py` prevents hardcoded color or font literals from creeping into the UI window code.

However, several intentional layout and sizing dimensions currently remain as inline constants or numeric literals in `library_visualizer.py` and `course_builder.py`:
- `DIST_PANEL_WIDTH = 320` and `CHART_MIN_CLICK_FRACTION = 0.15` are defined at module scope in `library_visualizer.py`.
- Treeview `rowheight=27` is hardcoded inline in `library_visualizer.py:241`. As noted in `README.md:64`, increasing font sizes requires adjusting this row height to avoid text clipping.
- Default window and dialog sizes (`geometry(...)` and `minsize(...)`) are hardcoded in `library_visualizer.py` and `course_builder.py`.
- Common button padding (`padx=11, pady=7`) and chart bar height (`height=0.68`) are hardcoded literals.

The goal of this change is to complete the visual design system by moving intentional layout and sizing constants into `theme.py`, keeping the "everything visual is named" architecture consistent and making future visual restyling or scaling safer.

---

## 2. Inventory of Current Layout Values

Measured against current `main` (`9912263`):

| Scope / Component | File & Line | Current Value | Purpose |
|---|---|---|---|
| **Table row height** | `library_visualizer.py:241` | `rowheight=27` | Song table row height in pixels |
| **Distribution panel width** | `library_visualizer.py:38` | `DIST_PANEL_WIDTH = 320` | Width of right-hand distribution side panel in pixels |
| **Chart click target zone** | `library_visualizer.py:41` | `CHART_MIN_CLICK_FRACTION = 0.15` | Minimum clickable width fraction for small bars |
| **Chart bar height** | `library_visualizer.py:1286` | `height=0.68` | Matplotlib horizontal bar thickness |
| **Button padding** | `library_visualizer.py:755` | `padx=11, pady=7` | Standard padding for themed buttons in `_button` factory |
| **Main window geometry** | `library_visualizer.py:112` | `geometry("1500x850")` | Initial window size |
| **Main window minsize** | `library_visualizer.py:113` | `minsize(900, 550)` | Minimum window dimensions |
| **Advanced Search geometry** | `library_visualizer.py:1408` | `geometry("560x620")` | Initial dialog size |
| **Advanced Search minsize** | `library_visualizer.py:1409` | `minsize(480, 520)` | Minimum dialog dimensions |
| **Course Builder geometry** | `course_builder.py:63` | `geometry("900x620")` | Initial dialog size |
| **Course Builder minsize** | `course_builder.py:64` | `minsize(700, 440)` | Minimum dialog dimensions |

---

## 3. Options

### Option 1: Focused Core Layout Constants (Recommended)
Move the intentional, macro-level visual sizing constants that govern overall window proportions, table row heights, button metrics, and distribution panel geometry into `theme.py`.

- **Add to `theme.py`:**
  ```python
  # --- Layout & Geometry ---
  WINDOW_DEFAULT_GEOMETRY = "1500x850"
  WINDOW_MIN_SIZE = (900, 550)

  ADVANCED_SEARCH_GEOMETRY = "560x620"
  ADVANCED_SEARCH_MIN_SIZE = (480, 520)

  COURSE_BUILDER_GEOMETRY = "900x620"
  COURSE_BUILDER_MIN_SIZE = (700, 440)

  TABLE_ROW_HEIGHT = 27
  BUTTON_PADX = 11
  BUTTON_PADY = 7

  DIST_PANEL_WIDTH = 320
  CHART_MIN_CLICK_FRACTION = 0.15
  CHART_BAR_HEIGHT = 0.68
  ```
- **Update references:**
  - `library_visualizer.py` imports and references `theme.DIST_PANEL_WIDTH`, `theme.CHART_MIN_CLICK_FRACTION`, `theme.TABLE_ROW_HEIGHT`, `theme.CHART_BAR_HEIGHT`, `theme.WINDOW_DEFAULT_GEOMETRY`, `theme.WINDOW_MIN_SIZE`, `theme.ADVANCED_SEARCH_GEOMETRY`, `theme.ADVANCED_SEARCH_MIN_SIZE`, `theme.BUTTON_PADX`, `theme.BUTTON_PADY`.
  - `course_builder.py` references `theme.COURSE_BUILDER_GEOMETRY` and `theme.COURSE_BUILDER_MIN_SIZE`.
- **Readability & Maintenance:** High. `theme.py` remains concise and easy to navigate. Column default widths (which are user-resizable and saved in `settings.json`) remain co-located with column definitions.

### Option 2: Exhaustive Layout Migration
In addition to all constants in Option 1, also move column minimum widths (`minwidth=55`, `minwidth=65`), dialog margins (`padx=18`, `pady=(14, 2)`), and default column width dictionaries into `theme.py`.

- **Trade-off:** Adds dozens of granular micro-spacing numbers into `theme.py`. This dilutes `theme.py`'s focus as a high-level styling and theming manifest, increasing maintenance overhead without meaningful theming benefit.

---

## 4. Test Strategy

1. **Existing Theme Guards (`tests/test_theme.py`)**:
   - `test_every_theme_name_is_used`: Automatically checks that any uppercase constant added to `theme.py` is actively referenced by window code.
   - `test_every_theme_name_the_window_uses_exists`: Automatically verifies that any `theme.X` accessed in `library_visualizer.py` or `course_builder.py` is defined in `theme.py`.
2. **New Layout Guard Tests (`tests/test_theme.py`)**:
   - `test_no_hardcoded_rowheight_in_treeview`: Checks via regex/AST that `Treeview` styling does not hardcode an integer literal for `rowheight`.
   - `test_no_dist_constants_in_visualizer`: Verifies that `DIST_PANEL_WIDTH` and `CHART_MIN_CLICK_FRACTION` are no longer defined at module scope in `library_visualizer.py`.
   - `test_geometry_and_minsize_use_theme`: Verifies window and dialog setup calls reference `theme`.
3. **Full Regression**:
   - Run the complete 210-test suite (`python -m unittest discover -s tests`) to verify 0 regressions in window creation, layout, chart clicks, and dialog lifecycles.

---

## 5. Acceptance Criteria Mapping

| Issue #20 Requirement | Proposed Plan |
|---|---|
| Add clearly named entries in `theme.py` for intentional design choices | Adds dedicated `# --- Layout & Geometry ---` section in `theme.py` |
| Reference them from `library_visualizer.py` and `course_builder.py` | Replaces hardcoded literals and module constants with `theme.*` |
| Guard tests updated where appropriate | Extends `tests/test_theme.py` to prevent regression of key layout values |
| Out of scope preserved | No user-resizable distribution panel, no changes to any current numeric values |
