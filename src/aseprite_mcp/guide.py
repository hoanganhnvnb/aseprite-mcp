from typing import Literal

Topic = Literal["basics", "animation", "idle", "walk", "attack", "effects"]

_BASICS = """\
Pixel art basics

1. Pick a small canvas and stay there: 16x16 or 32x32 for characters and items,
   48x48 or 64x64 for bosses. `create_sprite` without a background keeps the
   layer transparent.
2. Choose the palette before drawing. Four to eight colours per material is plenty.
   `generate_color_ramp` builds a ramp from one colour; use hue_shift so shadows
   lean cool (towards blue/purple) and highlights lean warm (towards yellow).
   Load the result with `set_palette`.
3. Block in the silhouette with one dark colour (`draw_rect`, `draw_ellipse`,
   `draw_polygon`, or `draw_ascii` for small hand-placed shapes). Check it with
   `view_sprite` at scale 8: the shape alone should read clearly.
4. Decide on one light source (top-left is the usual choice) and keep it for every
   part. Fill the flat base colours, then add one shadow and one highlight step.
5. Work in clusters: groups of same-coloured pixels with clean shapes. Avoid lone
   pixels and checkerboard noise; `find_stray_pixels` lists the specks.
6. Clean the lines. Curves should step evenly (3-2-1, not 3-1-2). Remove doubled
   pixels on diagonals ("jaggies"); add a mid-tone pixel in a corner only where a
   step looks too sharp.
7. Outline: a dark outline keeps the sprite readable on any background (`outline`).
   Selective outlining - lighter outline on the lit side, darker colour on the
   shadow side - looks softer once the shapes work.
8. Check the result with `view_sprite` (grid=true helps) and `get_color_stats` to
   see whether the colour count crept up, then `export` to PNG.
"""

_ANIMATION = """\
Animation basics

1. Plan the motion as keyframes first: the extreme poses that tell the action.
   Add in-betweens only after the keyframes read well.
2. Set up the frames with `add_frames` (copy_content=true starts each frame from
   the previous drawing) and name loops with `set_tag`.
3. Timing carries the feel. Use `set_frame_duration` per frame instead of adding
   frames: hold a key pose for 150-300 ms and pass through fast in-betweens at
   60-100 ms.
4. Ease in and out: frames bunch up near the start and end of a move and spread
   out in the middle. `tween_cels` with an easing does this for moving parts.
5. Keep volumes steady. A body that changes size between frames looks like it is
   boiling; compare frames with `compare_frames` to see what really changed.
6. Overlapping action: hair, capes and tails lag a frame or two behind the body
   and settle after it stops.
7. For a fast move, a smear frame (a stretched shape between two poses) reads
   better than extra in-betweens.
8. Loops: the last frame must flow into the first. Check the timing and the loop
   with `view_sprite` on all frames and `check_animation` for empty or misplaced
   cels, then `export` as .gif or `export_spritesheet` for a game engine.
"""

_IDLE = """\
Idle animation

1. Keep it small: 4 to 8 frames, 120-200 ms each. An idle that moves too much
   reads as nervous.
2. Breathing is the core: the chest and shoulders rise one pixel, the head
   follows a frame later. Feet never move.
3. Put the parts that move on their own layers (`add_layer`), e.g. body, head,
   arms. Then a one-pixel bob is just a cel offset: `oscillate_cels` with
   amplitude_y=1 on the upper layers gives a smooth loop.
4. Offset the timing of secondary parts (hair, scarf, ears) with the phase
   argument of `oscillate_cels`, so they settle after the body.
5. Add one small extra if the character has time to spare: a blink on one frame,
   a sway of a weapon tip. Do not move everything at once.
6. Tag the frames ("idle") with `set_tag`, run `check_animation`, and watch the
   loop with `view_sprite` using onion_skin to spot jumps.
"""

_WALK = """\
Walk cycle

1. A walk has four key poses per step, eight frames for both legs:
   contact (both feet on the ground, legs spread), down (weight lands, body
   lowest), passing (one leg passes the other, body rising), up (body highest,
   pushing off). Mirror the four for the other leg.
2. Draw the contact poses first, then passing, then down and up.
3. The body moves up and down by one or two pixels over the cycle: lowest on
   down, highest on up. `set_cel` with relative=true shifts the upper layers.
4. Arms swing opposite to the legs. The far arm and leg are drawn darker so the
   limbs do not merge.
5. Keep frame durations even (about 100 ms) for a steady pace; a heavy
   character uses longer holds on the down pose.
6. Walk in place: the character stays centred and the game moves it. Use
   `get_bounds` to check that the feet stay on the same baseline row.
7. Copy shared parts between frames with `copy_frames` and change only what
   moves. Finish with `set_tag` ("walk"), `check_animation` and an `export`
   preview as .gif.
"""

_ATTACK = """\
Attack animation

1. Three phases: anticipation, strike, recovery.
   - Anticipation: the body winds up opposite to the hit (2-3 frames, slowish).
   - Strike: one or two very fast frames; the weapon is often only a smear here.
   - Recovery: the follow-through and the way back to the idle pose (2-4 frames).
2. Hold frames make attacks feel heavy. Give the last anticipation frame and
   the impact frame long durations with `set_frame_duration` (150-250 ms), the
   in-between strike frame a short one (40-60 ms).
3. Draw the smear as a filled arc in a light colour of the weapon's ramp
   (`draw_polygon` or `draw_ascii`), with no outline, on its own layer.
4. Push the poses further than feels natural; small sprites need exaggeration.
5. Keep the feet planted unless the attack lunges, so the move does not drift.
6. Tag the frames with `set_tag` ("attack", direction forward), check them with
   `check_animation`, then `export_spritesheet` for the engine.
"""

_EFFECTS = """\
Effects: sparks, smoke, flashes

1. Effects work with very few frames: 3 to 6 is typical, 50-80 ms each.
2. Use a short ramp of three or four colours from `generate_color_ramp`, from a
   white or pale core to a saturated edge. Fewer colours read better at speed.
3. Sparks: a bright core pixel cluster on frame 1, short lines flying outward on
   frame 2 (`draw_line`), single pixels fading to the darker colours after that.
4. Smoke: round puffs (`draw_ellipse` with fill) that grow, rise and break into
   smaller clusters; the last frames use the darkest colour and holes.
5. Flash or hit: one frame where the whole sprite turns white or a single bright
   colour. `replace_colors` on a copied frame does it without redrawing.
6. Palette flashes: cycle the effect through the ramp instead of moving pixels,
   e.g. swap colours frame by frame with `replace_colors`.
7. Keep effects on their own layer so they can be exported apart with
   `export_layers`, and check the frames with `view_sprite`.
"""

GUIDES: dict[str, str] = {
    "basics": _BASICS,
    "animation": _ANIMATION,
    "idle": _IDLE,
    "walk": _WALK,
    "attack": _ATTACK,
    "effects": _EFFECTS,
}
