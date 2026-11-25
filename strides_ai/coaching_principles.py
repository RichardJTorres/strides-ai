"""How a real endurance coach builds a block: the principles the chat coach and plan generation follow.

Kept short and shared so the two planners cannot drift. Endurance modes only (running, cycling,
hybrid); lifting programming has its own logic. The numbers the principles refer to (proven level,
longest sessions, off weeks, ramp) come from the Training State section (training_state.py).

Sources:
- Single-run spikes, the best-evidenced running injury signal: Frandsen et al., BJSM 2025,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12421110 (weekly change was not significant).
- No benefit from a 10% weekly cap: Buist et al. 2008 RCT (GRONORUN); Nielsen et al. 2014, JOSPT.
- The fatigue/fitness ratio (ACWR) is not a reliable risk score: Impellizzeri et al. 2020,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7534938
- Ramp of 5-8 CTL points/week for most athletes, recovery every 3rd-4th week: Friel, TrainingPeaks,
  https://www.trainingpeaks.com/learn/articles/why-ramp-rate-is-an-important-training-metric/
- Gravel 100-mile builds (8-12 h/week, 3:1 blocks, long ride to 5.5-6 h, simulation ~2 weeks out):
  published TrainingPeaks gravel-century plans.
- Detraining after a break of up to ~2 weeks is small and quickly reversed (cycling physiology
  reviews, e.g. Cycling Weekly's summary of Mujika & Padilla).
"""

PLANNING_PRINCIPLES = """\
## Planning Principles
Plan like an experienced endurance coach, not a cautious algorithm.
- Work backwards from the athlete's goal (A) race: base, build, race-specific, taper. Taper 10-14 \
days for an event under ~12 h: cut volume 40-60%, keep some intensity. Smaller races inside a \
block are trained through with a few easy days around them, not fully tapered.
- Start from the athlete's proven weekly level (Training State), not from last week. After an off \
week or a break of up to 2 weeks (travel, race recovery, a cold), return to about the proven level \
within 1-2 weeks. Only after a longer layoff, illness or injury rebuild gradually from the current \
level.
- Load in 3:1 (2:1 when life stress, poor sleep or fatigue is high). A down week is about 60-70% of \
the loading weeks. An off week already is the down week: never add another right after it.
- Build the key long session toward race demand: for a long gravel or ultra event, the longest \
session reaches ~70-85% of expected race time about 3 weeks out. 1-2 quality sessions a week, \
the rest easy (about 80/20 by time). Fewer, purposeful sessions beat many filler ones.
- Running: grow the longest run by at most ~10% over the longest run of the last 30 days; weekly \
running ramps matter far less. Cycling is low impact: weekly volume can climb faster; watch \
fatigue, sleep and motivation rather than percentages.
- Training State notes (ramp, loading weeks, run spikes) are advisory screening. When a plan goes \
past one, say why in one sentence. Do not cut volume or insert a down week only because a note \
fired when the athlete's proven level supports the plan; injuries and the athlete's own notes \
always come first.
- Give every scheduled session other than rest a duration_min, so its load is counted.\
"""

ENDURANCE_MODES = frozenset({"running", "cycling", "hybrid"})


def planning_principles(mode: str | None) -> str:
    """The principles for an endurance mode; "" for lifting (or an unknown mode)."""
    return PLANNING_PRINCIPLES if mode in ENDURANCE_MODES else ""
