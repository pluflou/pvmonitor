# In a Jupyter cell:
# %matplotlib widget

import math
import time
from typing import Callable, Dict, List, Optional
import threading
from datetime import datetime
import pytz

import epics
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


class PvMonitor:
    """
    Real-time monitor for EPICS Process Variables with live plotting in Jupyter notebooks.
    
    Creates a multi-panel plot that continuously updates with PV values over time.
    Runs in a background thread to keep the Jupyter notebook responsive.
    
    Example:
        >>> monitor = PvMonitor(
        ...     pv_list=["PV:NAME:1", "PV:NAME:2"],
        ...     time_window=300.0,
        ...     sample_interval=1.0
        ... )
        >>> monitor.run()
        >>> # ... monitor runs in background ...
        >>> monitor.stop()
    """
    
    def __init__(
        self,
        pv_list: List[str],
        sample_interval: float = 0.2,
        plot_fps: float = 10.0,
        time_window: float = 300.0,
        sample_callback: Optional[Callable[[], Dict]] = None,
        n_cols: int = 2,
        history_factor: float = 2.0,
        timezone: str = "US/Pacific",
    ):
        """
        Initialize the PV monitor.
        
        Args:
            pv_list: List of EPICS PV names to monitor. Each PV will get its own subplot.
                Example: ["MACHINE:BEAM:CURRENT", "MACHINE:TEMP:SENSOR1"]
            
            sample_interval: Time between PV samples in seconds. Controls how often
                the PVs are read from EPICS. Default is 0.2 seconds (5 Hz sampling).
                Lower values = more frequent updates but higher CPU usage.
                Example: 1.0 for once per second, 0.1 for 10 times per second.
            
            plot_fps: Target frames per second for plot updates. Controls how often
                the matplotlib figure is redrawn. Default is 10.0 (redraw 10 times/sec).
                Can be lower than sample rate to reduce CPU load while still collecting
                data at high rate. Example: 5.0 for smoother updates, 2.0 for slower.
            
            time_window: Width of the time window displayed on each plot, in seconds.
                The x-axis will show data from (now - time_window) to now.
                Default is 300.0 seconds (5 minutes). The plot scrolls as time advances.
                Example: 60.0 for 1 minute, 600.0 for 10 minutes, 3600.0 for 1 hour.
            
            sample_callback: Optional function that returns additional data to log
                with each sample. Must return a dictionary with column names as keys.
                Called once per sample. Useful for adding computed values or metadata.
                Example: lambda: {"computed": some_calculation()}
            
            n_cols: Number of columns in the subplot grid. Plots are arranged in a
                grid with this many columns. Default is 4. Number of rows is calculated
                automatically based on number of PVs.
                Example: 3 for narrower layout, 6 for wider layout.
            
            history_factor: Multiplier for data retention. Data is kept for
                (time_window * history_factor) seconds, even though only time_window
                is displayed. This provides a buffer for scrolling back or changing
                the window size. Default is 2.0 (keep 2x the displayed window).
                Example: 1.5 for less memory, 3.0 for more historical data.
            
            timezone: Timezone for x-axis time labels. Must be a valid pytz timezone
                string. Default is "US/Pacific". The raw data is stored in UTC but
                displayed in this timezone.
                Examples: "US/Eastern", "Europe/London", "Asia/Tokyo", "UTC"
        
        Attributes:
            data: pandas DataFrame containing all sampled data with columns:
                - "time": Unix timestamp (float)
                - "datetime": timezone-aware datetime
                - One column per PV name
                - Additional columns from sample_callback if provided
        """
        self.pv_list = pv_list
        self.sample_interval = float(sample_interval)
        self.plot_fps = float(plot_fps)
        self.time_window = float(time_window)
        self.sample_callback = sample_callback
        self.n_cols = int(n_cols)
        self.history_factor = float(history_factor)
        self.timezone = pytz.timezone(timezone)

        self.data = pd.DataFrame(columns=["time", "datetime", *pv_list])

        self.fig = None
        self.axes = None
        self.lines = {}
        self._running = False
        self._last_plot = 0.0
        self._thread = None

    def setup(self):
        """
        Set up the matplotlib figure and subplots.
        
        Creates a grid of subplots (one per PV) and configures axes formatting.
        Called automatically by run() if not already called.
        Can be called manually to create the figure before starting monitoring.
        """
        if self.fig is not None:
            return

        n_rows = math.ceil(len(self.pv_list) / self.n_cols)
        self.fig, self.axes = plt.subplots(
            n_rows, self.n_cols, squeeze=False, 
            constrained_layout=True, figsize=(self.n_cols * 3.8, n_rows * 2.9)
        )

        # Create a formatter for Pacific time
        class PacificFormatter(mdates.DateFormatter):
            def __init__(self, fmt, tz):
                super().__init__(fmt, tz=tz)
        
        for i, name in enumerate(self.pv_list):
            a = self.axes.flatten()[i]
            (ln,) = a.plot([], [], "-", lw=1.2, marker="o", ms=3)
            a.set_title(name, fontsize=10)
            a.grid(True, alpha=0.25)
            a.xaxis.set_major_formatter(PacificFormatter("%H:%M:%S", tz=self.timezone))
            a.xaxis_date()
            a.set_autoscalex_on(False)
            a.tick_params(axis="x", labelrotation=30, labelsize=8)
            a.tick_params(axis="y", labelsize=8)
            self.lines[name] = (a, ln)

        for j in range(len(self.pv_list), n_rows * self.n_cols):
            self.axes.flatten()[j].set_visible(False)

        # Initial draw
        self.fig.canvas.draw()

    @staticmethod
    def _to_float(v):
        """Convert a value to float, returning nan if conversion fails."""
        if v is None:
            return np.nan
        try:
            return float(v)
        except Exception:
            return np.nan

    def _run_loop(self):
        """
        Internal monitoring loop that runs in background thread.
        
        Continuously samples PVs and updates plots at the specified intervals.
        Should not be called directly - use run() instead.
        """
        while self._running:
            t0 = time.perf_counter()
            
            self.sample()
            self.plot()
            
            dt = time.perf_counter() - t0
            sleep_time = max(0.0, self.sample_interval - dt)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def run(self):
        """
        Start monitoring PVs in a background thread.
        
        Creates the figure (if not already created) and begins sampling PVs
        and updating plots. Returns immediately - monitoring continues in background.
        The Jupyter notebook remains responsive while monitoring runs.
        
        Call stop() to stop monitoring.
        
        Example:
            >>> monitor = PvMonitor(pv_list=["PV1", "PV2"])
            >>> monitor.run()
            Monitor started. Call monitor.stop() to stop.
            >>> # ... do other work in notebook ...
            >>> monitor.stop()
        """
        self.setup()
        
        if self._running:
            print("Monitor is already running!")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("Monitor started. Call monitor.stop() to stop.")

    def stop(self):
        """
        Stop the monitoring.
        
        Stops the background thread and halts PV sampling and plot updates.
        The figure and all collected data remain available.
        Can call run() again to restart monitoring.
        
        Example:
            >>> monitor.stop()
            Monitor stopped.
            >>> # Access collected data
            >>> print(monitor.data)
        """
        if not self._running:
            print("Monitor is not running.")
            return
            
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        print("Monitor stopped.")

    def sample(self):
        """
        Sample all PVs once and add data to the DataFrame.
        
        Reads all PVs using epics.caget_many(), converts values to floats,
        adds timestamp and timezone-aware datetime, calls sample_callback if provided,
        and appends the row to self.data. Old data beyond history_factor * time_window
        is discarded to limit memory usage.
        
        Called automatically by the monitoring loop - usually no need to call directly.
        """
        raw_vals = epics.caget_many(self.pv_list)
        vals = [self._to_float(v) for v in raw_vals]

        now = time.time()
        row = dict(zip(self.pv_list, vals))
        row["time"] = now
        # Convert to Pacific time
        row["datetime"] = pd.to_datetime(now, unit="s", utc=True).tz_convert(self.timezone)

        if self.sample_callback is not None:
            row.update(self.sample_callback())

        self.data = pd.concat([self.data, pd.DataFrame([row])], ignore_index=True)

        cutoff = now - self.time_window * self.history_factor
        self.data = self.data[self.data["time"] >= cutoff].reset_index(drop=True)

    def plot(self):
        """
        Update all plots with current data.
        
        Filters data to the current time window, updates line data and axis limits
        for all subplots, and triggers a canvas redraw. Respects the plot_fps limit
        to avoid excessive redraws.
        
        Called automatically by the monitoring loop - usually no need to call directly.
        """
        now = time.time()
        if (now - self._last_plot) < (1.0 / self.plot_fps):
            return

        w = self.data[self.data["time"] >= (now - self.time_window)]
        if w.empty:
            self._last_plot = now
            return

        x = mdates.date2num(w["datetime"].to_numpy())
        if len(x) == 0:
            self._last_plot = now
            return
        
        # Set x-axis limits to show the full time window, with current time on the right
        now_dt = datetime.fromtimestamp(now, tz=pytz.utc).astimezone(self.timezone)
        start_dt = datetime.fromtimestamp(now - self.time_window, tz=pytz.utc).astimezone(self.timezone)
        
        xl = mdates.date2num(start_dt)
        xr = mdates.date2num(now_dt)

        for name in self.pv_list:
            a, ln = self.lines[name]
            y = pd.to_numeric(w[name], errors="coerce").to_numpy(dtype=float)

            ln.set_data(x, y)
            a.set_xlim(xl, xr)  # Always show the full time window

            if np.isfinite(y).any():
                a.relim()
                a.autoscale_view(scalex=False, scaley=True)
            else:
                a.set_ylim(0, 1)

        # Thread-safe canvas update
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        self._last_plot = now
