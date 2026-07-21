#!/usr/bin/env python3
"""
Run macro and trend analyses periodically
Can be called from cron or systemd timer
Now includes autonomous trading decision making
"""

import sys
import os
sys.path.insert(0, '/root/bastobot')

from skills.macro_monitor import MacroMonitor
from skills.trend_monitor import TrendMonitor
from skills.notion_macro_logger import log_macro_analysis_to_notion
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    logger.info('=' * 60)
    logger.info('BARRY AUTONOMOUS ANALYSIS & TRADING CYCLE')
    logger.info('=' * 60)

    # Run macro analysis
    logger.info('[1/4] Running macro analysis...')
    macro = MacroMonitor()
    macro_result = macro.analyze()
    if macro_result:
        logger.info(f'✓ Macro: {macro_result.get("summary", "No summary")}')

    # Run trend analysis
    logger.info('[2/4] Running trend analysis...')
    trend = TrendMonitor()
    trend_result = trend.analyze()
    if trend_result:
        logger.info(f'✓ Trend: {trend_result.get("summary", "No summary")}')

    # Log to Notion if both analyses succeeded
    if macro_result and trend_result:
        logger.info('[3/4] Logging to Notion...')
        notion_url = log_macro_analysis_to_notion(macro_result, trend_result)
        if notion_url:
            logger.info(f'✓ Logged to Notion: {notion_url}')
        else:
            logger.warning('Failed to log to Notion (API key or database ID not configured)')

    # Run autonomous trading decision
    if os.getenv('ENABLE_AUTONOMOUS_TRADING', 'true').lower() == 'true':
        logger.info('[4/4] Querying OpenClaw for trade decision...')
        try:
            from scripts.autonomous_trader import AutonomousTrader
            trader = AutonomousTrader()
            trader.run()
            logger.info('✓ Autonomous trading cycle complete')
        except Exception as e:
            logger.warning(f'Autonomous trading disabled or error: {e}')
    else:
        logger.info('[4/4] Autonomous trading disabled')

    if macro_result or trend_result:
        logger.info('✓ Cycle completed successfully')
    else:
        logger.warning('No data available for analysis')

if __name__ == '__main__':
    main()
