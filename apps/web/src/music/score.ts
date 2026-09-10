/**
 * The tune, as data, and the notation it is written in.
 *
 * Ben, 2026-09-10: "is it possible to add some background old gaming music to our website. and
 * just put a mute button somewhere". The music is synthesised in the browser from this file
 * rather than streamed from a recording. The sound Ben is after is the four-channel one an NES
 * made — two pulse waves, a triangle and noise — and the Web Audio API produces those waveforms
 * directly, so a tune written here is nobody's copyright, adds nothing to the bundle beyond
 * this file, downloads nothing, and loops without a seam.
 *
 * `engine.ts` turns the score into sound; this file has no idea what an AudioContext is, which
 * is what lets the tests below run in Node and keep the data honest.
 */

/** A note in a part: which pitch, and where it starts and how long it lasts, in steps. */
export interface NoteEvent {
  midi: number;
  startStep: number;
  steps: number;
}

/** A part's notes and its full length in steps — rests at the end count, or the loop drifts. */
export interface Voice {
  events: readonly NoteEvent[];
  steps: number;
}

/**
 * How a part sounds. A pulse wave's duty cycle is the fraction of each period it spends high:
 * a half is a square wave, and the thinner quarter and eighth are the classic lead sounds.
 */
export type Timbre = { kind: "pulse"; duty: number } | { kind: "triangle" };

export interface Part extends Voice {
  name: string;
  timbre: Timbre;
  /** The part's level relative to the others, before the engine's own master level. */
  gain: number;
  /** Seconds of silence trimmed from the end of every note, so repeated notes articulate. */
  gap: number;
}

export type DrumKind = "kick" | "snare" | "hat";

export interface DrumHit {
  kind: DrumKind;
  step: number;
}

export interface Score {
  bpm: number;
  /** Steps per beat; four makes a step a sixteenth note. */
  stepsPerBeat: number;
  totalSteps: number;
  parts: readonly Part[];
  drums: readonly DrumHit[];
}

/** Sixteen steps to a bar: four beats of four sixteenths. */
export const STEPS_PER_BAR = 16;

/** A step is one sixteenth; an eighth is two of them. */
const EIGHTH = 2;

const PITCH_CLASSES: Readonly<Record<string, number>> = {
  C: 0,
  D: 2,
  E: 4,
  F: 5,
  G: 7,
  A: 9,
  B: 11,
};

const NOTE_PATTERN = /^([A-G])([#b]?)(\d)$/;

/** `A4` is 69, the MIDI convention; a sharp is one up and a flat one down. */
export function noteToMidi(name: string): number {
  const match = NOTE_PATTERN.exec(name);
  if (match === null) throw new Error(`Not a note: "${name}"`);
  const [, letter, accidental, octave] = match;
  const semitone =
    PITCH_CLASSES[letter] +
    (accidental === "#" ? 1 : accidental === "b" ? -1 : 0);
  return (Number(octave) + 1) * 12 + semitone;
}

/** Equal temperament with A4 at 440 Hz. */
export function midiToFrequency(midi: number): number {
  return 440 * 2 ** ((midi - 69) / 12);
}

/** A token of the notation: a pitch or a rest (`-`), then an optional `:steps`. */
const TOKEN_PATTERN = /^(-|[A-G][#b]?\d)(?::(\d+))?$/;

/**
 * Reads a part written the way it would be hummed: `E5:3 E5:1 A5:2` is a dotted eighth, a
 * sixteenth and an eighth in a row, each starting where the one before it ends. A bare pitch is
 * one step, `-` is a rest, and `|` marks a bar and means nothing. A token it cannot read throws,
 * naming the token, so a typo in the score fails the suite and never reaches a tap.
 */
export function parseVoice(notation: string): Voice {
  const events: NoteEvent[] = [];
  let step = 0;
  for (const token of notation.split(/\s+/)) {
    if (token === "" || token === "|") continue;
    const match = TOKEN_PATTERN.exec(token);
    const steps =
      match === null ? 0 : match[2] === undefined ? 1 : Number(match[2]);
    if (match === null || steps <= 0) {
      throw new Error(`Bad token in the score: "${token}"`);
    }
    if (match[1] !== "-") {
      events.push({ midi: noteToMidi(match[1]), startStep: step, steps });
    }
    step += steps;
  }
  return { events, steps: step };
}

/**
 * Enough harmonics that a pulse wave keeps its edge across the lead's range. The browser
 * band-limits the table per octave itself, so more here never aliases; it only costs a little
 * memory once per context.
 */
export const PULSE_HARMONICS = 64;

/**
 * The Fourier series of a pulse wave with the given duty cycle, in the shape
 * `AudioContext.createPeriodicWave` takes: cosine terms in `real`, sine terms in `imag`. A pulse
 * centred on the origin has only cosine terms, `2 sin(nπd) / nπ` for the n-th harmonic, and its
 * DC term is dropped so the wave sits about zero. At a duty of a half the even harmonics vanish
 * and what is left is a square wave.
 */
export function pulseWave(
  duty: number,
  harmonics: number = PULSE_HARMONICS,
): { real: Float32Array; imag: Float32Array } {
  const real = new Float32Array(harmonics + 1);
  const imag = new Float32Array(harmonics + 1);
  for (let n = 1; n <= harmonics; n += 1) {
    real[n] = (2 / (n * Math.PI)) * Math.sin(n * Math.PI * duty);
  }
  return { real, imag };
}

/** One bar's harmony: the tones the arpeggio cycles, and the root the bass sits on. */
export interface Chord {
  tones: readonly string[];
  bass: string;
  /** Notes the bass walks up through on the bar's last eighths, to lead into the next bar. */
  walkUp?: readonly string[];
}

/** The chord's tones in sixteenths, round and round, one bar per chord. */
export function arpeggioVoice(
  chords: readonly Chord[],
  stepsPerBar: number,
): Voice {
  const events: NoteEvent[] = [];
  chords.forEach((chord, bar) => {
    for (let step = 0; step < stepsPerBar; step += 1) {
      events.push({
        midi: noteToMidi(chord.tones[step % chord.tones.length]),
        startStep: bar * stepsPerBar + step,
        steps: 1,
      });
    }
  });
  return { events, steps: chords.length * stepsPerBar };
}

/**
 * The root and the octave above it, alternating in eighths — the driving bass every game of the
 * era ran on — with a chord's walk-up, where it has one, taking over the last eighths of the bar.
 */
export function bassVoice(
  chords: readonly Chord[],
  stepsPerBar: number,
): Voice {
  const events: NoteEvent[] = [];
  const eighths = stepsPerBar / EIGHTH;
  chords.forEach((chord, bar) => {
    const root = noteToMidi(chord.bass);
    const walkUp = (chord.walkUp ?? []).map(noteToMidi);
    for (let eighth = 0; eighth < eighths; eighth += 1) {
      const walkIndex = walkUp.length - (eighths - eighth);
      const midi =
        walkIndex >= 0
          ? walkUp[walkIndex]
          : eighth % 2 === 0
            ? root
            : root + 12;
      events.push({
        midi,
        startStep: bar * stepsPerBar + eighth * EIGHTH,
        steps: EIGHTH,
      });
    }
  });
  return { events, steps: chords.length * stepsPerBar };
}

/** Which steps of a bar each drum falls on. */
export type DrumPattern = Partial<Record<DrumKind, readonly number[]>>;

/**
 * The same bar of drums repeated, plus a fill on the bars (counted from zero) that have one.
 * Hits come back in step order.
 */
export function drumTrack({
  bars,
  stepsPerBar,
  pattern,
  fills = {},
}: {
  bars: number;
  stepsPerBar: number;
  pattern: DrumPattern;
  fills?: Readonly<Record<number, DrumPattern>>;
}): DrumHit[] {
  const hits: DrumHit[] = [];
  for (let bar = 0; bar < bars; bar += 1) {
    for (const source of [pattern, fills[bar] ?? {}]) {
      for (const [kind, steps] of Object.entries(source) as [
        DrumKind,
        readonly number[],
      ][]) {
        for (const step of steps) {
          hits.push({ kind, step: bar * stepsPerBar + step });
        }
      }
    }
  }
  return hits.sort((a, b) => a.step - b.step);
}

/** Everything that starts on one step: the notes, each with its part, and the drums. */
export interface StepEvents {
  notes: { part: Part; event: NoteEvent }[];
  drums: DrumKind[];
}

/** The score by step, so the engine can ask "what starts now?" without scanning every part. */
export function indexByStep(score: Score): ReadonlyMap<number, StepEvents> {
  const index = new Map<number, StepEvents>();
  const at = (step: number): StepEvents => {
    let entry = index.get(step);
    if (entry === undefined) {
      entry = { notes: [], drums: [] };
      index.set(step, entry);
    }
    return entry;
  };
  for (const part of score.parts) {
    for (const event of part.events) {
      at(event.startStep).notes.push({ part, event });
    }
  }
  for (const hit of score.drums) {
    at(hit.step).drums.push(hit.kind);
  }
  return index;
}

/** How long one step lasts. */
export function stepSeconds(score: Score): number {
  return 60 / score.bpm / score.stepsPerBeat;
}

/*
  The tune: sixteen bars in A minor at 150 beats per minute, a shade under twenty-six seconds
  round. The arpeggio and the bass are generated from the chords below; the lead is written out.
*/

const Am: Chord = { tones: ["A4", "C5", "E5", "A5"], bass: "A2" };
const F: Chord = { tones: ["F4", "A4", "C5", "F5"], bass: "F2" };
const C: Chord = { tones: ["C4", "E4", "G4", "C5"], bass: "C3" };
const G: Chord = { tones: ["G4", "B4", "D5", "G5"], bass: "G2" };
const Dm: Chord = { tones: ["D4", "F4", "A4", "D5"], bass: "D3" };
/** The dominant: every time it comes round the bass walks F, G♯ up into the A of the next bar. */
const E: Chord = {
  tones: ["E4", "G#4", "B4", "E5"],
  bass: "E2",
  walkUp: ["F2", "G#2"],
};

/**
 * The form. A four-bar motif; its answer a fourth higher, turning around on the dominant; a
 * bridge that holds the third of each chord over a slower line; and the answer again, whose
 * last bar runs back up to the top.
 */
// prettier-ignore
const CHORDS: readonly Chord[] = [
  Am, F, C,  G,
  Am, F, Dm, E,
  F,  G, Am, E,
  Am, F, Dm, E,
];

/**
 * The lead. A dotted eighth, a sixteenth, then two eighths is the figure the whole tune is made
 * of; the fourth bar of each phrase answers it, and the bridge trades it for held thirds.
 */
const LEAD_NOTATION = `
  E5:3 E5:1 A5:2 G5:2 E5:4 C5:2 D5:2 |
  F5:3 F5:1 A5:2 C6:2 A5:4 G5:2 F5:2 |
  E5:3 E5:1 G5:2 E5:2 C5:4 D5:2 E5:2 |
  D5:2 B4:2 G4:2 B4:2 D5:4 B4:2 D5:2 |

  A5:3 A5:1 C6:2 B5:2 A5:4 E5:2 G5:2 |
  F5:3 F5:1 A5:2 G5:2 F5:2 E5:2 F5:2 A5:2 |
  D5:2 F5:2 A5:2 D6:2 C6:2 A5:2 F5:2 D5:2 |
  G#5:3 G#5:1 B5:2 G#5:2 E5:4 B4:2 D5:2 |

  A5:6 G5:2 F5:4 E5:2 D5:2 |
  B4:6 D5:2 G5:4 D5:2 B4:2 |
  C5:6 E5:2 A5:4 E5:2 C5:2 |
  E5:6 G#5:2 B5:4 -:2 G#5:2 |

  A5:3 A5:1 C6:2 B5:2 A5:4 E5:2 G5:2 |
  F5:3 F5:1 A5:2 G5:2 F5:2 E5:2 F5:2 A5:2 |
  D5:2 F5:2 A5:2 D6:2 C6:2 A5:2 F5:2 D5:2 |
  G#5:3 G#5:1 B5:2 G#5:2 E5:2 -:2 B4:1 C5:1 D5:1 -:1 |
`;

/** Kick on the one, the three and the and-of-three; snare on the two and the four; hats in eighths. */
const DRUM_PATTERN: DrumPattern = {
  kick: [0, 8, 10],
  snare: [4, 12],
  hat: [0, 2, 4, 6, 8, 10, 12, 14],
};

/** Two extra snares close a phrase; four in a row close the turnaround into the next one. */
const PHRASE_FILL: DrumPattern = { snare: [14, 15] };
const TURNAROUND_FILL: DrumPattern = { snare: [12, 13, 14, 15] };

const BARS = CHORDS.length;

export const SCORE: Score = {
  bpm: 150,
  stepsPerBeat: 4,
  totalSteps: BARS * STEPS_PER_BAR,
  parts: [
    {
      name: "lead",
      timbre: { kind: "pulse", duty: 0.25 },
      gain: 0.5,
      gap: 0.03,
      ...parseVoice(LEAD_NOTATION),
    },
    {
      name: "arp",
      timbre: { kind: "pulse", duty: 0.125 },
      gain: 0.18,
      gap: 0.045,
      ...arpeggioVoice(CHORDS, STEPS_PER_BAR),
    },
    {
      name: "bass",
      timbre: { kind: "triangle" },
      gain: 0.7,
      gap: 0.02,
      ...bassVoice(CHORDS, STEPS_PER_BAR),
    },
  ],
  drums: drumTrack({
    bars: BARS,
    stepsPerBar: STEPS_PER_BAR,
    pattern: DRUM_PATTERN,
    fills: {
      3: PHRASE_FILL,
      7: TURNAROUND_FILL,
      11: PHRASE_FILL,
      15: TURNAROUND_FILL,
    },
  }),
};
