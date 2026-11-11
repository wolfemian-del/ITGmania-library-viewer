"""Colors and fonts for the ITGmania Library Visualizer window.

Every color and font the window uses is defined here, named by what it is for. Layout and geometry
constants (window sizes, row height, paddings) are also defined here. To restyle the app, edit
the values in this file and restart it. The values are plain strings and tuples so that this file does
not need Tkinter.

Colors are written as "#rrggbb". A font is (family, size) or (family, size, style); sizes are in points.
"""

# --- Surfaces (backgrounds) ---
BG_WINDOW = "#10151d"         # main window and dialogs
BG_PANEL = "#171f2a"          # distribution panel, path rows, chart background
BG_INPUT = "#202b38"          # text boxes, drop-downs, checkbox squares
BG_TABLE = "#151d28"          # song table body
BG_TABLE_HEADING = "#222d3b"  # song table column headings, progress bar trough
BG_PREVIEW = "#17202c"        # query preview strip in Advanced Search
BG_BUTTON = "#263443"         # secondary button
BG_BUTTON_HOVER = "#344659"   # secondary button while pressed or hovered

# --- Accent (teal) and selection ---
ACCENT = "#4fc3b0"            # progress bar, focus outline, chart bars
ACCENT_BG = "#287c78"         # primary button, selected drop-down item, checkbox tick
ACCENT_BG_HOVER = "#368f89"   # primary button while pressed or hovered
SELECTION_BG = "#285c74"      # selected table row

# --- Lines ---
BORDER = "#2c3948"            # text box outline
CHART_AXIS_LINE = "#2a3749"   # baseline under the distribution chart

# --- Text ---
TEXT_TITLE = "#f2f6fa"        # window and dialog titles
TEXT_PRIMARY = "#ecf3f9"      # text typed in boxes, drop-downs, chart counts
TEXT_TABLE = "#e8edf4"        # song table rows
TEXT_HEADING = "#dbe7f4"      # song table column headings
TEXT_LABEL = "#dce5ee"        # checkbox label, query preview
TEXT_FIELD_LABEL = "#bdc9d5"  # labels beside input boxes
TEXT_MUTED = "#9eacbb"        # secondary text, chart ticks
TEXT_HINT = "#607285"         # hints and "to" between range boxes
TEXT_FOOTER = "#6f7e8e"       # footer text
TEXT_DISABLED = "#8794a3"     # disabled drop-down
WHITE = "#ffffff"             # highlighted chart bar outline, selected drop-down text
TEXT_ON_ACCENT = "white"      # text on buttons and on the selected table row
CURSOR = "white"              # blinking text cursor

# --- Distribution chart ---
DIFFICULTY_COLORS = {
    "Beginner": "#38bdf8",
    "Easy": "#facc15",
    "Medium": "#f43f5e",
    "Hard": "#34d399",
    "Challenge": "#c084fc",
    "Edit": "#94a3b8",
}
DIFFICULTY_COLOR_UNKNOWN = "#94a3b8"  # a difficulty name not listed above
CHART_BAR_UNKNOWN = "#64748b"         # the "?" bar (value missing)

# --- Fonts ---
FONT_BODY = ("Segoe UI", 9)
FONT_BODY_BOLD = ("Segoe UI Semibold", 9)
FONT_SMALL = ("Segoe UI", 8)
FONT_ENTRY_LARGE = ("Segoe UI", 10)           # course title box
FONT_PANEL_TITLE = ("Segoe UI Semibold", 11)  # "Distribution" heading
FONT_DIALOG_TITLE = ("Segoe UI Semibold", 15) # Advanced Search heading
FONT_COURSE_TITLE = ("Segoe UI Semibold", 17) # course builder heading
FONT_APP_TITLE = ("Segoe UI Semibold", 19)    # main window heading
FONT_MONO_BOLD = ("Consolas", 9, "bold")      # query text in Advanced Search

# --- Distribution chart text sizes (points; the chart is drawn by matplotlib, which picks its own font family) ---
CHART_TEXT_SIZE_MESSAGE = 9   # "no data" message in the chart area
CHART_TEXT_SIZE_COUNT = 7.5   # count printed beside each bar
CHART_TEXT_SIZE_LABEL = 8     # bar labels on the left and the axis tick numbers

# --- Layout & Geometry ---
WINDOW_DEFAULT_GEOMETRY = "1500x850"
WINDOW_MIN_SIZE = (900, 550)

ADVANCED_SEARCH_GEOMETRY = "560x620"
ADVANCED_SEARCH_MIN_SIZE = (480, 520)

COURSE_BUILDER_GEOMETRY = "1000x620"
COURSE_BUILDER_MIN_SIZE = (700, 440)

TABLE_ROW_HEIGHT = 27
BUTTON_PADX = 11
BUTTON_PADY = 7

DIST_PANEL_WIDTH = 320
# A bar can be clicked across at least this fraction of the chart's width, so a very short bar (one chart
# among hundreds) is still easy to hit, while a click far to the right of it does nothing.
CHART_MIN_CLICK_FRACTION = 0.15
CHART_BAR_HEIGHT = 0.68
# The chart's x-axis runs this many times past the longest bar, leaving headroom for the count labels.
CHART_AXIS_HEADROOM = 1.25
