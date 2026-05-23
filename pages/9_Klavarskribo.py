import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import xml.etree.ElementTree as ET
import zipfile
import io
import re

st.set_page_config(
    page_title="Sonare — Klavarskribo",
    page_icon="🎹",
)

st.title("🎹 Klavarskribo Converter")

st.markdown(
    """
Convert traditional music notation into **Klavarskribo** — a vertical music
notation invented by *Cornelis Pot* in 1931. Time flows top-to-bottom and the
horizontal axis mirrors a piano keyboard.

- **Open circles** — white keys
- **Filled circles** — black keys
- **Thin vertical lines** mark the E–F gap, **thicker lines** the B–C / octave gap
- **Thin horizontal lines** mark beats, **thicker lines** mark measures
"""
)

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

STEP_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
BLACK_PCS = {1, 3, 6, 8, 10}
DUR_MAP = {"w": 4.0, "h": 2.0, "q": 1.0, "e": 0.5, "s": 0.25, "t": 0.125}


def is_black(midi: int) -> bool:
    return (midi % 12) in BLACK_PCS


# ---------------------------------------------------------------------------
# Klavarskribo renderer (matplotlib)
# ---------------------------------------------------------------------------

def render_klavar(
    notes,
    quarters_per_measure=4,
    row_height=0.55,
    beams=None,
    title=None,
    dynamics=None,
    show_octave_labels=False,
    show_beat_ticks=False,
    show_measure_numbers=True,
    show_clef=False,
    oct_gap=0.3,
):
    """Render a Klavarskribo score from `notes`.

    Parameters
    ----------
    notes : list of (start_in_quarters, duration_in_quarters, midi_pitch, hand)
        Hand is 'L' or 'R'.
    beams : list of list of int, optional
        Each entry is a list of indices into `notes` that should be beamed
        together. All notes within a single beam group must share the same
        hand. Beamed notes do not get an individual duration line; the beam
        itself indicates the rhythmic grouping.
    title : str, optional       Italic tempo/title text printed above the staff.
    dynamics : list of (start_in_quarters, str), optional
        Dynamic markings (e.g. "p", "f") placed at the given time in the
        left margin.
    show_octave_labels : bool   Print "c1", "c2", … above each C.
    show_beat_ticks    : bool   Small tick marks for sub-measure beats.
    show_measure_numbers : bool Number every measure down the left edge.
    show_clef : bool            Diamond octave-clef marker on the left.
    oct_gap : float             Extra horizontal space inserted at every
                                B–C octave boundary (in semitone units).

    Klavarskribo conventions used here:
      - Vertical staff lines at the **five black-key positions** per octave,
        in 2 + 3 groups (C#/D#  and  F#/G#/A#).
      - White-key notes sit in the spaces (open circles); black-key notes
        sit on a line (filled circles).
      - **Time** flows top-to-bottom. Bar lines are horizontal **dashed**
        lines drawn only at measure boundaries.
      - Every note has a short **horizontal stem** that indicates the hand
        (left = LH, right = RH). The stem is tangent to the **top edge** of
        a white head and to the **bottom edge** of a black head, so open
        circles hang from the stem and filled circles sit on top of it.
      - Beamed groups share a thick line connecting the outer stem ends.
    """
    fig, ax = plt.subplots(figsize=(6, 6))

    if not notes:
        ax.text(0.5, 0.5, "(no notes)", ha="center", va="center")
        ax.axis("off")
        return fig

    pitches = [n[2] for n in notes]
    # Snap to the octave boundaries that contain the lowest and highest note,
    # without extra padding — printed Klavar shows only the relevant octaves.
    min_p = (min(pitches) // 12) * 12              # C of lowest note's octave
    max_p = ((max(pitches) // 12) + 1) * 12 - 1     # B of highest note's octave

    def x_of(midi):
        rel = midi - min_p
        return rel + (rel // 12) * oct_gap

    x_left = x_of(min_p) - 0.8
    x_right = x_of(max_p) + 0.8

    max_time = max(s + d for s, d, _, _ in notes)
    n_measures = int(max_time / quarters_per_measure) + 1
    total_time = n_measures * quarters_per_measure

    width = max(4, (x_right - x_left + 2) * 0.32)
    height = max(4, total_time * row_height + 1)
    fig.set_size_inches(width, height)

    y_top = 0.0
    y_bottom = -total_time

    # Vertical staff lines at every black key (2+3 per octave)
    for midi in range(min_p, max_p + 1):
        if (midi % 12) in BLACK_PCS:
            x = x_of(midi)
            ax.plot([x, x], [y_top, y_bottom],
                    color="black", linewidth=0.8, zorder=1)

    # Bar lines — dashed horizontal lines at measure boundaries only
    bar_x0 = x_of(min_p) - 0.5
    bar_x1 = x_of(max_p) + 0.5
    for m in range(n_measures + 1):
        y = -m * quarters_per_measure
        ax.plot([bar_x0, bar_x1], [y, y],
                color="black", linewidth=0.8,
                linestyle=(0, (5, 3)), zorder=1)

    if show_beat_ticks:
        for m in range(n_measures):
            for b in range(1, int(quarters_per_measure)):
                y = -(m * quarters_per_measure + b)
                ax.plot([bar_x0 - 0.6, bar_x0 - 0.15], [y, y],
                        color="gray", linewidth=0.5, zorder=1)

    if show_octave_labels:
        for midi in range(min_p, max_p + 1):
            if midi % 12 == 0:
                octave = midi // 12 - 1
                ax.text(x_of(midi), y_top + 0.55, f"c{octave}",
                        ha="center", va="bottom",
                        fontsize=8, color="dimgray", style="italic")

    if show_measure_numbers:
        for m in range(n_measures):
            y = -m * quarters_per_measure - quarters_per_measure / 2
            ax.text(bar_x0 - 1.2, y, str(m + 1),
                    ha="right", va="center", fontsize=9, color="dimgray")

    if title:
        ax.text(bar_x0, y_top + 1.0, title,
                ha="left", va="bottom", fontsize=11, style="italic")

    if show_clef:
        # Diamond octave-clef marker before the first bar, centred on
        # middle C (or the nearest visible C). Small "o" inside marks
        # the reference octave.
        anchor_midi = 60 if min_p <= 60 <= max_p else (min_p + (-min_p) % 12)
        cx = x_of(anchor_midi)
        cy = y_top + 0.5
        d = 0.45
        ax.plot([cx, cx + d, cx, cx - d, cx],
                [cy + d, cy, cy - d, cy, cy + d],
                color="black", linewidth=1.0, zorder=4)
        ax.add_patch(Circle((cx, cy), d * 0.25,
                            facecolor="white", edgecolor="black",
                            linewidth=0.9, zorder=5))

    if dynamics:
        # Place dynamics inside the staff area, just below middle C, at the
        # given onset time. Matches how printed Klavar tucks dynamics next
        # to the notes rather than in a separate margin.
        anchor_midi = 60 if min_p <= 60 <= max_p else min_p
        dyn_x = x_of(anchor_midi) - 1.2
        for t, label in dynamics:
            ax.text(dyn_x, -t - 0.2, label,
                    ha="right", va="center",
                    fontsize=12, style="italic", weight="bold")

    # --- Note geometry ----------------------------------------------------
    radius = 0.45               # smaller heads, like printed Klavar
    stem_len = 0.7              # short, like printed Klavar

    # Stems attach at the note centre (the equator of the circle) and run
    # purely horizontally outward. This matches the cleaner look of printed
    # Klavar — beams in a group will then line up with the actual note
    # positions on the time axis instead of zig-zagging by note colour.
    n = len(notes)
    stem_y = [-notes[i][0] for i in range(n)]
    stem_end_x = [0.0] * n
    for i, (_start, _dur, midi, hand) in enumerate(notes):
        x = x_of(midi)
        if hand == "R":
            stem_end_x[i] = x + stem_len
        elif hand == "L":
            stem_end_x[i] = x - stem_len
        else:
            stem_end_x[i] = x

    # If beams are specified, stretch each beamed note's stem so they all
    # reach the same outer x, and draw the beam itself.
    beamed_idx = set()
    if beams:
        for group in beams:
            if not group:
                continue
            beamed_idx.update(group)
            hand = notes[group[0]][3]
            xs = [x_of(notes[i][2]) for i in group]
            if hand == "R":
                beam_x = max(xs) + stem_len
            else:
                beam_x = min(xs) - stem_len
            ys = [stem_y[i] for i in group]
            ax.plot([beam_x, beam_x], [min(ys), max(ys)],
                    color="black", linewidth=2.2,
                    solid_capstyle="butt", zorder=2)
            for i in group:
                stem_end_x[i] = beam_x

    # --- Draw notes -------------------------------------------------------
    for i, (start, dur, midi, hand) in enumerate(notes):
        x = x_of(midi)
        y_center = -start
        bottom_edge = y_center - radius
        sy = stem_y[i]

        # Horizontal hand stem — starts at the side of the head and extends
        # outward (to the beam end if beamed, otherwise stem_len away).
        if hand in ("L", "R"):
            edge_x = x + (radius if hand == "R" else -radius)
            ax.plot([edge_x, stem_end_x[i]], [sy, sy],
                    color="black", linewidth=1.6,
                    solid_capstyle="butt", zorder=2)

        # Vertical duration line — only for unbeamed notes longer than a
        # half note (beamed notes get rhythm from the beam itself).
        if i not in beamed_idx:
            dur_end = -(start + dur)
            if bottom_edge - dur_end > 0.6:
                ax.plot([x, x], [bottom_edge, dur_end],
                        color="black", linewidth=1.3,
                        solid_capstyle="butt", zorder=2)

        # Note head
        face = "black" if is_black(midi) else "white"
        ax.add_patch(Circle((x, y_center), radius,
                            facecolor=face, edgecolor="black",
                            linewidth=1.4, zorder=3))

    ax.set_xlim(bar_x0 - 2.2, bar_x1 + stem_len + 0.6)
    ax.set_ylim(y_bottom - 0.8, y_top + (1.8 if title else 1.4))
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    return fig


# ---------------------------------------------------------------------------
# Simple text parser
# ---------------------------------------------------------------------------

def parse_pitch(tok):
    m = re.match(r"^([A-Ga-g])([#♯b♭]*)(-?\d+)$", tok)
    if not m:
        return None
    step = m.group(1).upper()
    acc = m.group(2)
    octave = int(m.group(3))
    pc = STEP_PC[step]
    for c in acc:
        if c in "#♯":
            pc += 1
        elif c in "b♭":
            pc -= 1
    return pc + (octave + 1) * 12


def parse_duration(tok):
    if tok in DUR_MAP:
        return DUR_MAP[tok]
    try:
        return float(tok)
    except ValueError:
        return 1.0


def parse_simple_text(text, hand="R"):
    """Tokens: `<pitch> <dur>`, `r <dur>` for a rest, `[C4,E4,G4] <dur>` for a chord.

    `|` separates measures (visual only). Pitches like `C4`, `C#4`, `Db4`,
    `F##5`. Durations: w/h/q/e/s/t or a number in quarter-notes.

    All notes parsed from this text are tagged with `hand` ('L' or 'R').
    """
    notes = []
    t = 0.0

    text = text.replace("|", " ")
    # Keep chord brackets intact even if user put spaces inside
    text = re.sub(r"\[\s*", "[", text)
    text = re.sub(r"\s*\]", "]", text)
    text = re.sub(r"\s*,\s*", ",", text)

    tokens = text.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("[") and tok.endswith("]"):
            chord = [parse_pitch(p) for p in tok[1:-1].split(",")]
            i += 1
            if i >= len(tokens):
                break
            d = parse_duration(tokens[i])
            for p in chord:
                if p is not None:
                    notes.append((t, d, p, hand))
            t += d
        elif tok.lower() in ("r", "rest"):
            i += 1
            if i >= len(tokens):
                break
            t += parse_duration(tokens[i])
        else:
            p = parse_pitch(tok)
            i += 1
            if i >= len(tokens):
                break
            d = parse_duration(tokens[i])
            if p is not None:
                notes.append((t, d, p, hand))
            t += d
        i += 1
    return notes


# ---------------------------------------------------------------------------
# MusicXML parser (plain .xml/.musicxml or compressed .mxl)
# ---------------------------------------------------------------------------

def _extract_mxl(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        try:
            container = z.read("META-INF/container.xml").decode("utf-8")
            cr = ET.fromstring(container)
            rf = cr.find(".//{*}rootfile") or cr.find(".//rootfile")
            path = rf.attrib["full-path"]
        except Exception:
            # Fallback: first .xml that isn't the container
            path = next(n for n in z.namelist()
                        if n.endswith((".xml", ".musicxml"))
                        and "container" not in n)
        return z.read(path)


def parse_musicxml_bytes(data: bytes):
    if data[:2] == b"PK":
        data = _extract_mxl(data)

    root = ET.fromstring(data)
    notes = []
    quarters_per_measure = 4.0

    # MusicXML has parts; iterate every part. For piano scores the two
    # staves of a single part carry the hand assignment via <staff>:
    # staff 1 = right hand, staff 2 = left hand.
    parts = root.findall(".//part")
    for part_idx, part in enumerate(parts):
        current = 0.0
        divisions = 1
        prev_dur = 0.0
        beats = 4
        beat_unit = 4
        # If a score has two separate parts (e.g. a duet) and no <staff>
        # tags, treat the first part as RH, second as LH.
        default_hand = "R" if part_idx == 0 else "L"

        for measure in part.findall("measure"):
            attrs = measure.find("attributes")
            if attrs is not None:
                d = attrs.find("divisions")
                if d is not None:
                    divisions = int(d.text)
                ts = attrs.find("time")
                if ts is not None:
                    beats = int(ts.find("beats").text)
                    beat_unit = int(ts.find("beat-type").text)
                    quarters_per_measure = beats * 4.0 / beat_unit

            for elem in measure:
                if elem.tag == "note":
                    de = elem.find("duration")
                    if de is None:  # grace note
                        continue
                    dur_q = int(de.text) / divisions  # in quarter notes

                    is_rest = elem.find("rest") is not None
                    is_chord = elem.find("chord") is not None
                    pe = elem.find("pitch")
                    se = elem.find("staff")
                    if se is not None:
                        hand = "L" if int(se.text) >= 2 else "R"
                    else:
                        hand = default_hand

                    start = current - prev_dur if is_chord else current

                    if not is_rest and pe is not None:
                        step = pe.find("step").text
                        octave = int(pe.find("octave").text)
                        ae = pe.find("alter")
                        alter = int(ae.text) if ae is not None else 0
                        midi = STEP_PC[step] + alter + (octave + 1) * 12
                        notes.append((start, dur_q, midi, hand))

                    if not is_chord:
                        current += dur_q
                        prev_dur = dur_q

                elif elem.tag == "backup":
                    current -= int(elem.find("duration").text) / divisions
                    prev_dur = 0.0
                elif elem.tag == "forward":
                    current += int(elem.find("duration").text) / divisions
                    prev_dur = 0.0

    return notes, quarters_per_measure


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

EXAMPLE_SCALE_RH = (
    "C4 q D4 q E4 q F4 q | G4 q A4 q B4 q C5 q | "
    "[C4,E4,G4] h [F4,A4,C5] h | [G4,B4,D5] h [C4,E4,G4] h"
)
EXAMPLE_SCALE_LH = (
    "C3 h G3 h | C3 h G3 h | "
    "C3 h F3 h | G3 h C3 h"
)

EXAMPLE_FUR_ELISE_RH = (
    "E5 e D#5 e E5 e D#5 e E5 e B4 e D5 e C5 e A4 q "
    "r e C4 e E4 e A4 e B4 q "
    "r e E4 e G#4 e B4 e C5 q "
    "r e E4 e E5 e D#5 e E5 e D#5 e E5 e B4 e D5 e C5 e A4 q"
)
EXAMPLE_FUR_ELISE_LH = (
    "r q r q r q "
    "A2 e E3 e A3 e r q r q "
    "E2 e E3 e G#3 e r q r q "
    "A2 e E3 e A3 e r q r q r q r q"
)

mode = st.radio(
    "Input method:",
    ["Simple text", "MusicXML upload", "Example: scale + chords", "Example: Für Elise"],
    horizontal=True,
)

notes = []
qpm = 4.0

if mode == "Simple text":
    with st.expander("Syntax help", expanded=False):
        st.markdown(
            """
- **Pitch + duration**, separated by spaces: `C4 q D4 q E4 h`
- **Pitches**: `C4`, `C#4`, `Db4`, `F##5`, etc.
- **Durations**: `w` whole, `h` half, `q` quarter, `e` eighth,
  `s` sixteenth, `t` 32nd — or a number in quarter notes (`1.5`).
- **Rests**: `r q`
- **Chords**: `[C4,E4,G4] q`
- `|` is an optional bar separator.

The right-hand and left-hand fields are rendered together; each note
gets a horizontal stem in its hand's direction
(right-going = RH, left-going = LH).
"""
        )
    col_rh, col_lh = st.columns(2)
    with col_rh:
        rh_text = st.text_area("Right hand", value=EXAMPLE_SCALE_RH, height=160)
    with col_lh:
        lh_text = st.text_area("Left hand", value=EXAMPLE_SCALE_LH, height=160)
    qpm = float(st.number_input("Quarter notes per measure", 1, 16, 4))
    notes = []
    if rh_text.strip():
        notes += parse_simple_text(rh_text, hand="R")
    if lh_text.strip():
        notes += parse_simple_text(lh_text, hand="L")

elif mode == "MusicXML upload":
    st.markdown(
        "MusicXML is the standard interchange format for sheet music — exportable "
        "from MuseScore, Sibelius, Finale, Dorico, Logic, etc. "
        "For piano scores the upper staff is taken as right hand, the lower as left hand."
    )
    uploaded = st.file_uploader(
        "Upload MusicXML",
        type=["xml", "musicxml", "mxl"],
        accept_multiple_files=False,
    )
    if uploaded is not None:
        try:
            notes, qpm = parse_musicxml_bytes(uploaded.read())
            st.success(f"Parsed {len(notes)} notes from **{uploaded.name}** "
                       f"(time signature ≈ {qpm:g}/4)")
        except Exception as e:
            st.error(f"Could not parse the file: {e}")

elif mode == "Example: scale + chords":
    notes = (parse_simple_text(EXAMPLE_SCALE_RH, hand="R")
             + parse_simple_text(EXAMPLE_SCALE_LH, hand="L"))

else:  # Für Elise
    notes = (parse_simple_text(EXAMPLE_FUR_ELISE_RH, hand="R")
             + parse_simple_text(EXAMPLE_FUR_ELISE_LH, hand="L"))
    qpm = 3.0  # 3/8 — display 3 quarters per "measure" for a rough fit

row_h = st.slider("Vertical scale", 0.25, 1.2, 0.55, 0.05,
                  help="Height per quarter note in the rendered image.")

if notes:
    fig = render_klavar(notes, quarters_per_measure=qpm, row_height=row_h)
    st.pyplot(fig, use_container_width=False)

    png_buf = io.BytesIO()
    fig.savefig(png_buf, format="png", dpi=200, bbox_inches="tight")
    svg_buf = io.BytesIO()
    fig.savefig(svg_buf, format="svg", bbox_inches="tight")

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Download PNG", png_buf.getvalue(),
                           file_name="klavarskribo.png", mime="image/png")
    with c2:
        st.download_button("Download SVG", svg_buf.getvalue(),
                           file_name="klavarskribo.svg", mime="image/svg+xml")
else:
    st.info("Enter some notes or upload a MusicXML file to see the Klavarskribo rendering.")

st.sidebar.markdown(
    "Sonare © 2025 by Niko Plath is licensed under Creative Commons "
    "Attribution-NonCommercial-ShareAlike 4.0 International"
)
st.sidebar.markdown(
    "Contact: [www.culturalheritage.digital](http://www.culturalheritage.digital/)"
)
