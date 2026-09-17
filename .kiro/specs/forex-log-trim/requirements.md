# Requirement: Forex Log Trim

After moving from Selenium-based forex scraping to direct data retrieval (SP-309), the `VPA_Forex_App` logs have increased significantly in size (~10MB/run) due to verbose historic row-by-row logging.

1.  **Reduce Log Verbosity:** The application MUST only log operational details (candle creation, analysis) for the most recent 3 bars (or configurable number).
2.  **Preserve Operational Integrity:** The underlying `MarketAnalyzer` must continue to process the *full* daily history (e.g., 5,000+ bars) to ensure long-period SMA calculations (e.g., 200) remain accurate.
3.  **Configurability:** The number of recent bars to log must be configurable, defaulting to 3 to minimize log file size.
