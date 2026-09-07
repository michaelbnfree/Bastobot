"""
Barry's Brain Dashboard — Web interface to the persistent knowledge vault.
Displays watchlist, trades, patterns, market analysis, and learnings.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
import sys

sys.path.insert(0, '/root/bastobot')
from skills.brain import (
    read_watchlist, read_patterns, export_brain_summary,
    search_brain, BRAIN_ROOT
)

app = FastAPI(title="Barry's Brain Dashboard")

BRAIN_ROOT = Path("/root/bastobot/brain")


@app.get("/api/brain/summary", response_class=JSONResponse)
async def get_summary():
    """Brain statistics and overview."""
    try:
        return export_brain_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/watchlist", response_class=JSONResponse)
async def get_watchlist():
    """Fetch all watchlist items."""
    try:
        watchlist = read_watchlist()
        return {
            "count": len(watchlist),
            "items": {symbol: content for symbol, content in watchlist.items()}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/watchlist/{symbol}", response_class=JSONResponse)
async def get_watchlist_item(symbol: str):
    """Fetch specific watchlist item."""
    try:
        watchlist = read_watchlist()
        if symbol.upper() not in watchlist:
            raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")
        return {
            "symbol": symbol.upper(),
            "content": watchlist[symbol.upper()]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trades", response_class=JSONResponse)
async def get_trades():
    """Fetch recent trades."""
    try:
        trades_dir = BRAIN_ROOT / "trades"
        trades = []
        if trades_dir.exists():
            for file in sorted(trades_dir.glob("*.md"), reverse=True)[:20]:
                trades.append({
                    "filename": file.stem,
                    "content": file.read_text()[:500]  # Preview
                })
        return {"count": len(trades), "trades": trades}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/patterns", response_class=JSONResponse)
async def get_patterns():
    """Fetch all recorded patterns."""
    try:
        patterns = read_patterns()
        return {
            "count": len(patterns),
            "patterns": {name: content[:300] for name, content in patterns.items()}  # Preview
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market", response_class=JSONResponse)
async def get_market_notes():
    """Fetch market analysis notes."""
    try:
        market_dir = BRAIN_ROOT / "market"
        notes = []
        if market_dir.exists():
            for file in sorted(market_dir.glob("*.md"), reverse=True)[:10]:
                notes.append({
                    "date": file.stem,
                    "content": file.read_text()[:500]
                })
        return {"count": len(notes), "notes": notes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learnings", response_class=JSONResponse)
async def get_learnings():
    """Fetch recorded learnings."""
    try:
        learnings_dir = BRAIN_ROOT / "learnings"
        learnings = []
        if learnings_dir.exists():
            for file in sorted(learnings_dir.glob("*.md"), reverse=True)[:15]:
                learnings.append({
                    "timestamp": file.stem,
                    "content": file.read_text()[:300]
                })
        return {"count": len(learnings), "learnings": learnings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/search", response_class=JSONResponse)
async def search(q: str):
    """Search the brain."""
    if not q or len(q) < 2:
        raise HTTPException(status_code=400, detail="Query too short")
    try:
        results = search_brain(q, max_results=10)
        return {
            "query": q,
            "results": [{"path": str(p), "excerpt": e} for p, e in results]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Main dashboard UI."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Barry's Brain Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #0f1419;
            color: #e0e6ed;
            line-height: 1.6;
        }

        header {
            background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%);
            padding: 2rem;
            border-bottom: 2px solid #00d9ff;
            box-shadow: 0 2px 8px rgba(0, 217, 255, 0.1);
        }

        header h1 {
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #00d9ff, #00b4d8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: #1a1f2e;
            border: 1px solid #00d9ff;
            border-radius: 8px;
            padding: 1.5rem;
            text-align: center;
            transition: all 0.3s ease;
        }

        .stat-card:hover {
            background: #16213e;
            box-shadow: 0 0 15px rgba(0, 217, 255, 0.3);
            transform: translateY(-2px);
        }

        .stat-card .number {
            font-size: 2.5rem;
            font-weight: bold;
            color: #00d9ff;
            margin-bottom: 0.5rem;
        }

        .stat-card .label {
            font-size: 0.9rem;
            color: #a8b2c1;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
            border-bottom: 1px solid #2a3f5f;
            flex-wrap: wrap;
        }

        .tab {
            padding: 1rem 1.5rem;
            background: none;
            border: none;
            border-bottom: 3px solid transparent;
            color: #a8b2c1;
            cursor: pointer;
            font-size: 1rem;
            transition: all 0.3s ease;
        }

        .tab:hover {
            color: #00d9ff;
        }

        .tab.active {
            color: #00d9ff;
            border-bottom-color: #00d9ff;
        }

        .content {
            display: none;
        }

        .content.active {
            display: block;
        }

        .item {
            background: #1a1f2e;
            border-left: 4px solid #00d9ff;
            padding: 1.5rem;
            margin-bottom: 1rem;
            border-radius: 4px;
            transition: all 0.3s ease;
        }

        .item:hover {
            background: #16213e;
            transform: translateX(4px);
        }

        .item h3 {
            color: #00d9ff;
            margin-bottom: 0.5rem;
            font-size: 1.2rem;
        }

        .item p {
            color: #a8b2c1;
            font-size: 0.9rem;
            line-height: 1.5;
        }

        .item small {
            color: #6b7280;
            display: block;
            margin-top: 0.5rem;
        }

        .search-box {
            margin-bottom: 2rem;
            display: flex;
            gap: 0.5rem;
        }

        .search-box input {
            flex: 1;
            padding: 0.75rem 1rem;
            background: #1a1f2e;
            border: 1px solid #00d9ff;
            color: #e0e6ed;
            border-radius: 4px;
            font-size: 0.95rem;
        }

        .search-box input::placeholder {
            color: #6b7280;
        }

        .search-box button {
            padding: 0.75rem 1.5rem;
            background: #00d9ff;
            color: #0f1419;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.3s ease;
        }

        .search-box button:hover {
            background: #00b4d8;
            transform: translateY(-2px);
        }

        footer {
            text-align: center;
            padding: 2rem;
            color: #6b7280;
            border-top: 1px solid #2a3f5f;
            margin-top: 3rem;
        }

        .loading {
            text-align: center;
            padding: 2rem;
            color: #00d9ff;
        }

        .error {
            background: #3f2a2a;
            border: 1px solid #c94b3f;
            color: #ffb3a7;
            padding: 1rem;
            border-radius: 4px;
            margin-bottom: 1rem;
        }
    </style>
</head>
<body>
    <header>
        <h1>🧠 Barry's Brain</h1>
        <p>Persistent Knowledge Vault | Trades | Patterns | Watchlist</p>
    </header>

    <div class="container">
        <div class="stats" id="stats">
            <div class="loading">Loading statistics...</div>
        </div>

        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search brain (patterns, trades, etc.)">
            <button onclick="search()">Search</button>
        </div>

        <div class="tabs">
            <button class="tab active" onclick="switchTab('watchlist')">📊 Watchlist</button>
            <button class="tab" onclick="switchTab('trades')">📈 Trades</button>
            <button class="tab" onclick="switchTab('patterns')">🎯 Patterns</button>
            <button class="tab" onclick="switchTab('market')">📉 Market</button>
            <button class="tab" onclick="switchTab('learnings')">💡 Learnings</button>
        </div>

        <div id="watchlist" class="content active">
            <div class="loading">Loading watchlist...</div>
        </div>

        <div id="trades" class="content">
            <div class="loading">Loading trades...</div>
        </div>

        <div id="patterns" class="content">
            <div class="loading">Loading patterns...</div>
        </div>

        <div id="market" class="content">
            <div class="loading">Loading market notes...</div>
        </div>

        <div id="learnings" class="content">
            <div class="loading">Loading learnings...</div>
        </div>

        <div id="search-results" class="content">
            <div class="loading">Searching...</div>
        </div>
    </div>

    <footer>
        <p>Barry's Brain Dashboard | Auto-updated from /root/bastobot/brain/</p>
        <small>Last refreshed: <span id="refresh-time">now</span></small>
    </footer>

    <script>
        function escapeHtml(value) {
            return String(value)
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#039;');
        }

        async function loadStats() {
            try {
                const res = await fetch('/api/brain/summary');
                const data = await res.json();
                document.getElementById('stats').innerHTML = `
                    <div class="stat-card">
                        <div class="number">${escapeHtml(data.trades)}</div>
                        <div class="label">Trades</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${escapeHtml(data.watchlist)}</div>
                        <div class="label">Watchlist</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${escapeHtml(data.patterns)}</div>
                        <div class="label">Patterns</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${escapeHtml(data.learnings)}</div>
                        <div class="label">Learnings</div>
                    </div>
                `;
            } catch (e) {
                console.error(e);
            }
        }

        async function loadWatchlist() {
            try {
                const res = await fetch('/api/watchlist');
                const data = await res.json();
                let html = '';
                for (const [symbol, content] of Object.entries(data.items)) {
                    html += `
                        <div class="item">
                            <h3>${escapeHtml(symbol)}</h3>
                            <p>${escapeHtml(content.substring(0, 300))}...</p>
                            <small>Full content available in /root/bastobot/brain/watchlist/${escapeHtml(symbol)}.md</small>
                        </div>
                    `;
                }
                document.getElementById('watchlist').innerHTML = html || '<p>No watchlist items yet.</p>';
            } catch (e) {
                document.getElementById('watchlist').innerHTML = `<div class="error">Error loading watchlist: ${e.message}</div>`;
            }
        }

        async function loadTrades() {
            try {
                const res = await fetch('/api/trades');
                const data = await res.json();
                let html = '';
                for (const trade of data.trades) {
                    html += `
                        <div class="item">
                            <h3>${escapeHtml(trade.filename)}</h3>
                            <p>${escapeHtml(trade.content)}...</p>
                            <small>View full trade in /root/bastobot/brain/trades/</small>
                        </div>
                    `;
                }
                document.getElementById('trades').innerHTML = html || '<p>No trades recorded yet.</p>';
            } catch (e) {
                document.getElementById('trades').innerHTML = `<div class="error">Error loading trades: ${e.message}</div>`;
            }
        }

        async function loadPatterns() {
            try {
                const res = await fetch('/api/patterns');
                const data = await res.json();
                let html = '';
                for (const [name, content] of Object.entries(data.patterns)) {
                    html += `
                        <div class="item">
                            <h3>${escapeHtml(name)}</h3>
                            <p>${escapeHtml(content)}...</p>
                        </div>
                    `;
                }
                document.getElementById('patterns').innerHTML = html || '<p>No patterns recorded yet.</p>';
            } catch (e) {
                document.getElementById('patterns').innerHTML = `<div class="error">Error loading patterns: ${e.message}</div>`;
            }
        }

        async function loadMarket() {
            try {
                const res = await fetch('/api/market');
                const data = await res.json();
                let html = '';
                for (const note of data.notes) {
                    html += `
                        <div class="item">
                            <h3>${escapeHtml(note.date)}</h3>
                            <p>${escapeHtml(note.content)}...</p>
                        </div>
                    `;
                }
                document.getElementById('market').innerHTML = html || '<p>No market notes yet.</p>';
            } catch (e) {
                document.getElementById('market').innerHTML = `<div class="error">Error loading market notes: ${e.message}</div>`;
            }
        }

        async function loadLearnings() {
            try {
                const res = await fetch('/api/learnings');
                const data = await res.json();
                let html = '';
                for (const learning of data.learnings) {
                    html += `
                        <div class="item">
                            <h3>${escapeHtml(learning.timestamp)}</h3>
                            <p>${escapeHtml(learning.content)}...</p>
                        </div>
                    `;
                }
                document.getElementById('learnings').innerHTML = html || '<p>No learnings recorded yet.</p>';
            } catch (e) {
                document.getElementById('learnings').innerHTML = `<div class="error">Error loading learnings: ${e.message}</div>`;
            }
        }

        async function search() {
            const query = document.getElementById('searchInput').value;
            if (!query) return;

            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
                const data = await res.json();
                let html = '<h2>Search Results</h2>';
                for (const result of data.results) {
                    html += `
                        <div class="item">
                            <h3>${escapeHtml(result.path)}</h3>
                            <p>${escapeHtml(result.excerpt)}</p>
                        </div>
                    `;
                }
                document.getElementById('watchlist').innerHTML = html;
                switchTab('watchlist');
            } catch (e) {
                alert('Search error: ' + e.message);
            }
        }

        function switchTab(tab) {
            document.querySelectorAll('.content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.getElementById(tab).classList.add('active');
            event.target.classList.add('active');

            if (tab === 'watchlist') loadWatchlist();
            if (tab === 'trades') loadTrades();
            if (tab === 'patterns') loadPatterns();
            if (tab === 'market') loadMarket();
            if (tab === 'learnings') loadLearnings();
        }

        // Load on startup
        loadStats();
        loadWatchlist();

        // Refresh every 30s
        setInterval(() => {
            loadStats();
            document.getElementById('refresh-time').textContent = new Date().toLocaleTimeString();
        }, 30000);

        document.getElementById('searchInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') search();
        });
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18792)
