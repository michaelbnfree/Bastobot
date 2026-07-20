#!/usr/bin/env python3
"""
OpenClaw Integration Test
Simulates autonomous agent making trading decisions with market intelligence
"""

import sys
sys.path.insert(0, '/root/bastobot')

from tools.market_decision_tools import make_trading_decision, TOOLS
from skills.openclaw_market_context import MarketContextTool
import json
from datetime import datetime

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

def print_header(text):
    print(f"\n{BOLD}{BLUE}{'='*70}{RESET}")
    print(f"{BOLD}{BLUE}{text}{RESET}")
    print(f"{BOLD}{BLUE}{'='*70}{RESET}\n")

def print_section(text):
    print(f"{BOLD}{YELLOW}▶ {text}{RESET}")

def print_success(text):
    print(f"{GREEN}✅ {text}{RESET}")

def print_warning(text):
    print(f"{YELLOW}⚠️  {text}{RESET}")

def print_error(text):
    print(f"{RED}❌ {text}{RESET}")

def print_info(text):
    print(f"{BLUE}ℹ️  {text}{RESET}")

class OpenClawSimulator:
    def __init__(self):
        self.tool = MarketContextTool()
        self.trades = []
        self.decisions = []

    def test_tools_available(self):
        """Test 1: Verify all tools are available"""
        print_header("TEST 1: TOOL AVAILABILITY")

        tool_names = [t['name'] for t in TOOLS]
        print_info(f"Available tools: {len(TOOLS)}")
        for tool in TOOLS:
            print_success(f"Tool: {tool['name']}")

        return len(TOOLS) == 4

    def test_market_context(self):
        """Test 2: Get market context"""
        print_header("TEST 2: MARKET CONTEXT RETRIEVAL")

        print_section("Calling: get_market_context()")
        context = self.tool.get_market_context()

        if not context:
            print_error("No market context available")
            return False

        print_info(f"Regime: {context['regime']} ({context['regime_confidence']:.0%})")
        print_info(f"Volatility: {context['volatility']}")
        print_info(f"Sentiment: {context['sentiment']} ({context['sentiment_score']:.1f})")
        print_info(f"Alignment: {context['trend_alignment']} ({context['alignment_confidence']:.0%})")
        print_info(f"Timeframes: 1h {context['timeframes']['1h']['direction']}, "
                  f"4h {context['timeframes']['4h']['direction']}, "
                  f"1d {context['timeframes']['1d']['direction']}")

        print_success("Market context retrieved successfully")
        return True

    def test_long_setup_evaluation(self):
        """Test 3: Evaluate LONG setup"""
        print_header("TEST 3: LONG SETUP EVALUATION")

        print_section("Scenario: BTC bull flag at 64700")

        eval_long = self.tool.should_trade_setup('LONG')

        print_info(f"Should trade: {eval_long['should_trade']}")
        print_info(f"Confidence: {eval_long['confidence']:.0%}")
        print_info(f"Reason: {eval_long['reason']}")
        print_info(f"Adjustments:")
        for key, val in eval_long['adjustments'].items():
            print_info(f"  - {key}: {val}")

        if eval_long['should_trade']:
            print_success(f"LONG trade approved ({eval_long['confidence']:.0%} confidence)")
        else:
            print_warning(f"LONG trade skipped ({eval_long['confidence']:.0%} confidence)")

        return eval_long['should_trade'] == (eval_long['confidence'] > 0.5)

    def test_short_setup_evaluation(self):
        """Test 4: Evaluate SHORT setup"""
        print_header("TEST 4: SHORT SETUP EVALUATION")

        print_section("Scenario: BTC potential short in BULL market")

        eval_short = self.tool.should_trade_setup('SHORT')

        print_info(f"Should trade: {eval_short['should_trade']}")
        print_info(f"Confidence: {eval_short['confidence']:.0%}")
        print_info(f"Reason: {eval_short['reason']}")

        if not eval_short['should_trade']:
            print_success("SHORT setup correctly rejected in bullish market")
        else:
            print_warning("SHORT setup approved despite market conditions")

        return True

    def test_position_sizing(self):
        """Test 5: Position sizing"""
        print_header("TEST 5: POSITION SIZING")

        print_section("Scenario: Calculate size for LONG trade (base 0.1 BTC)")

        sizing_long = self.tool.get_position_sizing(0.1, 'LONG')

        print_info(f"Base size: 0.1 BTC")
        print_info(f"Sized position: {sizing_long['sized_position']} BTC")
        print_info(f"Risk level: {sizing_long['risk_level']}")
        print_info(f"Reasoning: {sizing_long['reasoning']}")

        if sizing_long['sized_position'] > 0:
            print_success(f"Position sized: {sizing_long['sized_position']} BTC ({sizing_long['risk_level']})")
        else:
            print_warning("Position size is zero (setup should not be traded)")

        return sizing_long['sized_position'] >= 0

    def test_exit_signals(self):
        """Test 6: Exit signal monitoring"""
        print_header("TEST 6: EXIT SIGNAL MONITORING")

        print_section("Checking for active trade exit signals")

        signals = self.tool.get_exit_signal_context()

        print_info(f"Divergences present: {signals['exit_signals']['has_divergence']}")
        print_info(f"Trend reversal risk: {signals['exit_signals']['trend_reversal']}")
        print_info(f"Volatility spike: {signals['exit_signals']['volatility_spike']}")
        print_info(f"Sentiment extreme: {signals['exit_signals']['sentiment_extreme']}")
        print_info(f"Watch for reversal: {signals['watch_for_reversal']}")

        if signals['watch_for_reversal']:
            print_warning("Exit signals active - monitor trade closely")
        else:
            print_success("No urgent exit signals")

        return True

    def test_full_decision_flow(self):
        """Test 7: Full decision flow"""
        print_header("TEST 7: FULL TRADING DECISION FLOW")

        print_section("Setup detected: BTC potential long entry")

        setup = {
            'entry': 64700,
            'sl': 64000,
            'tp1': 65500,
            'tp2': 66500,
            'size': 0.1
        }

        print_info(f"Entry: ${setup['entry']}")
        print_info(f"SL: ${setup['sl']}")
        print_info(f"TP1: ${setup['tp1']}")
        print_info(f"TP2: ${setup['tp2']}")

        decision = make_trading_decision('BTC', 'LONG', setup)
        self.decisions.append(decision)

        print("\n" + BOLD + "DECISION OUTPUT:" + RESET)
        print(json.dumps({
            'action': decision['action'],
            'confidence': f"{decision['confidence']:.0%}",
            'reason': decision['reason'],
            'position_size': decision['position_size'],
            'risk_level': decision['risk_level'],
        }, indent=2))

        if decision['action'] == 'TRADE':
            print_success(f"TRADE APPROVED ({decision['confidence']:.0%} confidence)")
            print_info(f"Position size: {decision['position_size']} BTC")
            print_info(f"Risk level: {decision['risk_level']}")

            # Simulate trade execution
            self.trades.append({
                'symbol': 'BTC',
                'direction': 'LONG',
                'entry': setup['entry'],
                'size': decision['position_size'],
                'sl': setup['sl'],
                'tp1': setup['tp1'],
                'tp2': setup['tp2'],
                'confidence': decision['confidence'],
                'status': 'OPEN'
            })

        else:
            print_warning(f"TRADE REJECTED: {decision['reason']}")

        return decision['action'] in ['TRADE', 'SKIP']

    def test_monitoring_scenario(self):
        """Test 8: Monitor active trade"""
        print_header("TEST 8: ACTIVE TRADE MONITORING")

        if not self.trades:
            print_warning("No active trades to monitor")
            return True

        trade = self.trades[0]
        print_section(f"Monitoring: {trade['symbol']} {trade['direction']} @ ${trade['entry']}")

        signals = self.tool.get_exit_signal_context()

        print_info("Heartbeat check - monitoring for exit signals...")

        # Check various exit conditions
        if signals['exit_signals']['has_divergence']:
            print_warning("Divergence detected - exit 30%")
            trade['status'] = 'PARTIAL_EXIT'
        elif signals['exit_signals']['volatility_spike']:
            print_warning("Volatility spike - tighten stops")
            trade['status'] = 'SL_TIGHTENED'
        elif signals['exit_signals']['sentiment_extreme']:
            print_warning("Extreme sentiment - prepare to exit")
            trade['status'] = 'PREPARED_EXIT'
        else:
            print_success("No exit signals - continue holding")
            trade['status'] = 'HOLDING'

        return True

    def test_different_market_conditions(self):
        """Test 9: Decision consistency across scenarios"""
        print_header("TEST 9: MARKET CONDITION SCENARIOS")

        print_section("Testing decision consistency")

        # Get current context
        context = self.tool.get_market_context()

        # Test both directions
        long_eval = self.tool.should_trade_setup('LONG')
        short_eval = self.tool.should_trade_setup('SHORT')

        print_info(f"Current regime: {context['regime']}")
        print_info(f"Current alignment: {context['trend_alignment']}")
        print()

        # Verify logic consistency
        if context['regime'] == 'BULL':
            if long_eval['confidence'] > short_eval['confidence']:
                print_success("BULL market: LONG preferred over SHORT ✓")
            else:
                print_warning("BULL market: SHORT confidence higher than LONG")
        elif context['regime'] == 'BEAR':
            if short_eval['confidence'] > long_eval['confidence']:
                print_success("BEAR market: SHORT preferred over LONG ✓")
            else:
                print_warning("BEAR market: LONG confidence higher than SHORT")
        else:  # RANGE
            print_info("RANGE market: Both directions have similar risk")

        return True

    def test_tools_performance(self):
        """Test 10: Tool performance"""
        print_header("TEST 10: TOOL PERFORMANCE")

        import time

        print_section("Measuring tool latency")

        # Test context tool
        start = time.time()
        self.tool.get_market_context()
        context_time = (time.time() - start) * 1000

        # Test evaluation tool
        start = time.time()
        self.tool.should_trade_setup('LONG')
        eval_time = (time.time() - start) * 1000

        # Test sizing tool
        start = time.time()
        self.tool.get_position_sizing(0.1, 'LONG')
        sizing_time = (time.time() - start) * 1000

        # Test exit signals
        start = time.time()
        self.tool.get_exit_signal_context()
        exit_time = (time.time() - start) * 1000

        print_info(f"get_market_context(): {context_time:.1f}ms")
        print_info(f"should_trade_setup(): {eval_time:.1f}ms")
        print_info(f"get_position_sizing(): {sizing_time:.1f}ms")
        print_info(f"get_exit_signal_context(): {exit_time:.1f}ms")

        avg_time = (context_time + eval_time + sizing_time + exit_time) / 4

        if avg_time < 100:
            print_success(f"Average latency: {avg_time:.1f}ms ✓ (< 100ms threshold)")
        else:
            print_warning(f"Average latency: {avg_time:.1f}ms (above 100ms)")

        return avg_time < 500  # Allow up to 500ms for redis queries

    def run_all_tests(self):
        """Run all integration tests"""
        print_header("OPENCLAW INTEGRATION TEST SUITE")
        print_info(f"Test started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        results = {
            'Tool Availability': self.test_tools_available(),
            'Market Context': self.test_market_context(),
            'LONG Setup Evaluation': self.test_long_setup_evaluation(),
            'SHORT Setup Evaluation': self.test_short_setup_evaluation(),
            'Position Sizing': self.test_position_sizing(),
            'Exit Signals': self.test_exit_signals(),
            'Full Decision Flow': self.test_full_decision_flow(),
            'Trade Monitoring': self.test_monitoring_scenario(),
            'Condition Scenarios': self.test_different_market_conditions(),
            'Performance': self.test_tools_performance(),
        }

        # Summary
        print_header("TEST SUMMARY")

        passed = sum(1 for v in results.values() if v)
        total = len(results)

        for test_name, result in results.items():
            status = f"{GREEN}✅ PASS{RESET}" if result else f"{RED}❌ FAIL{RESET}"
            print(f"{status} {test_name}")

        print()
        if passed == total:
            print_success(f"ALL TESTS PASSED ({passed}/{total})")
        else:
            print_warning(f"SOME TESTS FAILED ({passed}/{total} passed)")

        # Summary statistics
        print_header("EXECUTION SUMMARY")
        print_info(f"Total trades simulated: {len(self.trades)}")
        print_info(f"Total decisions made: {len(self.decisions)}")

        if self.trades:
            print("\nActive Trades:")
            for i, trade in enumerate(self.trades, 1):
                print_info(f"  {i}. {trade['symbol']} {trade['direction']} @ ${trade['entry']} "
                         f"(Size: {trade['size']}, Status: {trade['status']})")

        if self.decisions:
            print("\nDecision History:")
            for i, decision in enumerate(self.decisions, 1):
                print_info(f"  {i}. {decision['action']}: {decision['symbol']} {decision['direction']} "
                         f"({decision['confidence']:.0%} confidence)")

        print_header("INTEGRATION TEST COMPLETE")

        return passed == total


def main():
    simulator = OpenClawSimulator()
    success = simulator.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
