#!/usr/bin/env python3
"""
Barry Autonomous Analysis & Trading Cycle v2.0
Includes:
1. Macro Analysis
2. Trend Analysis
3. Notion Logging
4. Autonomous Trading (v2 with setup integration + entry/exit + momentum)
5. Trade Performance Tracking
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
    logger.info('BARRY AUTONOMOUS ANALYSIS & TRADING CYCLE v2.1')
    logger.info('With: Trailing Stops + Drawdown Protection + Real-time Alerts')
    logger.info('=' * 60)

    # Step 1: Macro Analysis
    logger.info('[1/5] Running macro analysis...')
    macro = MacroMonitor()
    macro_result = macro.analyze()
    if macro_result:
        logger.info(f'✓ Macro: {macro_result.get("summary", "No summary")}')
    else:
        logger.warning('Macro analysis failed')

    # Step 2: Trend Analysis
    logger.info('[2/5] Running trend analysis...')
    trend = TrendMonitor()
    trend_result = trend.analyze()
    if trend_result:
        logger.info(f'✓ Trend: {trend_result.get("summary", "No summary")}')
    else:
        logger.warning('Trend analysis failed')

    # Step 3: Notion Logging
    if macro_result and trend_result:
        logger.info('[3/5] Logging to Notion...')
        try:
            notion_url = log_macro_analysis_to_notion(macro_result, trend_result)
            if notion_url:
                logger.info(f'✓ Logged to Notion: {notion_url}')
            else:
                logger.warning('Failed to log to Notion')
        except Exception as e:
            logger.warning(f'Notion logging error: {e}')

    # Step 4: Autonomous Trading Decision (v2)
    if os.getenv('ENABLE_AUTONOMOUS_TRADING', 'true').lower() == 'true':
        logger.info('[4/5] Advanced trading decision (v2)...')
        try:
            from scripts.autonomous_trader_v2 import AutonomousTraderV2
            trader = AutonomousTraderV2()
            signal = trader.get_trade_signal()
            if signal:
                trader.execute_trade(signal)
                logger.info('✓ Trade signal processed and logged')
            else:
                logger.info('No trade signal this cycle')
        except Exception as e:
            logger.warning(f'Autonomous trading error: {e}')
            import traceback
            traceback.print_exc()
    else:
        logger.info('[4/5] Autonomous trading disabled')

    # Step 5: Trade Performance Tracking
    logger.info('[5/5] Updating trade performance stats...')
    try:
        from scripts.trade_performance_tracker import TradePerformanceTracker
        tracker = TradePerformanceTracker()
        tracker.run()
        logger.info('✓ Performance tracking updated')
    except Exception as e:
        logger.warning(f'Performance tracking error: {e}')

    # Step 6: Trailing Stop Management
    logger.info('[6/8] Managing trailing stops...')
    try:
        from scripts.trailing_stop_manager import TrailingStopManager
        stops = TrailingStopManager()
        updated = stops.update_trailing_stops()
        if updated > 0:
            logger.info(f'✓ Updated {updated} trailing stops')
        else:
            logger.info('✓ No stops to update')
    except Exception as e:
        logger.warning(f'Trailing stop error: {e}')

    # Step 7: Drawdown Protection Check
    logger.info('[7/8] Checking drawdown protection...')
    try:
        from scripts.drawdown_protection import DrawdownProtection
        protection = DrawdownProtection()
        is_enabled = protection.check_circuit_breaker()
        logger.info(f'✓ Circuit breaker: {"NORMAL" if is_enabled else "TRIGGERED"}')
    except Exception as e:
        logger.warning(f'Drawdown protection error: {e}')

    # Step 8: Alert Management (if alerts configured)
    logger.info('[8/8] Processing alerts...')
    try:
        from scripts.alert_manager import AlertManager
        alerts = AlertManager()
        recent_alerts = alerts.get_recent_alerts(5)
        if recent_alerts:
            logger.info(f'✓ {len(recent_alerts)} recent alerts')
        else:
            logger.info('✓ No pending alerts')
    except Exception as e:
        logger.debug(f'Alert manager error: {e}')

    if macro_result or trend_result:
        logger.info('✓ Cycle completed successfully (8/8 steps)')
    else:
        logger.warning('No data available for analysis')

if __name__ == '__main__':
    main()
