# Tasks: Forex Log Trim

1. [ ] Update `vpa/config/settings.py` to include `log_tail_size` in the `Settings` class (with default value).
2. [ ] Update `vpa/config/config.json` to include `log_tail_size` parameter.
3. [ ] Modify `vpa/app_runner.py` to implement the log tail condition in `MarketAnalyzer.process_data()`.
4. [ ] Verify that log file size is reduced.
5. [ ] Ensure full history analysis still works correctly.
