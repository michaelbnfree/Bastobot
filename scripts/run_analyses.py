#!/usr/bin/env python3
"""
Run macro and trend analyses periodically
Can be called from cron or systemd timer
"""

import sys
sys.path.insert(0, '/root/bastobot')

from skills.macro_monitor import MacroMonitor
from skills.trend_monitor import TrendMonitor
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    logger.info('Running macro and trend analyses...')

    # Run macro analysis
    macro = MacroMonitor()
    macro_result = macro.analyze()
    if macro_result:
        logger.info(f'✓ Macro: {macro_result.get("summary", "No summary")}')

    # Run trend analysis
    trend = TrendMonitor()
    trend_result = trend.analyze()
    if trend_result:
        logger.info(f'✓ Trend: {trend_result.get("summary", "No summary")}')

    if macro_result or trend_result:
        logger.info('Analyses completed successfully')
    else:
        logger.warning('No data available for analysis')

if __name__ == '__main__':
    main()
