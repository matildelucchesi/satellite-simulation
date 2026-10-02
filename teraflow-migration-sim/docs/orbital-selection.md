# Orbital sample and migration-event selection

## Frozen input and common epoch

Use the archived CelesTrak Starlink GP/TLE snapshot recorded in `data/source_manifest.json`. For reproducibility, do not fetch a new TLE during a run. TLE elements in one catalog can have different epochs. The selector propagates each object with SGP4 to the latest epoch present in the file, then derives the instantaneous orbital-plane normal and RAAN there. It also uses SGP4's un-Kozai semi-major axis for screening altitude. Raw RAAN from different TLE epochs is not compared directly.

## Current reduced sample

The screen is inclination 52.5–53.5 degrees and mean semi-major-axis altitude 520–580 km, around the nominal 53-degree / 550-km shell. The frozen 2026-10-01 catalog yields 66 screened records. Group by normalized RAAN with a 1.5-degree maximum gap; among plane pairs separated by 10–30 degrees in RAAN, select the pair with the greatest combined candidate count. Keep all screened satellites in the chosen pair. This gives 17 satellites (6+11), RAAN centers 90.00 and 110.03 degrees, and actual TLE-derived mean altitudes 521.9–540.1 km.

The 520–580 km tolerance is the selected modeling choice because it retains destination diversity: the stricter 530–570 km screen leaves 16 candidates in the selected planes but no source satellite has more than one direct FSO neighbor during the one-day preflight, so the score would have no meaningful destination choice. The wider screen gives three source satellites with two or more reachable destinations. One selected object, STARLINK-3527 (NORAD 51726), has a TLE-derived mean semi-major-axis altitude of 521.9 km, close to the 520-km lower screening boundary. Keep it in the primary sample and label it as a boundary case in results; include an optional sensitivity run without it if the schedule permits. The nominal shell remains 550 km, while this particular frozen TLE sample spans only 521.9–540.1 km. Report this limitation when interpreting results rather than implying every selected object is centered at 550 km.

The orbital-plane angle is not equal to RAAN separation. For equal inclinations `i`, the angle `α` between plane normals is

\[
\cos\alpha = \cos^2 i + \sin^2 i\cos(\Delta\Omega).
\]

At `i≈53°` and `ΔΩ≈20°`, this selected pair has a plane-normal angle of about 16 degrees. The altitude screen is explicit because the selected current TLEs do not sit at exactly 550 km. The recorded TLE positions, rather than the nominal shell label, drive propagation.

## Link and event screening

The one-day geometry run uses a one-second step. A direct FSO edge exists only when both conditions hold: range ≤1,700 km, and the straight segment between the satellites does not intersect a spherical Earth of radius 6,378.137 km. The edge must remain available for 60 seconds for the alignment stage to fit. The resulting 168 windows across seven distinct pairs are a geometry preflight. They are not 168 controller migrations.

The final event set must be created from **trigger-qualified** events. For each event, calculate

\[
T_{\text{available}} = \min(W_{\text{FSO}},T_{\text{deadline}}), \qquad
M_{\text{orb}} = T_{\text{available}}-60\,\text{s}.
\]

Choose one real event nearest each P10/P50/P90 of the resulting distinct-event `M_orb` distribution. Pair the same SAT-A, elected SAT-B, trigger time, and event across cold/hot and all three rates. The final migration margin subtracts the actual transfer, startup, API restoration, verification, and cutover time from `M_orb`. Negative margin means the operation does not fit under the modeled assumptions.

The reference epoch is the freshest TLE epoch, not an Italy pass time. This experiment currently has no ground gateway in its forwarding path, so Italian ground-station visibility is not a simulation metric. If a gateway becomes part of the experiment, pin its coordinates and elevation mask and choose its observation window explicitly.
