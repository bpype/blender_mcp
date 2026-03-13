
###############
Prompt Examples
###############

Tested With 5.1, Claude Opus 4.6.
(with "High Effort" thinking enabled).

All of these prompts have been tested to work.

Some of them use files from blenders testing repository:

Simple Video Editing Example
   Works with 4 prompts or 1 prompt as dot-points.

   Make a new file "Video Editor" and add a text strip that says "Hello World"

   Animate the text, starting small and ending 5x the current scale.

   Add a grey background that animates to black.

   Render this to an image sequencer at 10% scale, to output.mpg, then play it.

Geometry Nodes Example (NOTE: each dot-point is a prompt)
   - Make a new file, set the "Geometry Nodes" workspace.
   - This animation starts at frame 1 and ends at 500.
   - Create geometry nodes where the words "Hello World" appear one letter at a time.
   - The letters must "jiggle" slightly, continuously.
   - Near the end of the animation the letters should "explode" and vanish.

Scene Editing
   ./tests/files/animation/luxo.blend

   Create another lamp facing the opposite direction,
   jumping from left to right passing by the other lamp (not touching it).

Text Editing in the Scene
   ./tests/files/modeling/text-regression.blend

   In the 3D scene, below the text "I am red" and so on, I wanted to do add:
   "I am cyan", "I am magenta" and "I am yellow".
   With the appropriate materials colors.

Grease Pencil Animated Hand-Drawn Title Card
   Make a new file, switch to the 2D Animation workspace.

   On a Grease Pencil object, use a "Solid Fill" layer to draw a colored rounded rectangle as a background card.

   On a second "Text" layer, write the words "HELLO WORLD" as stroke-based letters across multiple frames,
   so each frame adds one more letter (progressive reveal over frames 1-40).

   Add a GP Build modifier to the text layer to animate the actual stroke drawing,
   so each letter appears to be hand-drawn.

   Add a GP Noise modifier with animated seed for a subtle hand-drawn wobble.

   On a third "Underline" layer, draw a wavy underline stroke that builds in from left to right (frames 30-50).

Armature Rig, IK & Walk Cycle via NLA
   Your task: Armature Rig, IK & Walk Cycle via NLA

   Make a new file.

   Build a simple biped stick-figure from extruded cylinders (torso, upper/lower arms, upper/lower legs, head sphere).

   Create an armature matching the hierarchy, with IK constraints on both feet and both hands.

   Weight-paint each mesh segment to its corresponding bone.

   In the Action Editor, create a 24-frame looping walk cycle pose-to-pose (contact, down, passing, up for each leg).

   Push the action into the NLA Editor and set it to repeat 5 times.

   Add a camera at a 3/4 angle and render to walkcycle.mpg, then play it.


Modifier-Driven Spiral Staircase
   Make a new file.

   Create a single flat "step" mesh (a shallow box).

   Add an Array modifier (30 copies) with a constant Z offset,
   combined with a second Array or Object Offset that rotates each copy to form a spiral.

   Add a Curve modifier using a helix-shaped curve so the steps follow a smooth spiral path.

   Add a camera and a light placed to frame the full staircase, and render a single frame to staircase.png.
