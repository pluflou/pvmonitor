# pvmonitor
Easy to use, continuous python monitor for epics pv's

Usage:
 ```
%matplotlib widget

# Basic usage with defaults (5-minute window, Pacific time)
monitor = PvMonitor(pv_list=["pv1", "pv2"])
monitor.run()
```
Fast sampling, slow updates (collect at 10 Hz, display at 2 Hz)
```
monitor = PvMonitor(
    pv_list=["PV:FAST:SIGNAL"],
    sample_interval=0.1,  # Sample every 100ms
    plot_fps=2.0,         # Update display 2 times/second
    time_window=60.0      # Show last 1 minute
)
```
Long-term monitoring with custom callback
```
def add_computed_values():
    return {"status": "OK", "computed_avg": np.random.random()}

monitor = PvMonitor(
    pv_list=["PV1", "PV2", "PV3"],
    time_window=3600.0,      # 1 hour window
    sample_interval=5.0,     # Sample every 5 seconds
    sample_callback=add_computed_values,
    timezone="US/Eastern"
)
```
For example, you have two PVs and want to compute their ratio
```
def compute_ratio():
    # This gets called every sample
    pv1_val = epics.caget("PV:VALUE:1")
    pv2_val = epics.caget("PV:VALUE:2")
    
    if pv2_val and pv2_val != 0:
        ratio = pv1_val / pv2_val
    else:
        ratio = None
    
    return {"ratio": ratio}

monitor = PvMonitor(
    pv_list=["PV:VALUE:1", "PV:VALUE:2"],
    sample_callback=compute_ratio
)

monitor.run()
```
