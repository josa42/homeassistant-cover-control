# To think about

Decisions that are not made yet. Nothing here is a bug.

## Should Resume drive the cover when the engine wants nothing?

Pressing **Resume** on a cover already acts at once when an episode applies: the
target is recomputed and sent in the same moment. When the engine wants nothing,
which is any time outside an episode, the cover keeps whatever position it was
left in, and no button brings it back to what the engine would have it do.

Making Resume open the cover fully in that case would be the tidy behaviour, and
matches what the end of an episode does. The cost is that a Resume pressed at
23:00 on a paused bedroom cover opens it. A pause running out on its own must
keep its current protection either way, which is a separate thing from the
button and is why `released_from_pause` exists.

Three ways it could go:

- Open fully whenever Resume is pressed and no episode applies.
- Open fully only while the sun is up, and leave the cover alone after dark.
  Safer, at the cost of one button doing two things depending on the hour.
- Leave it as it is, and say so in the docs so it is not a surprise.
