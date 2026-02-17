# pvmonitor
Easy to use, continuous python monitor for epics pv's

Usage:
 ```
monitor = PvMonitor(
    pv_list=["PV:SIGMA:X", "PV:SIGMA:Y", "PV:SIGMA:Z", "PV:EMIT:X", "PV:EMIT:Y"],
    pv_groups=[[0, 1], [2], [3, 4]],  # Group indices: first 2, third alone, last 2
    group_titles=["Transverse Beam Sizes", "Longitudinal Beam Size", "Normalized Emittances"],
    time_window=300.0,
    n_cols=3
)
monitor.run()
```
