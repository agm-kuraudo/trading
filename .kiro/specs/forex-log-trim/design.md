# Design: Forex Log Trim

To resolve the logging verbosity issue while keeping full data analysis, we will implement a "log tail" mechanism in `MarketAnalyzer.process_data()`.

## Core Logic
In the `process_data()` loop, we will introduce a condition that checks if the current `row_position` is within the "log window" (last N rows).

```python
# Before starting the loop
log_tail_size = self.__config.log_tail_size or 3
total_rows = len(self.myDF)
log_start_index = max(0, total_rows - log_tail_size)

# Inside the loop:
# Replace unconditional logging with a conditional check based on row_position
if row_position >= log_start_index:
    self.__logger.log(f"Processing row: {index}", level="DEBUG")
    # ... other verbose logs ...
```

## Configuration
- Add `log_tail_size` to the `Settings` schema (in `vpa/config/settings.py` / `config.json`).
- Default value will be `3`.
