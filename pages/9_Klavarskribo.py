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

def render_klavar(notes, quarters_per_measure=4, row_height=0.55):
    """notes: list of (start_in_quarters, duration_in_quarters, midi_pitch)."""
    fig, ax = plt.subplots(figsize=(6, 6))

    if not notes:
        ax.text(0.5, 0.5, "(no notes)", ha="center", va="center")
        ax.axis("off")
        return fig

    pitches = [n[2] for n in notes]
    min_p = min(pitches) - 3
    max_p = max(pitches) + 3
    while min_p % 12 != 0:
        min_p -= 1
    while max_p % 12 != 11:
        max_p += 1

    max_time = max(s + d for s, d, _ in notes)
    n_measures = int(max_time / quarters_per_measure) + 1
    total_time = n_measures * quarters_per_measure

    width = max(4, (max_p - min_p + 2) * 0.22)
    height = max(4, total_time * row_height + 1)
    fig.set_size_inches(width, height)

    # Vertical staff lines at piano black-key gaps
    for midi in range(min_p, max_p + 2):
        pc = midi % 12
        if pc == 5:  # E-F gap
            ax.axvline(midi - 0.5, color="black", linewidth=0.7, zorder=1)
        elif pc == 0:  # B-C gap (octave)
            ax.axvline(midi - 0.5, color="black", linewidth=1.3, zorder=1)

    # Horizontal beat & measure lines
    beat = 0
    while beat <= total_time + 1e-6:
        y = -beat
        if abs(beat % quarters_per_measure) < 1e-6:
            ax.axhline(y, color="black", linewidth=1.1, zorder=1)
        else:
            ax.axhline(y, color="gray", linewidth=0.35,
                       linestyle=(0, (1, 3)), zorder=1)
        beat += 1

    # C-octave labels
    for midi in range(min_p, max_p + 1):
        if midi % 12 == 0:
            octave = midi // 12 - 1
            ax.text(midi, 0.6, f"C{octave}", ha="center", va="bottom",
                    fontsize=8, color="dimgray")

    # Notes
    radius = 0.42
    for start, dur, midi in notes:
        x = midi
        y_top = -start
        y_bot = -(start + dur)

        if dur > 0.05:
            ax.plot([x, x], [y_top, y_bot], color="black", linewidth=2.5,
                    solid_capstyle="butt", zorder=2)

        face = "black" if is_black(midi) else "white"
        ax.add_patch(Circle((x, y_top), radius,
                            facecolor=face, edgecolor="black",
                            linewidth=1.3, zorder=3))

    ax.set_xlim(min_p - 0.8, max_p + 0.8)
    ax.set_ylim(-total_time - 0.5, 1.6)
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


def parse_simple_text(text):
    """Tokens: `<pitch> <dur>`, `r <dur>` for a rest, `[C4,E4,G4] <dur>` for a chord.

    `|` separates measures (visual only). Pitches like `C4`, `C#4`, `Db4`,
    `F##5`. Durations: w/h/q/e/s/t or a number in quarter-notes.
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
                    notes.append((t, d, p))
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
                notes.append((t, d, p))
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

    # MusicXML has parts; iterate every part and merge — Klavar shows all hands together.
    for part in root.findall(".//part"):
        current = 0.0
        divisions = 1
        prev_dur = 0.0
        beats = 4
        beat_unit = 4

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

                    start = current - prev_dur if is_chord else current

                    if not is_rest and pe is not None:
                        step = pe.find("step").text
                        octave = int(pe.find("octave").text)
                        ae = pe.find("alter")
                        alter = int(ae.text) if ae is not None else 0
                        midi = STEP_PC[step] + alter + (octave + 1) * 12
                        notes.append((start, dur_q, midi))

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

EXAMPLE_FUR_ELISE = (
    "E5 e D#5 e E5 e D#5 e E5 e B4 e D5 e C5 e A4 q "
    "r e C4 e E4 e A4 e B4 q "
    "r e E4 e G#4 e B4 e C5 q "
    "r e E4 e E5 e D#5 e E5 e D#5 e E5 e B4 e D5 e C5 e A4 q"
)

EXAMPLE_SCALE = (
    "C4 q D4 q E4 q F4 q | G4 q A4 q B4 q C5 q | "
    "[C4,E4,G4] h [F4,A4,C5] h | [G4,B4,D5] h [C4,E4,G4] h"
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
"""
        )
    text = st.text_area("Notes:", value=EXAMPLE_SCALE, height=140)
    qpm = float(st.number_input("Quarter notes per measure", 1, 16, 4))
    if text.strip():
        notes = parse_simple_text(text)

elif mode == "MusicXML upload":
    st.markdown(
        "MusicXML is the standard interchange format for sheet music — exportable "
        "from MuseScore, Sibelius, Finale, Dorico, Logic, etc."
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
    notes = parse_simple_text(EXAMPLE_SCALE)

else:  # Für Elise
    notes = parse_simple_text(EXAMPLE_FUR_ELISE)
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
